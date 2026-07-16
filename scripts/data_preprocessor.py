"""
HybridGuard Data Preprocessor
Dataset: DNN-EdgeIIoT-dataset.csv (2.2M rows, 63 raw packet features)

Feature mapping rationale:
  The DNN-EdgeIIoT-dataset uses raw packet-level features (not CICFlowMeter flow
  features). We map 4 columns to HybridGuard's telemetry proxy features:

  net_bytes  <- tcp.len        : TCP payload length = network I/O volume
  cpu_pct    <- tcp.flags      : TCP flag patterns differ sharply attack vs normal
  mem_pct    <- mqtt.len       : IoT message buffer sizes = memory pressure proxy
  disk_pct   <- tcp.seq        : Sequence number patterns = connection volume proxy

  Labels: Attack_type == 'Normal' -> 0, anything else -> 1 (binary anomaly)
"""
import pandas as pd, numpy as np, joblib, os, json
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from tqdm import tqdm
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = os.getenv("PROJECT_ROOT")
DATASET_PATH = os.path.join(os.getenv("DATASET_PATH"), "DNN-EdgeIIoT-dataset.csv")
CHUNK_SIZE = 100_000
OUT_DIR = os.path.join(PROJECT_ROOT, "dataset", "processed")
MODEL_DIR = os.path.join(PROJECT_ROOT, "models")
os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(MODEL_DIR, exist_ok=True)

print(f"[1/6] Dataset: {DATASET_PATH}")
sample = pd.read_csv(DATASET_PATH, nrows=3, low_memory=False)
all_cols = sample.columns.tolist()
print(f"      Columns ({len(all_cols)})")

FEATURE_MAP = {
    "net_bytes": "tcp.len",
    "cpu_pct": "tcp.flags",
    "mem_pct": "mqtt.len",
    "disk_pct": "tcp.seq",
}
LABEL_COL = "Attack_type"
NORMAL_LABELS = ["Normal", "normal", "NORMAL", "Benign", "benign"]

for feat, col in FEATURE_MAP.items():
    if col not in all_cols:
        raise ValueError(f"Column '{col}' not found in dataset! Available: {all_cols}")

print(f"\n[2/6] Feature mapping:")
for feat, col in FEATURE_MAP.items():
    print(f"      {feat:10s} <- {col}")
print(f"      label      <- {LABEL_COL}")

print("\n[3/6] Loading in chunks (100k rows each)...")
use_cols = list(FEATURE_MAP.values()) + [LABEL_COL]
X_chunks, y_chunks = [], []

for chunk in tqdm(pd.read_csv(DATASET_PATH, chunksize=CHUNK_SIZE,
                              usecols=use_cols, low_memory=False)):
    chunk = chunk.dropna(subset=[LABEL_COL])
    X_chunk = pd.DataFrame({
        k: pd.to_numeric(chunk[v], errors="coerce").fillna(0)
        for k, v in FEATURE_MAP.items()
    })
    y_chunk = chunk[LABEL_COL].apply(
        lambda x: 0 if str(x).strip() in NORMAL_LABELS else 1
    ).values
    X_chunks.append(X_chunk.values.astype(np.float32))
    y_chunks.append(y_chunk.astype(np.int32))

X = np.vstack(X_chunks)
y = np.concatenate(y_chunks)
print(f"      Total: {len(X):,} | Normal: {(y==0).sum():,} | Anomaly: {(y==1).sum():,}")
print(f"      Anomaly ratio: {(y==1).mean():.1%}")

print("\n[4/6] Clipping outliers at 99th percentile...")
for i in range(X.shape[1]):
    p99 = np.percentile(X[:, i], 99)
    if p99 > 0:
        X[:, i] = np.clip(X[:, i], 0, p99)

print("[5/6] Scaling features...")
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, stratify=y, random_state=42)
scaler = StandardScaler()
X_train = scaler.fit_transform(X_train)
X_test = scaler.transform(X_test)

print("[6/6] Saving...")
np.save(os.path.join(OUT_DIR, "X_train.npy"), X_train)
np.save(os.path.join(OUT_DIR, "X_test.npy"), X_test)
np.save(os.path.join(OUT_DIR, "y_train.npy"), y_train)
np.save(os.path.join(OUT_DIR, "y_test.npy"), y_test)
joblib.dump(scaler, os.path.join(MODEL_DIR, "feature_scaler.pkl"))

meta = {
    "dataset_file": "DNN-EdgeIIoT-dataset.csv",
    "features": list(FEATURE_MAP.keys()),
    "feature_mapping": FEATURE_MAP,
    "label_column": LABEL_COL,
    "total_samples": int(len(X)),
    "train_samples": int(len(X_train)),
    "test_samples": int(len(X_test)),
    "normal_count": int((y == 0).sum()),
    "anomaly_count": int((y == 1).sum()),
    "normal_pct": float((y == 0).mean()),
    "anomaly_pct": float((y == 1).mean()),
    "note": "DNN-EdgeIIoT raw packet features mapped to HybridGuard telemetry proxies"
}
with open(os.path.join(OUT_DIR, "dataset_meta.json"), "w") as f:
    json.dump(meta, f, indent=2)

print(f"\n[DONE] Train: {len(X_train):,} | Test: {len(X_test):,}")
print(f"       Scaler: {MODEL_DIR}\\feature_scaler.pkl")
print(f"       Metadata: {OUT_DIR}\\dataset_meta.json")
