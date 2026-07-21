# scripts/run_simulation.py
import subprocess, sys, os, time, argparse, threading
from dotenv import load_dotenv
load_dotenv()

PROJECT_ROOT = os.getenv("PROJECT_ROOT")
PYTHON       = os.path.join(PROJECT_ROOT, "hybridguard-env", "Scripts", "python.exe")
SIM_SCRIPT   = os.path.join(PROJECT_ROOT, "edge", "simulator.py")

TESTS = {
    "FULL_NORMAL": [
        ("sim-device-01", "NORMAL_OPERATION", 300),
        ("sim-device-02", "NORMAL_OPERATION", 300),
        ("sim-device-03", "NORMAL_OPERATION", 300),
        ("sim-device-04", "NORMAL_OPERATION", 300),
    ],
    "SINGLE_ATTACK": [
        ("sim-device-01", "NORMAL_OPERATION",    300),
        ("sim-device-02", "MIRAI_FLOOD",         120),
        ("sim-device-03", "NORMAL_OPERATION",    300),
        ("sim-device-04", "NORMAL_OPERATION",    300),
    ],
    "MULTI_ATTACK": [
        ("sim-device-01", "MIRAI_FLOOD",         120),
        ("sim-device-02", "NORMAL_OPERATION",    300),
        ("sim-device-03", "GRADUAL_DEGRADATION",  90),
        ("sim-device-04", "NORMAL_OPERATION",    300),
    ],
    "POISONING_TEST": [
        ("sim-device-01", "NORMAL_OPERATION",    300),
        ("sim-device-02", "NORMAL_OPERATION",    300),
        ("sim-device-03", "MODEL_POISONING",     300),
        ("sim-device-04", "NORMAL_OPERATION",    300),
    ],
}

def run_device(device, scenario, duration):
    cmd = [PYTHON, SIM_SCRIPT,
           "--device", device, "--scenario", scenario, "--duration", str(duration)]
    subprocess.run(cmd)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", required=True, choices=list(TESTS.keys()))
    args = parser.parse_args()

    print(f"[SIM] Running test: {args.test}")
    threads = []
    for device, scenario, duration in TESTS[args.test]:
        t = threading.Thread(target=run_device, args=(device, scenario, duration))
        t.start()
        threads.append(t)
        time.sleep(0.5)

    for t in threads:
        t.join()
    print("[SIM] Test complete.")
