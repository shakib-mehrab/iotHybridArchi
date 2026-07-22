# dashboard/models.py
"""
Plain dataclasses for the dashboard. No DB, no ORM — these are just typed
snapshots produced by services.py and consumed by app.py. Every field has a
default so a partial/failed probe still yields a renderable object.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class ServiceHealth:
    name: str
    up: bool = False
    detail: str = ""          # short status line, e.g. "round=3" or "not reachable"
    hint: str = ""            # how to activate it if down
    target: str = ""          # url/container being probed


@dataclass
class DeviceInfo:
    device_id: str
    registered: bool = False
    status: str = "unknown"           # trusted / blacklisted / unknown
    trust_score: Optional[float] = None
    cid_count: int = 0
    latest_cid: str = ""
    tx_count: Optional[int] = None
    excluded: bool = False            # excluded from FL aggregation


@dataclass
class CIDEntry:
    device_id: str
    cid_hash: str
    timestamp: str
    tx_id: str = ""


@dataclass
class FLStatus:
    round: int = 0
    pending_devices: List[str] = field(default_factory=list)
    excluded_devices: List[str] = field(default_factory=list)
    trust_scores: Dict[str, float] = field(default_factory=dict)
    reachable: bool = False


@dataclass
class PipelineState:
    """Furthest stage the most recent telemetry tick reached, inferred from the
    gateway log. Stages, in order:
        signed -> gateway_recv -> ipfs -> ledger -> fl
    'stage' is the index of the furthest reached; 'ok' is False if the last
    tick errored (e.g. store_cid did not commit)."""
    stage: int = -1
    ok: bool = True
    last_device: str = ""
    last_line: str = ""
    anomaly: bool = False


PIPELINE_STAGES = ["Signed", "Gateway", "IPFS", "Ledger", "FL Trust"]
