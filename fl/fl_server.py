# fl/fl_server.py
import os, sys, json, time, threading, logging
import numpy as np
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()
PROJECT_ROOT = os.getenv("PROJECT_ROOT")
sys.path.insert(0, PROJECT_ROOT)

from fl.xai          import XAIEngine
from fl.trust_manager import TrustManager
from blockchain.fabric_client import FabricClient
from blockchain.ipfs_client   import IPFSClient

LOG_PATH  = os.path.join(os.getenv("LOGS_PATH"), "fl_server.log")
BENCH_DIR = os.getenv("BENCHMARKS_PATH")
STATE_DIR = os.getenv("STATE_PATH")
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
os.makedirs(BENCH_DIR, exist_ok=True)
os.makedirs(STATE_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [FL-SERVER] %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()]
)
log = logging.getLogger("fl_server")

# ── State ─────────────────────────────────────────────────────────────────
excluded_devices = set()
pending_weights  = {}
fl_round_number  = 0
MIN_CONTRIBUTIONS = int(os.getenv("FL_MIN_CONTRIBUTIONS", "2"))
DEVICE_PORTS = {
    "sim-device-01": "http://127.0.0.1:8082",
    "sim-device-02": "http://127.0.0.1:8083",
    "sim-device-03": "http://127.0.0.1:8084",
    "sim-device-04": "http://127.0.0.1:8085",
}
lock = threading.Lock()

# ── Components ────────────────────────────────────────────────────────────
xai     = XAIEngine()
trust   = TrustManager()
fabric  = FabricClient()
ipfs    = IPFSClient()

def on_trust_change(device_id, score):
    if score <= 0.0 and device_id not in excluded_devices:
        log.warning(f"Trust=0 — excluding {device_id}")
        excluded_devices.add(device_id)
        pending_weights.pop(device_id, None)

trust.register_callback(on_trust_change)

app = Flask(__name__)

@app.route("/submit_weights", methods=["POST"])
def submit_weights():
    data      = request.json
    device_id = data.get("device_id")
    weights   = data.get("weights")
    n_samples = data.get("n_samples", 100)
    if device_id in excluded_devices:
        return jsonify({"status": "excluded"}), 403
    t = trust.get(device_id)
    with lock:
        pending_weights[device_id] = {
            "weights": np.array(weights, dtype=np.float32),
            "trust": t, "n_samples": n_samples,
        }
        log.info(f"Weights from {device_id} (trust={t:.3f})")
        if len(pending_weights) >= MIN_CONTRIBUTIONS:
            threading.Thread(target=aggregate, daemon=True).start()
    return jsonify({"status": "accepted", "trust_weight": t})

@app.route("/exclude", methods=["POST"])
def exclude():
    device_id = request.json.get("device_id")
    excluded_devices.add(device_id)
    pending_weights.pop(device_id, None)
    log.info(f"Excluded by blockchain event: {device_id}")
    return jsonify({"status": "excluded"})

@app.route("/contribution_ready", methods=["POST"])
def contribution_ready():
    data      = request.json
    device_id = data.get("device_id")
    score     = data.get("anomaly_score", 0.0)
    if device_id not in excluded_devices:
        new_t = trust.update(device_id, score)
        log.info(f"Trust updated: {device_id} -> {new_t:.3f}")
        if new_t < float(os.getenv("ANOMALY_THRESHOLD", "0.3")):
            fabric.update_trust_score(device_id, new_t)
    return jsonify({"status": "ok"})

@app.route("/trigger_round", methods=["POST"])
def trigger_round():
    threading.Thread(target=aggregate, daemon=True).start()
    return jsonify({"status": "aggregation_triggered"})

@app.route("/status", methods=["GET"])
def status():
    return jsonify({
        "fl_round":         fl_round_number,
        "pending_devices":  list(pending_weights.keys()),
        "excluded_devices": list(excluded_devices),
        "trust_scores":     trust.get_all(),
    })

@app.route("/explain", methods=["POST"])
def explain():
    data      = request.json
    instance  = np.array(data["features"], dtype=np.float32)
    score     = data.get("anomaly_score", 0.0)
    device_id = data.get("device_id", "unknown")
    lime_exp  = xai.explain_lime(instance)
    shap_exp  = xai.explain_shap(instance)
    alert     = xai.format_alert(device_id, score, lime_exp)
    log.info(alert)
    return jsonify({"lime": lime_exp, "shap": shap_exp, "alert": alert})

def aggregate():
    global fl_round_number
    with lock:
        if not pending_weights: return
        snapshot        = dict(pending_weights)
        pending_weights.clear()
    fl_round_number += 1
    log.info(f"[FL Round {fl_round_number}] Aggregating {len(snapshot)} devices...")
    total_trust = sum(v["trust"] for v in snapshot.values())
    if total_trust == 0:
        log.warning("All trust=0 — skipping round")
        return
    global_weights = sum(
        v["weights"] * (v["trust"] / total_trust) for v in snapshot.values()
    )
    model_path = os.path.join(os.getenv("PROJECT_ROOT"), "models", "global_weights.npy")
    np.save(model_path, global_weights)
    try:
        cid = ipfs.upload_file(model_path)
        fabric.log_model_update(cid, fl_round_number)
        log.info(f"Global model CID: {cid}")
    except Exception as e:
        log.error(f"IPFS/Fabric model log failed: {e}")
        cid = "N/A"
    import requests as req
    for device_id, url in DEVICE_PORTS.items():
        if device_id in excluded_devices: continue
        try:
            req.post(f"{url}/receive_weights",
                     json={"weights": global_weights.tolist(), "round": fl_round_number},
                     timeout=5)
            log.info(f"Model pushed to {device_id}")
        except Exception as e:
            log.warning(f"Push failed to {device_id}: {e}")
    with open(os.path.join(BENCH_DIR, f"fl_round_{fl_round_number}.json"), "w") as f:
        json.dump({
            "round": fl_round_number,
            "participants": list(snapshot.keys()),
            "excluded": list(excluded_devices),
            "global_model_cid": cid,
            "trust_scores": {k: v["trust"] for k,v in snapshot.items()},
            "timestamp": time.time(),
        }, f, indent=2)
    log.info(f"[FL Round {fl_round_number}] COMPLETE")

if __name__ == "__main__":
    log.info(f"FL Server starting on port {os.getenv('FL_SERVER_PORT', '8081')}...")
    app.run(host="0.0.0.0",
            port=int(os.getenv("FL_SERVER_PORT", "8081")),
            debug=False, threaded=True)
