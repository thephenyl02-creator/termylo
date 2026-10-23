"""Windows PowerShell runner. Human approval is required; this is NOT a sandbox."""
from __future__ import annotations
import base64
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

MAX_COMMAND = 2_000
MAX_OUTPUT_BYTES = 32_768
MAX_TIMEOUT = 120

def validate(command: str, timeout_seconds: int) -> str | None:
    if not isinstance(command, str) or not command.strip():
        return "Command must be nonempty text."
    if len(command) > MAX_COMMAND or "\x00" in command:
        return f"Command must be at most {MAX_COMMAND} characters and contain no NUL bytes."
    if not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool) or not (1 <= timeout_seconds <= MAX_TIMEOUT):
        return f"Timeout must be a whole number between 1 and {MAX_TIMEOUT} seconds."
    return None

def _environment() -> dict[str, str]:
    """Avoid copying API keys from the parent process to PowerShell."""
    allowed = {
        "SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "USERPROFILE", "HOMEDRIVE",
        "HOMEPATH", "TEMP", "TMP", "APPDATA", "LOCALAPPDATA", "PROGRAMFILES",
        "PROGRAMFILES(X86)", "PROGRAMW6432", "PSMODULEPATH",
    }
    return {name: value for name, value in os.environ.items() if name.upper() in allowed}

def _is_admin() -> bool:
    if os.name != "nt":
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return True

def _terminate_tree(proc: subprocess.Popen) -> None:
    """Best-effort termination of descendants on Windows."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill.exe", "/PID", str(proc.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=5, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    if proc.poll() is None:
        try:
            proc.kill()
        except OSError:
            pass

def run_command(
    command: str,
    timeout_seconds: int = 45,
    *,
    approve: Callable[[str, threading.Event], bool] | None = None,
    cancel_event: threading.Event | None = None,
    platform: str | None = None,
    elevated: bool | None = None,
) -> dict:
    """Run after local user confirmation; return a structured result."""
    problem = validate(command, timeout_seconds)
    if problem:
        return {"status": "rejected", "error": problem}
    platform = platform or os.name
    if platform != "nt":
        return {"status": "unavailable", "error": "PowerShell command execution requires Windows."}
    if elevated is None:
        elevated = _is_admin()
    if elevated:
        return {"status": "unavailable", "error": "Termylo refuses to execute when run as Administrator."}
    cancel_event = cancel_event or threading.Event()
    if cancel_event.is_set():
        return {"status": "cancelled"}
    if approve is None:
        from .approval import ask_local_user
        approve = ask_local_user
    try:
        approved = bool(approve(command, cancel_event))
    except Exception:
        approved = False
    if cancel_event.is_set():
        return {"status": "cancelled"}
    if not approved:
        return {"status": "denied", "error": "Command was denied or local approval was unavailable."}

    working_directory = Path(os.getenv("TERMYLO_WORKDIR", str(Path.home()))).expanduser()
    if not working_directory.is_dir():
        return {"status": "rejected", "error": "TERMYLO_WORKDIR must refer to an existing directory."}
    # UTF-16LE PowerShell EncodedCommand avoids OS shell argument quoting issues.
    # It does NOT sanitize, restrict, or otherwise change the meaning of the command.
    utf8_command = "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); $OutputEncoding = [Console]::OutputEncoding; " + command
    encoded = base64.b64encode(utf8_command.encode("utf-16le")).decode("ascii")
    powershell = shutil.which("powershell.exe")
    if not powershell:
        return {"status": "unavailable", "error": "powershell.exe was not found in PATH."}
    args = [powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]
    try:
        proc = subprocess.Popen(
            args, cwd=str(working_directory), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=_environment(), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        return {"status": "error", "error": "PowerShell could not be started."}

    streams: list[bytearray] = [bytearray(), bytearray()]
    overflow = [False, False]

    def drain(pipe, index: int) -> None:
        try:
            while True:
                block = pipe.read(4096)
                if not block:
                    return
                remaining = MAX_OUTPUT_BYTES - len(streams[index])
                if remaining > 0:
                    streams[index].extend(block[:remaining])
                if len(block) > remaining:
                    overflow[index] = True
        finally:
            pipe.close()

    readers = [
        threading.Thread(target=drain, args=(proc.stdout, 0), daemon=True),
        threading.Thread(target=drain, args=(proc.stderr, 1), daemon=True),
    ]
    for reader in readers:
        reader.start()
    deadline = time.monotonic() + timeout_seconds
    reason = "completed"
    try:
        while proc.poll() is None:
            if cancel_event.is_set():
                reason = "cancelled"
                break
            if time.monotonic() >= deadline:
                reason = "timeout"
                break
            time.sleep(0.05)
        if reason != "completed":
            _terminate_tree(proc)
        try:
            proc.wait(timeout=6)
        except subprocess.TimeoutExpired:
            _terminate_tree(proc)
        for reader in readers:
            reader.join(timeout=6)
        if reason == "timeout":
            return {"status": "timeout", "error": f"Command exceeded {timeout_seconds} seconds; attempted to terminate its process tree."}
        if reason == "cancelled":
            return {"status": "cancelled", "error": "Attempted to terminate the command process tree."}
        return {
            "status": "completed", "exit_code": proc.returncode,
            "stdout": streams[0].decode("utf-8", errors="replace"),
            "stderr": streams[1].decode("utf-8", errors="replace"),
            "stdout_truncated": overflow[0], "stderr_truncated": overflow[1],
        }
    finally:
        if proc.poll() is None:
            _terminate_tree(proc)
