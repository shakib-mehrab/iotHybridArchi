# config/settings.py
"""
HybridGuard — single source of truth for the dashboard + automation layer.

Everything the dashboard needs to know about *where* things live (ports, URLs,
paths, executables, device IDs, poll cadences) is read from .env here, with
sensible defaults so a missing key never crashes the UI. Nothing is hardcoded
elsewhere in dashboard/ — import from this module instead.

Read-only: importing this module has no side effects beyond loading .env.
"""

import os
import shutil
from dotenv import load_dotenv

load_dotenv()


def _get(key: str, default: str = "") -> str:
    val = os.getenv(key)
    return val if val is not None and val != "" else default


def _int(key: str, default: int) -> int:
    try:
        return int(_get(key, str(default)))
    except (TypeError, ValueError):
        return default


def _float(key: str, default: float) -> float:
    try:
        return float(_get(key, str(default)))
    except (TypeError, ValueError):
        return default


# ── Paths ──────────────────────────────────────────────────────────────────
PROJECT_ROOT = _get("PROJECT_ROOT", os.getcwd())
LOGS_PATH    = _get("LOGS_PATH", os.path.join(PROJECT_ROOT, "logs"))
STATE_PATH   = _get("STATE_PATH", os.path.join(PROJECT_ROOT, "state"))
KEYS_PATH    = _get("KEYS_PATH", os.path.join(PROJECT_ROOT, "keys"))

# ── Hosts / ports ────────────────────────────────────────────────────────────
SERVICE_HOST      = _get("SERVICE_HOST", "127.0.0.1")
GATEWAY_PORT      = _int("GATEWAY_PORT", 8080)
FL_SERVER_PORT    = _int("FL_SERVER_PORT", 8081)
FL_RECEIVER_BASE  = _int("FL_RECEIVER_PORT_BASE", 8082)
DASHBOARD_PORT    = _int("DASHBOARD_PORT", 8090)

GATEWAY_URL   = f"http://{SERVICE_HOST}:{GATEWAY_PORT}"
FL_SERVER_URL = f"http://{SERVICE_HOST}:{FL_SERVER_PORT}"
IPFS_API_URL  = _get("IPFS_API_URL", "http://127.0.0.1:5001")

# ── Devices ──────────────────────────────────────────────────────────────────
DEVICE_IDS = [
    d.strip() for d in
    _get("DEVICE_IDS", "sim-device-01,sim-device-02,sim-device-03,sim-device-04").split(",")
    if d.strip()
]


def receiver_port(device_id: str) -> int:
    """FL receiver port for a device = base + its index in DEVICE_IDS."""
    try:
        return FL_RECEIVER_BASE + DEVICE_IDS.index(device_id)
    except ValueError:
        return FL_RECEIVER_BASE


def receiver_url(device_id: str) -> str:
    return f"http://{SERVICE_HOST}:{receiver_port(device_id)}"


# ── Simulation ───────────────────────────────────────────────────────────────
# Kept in sync with edge/simulator.py SCENARIOS and scripts/run_simulation.py TESTS.
SCENARIOS = [
    "NORMAL_OPERATION",
    "GRADUAL_DEGRADATION",
    "MIRAI_FLOOD",
    "MODEL_POISONING",
]

# Multi-device presets mirrored from scripts/run_simulation.py so the dashboard
# and the CLI stay identical. Each entry: (device, scenario, duration_seconds).
PRESETS = {
    "FULL_NORMAL": [
        ("sim-device-01", "NORMAL_OPERATION", 300),
        ("sim-device-02", "NORMAL_OPERATION", 300),
        ("sim-device-03", "NORMAL_OPERATION", 300),
        ("sim-device-04", "NORMAL_OPERATION", 300),
    ],
    "SINGLE_ATTACK": [
        ("sim-device-01", "NORMAL_OPERATION", 300),
        ("sim-device-02", "MIRAI_FLOOD", 120),
        ("sim-device-03", "NORMAL_OPERATION", 300),
        ("sim-device-04", "NORMAL_OPERATION", 300),
    ],
    "MULTI_ATTACK": [
        ("sim-device-01", "MIRAI_FLOOD", 120),
        ("sim-device-02", "NORMAL_OPERATION", 300),
        ("sim-device-03", "GRADUAL_DEGRADATION", 90),
        ("sim-device-04", "NORMAL_OPERATION", 300),
    ],
    "POISONING_TEST": [
        ("sim-device-01", "NORMAL_OPERATION", 300),
        ("sim-device-02", "NORMAL_OPERATION", 300),
        ("sim-device-03", "MODEL_POISONING", 300),
        ("sim-device-04", "NORMAL_OPERATION", 300),
    ],
}

