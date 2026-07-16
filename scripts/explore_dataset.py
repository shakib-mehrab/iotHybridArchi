import pandas as pd, os
from dotenv import load_dotenv
load_dotenv()

DATASET_PATH = os.path.join(os.getenv("DATASET_PATH"), "DNN-EdgeIoT-dataset.csv")
print(f"Dataset: {DATASET_PATH}")
print(f"File size: {os.path.getsize(DATASET_PATH) / (1024**2):.1f} MB")

print("\nLoading first 5 rows...")
chunk = pd.read_csv(DATASET_PATH, nrows=5)
print(f"Columns ({len(chunk.columns)}):")
for i, col in enumerate(chunk.columns.tolist()):
    print(f"  [{i:2d}] {col}")

print("\nFirst 3 rows (transposed):")
print(chunk.head(3).T.to_string())

print("\n--- Checking label column ---")
df_sample = pd.read_csv(DATASET_PATH, nrows=100000)
for label_col in ['Attack_type', 'label', 'Label', 'attack_type', 'class']:
    if label_col in df_sample.columns:
        print(f"Label column found: '{label_col}'")
        print(df_sample[label_col].value_counts())
        break
else:
    print("WARNING: No known label column found!")
    print("All columns:", df_sample.columns.tolist())

print("\n--- Checking feature candidates ---")
for name, candidates in [
    ("net_bytes", ['flow_bytes_per_second', 'Flow Bytes/s', 'flow_byts_per_sec']),
    ("cpu_pct (packet rate)", ['flow_packets_per_second', 'Flow Packets/s', 'flow_pkts_per_sec']),
    ("mem_pct (header len)", ['Header_Length', 'header_length']),
    ("disk_pct (duration)", ['Duration', 'duration', 'Flow Duration']),
]:
    found = [c for c in candidates if c in df_sample.columns]
    status = found[0] if found else "NOT FOUND"
    print(f"  {name:25s} -> {status}")
