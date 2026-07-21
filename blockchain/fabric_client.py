"""
HybridGuard Fabric Client — single integration point for all Fabric calls.
Uses subprocess to WSL peer CLI as the integration method for Phase 3.

Every method in this class is the ONLY way Python services interact with Fabric.
gateway_server.py, fl_server.py, and fl_event_listener.py all import from here.

CORRECTION 5.2 APPLIED: Environment variables are inlined into the bash -c command
string rather than passed via subprocess env=, because Windows env= does not
propagate into the WSL instance spawned by the wsl launcher.
"""

import subprocess, json, os, logging, time
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

    def _wsl_cmd(self, cmd_str: str) -> subprocess.CompletedProcess:
        """Run a command in WSL via login shell to get proper PATH."""
        return subprocess.run(
            ["wsl", "-u", "mehrab", "--", "bash", "--login", "-c", cmd_str],
            capture_output=True, text=True, timeout=30
        )

    # Endorsement/commit errors that stem from transient cross-peer state
    # skew on a hot key, not from a logic fault. Re-proposing after a short
    # pause lets both endorsing peers catch up to the same read-set version.
    # This mirrors what the Fabric Gateway SDK retries automatically; the raw
    # peer CLI path does not, so we do it here.
    _TRANSIENT_ERRORS = (
        "ProposalResponsePayloads do not match",
        "MVCC_READ_CONFLICT",
        "PHANTOM_READ_CONFLICT",
    )

    def _invoke(self, function: str, args: list, retries: int = 3,
                backoff: float = 1.5) -> bool:
        """Execute a chaincode invoke (read-write transaction).

        Retries transient endorsement/commit conflicts (see _TRANSIENT_ERRORS)
        with a fixed backoff. Deterministic failures return immediately.
        """
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

        for attempt in range(1, retries + 1):
            result = self._wsl_cmd(cmd_str)
            if result.returncode == 0:
                if attempt > 1:
                    log.info(f"Fabric invoke OK: {function}({args[:2]}) "
                             f"[succeeded on attempt {attempt}]")
                else:
                    log.info(f"Fabric invoke OK: {function}({args[:2]})")
                return True

            stderr = result.stderr or ""
            transient = any(e in stderr for e in self._TRANSIENT_ERRORS)
            if transient and attempt < retries:
                log.warning(f"Fabric invoke [{function}] transient conflict, "
                            f"retry {attempt}/{retries - 1} after {backoff}s: "
                            f"{stderr[:120]}")
                time.sleep(backoff)
                continue

            log.error(f"Fabric invoke failed [{function}]: {stderr[:200]}")
            return False

        return False

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

        result = self._wsl_cmd(cmd_str)
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
        """Returns 'OK' or 'BREACH'. Uses invoke since CheckGasLimit writes state."""
        args_json = json.dumps([device_id])
        payload = f'{{"function":"CheckGasLimit","Args":{args_json}}}'

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

        result = self._wsl_cmd(cmd_str)
        if result.returncode != 0:
            log.error(f"CheckGasLimit failed: {result.stderr[:200]}")
            return "OK"
        output = result.stderr + result.stdout
        if "BREACH" in output:
            return "BREACH"
        return "OK"

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
