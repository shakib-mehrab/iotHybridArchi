# edge/simulator.py
"""
HybridGuard Device Simulator
Generates synthetic telemetry for 4 scenarios.
Sends signed payloads to gateway exactly as edge_agent.py would.
"""

import os, sys, json, time, random, threading, argparse, logging
import numpy as np, xgboost as xgb, joblib
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
import requests
from dotenv import load_dotenv
load_dotenv()

PROJECT_ROOT = os.getenv("PROJECT_ROOT")
sys.path.insert(0, PROJECT_ROOT)

GATEWAY_URL   = f"http://127.0.0.1:{os.getenv('GATEWAY_PORT', '8080')}"
FL_SERVER_URL = f"http://127.0.0.1:{os.getenv('FL_SERVER_PORT', '8081')}"
THRESHOLD     = float(os.getenv("ANOMALY_THRESHOLD", "0.85"))
GAS_LIMIT     = int(os.getenv("GAS_LIMIT", "50"))
KEYS_PATH     = os.getenv("KEYS_PATH")

def load_key(device_id: str):
    path = os.path.join(KEYS_PATH, device_id, "device_private.pem")
    with open(path, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)

def sign(payload: str, private_key) -> str:
    return private_key.sign(
        payload.encode(), padding.PKCS1v15(), hashes.SHA256()).hex()

def load_model():
    model = xgb.XGBClassifier()
    model.load_model(os.path.join(PROJECT_ROOT, "models", "xgb_anomaly.json"))
    scaler = joblib.load(os.path.join(PROJECT_ROOT, "models", "feature_scaler.pkl"))
    return model, scaler

def send(device_id: str, telemetry: dict, private_key, model, scaler):
    features = np.array([[
        telemetry["net_bytes"], telemetry["cpu_pct"],
        telemetry["mem_pct"],   telemetry["disk_pct"],
    ]], dtype=np.float32)
    score   = float(model.predict_proba(scaler.transform(features))[0][1])
    anomaly = score > THRESHOLD
    payload = json.dumps({
        "device_id": device_id, "anomaly_score": score,
        "telemetry": telemetry, "timestamp": time.time(),
    })
    sig  = sign(payload, private_key)
    try:
        resp = requests.post(f"{GATEWAY_URL}/ingest", json={
            "device_id": device_id, "payload": payload,
            "signature": sig, "anomaly": anomaly,
        }, timeout=5)
        return score, resp.json()
    except Exception as e:
        return score, {"status": "error", "reason": str(e)}

SCENARIOS = {
    "NORMAL_OPERATION": lambda t: {
        "net_bytes": random.randint(100, 800),
        "cpu_pct":   random.uniform(10, 40),
        "mem_pct":   random.uniform(30, 60),
        "disk_pct":  random.uniform(15, 35),
    },
    "GRADUAL_DEGRADATION": lambda t: {
        "net_bytes": int(500 + (t/60.0) * 7500),
        "cpu_pct":   20 + (t/60.0) * 70,
        "mem_pct":   random.uniform(40, 70),
        "disk_pct":  random.uniform(15, 35),
    },
    "MIRAI_FLOOD": lambda t: {
        "net_bytes": random.randint(40000, 60000),
        "cpu_pct":   random.uniform(85, 99),
        "mem_pct":   random.uniform(70, 90),
        "disk_pct":  random.uniform(20, 40),
    },
    "MODEL_POISONING": lambda t: {
        "net_bytes": random.randint(100, 500),
        "cpu_pct":   random.uniform(15, 35),
        "mem_pct":   random.uniform(30, 50),
        "disk_pct":  random.uniform(15, 30),
    },
}

def run(device_id: str, scenario: str, duration: int = 300):
    log = logging.getLogger(device_id)
    logging.basicConfig(level=logging.INFO,
                        format=f"%(asctime)s [{device_id.upper()}] %(message)s")
    private_key   = load_key(device_id)
    model, scaler = load_model()
    fn            = SCENARIOS[scenario]
    t_start       = time.time()
    tx_count      = 0
    window_start  = time.time()

    log.info(f"Starting scenario: {scenario} ({duration}s)")
    t = 0
    while duration < 0 or t < duration:
        telemetry = fn(t)

        # Gas limit check
        now = time.time()
        if now - window_start > 60:
            tx_count = 0; window_start = now
        tx_count += 1
        if tx_count > GAS_LIMIT:
            log.warning("GAS LIMIT BREACHED")
            requests.post(f"{GATEWAY_URL}/gas_breach",
                          json={"device_id": device_id}, timeout=5)
            time.sleep(60); tx_count = 0; window_start = time.time()
            continue

        score, resp = send(device_id, telemetry, private_key, model, scaler)
        log.info(f"t={t}s score={score:.3f} -> {resp.get('status')}")

        # FL: submit manipulated weights for POISONING scenario
        if scenario == "MODEL_POISONING":
            poisoned = (np.random.rand(10) * 10).astype(np.float32)
            try:
                requests.post(f"{FL_SERVER_URL}/submit_weights", json={
                    "device_id": device_id,
                    "weights": poisoned.tolist(), "n_samples": 100,
                }, timeout=5)
            except: pass

        time.sleep(5)
        t += 5

    log.info(f"Scenario {scenario} complete.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--device",   required=True)
    parser.add_argument("--scenario", required=True,
                        choices=list(SCENARIOS.keys()))
    parser.add_argument("--duration", type=int, default=300)
    args = parser.parse_args()
    run(args.device, args.scenario, args.duration)
