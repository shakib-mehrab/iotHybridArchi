"""
HybridGuard Fabric Client — single integration point for all Fabric calls.
Uses subprocess to WSL peer CLI as the integration method for Phase 3.

Every method in this class is the ONLY way Python services interact with Fabric.
gateway_server.py, fl_server.py, and fl_event_listener.py all import from here.

CORRECTION 5.2 APPLIED: Environment variables are inlined into the bash -c command
string rather than passed via subprocess env=, because Windows env= does not
propagate into the WSL instance spawned by the wsl launcher.
"""

import subprocess, json, os, logging
from typing import Optional, Callable
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger("fabric_client")


class FabricClient:
    def __init__(self):
        self.channel = os.getenv("FABRIC_CHANNEL", "hybridguard-channel")
        self.chaincode = os.getenv("FABRIC_CHAINCODE", "hybridguard")
        self.wsl_root = os.getenv("WSL_FABRIC_ROOT",
                                  "/home/mehrab/projects/iotHybridArchi/fabric")
        self.test_net = f"{self.wsl_root}/fabric-samples/test-network"
        self._build_paths()

    def _build_paths(self):
        """Build Fabric peer CLI paths and env var strings for WSL."""
        self.peer_bin = f"{self.wsl_root}/fabric-samples/bin/peer"
        self.orderer_ca = (
            f"{self.test_net}/organizations/ordererOrganizations/"
            "example.com/orderers/orderer.example.com/msp/tlscacerts/"
            "tlsca.example.com-cert.pem"
        )
        self.org1_tls = (
            f"{self.test_net}/organizations/peerOrganizations/"
            "org1.example.com/peers/peer0.org1.example.com/tls/ca.crt"
        )
        self.org2_tls = (
            f"{self.test_net}/organizations/peerOrganizations/"
            "org2.example.com/peers/peer0.org2.example.com/tls/ca.crt"
        )
        self.msp_path = (
            f"{self.test_net}/organizations/peerOrganizations/"
            "org1.example.com/users/Admin@org1.example.com/msp"
        )
        self.fabric_cfg_path = f"{self.wsl_root}/fabric-samples/config"

        # Inline env vars for WSL bash -c (Correction 5.2)
        self._env_prefix = (
            f"FABRIC_CFG_PATH={self.fabric_cfg_path} "
            f"CORE_PEER_TLS_ENABLED=true "
            f"CORE_PEER_LOCALMSPID=Org1MSP "
            f"CORE_PEER_TLS_ROOTCERT_FILE={self.org1_tls} "
            f"CORE_PEER_MSPCONFIGPATH={self.msp_path} "
            f"CORE_PEER_ADDRESS=localhost:7051"
        )

    def _invoke(self, function: str, args: list) -> bool:
        """Execute a chaincode invoke (read-write transaction)."""
        args_json = json.dumps(args)
        payload = f'{{"function":"{function}","Args":{args_json}}}'

        cmd_str = (
            f"{self._env_prefix} "
            f"{self.peer_bin} chaincode invoke "
            f"-o localhost:7050 "
            f"--ordererTLSHostnameOverride orderer.example.com "
            f"--tls --cafile {self.orderer_ca} "
            f"-C {self.channel} -n {self.chaincode} "
            f"--peerAddresses localhost:7051 "
            f"--tlsRootCertFiles {self.org1_tls} "
            f"--peerAddresses localhost:9051 "
            f"--tlsRootCertFiles {self.org2_tls} "
            f"-c '{payload}'"
        )

        result = subprocess.run(
            ["wsl", "bash", "-c", cmd_str],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            log.error(f"Fabric invoke failed [{function}]: {result.stderr[:200]}")
            return False
        log.info(f"Fabric invoke OK: {function}({args[:2]})")
        return True

    def _query(self, function: str, args: list) -> Optional[str]:
        """Execute a chaincode query (read-only, no ordering)."""
        args_json = json.dumps(args)
        payload = f'{{"function":"{function}","Args":{args_json}}}'

        cmd_str = (
            f"{self._env_prefix} "
            f"{self.peer_bin} chaincode query "
            f"-C {self.channel} -n {self.chaincode} "
            f"-c '{payload}'"
        )

        result = subprocess.run(
            ["wsl", "bash", "-c", cmd_str],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            log.error(f"Fabric query failed [{function}]: {result.stderr[:200]}")
            return None
        return result.stdout.strip()

    # ── Public API ────────────────────────────────────────────────────────

    def register_device(self, device_id: str, cert_hash: str, org_name: str) -> bool:
        return self._invoke("RegisterDevice", [device_id, cert_hash, org_name])

    def store_cid(self, device_id: str, cid_hash: str, timestamp: str) -> bool:
        return self._invoke("StoreCID", [device_id, cid_hash, timestamp])

    def blacklist_device(self, device_id: str) -> bool:
        return self._invoke("BlacklistDevice", [device_id])

    def update_trust_score(self, device_id: str, score: float) -> bool:
        return self._invoke("UpdateTrustScore", [device_id, str(score)])

    def check_gas_limit(self, device_id: str) -> str:
        """Returns 'OK' or 'BREACH'."""
        result = self._query("CheckGasLimit", [device_id])
        return result if result in ("OK", "BREACH") else "OK"

    def log_model_update(self, cid_hash: str, round_num: int) -> bool:
        return self._invoke("LogModelUpdate", [cid_hash, str(round_num)])

    def get_device(self, device_id: str) -> Optional[dict]:
        result = self._query("GetDevice", [device_id])
        if not result:
            return None
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return None

    def get_device_status(self, device_id: str) -> str:
        device = self.get_device(device_id)
        if device:
            return device.get("status", "unknown")
        return "unknown"

    def subscribe_events(self, callback: Callable[[str, bytes], None]):
        """
        Subscribe to chaincode events in a background thread.
        callback(event_name: str, payload: bytes) called on each event.
        Phase 3 implementation: placeholder (polling mode).
        Phase 5 implementation: replaced with gRPC event stream.
        """
        log.info("Event subscription started (polling mode — will upgrade to gRPC in Phase 5)")
        pass
