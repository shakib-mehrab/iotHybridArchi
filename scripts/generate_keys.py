import os, hashlib, json
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from dotenv import load_dotenv

load_dotenv()
PROJECT_ROOT = os.getenv("PROJECT_ROOT")
KEYS_PATH = os.getenv("KEYS_PATH")

devices = ["sim-device-01", "sim-device-02",
           "sim-device-03", "sim-device-04", "pc-gateway"]
key_registry = {}

for device_id in devices:
    key_dir = os.path.join(KEYS_PATH, device_id)
    os.makedirs(key_dir, exist_ok=True)

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    priv_path = os.path.join(key_dir, "device_private.pem")
    with open(priv_path, "wb") as f:
        f.write(private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption()
        ))

    pub_bytes = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo
    )
    with open(os.path.join(key_dir, "device_public.pem"), "wb") as f:
        f.write(pub_bytes)

    with open(os.path.join(key_dir, "device_id.txt"), "w") as f:
        f.write(device_id)

    cert_hash = hashlib.sha256(pub_bytes).hexdigest()
    key_registry[device_id] = {
        "cert_hash": cert_hash,
        "key_dir": key_dir
    }
    print(f"[OK] {device_id}: cert_hash={cert_hash[:16]}...")

with open(os.path.join(KEYS_PATH, "key_registry.json"), "w") as f:
    json.dump(key_registry, f, indent=2)

print(f"\n[DONE] All keypairs generated.")
print(f"       Registry: {KEYS_PATH}\\key_registry.json")
