"""Locally approved Windows PowerShell execution. NOT a security sandbox."""
from __future__ import annotations
import os
from pathlib import Path
import subprocess
import threading
from typing import Callable

_LOCK = threading.Lock()
MAX_COMMAND = 500
MAX_OUTPUT = 16_000
MAX_TIMEOUT = 120

def validate(command: str, timeout_seconds: int) -> str | None:
    if not isinstance(command, str) or not command.strip():
        return "The command must be nonempty text."
    if len(command) > MAX_COMMAND or "\x00" in command:
        return f"Command must be at most {MAX_COMMAND} characters without NUL bytes."
    if not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool) or not 1 <= timeout_seconds <= MAX_TIMEOUT:
        return f"Timeout must be an integer from 1 to {MAX_TIMEOUT} seconds."
    return None

def _environment() -> dict[str, str]:
    # Avoid passing credential-bearing environment variables to child processes.
    names = {"SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "TEMP", "TMP", "APPDATA", "LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432", "PSMODULEPATH"}
    return {key: value for key, value in os.environ.items() if key.upper() in names}

def execute(command: str, timeout_seconds: int = 45, *, approval: Callable[[str], bool] | None = None, windows: bool | None = None) -> dict:
    """Return structured result; fail closed if local approval is not available."""
    error = validate(command, timeout_seconds)
    if error:
        return {"status": "rejected", "error": error}
    if windows is None:
        windows = os.name == "nt"
    if not windows:
        return {"status": "unavailable", "error": "PowerShell execution is Windows-only."}
    if not _LOCK.acquire(blocking=False):
        return {"status": "busy", "error": "Another command is awaiting approval or running."}
    try:
        if approval is None:
            from .approval import ask_local_user
            approval = ask_local_user
        try:
            approved = approval(command)
        except Exception:
            approved = False
        if not approved:
            return {"status": "denied", "error": "Command denied or local approval timed out."}
        workdir = Path(os.environ.get("TERMYLO_WORKDIR", str(Path.home()))).expanduser()
        if not workdir.is_dir():
            return {"status": "rejected", "error": "TERMYLO_WORKDIR must be an existing directory."}
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
                cwd=str(workdir), stdin=subprocess.DEVNULL, capture_output=True,
                text=True, errors="replace", timeout=timeout_seconds, check=False,
                env=_environment(), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "error": f"Command exceeded {timeout_seconds} seconds; child processes may still be running."}
        except OSError:
            return {"status": "error", "error": "Could not launch Windows PowerShell."}
        stdout, stderr = result.stdout or "", result.stderr or ""
        return {"status": "completed", "exit_code": result.returncode,
                "stdout": stdout[:MAX_OUTPUT], "stderr": stderr[:MAX_OUTPUT],
                "stdout_truncated": len(stdout) > MAX_OUTPUT,
                "stderr_truncated": len(stderr) > MAX_OUTPUT}
    finally:
        _LOCK.release()