# ── Executables ──────────────────────────────────────────────────────────────
def _detect_python() -> str:
    explicit = _get("PYTHON_BIN")
    if explicit:
        return explicit
    venv = os.path.join(PROJECT_ROOT, "hybridguard-env", "Scripts", "python.exe")
    if os.path.exists(venv):
        return venv
    import sys
    return sys.executable


PYTHON_BIN   = _detect_python()
IPFS_BIN     = _get("IPFS_BIN") or (shutil.which("ipfs") or "ipfs")
SIM_SCRIPT   = os.path.join(PROJECT_ROOT, "edge", "simulator.py")

# ── Fabric ───────────────────────────────────────────────────────────────────
FABRIC_PEER_CONTAINER = _get("FABRIC_PEER_CONTAINER", "peer0.org1.example.com")
FABRIC_CHANNEL        = _get("FABRIC_CHANNEL", "hybridguard-channel")
FABRIC_CHAINCODE      = _get("FABRIC_CHAINCODE", "hybridguard")

# ── Poll cadences / timeouts (seconds) ───────────────────────────────────────
DASHBOARD_POLL_SECONDS = _float("DASHBOARD_POLL_SECONDS", 3)
FABRIC_POLL_SECONDS    = _float("FABRIC_POLL_SECONDS", 10)
HTTP_TIMEOUT           = _float("DASHBOARD_HTTP_TIMEOUT", 2)
LOG_TAIL_LINES         = _int("DASHBOARD_LOG_TAIL_LINES", 30)

# ── Log files the dashboard tails ────────────────────────────────────────────
def log_file(name: str) -> str:
    return os.path.join(LOGS_PATH, name)


# name -> filename, shown in the Live Logs panel
LOG_SOURCES = {
    "gateway":   "gateway.log",
    "fl_server": "fl_server.log",
    "simulator": "simulator.log",
}
for _d in DEVICE_IDS:
    LOG_SOURCES[f"{_d}-recv"] = f"{_d}-receiver.log"


# ── Service registry: what the System Status panel checks ────────────────────
# kind drives how services.py probes it:
#   "docker" -> container running    "http_health" -> GET /health
#   "http_status" -> GET /status     "ipfs" -> POST /api/v0/id
def service_registry():
    services = [
        {
            "name": "Docker / Fabric",
            "kind": "docker",
            "target": FABRIC_PEER_CONTAINER,
            "hint": "Start Docker Desktop, then bring the Fabric network up in WSL "
                    "(test-network: ./network.sh up). Do NOT use 'network.sh down' — "
                    "that wipes the ledger.",
        },
        {
            "name": "IPFS daemon",
            "kind": "ipfs",
            "target": IPFS_API_URL,
            "hint": "Run 'ipfs daemon' in a terminal (RPC API on :5001).",
        },
        {
            "name": "Gateway",
            "kind": "http_health",
            "target": f"{GATEWAY_URL}/health",
            "hint": "python gateway/gateway_server.py",
        },
        {
            "name": "FL Server",
            "kind": "http_status",
            "target": f"{FL_SERVER_URL}/status",
            "hint": "python fl/fl_server.py",
        },
    ]
    for d in DEVICE_IDS:
        services.append({
            "name": f"Receiver {d[-2:]}",
            "kind": "http_health",
            "target": f"{receiver_url(d)}/health",
            "hint": f"python edge/fl_receiver.py --device {d} --port {receiver_port(d)}",
        })
    return services
