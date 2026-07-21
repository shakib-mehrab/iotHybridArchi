# gateway/gateway_server.py
"""
HybridGuard Gateway Server — Layer 2
Port: 8080
Uses blockchain/fabric_client.py and blockchain/ipfs_client.py exclusively.
Never calls peer CLI directly.
"""

import os, sys, json, time, logging, threading
from flask import Flask, request, jsonify
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from dotenv import load_dotenv

load_dotenv()
PROJECT_ROOT  = os.getenv("PROJECT_ROOT")
sys.path.insert(0, PROJECT_ROOT)

from blockchain.fabric_client import FabricClient
from blockchain.ipfs_client   import IPFSClient

FL_SERVER_URL = f"http://127.0.0.1:{os.getenv('FL_SERVER_PORT', '8081')}"
KEYS_PATH     = os.getenv("KEYS_PATH")
LOG_PATH      = os.path.join(os.getenv("LOGS_PATH"), "gateway.log")
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [GATEWAY] %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()]
)
log = logging.getLogger("gateway")

# Load key registry
with open(os.path.join(KEYS_PATH, "key_registry.json")) as f:
    KEY_REGISTRY = json.load(f)

def load_public_key(device_id: str):
    pub_path = os.path.join(KEY_REGISTRY[device_id]["key_dir"], "device_public.pem")
    with open(pub_path, "rb") as f:
        return serialization.load_pem_public_key(f.read())

fabric = FabricClient()
ipfs   = IPFSClient()

app        = Flask(__name__)
BLACKLISTED = set()

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status":            "ok",
        "gateway":           "pc-gateway",
        "ipfs_available":    ipfs.is_available(),
        "blacklisted_count": len(BLACKLISTED),
    })

@app.route("/ingest", methods=["POST"])
def ingest():
    t_start   = time.perf_counter()
    data      = request.json
    device_id = data.get("device_id")
    payload   = data.get("payload")
    signature = data.get("signature")
    anomaly   = data.get("anomaly", False)

    if not all([device_id, payload, signature]):
        return jsonify({"status": "error", "reason": "missing fields"}), 400

    # 1. Local blacklist cache
    if device_id in BLACKLISTED:
        return jsonify({"status": "rejected", "reason": "blacklisted"}), 403

    # 2. Blockchain status check
    bc_status = fabric.get_device_status(device_id)
    if bc_status == "blacklisted":
        BLACKLISTED.add(device_id)
        return jsonify({"status": "rejected", "reason": "blacklisted on chain"}), 403

    # 3. RSA signature verification
    try:
        pub_key = load_public_key(device_id)
        pub_key.verify(
            bytes.fromhex(signature),
            payload.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256()
        )
    except Exception as e:
        log.warning(f"Invalid signature from {device_id}: {e}")
        return jsonify({"status": "error", "reason": "invalid signature"}), 401

    # 4. Upload to IPFS via ipfs_client wrapper
    try:
        cid = ipfs.upload(payload)
    except Exception as e:
        log.error(f"IPFS upload failed: {e}")
        return jsonify({"status": "error", "reason": "IPFS unavailable"}), 503

    # 5. Store CID on blockchain via fabric_client wrapper
    timestamp = str(int(time.time()))
    success = fabric.store_cid(device_id, cid, timestamp)
    if not success:
        log.warning(f"store_cid did NOT commit for {device_id}: "
                    f"CID {cid} uploaded to IPFS but NOT written to ledger")

    # 6. Handle anomaly
    if anomaly:
        log.warning(f"ANOMALY: {device_id} — triggering mitigation")
        fabric.blacklist_device(device_id)
        BLACKLISTED.add(device_id)
        try:
            import requests as req
            req.post(f"{FL_SERVER_URL}/exclude",
                     json={"device_id": device_id}, timeout=2)
        except:
            pass
        latency_ms = (time.perf_counter() - t_start) * 1000
        log.info(f"Mitigation complete: {latency_ms:.1f}ms")
        return jsonify({"status": "anomaly_detected", "cid": cid,
                        "mitigation_latency_ms": round(latency_ms, 2)})

    # 7. Notify FL server
    try:
        import requests as req
        anomaly_score = json.loads(payload).get("anomaly_score", 0)
        req.post(f"{FL_SERVER_URL}/contribution_ready",
                 json={"device_id": device_id, "cid": cid,
                       "anomaly_score": anomaly_score}, timeout=2)
    except:
        pass

    latency_ms = (time.perf_counter() - t_start) * 1000
    return jsonify({"status": "ok", "cid": cid,
                    "latency_ms": round(latency_ms, 2)})

@app.route("/gas_breach", methods=["POST"])
def gas_breach():
    device_id = request.json.get("device_id")
    log.warning(f"GAS LIMIT BREACH: {device_id}")
    fabric.blacklist_device(device_id)
    BLACKLISTED.add(device_id)
    try:
        import requests as req
        req.post(f"{FL_SERVER_URL}/exclude",
                 json={"device_id": device_id}, timeout=2)
    except:
        pass
    return jsonify({"status": "blacklisted", "device_id": device_id})

if __name__ == "__main__":
    log.info(f"Gateway starting on port {os.getenv('GATEWAY_PORT', '8080')}...")
    app.run(host="0.0.0.0",
            port=int(os.getenv("GATEWAY_PORT", "8080")),
            debug=False, threaded=True)
