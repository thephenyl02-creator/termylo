"""Local Termylo controls: start, revoke, stop and hot-restart."""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from .supervisor import SupervisorApproval, Unavailable, rpc

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts" / "start-tunnel-secure.ps1"

def tunnel_pids() -> list[int]:
    if os.name != "nt":
        return []
    expected = str(ROOT / "tunnel-client" / "tunnel-client.exe").replace("'", "''")
    script = ("$p='" + expected + "';"
              "$x=Get-CimInstance Win32_Process -Filter "
              '"Name=\'tunnel-client.exe\'" -ErrorAction SilentlyContinue;'
              "$x|Where-Object {$_.ExecutablePath -eq $p -and "
              "$_.CommandLine -match '(?i)\\brun\\b.*--profile\\s+termylo\\b'}"
              "|Select-Object -ExpandProperty ProcessId")
    report = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=20)
    if report.returncode:
        raise RuntimeError("Cannot query the local tunnel.")
    return [int(x) for x in report.stdout.splitlines() if x.strip().isdigit()]

def stop_tunnel() -> int:
    pids = tunnel_pids()
    for pid in pids:
        subprocess.run(["taskkill.exe", "/PID", str(pid), "/F"],
                       capture_output=True, timeout=12, check=False)
    return len(pids)

def start_tunnel() -> dict:
    if tunnel_pids():
        return {"status": "already_running"}
    if not LAUNCHER.is_file():
        return {"status": "error", "error": "Missing tunnel launcher."}
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", str(LAUNCHER), "-Headless"],
        capture_output=True, text=True, timeout=25)
    if result.returncode:
        return {"status": "error", "error": "Local tunnel failed to start."}
    return {"status": "started" if tunnel_pids() else "error",
            "approval": "not_granted_by_start"}

def revoke() -> dict:
    try:
        result = rpc("revoke", start=False)
        return {"status": "revoked", "approval": result.get("status")}
    except (Unavailable, OSError):
        return {"status": "already_closed"}

def stop() -> dict:
    approval = revoke()
    count = stop_tunnel()
    try:
        rpc("stop", start=False)
        try:
            rpc("ping", start=False)  # Wake broker's accept loop to exit.
        except (Unavailable, OSError):
            pass
    except (Unavailable, OSError):
        pass
    return {"status": "stopped", "approval": approval,
            "tunnel_processes_stopped": count}

def restart() -> dict:
    # Only the independent supervisor may restart its own tunnel.
    # Never spawn the restart helper under a worker-owned Windows Job Object.
    try:
        return rpc("restart", start=True)
    except (Unavailable, OSError):
        return {"status": "error", "error": "Independent supervisor unavailable."}

def restart_worker():
    time.sleep(3)
    try:
        stopped = stop_tunnel()
        time.sleep(2)
        started = start_tunnel()
        result = {"stopped": stopped, **started}
    except Exception as error:
        result = {"status": "error", "error": str(error)[:180]}
    output = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Termylo" / "Supervisor" / "last-restart.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result), encoding="utf-8")

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="termylo")
    parser.add_argument("command", choices=[
        "start", "stop", "revoke", "status", "restart", "_restart-worker"])
    args = parser.parse_args(argv)
    try:
        if args.command == "start":
            SupervisorApproval().status()  # No physical consent requested.
            result = start_tunnel()
        elif args.command == "stop":
            result = stop()
        elif args.command == "revoke":
            result = revoke()
        elif args.command == "restart":
            result = restart()
        elif args.command == "_restart-worker":
            restart_worker()
            result = {"status": "complete"}
        else:
            try:
                approval = rpc("status", start=False)
            except (Unavailable, OSError):
                approval = {"status": "closed"}
            result = {"status": "ok", "tunnel_running": bool(tunnel_pids()),
                      "approval": approval}
        print(json.dumps(result, indent=2))
        return 1 if result.get("status") in ("error", "unsupported") else 0
    except Exception as error:
        print(json.dumps({"status": "error", "error": str(error)[:180]}))
        return 1

if __name__ == "__main__":
    sys.exit(main())
