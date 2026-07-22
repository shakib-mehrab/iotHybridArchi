# dashboard/sim_runner.py
"""
Simulation launcher for the dashboard.

This is the ONE place the dashboard starts a process. It does exactly what you
would type in a terminal — `python edge/simulator.py --device D --scenario S
--duration N` — as a subprocess, and captures its stdout/stderr into
logs/simulator.log so the Live Logs panel shows it in real time. It never
touches chaincode, FL, or gateway state directly; the simulator drives the real
pipeline exactly as before.

Supports:
  - single runs (one device + scenario + duration)
  - multi-device presets (config.settings.PRESETS), launched concurrently,
    mirroring scripts/run_simulation.py

Running processes are tracked in-memory so the UI can list and stop them.
"""

import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from config import settings


@dataclass
class SimProc:
    key: str                       # unique label, e.g. "sim-device-01/MIRAI_FLOOD"
    device: str
    scenario: str
    duration: int
    proc: subprocess.Popen
    started_at: float = field(default_factory=lambda: time.time())

    @property
    def running(self) -> bool:
        return self.proc.poll() is None

    @property
    def elapsed(self) -> int:
        return int(time.time() - self.started_at)


class SimRunner:
    def __init__(self):
        self._procs: Dict[str, SimProc] = {}
        self._lock = threading.Lock()
        self._log_path = settings.log_file("simulator.log")
        os.makedirs(os.path.dirname(self._log_path), exist_ok=True)

    # ── launching ────────────────────────────────────────────────────────────
    def _spawn(self, device: str, scenario: str, duration: int) -> Optional[SimProc]:
        key = f"{device}/{scenario}"
        with self._lock:
            existing = self._procs.get(key)
            if existing and existing.running:
                return None  # already running this exact combo

            cmd = [
                settings.PYTHON_BIN, settings.SIM_SCRIPT,
                "--device", device,
                "--scenario", scenario,
                "--duration", str(duration),
            ]
            # Append (not truncate) so all concurrent sims share one tailed log.
            logf = open(self._log_path, "a", buffering=1, encoding="utf-8", errors="replace")
            logf.write(f"\n=== launch {key} duration={duration}s ===\n")
            proc = subprocess.Popen(
                cmd,
                stdout=logf, stderr=subprocess.STDOUT,
                cwd=settings.PROJECT_ROOT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            sp = SimProc(key=key, device=device, scenario=scenario,
                         duration=duration, proc=proc)
            self._procs[key] = sp
            return sp

    def run_single(self, device: str, scenario: str, duration: int) -> bool:
        """Launch one device. Returns False if that device/scenario is already
        running or the scenario is unknown."""
        if scenario not in settings.SCENARIOS:
            return False
        return self._spawn(device, scenario, duration) is not None

    def run_preset(self, name: str) -> int:
        """Launch a multi-device preset concurrently. Returns count launched."""
        preset = settings.PRESETS.get(name)
        if not preset:
            return 0
        launched = 0
        for device, scenario, duration in preset:
            if self._spawn(device, scenario, duration) is not None:
                launched += 1
            time.sleep(0.3)  # small stagger, mirrors run_simulation.py
        return launched

    # ── stopping ─────────────────────────────────────────────────────────────
    def stop(self, key: str) -> bool:
        with self._lock:
            sp = self._procs.get(key)
        if not sp or not sp.running:
            return False
        sp.proc.terminate()
        try:
            sp.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            sp.proc.kill()
        return True

    def stop_all(self) -> int:
        keys = list(self._procs.keys())
        return sum(1 for k in keys if self.stop(k))

    # ── inspection ─────────────────────────────────────────────────────────────
    def running(self) -> List[SimProc]:
        with self._lock:
            # Drop finished procs so the list reflects reality.
            for k in [k for k, v in self._procs.items() if not v.running]:
                self._procs.pop(k, None)
            return list(self._procs.values())

    def any_running(self) -> bool:
        return len(self.running()) > 0


# module-level singleton the UI imports
runner = SimRunner()
