# dashboard/services.py
"""
Read-only data layer for the dashboard.

Every function here is defensive and timeout-bounded: a down service or a slow
WSL `peer` call must never raise into the UI, only return an "unknown"/empty
snapshot. Nothing in this module mutates backend state — it polls existing
endpoints, tails log files, checks ports, and reads the ledger through the
existing Python FabricClient. The only heavier calls are the Fabric ones
(get_device / get_cid_history), which shell out to the WSL peer CLI; app.py
runs those on the slower FABRIC_POLL cadence and off the UI thread.
"""

import os
import re
import socket
from collections import deque
from typing import List, Dict

import requests

from config import settings
from dashboard.models import (
    ServiceHealth, DeviceInfo, CIDEntry, FLStatus,
    PipelineState, PIPELINE_STAGES,
)

# FabricClient is imported lazily so the dashboard still starts (System Status,
# logs, simulation control all work) even if blockchain deps are missing.
_fabric = None


def _get_fabric():
    global _fabric
    if _fabric is None:
        from blockchain.fabric_client import FabricClient
        _fabric = FabricClient()
    return _fabric


# ── low-level probes ─────────────────────────────────────────────────────────
def _port_open(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _http_get(url: str) -> tuple:
    """Returns (ok, json_or_none). Never raises."""
    try:
        r = requests.get(url, timeout=settings.HTTP_TIMEOUT)
        if r.status_code == 200:
            try:
                return True, r.json()
            except ValueError:
                return True, None
        return False, None
    except requests.RequestException:
        return False, None


def _ipfs_up(url: str) -> bool:
    try:
        r = requests.post(f"{url}/api/v0/id", timeout=settings.HTTP_TIMEOUT)
        return r.status_code == 200
    except requests.RequestException:
        return False


# ── System status ────────────────────────────────────────────────────────────
def get_service_health() -> List[ServiceHealth]:
    out: List[ServiceHealth] = []
    for svc in settings.service_registry():
        kind = svc["kind"]
        up, detail = False, ""

        if kind == "docker":
            # Peer endpoint reachable == Fabric network up. Avoids depending on
            # where the docker CLI lives (Desktop vs WSL-native).
            host, _, port = settings.GATEWAY_URL, None, None
            up = _port_open(settings.SERVICE_HOST, 7051, settings.HTTP_TIMEOUT)
            detail = "peer0.org1 reachable :7051" if up else "peer not reachable"

        elif kind == "ipfs":
            up = _ipfs_up(svc["target"])
            detail = "RPC :5001 ok" if up else "daemon not reachable"

        elif kind == "http_health":
            up, data = _http_get(svc["target"])
            if up and isinstance(data, dict):
                if "ipfs_available" in data:
                    detail = f"ipfs={data.get('ipfs_available')}, " \
                             f"blacklisted={data.get('blacklisted_count', 0)}"
                else:
                    detail = data.get("status", "ok")
            elif not up:
                detail = "not reachable"

        elif kind == "http_status":
            up, data = _http_get(svc["target"])
            if up and isinstance(data, dict):
                detail = f"round={data.get('fl_round', 0)}, " \
                         f"pending={len(data.get('pending_devices', []))}"
            elif not up:
                detail = "not reachable"

        out.append(ServiceHealth(
            name=svc["name"], up=up, detail=detail,
            hint=svc["hint"], target=str(svc["target"]),
        ))
    return out


# ── FL server ────────────────────────────────────────────────────────────────
def get_fl_status() -> FLStatus:
    ok, data = _http_get(f"{settings.FL_SERVER_URL}/status")
    if not ok or not isinstance(data, dict):
        return FLStatus(reachable=False)
    return FLStatus(
        round=data.get("fl_round", 0),
        pending_devices=data.get("pending_devices", []),
        excluded_devices=data.get("excluded_devices", []),
        trust_scores=data.get("trust_scores", {}) or {},
        reachable=True,
    )


# ── Devices (Fabric — slow path) ─────────────────────────────────────────────
def get_devices(fl: FLStatus = None) -> List[DeviceInfo]:
    """Read each device's on-chain record + CID count. Slow (WSL peer calls);
    call on the FABRIC_POLL cadence, off the UI thread."""
    fl = fl or FLStatus()
    fabric = None
    try:
        fabric = _get_fabric()
    except Exception:
        # Blockchain layer unavailable — return unregistered placeholders.
        return [DeviceInfo(device_id=d) for d in settings.DEVICE_IDS]

    devices: List[DeviceInfo] = []
    for d in settings.DEVICE_IDS:
        info = DeviceInfo(device_id=d)
        try:
            rec = fabric.get_device(d)
        except Exception:
            rec = None
        if rec:
            info.registered = True
            info.status = rec.get("status", "unknown")
            ts = rec.get("trust_score")
            info.trust_score = float(ts) if ts is not None else None
            info.tx_count = rec.get("tx_count")
            try:
                history = fabric.get_cid_history(d)
            except Exception:
                history = []
            info.cid_count = len(history)
            if history:
                info.latest_cid = history[-1].get("cid_hash", "")
        # Overlay live FL trust/exclusion (more current than on-chain)
        if d in fl.trust_scores:
            info.trust_score = fl.trust_scores[d]
        info.excluded = d in fl.excluded_devices
        devices.append(info)
    return devices


def get_cid_history(device_id: str) -> List[CIDEntry]:
    try:
        fabric = _get_fabric()
        records = fabric.get_cid_history(device_id)
    except Exception:
        return []
    return [
        CIDEntry(
            device_id=r.get("device_id", device_id),
            cid_hash=r.get("cid_hash", ""),
            timestamp=str(r.get("timestamp", "")),
            tx_id=r.get("tx_id", ""),
        )
        for r in records
    ]


# ── Logs ─────────────────────────────────────────────────────────────────────
def tail(path: str, n: int) -> List[str]:
    """Last n lines of a file, cheaply. Never raises."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, "rb") as f:
            return [
                ln.decode("utf-8", "replace").rstrip("\n")
                for ln in deque(f, maxlen=n)
            ]
    except OSError:
        return []


def get_logs() -> Dict[str, List[str]]:
    return {
        name: tail(settings.log_file(fname), settings.LOG_TAIL_LINES)
        for name, fname in settings.LOG_SOURCES.items()
    }


# ── Live pipeline (inferred from gateway log) ────────────────────────────────
_CID_OK   = re.compile(r"IPFS upload OK: CID=([\w.]+)")
_NOCOMMIT = re.compile(r"store_cid did NOT commit for (\S+)")
_INGEST   = re.compile(r'"POST /ingest')
_ANOMALY  = re.compile(r"ANOMALY: (\S+)")
_DEVICE   = re.compile(r"for (\S+):|from (\S+)")


def get_pipeline_state() -> PipelineState:
    """Infer the furthest pipeline stage the most recent /ingest tick reached by
    scanning the tail of the gateway log. Read-only, best-effort."""
    lines = tail(settings.log_file("gateway.log"), 40)
    st = PipelineState()
    if not lines:
        return st

    for ln in lines:  # oldest -> newest; keep overwriting so we end on latest
        if _ANOMALY.search(ln):
            m = _ANOMALY.search(ln)
            st = PipelineState(stage=4, ok=True, anomaly=True,
                               last_device=m.group(1), last_line=ln)
        elif _NOCOMMIT.search(ln):
            m = _NOCOMMIT.search(ln)
            # IPFS succeeded, ledger write failed -> furthest good stage = IPFS(2)
            st = PipelineState(stage=2, ok=False,
                               last_device=m.group(1), last_line=ln)
        elif _CID_OK.search(ln):
            st = PipelineState(stage=2, ok=True, last_line=ln)
        elif _INGEST.search(ln):
            # A 200 on /ingest with no error nearby -> full path incl. ledger + FL
            if st.stage < 4 and st.ok:
                st = PipelineState(stage=4, ok=True, last_line=ln)
    return st


def pipeline_labels() -> List[str]:
    return PIPELINE_STAGES
