import numpy as np, xgboost as xgb, joblib, json, os, time
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt, seaborn as sns
from sklearn.metrics import classification_report, roc_auc_score, f1_score, confusion_matrix
from dotenv import load_dotenv
load_dotenv()

PROJECT_ROOT = os.getenv("PROJECT_ROOT")
DATA_DIR     = os.path.join(PROJECT_ROOT, "dataset", "processed")
MODEL_DIR    = os.path.join(PROJECT_ROOT, "models")
BENCH_DIR    = os.path.join(PROJECT_ROOT, "benchmarks", "results")
os.makedirs(BENCH_DIR, exist_ok=True)

print("[1/5] Loading data...")
X_train = np.load(os.path.join(DATA_DIR, "X_train.npy"))
X_test  = np.load(os.path.join(DATA_DIR, "X_test.npy"))
y_train = np.load(os.path.join(DATA_DIR, "y_train.npy"))
y_test  = np.load(os.path.join(DATA_DIR, "y_test.npy"))
print(f"      Train: {X_train.shape} | Test: {X_test.shape}")

print("\n[2/5] Configuring XGBoost...")
try:
    t = xgb.XGBClassifier(tree_method='hist', device='cuda', n_estimators=5)
    t.fit(X_train[:50], y_train[:50])
    DEVICE = 'cuda'
    print("      GPU OK - GTX 1650 ready")
except Exception as e:
    DEVICE = 'cpu'
    print(f"      GPU unavailable ({e}) - using CPU")

model = xgb.XGBClassifier(
    n_estimators     = 300,
    max_depth        = 6,
    learning_rate    = 0.1,
    subsample        = 0.8,
    colsample_bytree = 0.8,
    min_child_weight = 5,
    scale_pos_weight = float((y_train==0).sum()) / float((y_train==1).sum()),
    tree_method      = 'hist',
    device           = DEVICE,
    eval_metric      = 'logloss',
    random_state     = 42,
    n_jobs           = -1,
)

print(f"\n[3/5] Training ({len(X_train):,} samples, device={DEVICE})...")
t0 = time.time()
model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=50)
train_time = time.time() - t0
print(f"      Training time: {train_time:.1f}s")

print("\n[4/5] Evaluating...")
y_pred  = model.predict(X_test)
y_proba = model.predict_proba(X_test)[:,1]
f1  = f1_score(y_test, y_pred)
auc = roc_auc_score(y_test, y_proba)
cm  = confusion_matrix(y_test, y_pred)
print(classification_report(y_test, y_pred, target_names=['Normal','Anomaly']))
print(f"ROC-AUC: {auc:.4f}  |  F1: {f1:.4f}")

fig, ax = plt.subplots(figsize=(6,5))
sns.heatmap(cm, annot=True, fmt='d', cmap='Blues', ax=ax,
            xticklabels=['Normal','Anomaly'], yticklabels=['Normal','Anomaly'])
ax.set_title(f'XGBoost - F1={f1:.3f}  AUC={auc:.3f}')
plt.tight_layout()
plt.savefig(os.path.join(BENCH_DIR, "confusion_matrix.png"), dpi=150)
plt.close()

print("\n[5/5] Saving model...")
MODEL_PATH = os.path.join(MODEL_DIR, "xgb_anomaly.json")
model.save_model(MODEL_PATH)

with open(os.path.join(BENCH_DIR, "benchmark_1_detection_accuracy.json"), "w") as f:
    json.dump({
        "f1_score": float(f1), "roc_auc": float(auc),
        "training_time_sec": float(train_time), "device": DEVICE,
        "n_estimators": 300, "confusion_matrix": cm.tolist(),
    }, f, indent=2)

print(f"\n[DONE] Model: {MODEL_PATH}")
if f1 >= 0.90:
    print(f"[PASS] Benchmark 1: F1={f1:.4f} >= 0.90")
else:
    print(f"[WARNING] F1={f1:.4f} below 0.90 - may need tuning")
