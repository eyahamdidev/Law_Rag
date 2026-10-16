"""Start the downloaded local model without administrator rights or a visible helper window."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]

def healthy():
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/health", timeout=2) as response:
            return response.status == 200
    except Exception:
        return False

def start():
    if healthy():
        print("Local model is already running.")
        return 0
    model = ROOT / "data" / "models" / "Qwen3-1.7B-Q4_K_M.gguf"
    runtime = next((ROOT / "data" / "runtime" / "llama").rglob("llama-server.exe"), None)
    if not runtime or not model.is_file():
        print("Local model resources are not prepared. Run scripts/prepare_local_runtime.py first.")
        return 1
    logs = ROOT / "data" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    command = [str(runtime), "--model", str(model), "--alias", "local-legal", "--host", "127.0.0.1", "--port", "11434",
               "--ctx-size", "8192", "--parallel", "1", "--threads", str(min(os.cpu_count() or 4, 6)),
               "--n-gpu-layers", "0", "--jinja", "--reasoning-budget", "0"]
    with (logs / "model.stdout.log").open("ab") as stdout, (logs / "model.stderr.log").open("ab") as stderr:
        process = subprocess.Popen(command, cwd=ROOT, stdout=stdout, stderr=stderr,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    (ROOT / "data" / "model-process.json").write_text(json.dumps({"pid": process.pid, "executable": str(runtime)}), encoding="utf-8")
    for _ in range(40):
        if healthy():
            print("Local multilingual model is ready on 127.0.0.1:11434.")
            return 0
        if process.poll() is not None:
            print("Local model stopped during startup. See data/logs/model.stderr.log.")
            return 1
        time.sleep(1)
    print("Local model is still starting. See data/logs/model.stderr.log.")
    return 1

if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-api",action="store_true")
    args=parser.parse_args()
    if args.check_api:
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/api/legal/status",timeout=3) as response:
                ready=json.load(response).get("service")=="startup-legal-agent"
            raise SystemExit(0 if ready else 1)
        except (OSError,ValueError):
            raise SystemExit(1)
    raise SystemExit(start())
