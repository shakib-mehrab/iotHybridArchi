# fl/trust_manager.py
import numpy as np
from collections import deque
from typing import Dict, Callable

class TrustManager:
    """Event-triggered LSTM-approximated behavioral trust scorer."""

    def __init__(self, decay_rate: float = 0.08, history_size: int = 20,
                 untrusted_threshold: float = 0.3):
        self.decay_rate          = decay_rate
        self.history_size        = history_size
        self.untrusted_threshold = untrusted_threshold
        self.scores:    Dict[str, float]     = {}
        self.history:   Dict[str, deque]     = {}
        self.callbacks: list                 = []

    def register_callback(self, fn: Callable):
        self.callbacks.append(fn)

    def update(self, device_id: str, anomaly_score: float) -> float:
        if device_id not in self.scores:
            self.scores[device_id]  = 1.0
            self.history[device_id] = deque(maxlen=self.history_size)
        self.history[device_id].append(anomaly_score)
        recent_mean = np.mean(self.history[device_id])
        old = self.scores[device_id]
        new = max(0.0, old - self.decay_rate * recent_mean)
        if anomaly_score < 0.2 and old < 1.0:
            new = min(1.0, new + 0.005)
        self.scores[device_id] = new
        for cb in self.callbacks:
            cb(device_id, new)
        return new

    def get(self, device_id: str) -> float:
        return self.scores.get(device_id, 1.0)

    def get_all(self) -> dict:
        return dict(self.scores)
