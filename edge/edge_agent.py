# edge/edge_agent.py
"""
HybridGuard Edge Agent — Layer 1
Runs on real Raspberry Pi 4 devices. Uses psutil for real telemetry.
For simulation, use simulator.py instead.
"""

import os, sys, json, time, threading, logging
import numpy as np, psutil, xgboost as xgb, joblib
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
import requests
from dotenv import load_dotenv

load_dotenv()

class EdgeAgent:
    def __init__(self, config_path: str):
        with open(config_path) as f:
            self.cfg = json.load(f)

        self.device_id    = self.cfg["device_id"]
        self.gateway_url  = self.cfg["gateway_url"]
        self.fl_server    = self.cfg["fl_server_url"]
        self.threshold    = self.cfg["anomaly_threshold"]
        self.tx_quota     = self.cfg["tx_quota"]
        self.interval     = self.cfg["telemetry_interval_seconds"]
        self.fl_interval  = self.cfg["fl_round_interval_seconds"]

        self.model  = xgb.XGBClassifier()
        self.model.load_model(self.cfg["model_path"])
        self.scaler = joblib.load(self.cfg["scaler_path"])

        with open(self.cfg["private_key_path"], "rb") as f:
            self.private_key = serialization.load_pem_private_key(f.read(), password=None)

        os.makedirs(os.path.dirname(self.cfg["log_path"]), exist_ok=True)
        logging.basicConfig(
            level=logging.INFO,
            format=f"%(asctime)s [{self.device_id.upper()}] %(message)s",
            handlers=[logging.FileHandler(self.cfg["log_path"]), logging.StreamHandler()]
        )
        self.log = logging.getLogger(self.device_id)

        self.tx_count    = 0
        self.window_start = time.time()

    def collect_telemetry(self) -> dict:
        return {
            "net_bytes": psutil.net_io_counters().bytes_sent,
            "cpu_pct":   psutil.cpu_percent(interval=1),
            "mem_pct":   psutil.virtual_memory().percent,
            "disk_pct":  psutil.disk_usage("/").percent,
            "timestamp": time.time(),
        }

    def infer(self, telemetry: dict) -> float:
        features = np.array([[
            telemetry["net_bytes"], telemetry["cpu_pct"],
            telemetry["mem_pct"],   telemetry["disk_pct"],
        ]], dtype=np.float32)
        scaled = self.scaler.transform(features)
        return float(self.model.predict_proba(scaled)[0][1])

    def sign(self, payload: str) -> str:
        sig = self.private_key.sign(
            payload.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
        return sig.hex()

    def check_gas_limit(self) -> bool:
        now = time.time()
        if now - self.window_start > 60:
            self.tx_count    = 0
            self.window_start = now
        self.tx_count += 1
        return self.tx_count > self.tx_quota

    def run(self):
        self.log.info(f"Edge agent started. Gateway: {self.gateway_url}")
        threading.Thread(target=self._fl_thread, daemon=True).start()

        while True:
            try:
                telemetry     = self.collect_telemetry()
                anomaly_score = self.infer(telemetry)
                anomaly       = anomaly_score > self.threshold

                if self.check_gas_limit():
                    self.log.warning("GAS LIMIT BREACHED")
                    requests.post(f"{self.gateway_url}/gas_breach",
                                  json={"device_id": self.device_id}, timeout=5)
                    time.sleep(60)
                    continue

                payload = json.dumps({
                    "device_id":    self.device_id,
                    "anomaly_score": anomaly_score,
                    "telemetry":    telemetry,
                    "timestamp":    telemetry["timestamp"],
                })
                signature = self.sign(payload)

                resp = requests.post(f"{self.gateway_url}/ingest", json={
                    "device_id": self.device_id,
                    "payload":   payload,
                    "signature": signature,
                    "anomaly":   anomaly,
                }, timeout=10)

                self.log.info(
                    f"score={anomaly_score:.3f} anomaly={anomaly} "
                    f"-> {resp.json().get('status')} ({resp.json().get('latency_ms','?')}ms)"
                )

            except Exception as e:
                self.log.error(f"Agent loop error: {e}")

            time.sleep(self.interval)

    def _fl_thread(self):
        time.sleep(30)
        while True:
            try:
                # Simplified: send random weight delta as placeholder
                # Real implementation: train on local telemetry history
                weights = np.random.rand(10).astype(np.float32)
                requests.post(f"{self.fl_server}/submit_weights", json={
                    "device_id": self.device_id,
                    "weights":   weights.tolist(),
                    "n_samples": 100,
                }, timeout=10)
                self.log.info("FL weight delta submitted")
            except Exception as e:
                self.log.error(f"FL thread error: {e}")
            time.sleep(self.fl_interval)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, required=True)
    args = parser.parse_args()
    agent = EdgeAgent(args.config)
    agent.run()
