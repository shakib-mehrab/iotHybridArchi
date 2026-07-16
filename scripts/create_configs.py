import json, os
from dotenv import load_dotenv

load_dotenv()
PROJECT_ROOT = os.getenv("PROJECT_ROOT")
MODEL_PATH = os.getenv("MODEL_PATH")
SCALER_PATH = os.getenv("SCALER_PATH")
KEYS_PATH = os.getenv("KEYS_PATH")
LOGS_PATH = os.getenv("LOGS_PATH")
GATEWAY_PORT = os.getenv("GATEWAY_PORT", "8080")
FL_SERVER_PORT = os.getenv("FL_SERVER_PORT", "8081")
THRESHOLD = float(os.getenv("ANOMALY_THRESHOLD", "0.85"))
GAS_LIMIT = int(os.getenv("GAS_LIMIT", "50"))
FL_INTERVAL = int(os.getenv("FL_ROUND_INTERVAL_SECONDS", "14400"))

devices = {
    "sim-device-01": 0,
    "sim-device-02": 1,
    "sim-device-03": 2,
    "sim-device-04": 3,
}

for device_id, offset in devices.items():
    config = {
        "device_id": device_id,
        "gateway_url": f"http://127.0.0.1:{GATEWAY_PORT}",
        "fl_server_url": f"http://127.0.0.1:{FL_SERVER_PORT}",
        "fl_receiver_port": 8082 + offset,
        "anomaly_threshold": THRESHOLD,
        "tx_quota": GAS_LIMIT,
        "telemetry_interval_seconds": 5,
        "fl_round_interval_seconds": FL_INTERVAL,
        "model_path": MODEL_PATH,
        "scaler_path": SCALER_PATH,
        "private_key_path": os.path.join(KEYS_PATH, device_id, "device_private.pem"),
        "device_id_path": os.path.join(KEYS_PATH, device_id, "device_id.txt"),
        "log_path": os.path.join(LOGS_PATH, f"{device_id}.log"),
    }
    out = os.path.join(PROJECT_ROOT, "config", "device_configs", f"{device_id}.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(config, f, indent=2)
    print(f"[OK] {out}")

print("\n[DONE] All device configs created.")
