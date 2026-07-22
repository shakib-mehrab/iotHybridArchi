# scripts/register_devices.py
"""
Re-register all HybridGuard devices on the Fabric ledger.

WHY THIS EXISTS
---------------
Devices live in the Fabric *world state*. If the network is redeployed fresh
(`network.sh up` -> `createChannel` -> `deployCC`), the world state is wiped and
every device disappears — GetDevice returns "not found" and the gateway then
rejects StoreCID on every telemetry tick. No service auto-registers devices;
registration is a manual on-chain write. This script makes recovery one command
instead of hand-running `peer chaincode invoke RegisterDevice` per device.

WHAT IT DOES
------------
Reads keys/key_registry.json, and for every device entry (cert_hash present)
calls fabric_client.register_device(device_id, cert_hash, ORG_NAME). It is
idempotent-safe to re-run: RegisterDevice on an already-registered device just
re-writes the same record. Devices are read from the key registry, so adding a
new device to the registry automatically includes it here.

USAGE
-----
    python scripts\register_devices.py                 # register all in registry
    python scripts\register_devices.py sim-device-01   # register only named ones
    python scripts\register_devices.py --skip-existing  # skip devices already on-chain

Requires Fabric network up + chaincode deployed (same preconditions as any
gateway/fl_server run). NOT tested yet — verify against a live network before
relying on it.
"""

import os
import sys
import json
import argparse

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = os.getenv("PROJECT_ROOT")
if PROJECT_ROOT:
    sys.path.insert(0, PROJECT_ROOT)

from blockchain.fabric_client import FabricClient

KEYS_PATH = os.getenv("KEYS_PATH", os.path.join(PROJECT_ROOT or ".", "keys"))
ORG_NAME = os.getenv("ORG_NAME", "HybridGuardOrg")


def load_registry() -> dict:
    """Load keys/key_registry.json. Only entries with a cert_hash are devices."""
    registry_file = os.path.join(KEYS_PATH, "key_registry.json")
    with open(registry_file) as f:
        return json.load(f)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Register HybridGuard devices from key_registry.json onto the ledger."
    )
    parser.add_argument(
        "devices",
        nargs="*",
        help="Specific device IDs to register (default: all in the registry).",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip devices already present on the ledger (GetDevice returns a record).",
    )
    args = parser.parse_args()

    registry = load_registry()
    fabric = FabricClient()

    # Which devices to act on. Only registry entries that carry a cert_hash are
    # real devices; skip anything else (e.g. a gateway key with no cert_hash).
    candidates = [
        (dev_id, meta["cert_hash"])
        for dev_id, meta in registry.items()
        if isinstance(meta, dict) and meta.get("cert_hash")
    ]
    if args.devices:
        wanted = set(args.devices)
        candidates = [(d, h) for (d, h) in candidates if d in wanted]
        missing = wanted - {d for (d, _) in candidates}
        for m in missing:
            print(f"[WARN] {m} not found in key_registry.json — skipping")

    if not candidates:
        print("No matching devices to register.")
        return 1

    ok, failed, skipped = 0, 0, 0
    for device_id, cert_hash in candidates:
        if args.skip_existing and fabric.get_device(device_id) is not None:
            print(f"[SKIP] {device_id} already registered")
            skipped += 1
            continue

        success = fabric.register_device(device_id, cert_hash, ORG_NAME)
        if success:
            print(f"[ OK ] {device_id} registered (org={ORG_NAME})")
            ok += 1
        else:
            print(f"[FAIL] {device_id} registration did NOT commit")
            failed += 1

    print(f"\nDone: {ok} registered, {skipped} skipped, {failed} failed.")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
