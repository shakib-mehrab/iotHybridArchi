"""
HybridGuard IPFS Client — single integration point for all IPFS calls.
All services import from here. No service calls IPFS directly.

CORRECTION 5.3 APPLIED: Uses plain requests against Kubo HTTP RPC API
instead of ipfshttpclient==0.8.0a2 which is incompatible with modern Kubo.
Public method signatures (upload, upload_file, get, is_available) unchanged.
"""

import os, logging, requests
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger("ipfs_client")


class IPFSClient:
    def __init__(self):
        self.api_url = os.getenv("IPFS_API_URL", "http://127.0.0.1:5001")

    def upload(self, content: str) -> str:
        """Upload string content to IPFS. Returns CID hash."""
        url = f"{self.api_url}/api/v0/add"
        files = {"file": ("data.txt", content.encode("utf-8"))}
        resp = requests.post(url, files=files)
        resp.raise_for_status()
        cid = resp.json()["Hash"]
        log.info(f"IPFS upload OK: CID={cid[:20]}...")
        return cid

    def upload_file(self, filepath: str) -> str:
        """Upload a file to IPFS. Returns CID hash."""
        url = f"{self.api_url}/api/v0/add"
        with open(filepath, "rb") as f:
            files = {"file": (os.path.basename(filepath), f)}
            resp = requests.post(url, files=files)
        resp.raise_for_status()
        cid = resp.json()["Hash"]
        log.info(f"IPFS file upload OK: {filepath} -> CID={cid[:20]}...")
        return cid

    def get(self, cid: str) -> str:
        """Retrieve content from IPFS by CID."""
        url = f"{self.api_url}/api/v0/cat"
        resp = requests.post(url, params={"arg": cid})
        resp.raise_for_status()
        return resp.text

    def is_available(self) -> bool:
        """Check if IPFS daemon is reachable."""
        try:
            url = f"{self.api_url}/api/v0/id"
            resp = requests.post(url, timeout=5)
            return resp.status_code == 200
        except (requests.ConnectionError, requests.Timeout):
            return False
