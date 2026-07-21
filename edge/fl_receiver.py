# edge/fl_receiver.py
import os, sys, numpy as np, logging
from flask import Flask, request, jsonify
from dotenv import load_dotenv
load_dotenv()

def create_receiver(port: int, device_id: str):
    PROJECT_ROOT = os.getenv("PROJECT_ROOT")
    MODEL_DIR    = os.path.join(PROJECT_ROOT, "models")
    LOG_PATH     = os.path.join(os.getenv("LOGS_PATH"), f"{device_id}-receiver.log")
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format=f"%(asctime)s [{device_id.upper()} RECV] %(message)s",
        handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()]
    )
    log = logging.getLogger(device_id)
    app = Flask(f"fl_receiver_{device_id}")

    @app.route("/receive_weights", methods=["POST"])
    def receive_weights():
        data    = request.json
        weights = np.array(data["weights"], dtype=np.float32)
        rnd     = data.get("round", 0)
        path    = os.path.join(MODEL_DIR, f"global_weights_{device_id}.npy")
        np.save(path, weights)
        log.info(f"Round {rnd} global model received and saved: {path}")
        return jsonify({"status": "updated", "round": rnd, "device_id": device_id})

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok", "device_id": device_id, "port": port})

    return app, port

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port",   type=int, required=True)
    parser.add_argument("--device", type=str, required=True)
    args = parser.parse_args()
    app, port = create_receiver(args.port, args.device)
    app.run(host="0.0.0.0", port=port, debug=False)
