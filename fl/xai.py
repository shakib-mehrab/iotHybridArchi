# fl/xai.py
import numpy as np, shap, lime.lime_tabular, joblib, os
import xgboost as xgb
from dotenv import load_dotenv
load_dotenv()

FEATURE_NAMES = ["net_bytes", "cpu_pct", "mem_pct", "disk_pct"]

class XAIEngine:
    def __init__(self):
        model_path  = os.getenv("MODEL_PATH")
        scaler_path = os.getenv("SCALER_PATH")
        self.model  = xgb.XGBClassifier()
        self.model.load_model(model_path)
        self.scaler = joblib.load(scaler_path)
        bg = np.random.rand(100, 4) * [50000, 100, 100, 100]
        bg_scaled = self.scaler.transform(bg)
        self.shap_explainer = shap.TreeExplainer(self.model)
        self.lime_explainer = lime.lime_tabular.LimeTabularExplainer(
            bg_scaled, feature_names=FEATURE_NAMES,
            class_names=["normal", "anomaly"],
            mode="classification", discretize_continuous=True,
        )

    def explain_lime(self, raw_instance: np.ndarray) -> dict:
        """Real-time operator alert. raw_instance: shape (4,) unscaled."""
        scaled = self.scaler.transform(raw_instance.reshape(1,-1))[0]
        exp = self.lime_explainer.explain_instance(
            scaled, self.model.predict_proba, num_features=4, num_samples=300)
        return {feat: round(val, 4) for feat, val in exp.as_list()}

    def explain_shap(self, raw_instance: np.ndarray) -> dict:
        """Forensic post-incident analysis. raw_instance: shape (4,) unscaled."""
        scaled = self.scaler.transform(raw_instance.reshape(1,-1))
        vals   = self.shap_explainer.shap_values(scaled)
        if isinstance(vals, list): vals = vals[1][0]
        else: vals = vals[0]
        return {FEATURE_NAMES[i]: round(float(vals[i]), 4) for i in range(4)}

    def format_alert(self, device_id: str, score: float, lime_exp: dict) -> str:
        top   = sorted(lime_exp.items(), key=lambda x: abs(x[1]), reverse=True)
        lines = [f"[ALERT] {device_id} | score={score:.3f}"]
        for feat, val in top[:3]:
            lines.append(f"  {feat}: {'^ HIGH' if val > 0 else 'v LOW'} ({val:+.4f})")
        return "\n".join(lines)
    
