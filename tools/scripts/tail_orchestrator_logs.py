import subprocess
from pathlib import Path

def cli(args, orch_url):
    script = Path.home() / "bobiverse" / "tools" / "scripts" / "tail_orchestrator_logs.sh"
    if not script.exists():
        print(f"[tail-orch-logs] Script not found: {script}")
        return
    subprocess.call([str(script)])
