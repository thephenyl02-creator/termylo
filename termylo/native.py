"""Optional, real Windows PowerShell terminal session.

The owner approves ONCE in a separate Tk process; the resulting real
powershell.exe owns its own visible native Windows console and an ephemeral
local named pipe. Shell state survives between remote commands and the user
can type into the console itself. The original per-command tool stays intact.
No TCP listener and no cloud API are introduced.
"""
from __future__ import annotations

import json
import os
import secrets
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

from .runner import _environment, _is_admin, _system_powershell, _terminate_tree, validate

MAX_SESSION_SECONDS = 4 * 60 * 60
APPROVAL_SECONDS = 60
MAX_REPLY_BYTES = 100_000


def _native_exchange(
    pipe_name: str,
    command: str,
    deadline: float,
    cancel_event: threading.Event,
) -> dict:
    """A single length-framed JSON request to an already authorized local pipe."""
    name = "\\\\.\\pipe\\" + pipe_name
    handle = None
    while time.monotonic() < deadline and not cancel_event.is_set():
        try:
            handle = open(name, "r+b", buffering=0)
            break
        except OSError:
            time.sleep(0.05)
    if handle is None:
        raise TimeoutError("Native PowerShell named pipe was not available.")

    with handle:
        encoded = json.dumps({"command": command}, ensure_ascii=False).encode("utf-8")
        if not (1 <= len(encoded) <= 16000):
            raise ValueError("Command payload is too long.")
        handle.write(struct.pack("<I", len(encoded)) + encoded)
        handle.flush()

        def read_exact(length: int) -> bytes:
            data = bytearray()
            while len(data) < length:
                block = handle.read(length - len(data))
                if not block:
                    raise EOFError("Native PowerShell disconnected during the response.")
                data.extend(block)
            return bytes(data)

        reply_size = struct.unpack("<I", read_exact(4))[0]
        if not 1 <= reply_size <= MAX_REPLY_BYTES:
            raise ValueError("Invalid PowerShell response size.")
        result = json.loads(read_exact(reply_size).decode("utf-8", errors="strict"))
        if not isinstance(result, dict) or result.get("status") != "completed":
            raise ValueError("Invalid PowerShell response.")
        return result


class NativeSession:
    def __init__(self):
        self._lock = threading.RLock()
        self._state = "closed"
        self._reason = "No native PowerShell session is open."
        self._session_id: str | None = None
        self._pipe_name: str | None = None
        self._consent_proc: subprocess.Popen | None = None
        self._console_proc: subprocess.Popen | None = None
        self._command_cancel: threading.Event | None = None
        self._opened_at = 0.0

    def _expire_reason(self) -> str | None:
        if self._state != "active":
            return None
        if self._console_proc is None or self._console_proc.poll() is not None:
            return "The native PowerShell console was closed."
        now = time.monotonic()
        if now - self._opened_at >= MAX_SESSION_SECONDS:
            return "Remote approval reached its four-hour maximum."
        return None

    def _close_locked(self, reason: str) -> list[subprocess.Popen]:
        processes = [p for p in (self._consent_proc, self._console_proc) if p is not None]
        self._state = "closed"
        self._reason = reason
        self._session_id = None
        self._pipe_name = None
        self._consent_proc = None
        self._console_proc = None
        if self._command_cancel is not None:
            self._command_cancel.set()
        self._command_cancel = None
        return processes

    @staticmethod
    def _stop(processes: list[subprocess.Popen]) -> None:
        for proc in processes:
            if proc.poll() is None:
                _terminate_tree(proc)

    def _check(self) -> None:
        """Expire remote authority without automatically closing the owner's console.

        The native console must ACK the local-only transition and dispose its
        named pipe. If it cannot, fail closed by terminating the console.
        An in-flight command is also terminated rather than left uncontrolled.
        """
        processes = []
        detached = None
        with self._lock:
            reason = self._expire_reason()
            if reason is not None:
                expired = reason.startswith("Remote approval")
                console = self._console_proc
                if (expired and self._command_cancel is None and
                        self._pipe_name and console is not None and console.poll() is None):
                    detached = (self._pipe_name, console)
                    self._close_locked(reason + " Remote access revoked; local PowerShell remains open.")
                else:
                    processes = self._close_locked(reason)
        self._stop(processes)
        if detached is not None:
            pipe, console = detached
            try:
                result = _native_exchange(
                    pipe, "__TERMYLO_REVOKE_IPC__",
                    time.monotonic() + 3, threading.Event(),
                )
                if result.get("exit_code") != 0:
                    raise RuntimeError("Native console did not acknowledge revocation.")
            except Exception:
                # Do not leave a remotely reachable named pipe behind.
                self._stop([console])

    def status(self) -> dict:
        self._check()
        with self._lock:
            result = {
                "status": self._state,
                "reason": self._reason,
                "session_id": self._session_id,
                "terminal": "real, user-editable Windows PowerShell console",
                "approval": "one physical approval per native session, no per-command prompts",
                "state": "same real PowerShell process across commands",
                "idle_limit_seconds": None,
                "absolute_limit_seconds": MAX_SESSION_SECONDS,
            }
            if self._state == "active":
                now = time.monotonic()
                result["remaining_seconds"] = max(0, int(MAX_SESSION_SECONDS - (now - self._opened_at)))
            return result

    def start(self) -> dict:
        if os.name != "nt":
            return {"status": "unavailable", "error": "Native PowerShell requires Windows."}
        if _is_admin():
            return {"status": "unavailable", "error": "Termylo refuses to run as Administrator."}
        if not _system_powershell():
            return {"status": "unavailable", "error": "Cannot verify system PowerShell."}
        self._check()
        with self._lock:
            if self._state in ("opening", "active"):
                return {"status": self._state, "session_id": self._session_id,
                        "message": "Existing native PowerShell session; check native_session_status."}
            sid = secrets.token_urlsafe(18)
            pipe = "termylo-" + secrets.token_hex(20)
            self._state = "opening"
            self._reason = "Waiting for explicit physical Windows session approval."
            self._session_id = sid
            self._pipe_name = pipe
            try:
                threading.Thread(
                    target=self._launch, args=(sid, pipe),
                    name="termylo-native-open", daemon=True,
                ).start()
            except (RuntimeError, OSError):
                self._close_locked("Could not start native-session worker.")
                return {"status": "error", "error": "Could not start native-session worker."}
        return {"status": "awaiting_approval", "session_id": sid,
                "message": "Click APPROVE SESSION on the Windows consent window. A real PowerShell terminal will then open."}

    def _launch(self, sid: str, pipe_name: str) -> None:
        consent = None
        native = None
        try:
            consent = subprocess.Popen(
                [sys.executable, "-m", "termylo.native_approval"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=_environment(),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            with self._lock:
                if self._state != "opening" or self._session_id != sid:
                    self._stop([consent])
                    return
                self._consent_proc = consent

            deadline = time.monotonic() + APPROVAL_SECONDS + 5
            while consent.poll() is None and time.monotonic() < deadline:
                with self._lock:
                    if self._state != "opening" or self._session_id != sid:
                        return
                time.sleep(.05)
            if consent.poll() is None or consent.returncode != 0:
                self._fail_open(sid, "Native-session approval denied or timed out.")
                return

            powershell = _system_powershell()
            assert powershell
            script = Path(__file__).with_name("native_console.ps1")
            if not script.is_file():
                self._fail_open(sid, "Native PowerShell console script missing.")
                return
            native = subprocess.Popen(
                [powershell, "-NoLogo", "-NoProfile", "-File",
                 str(script), "-PipeName", pipe_name],
                cwd=str(Path.home()),
                env=_environment(),
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
                stdin=None, stdout=None, stderr=None,
            )
            with self._lock:
                if self._state != "opening" or self._session_id != sid:
                    self._stop([native])
                    return
                self._console_proc = native
                self._consent_proc = None

            # Verify the real shell is listening, not merely that Popen succeeded.
            check = _native_exchange(
                pipe_name, "Write-Output 'Termylo native PowerShell ready'",
                time.monotonic() + 10, threading.Event(),
            )
            if native.poll() is not None or check.get("exit_code") != 0:
                self._fail_open(sid, "Native PowerShell readiness check failed.")
                return
            with self._lock:
                if self._state != "opening" or self._session_id != sid:
                    self._stop([native])
                    return
                self._state = "active"
                self._reason = "Owner-approved native Windows PowerShell console is running."
                self._opened_at = time.monotonic()
            threading.Thread(
                target=self._monitor, args=(sid,), daemon=True,
                name="termylo-native-monitor",
            ).start()
        except Exception:
            self._fail_open(sid, "Native PowerShell window or IPC could not initialize.")

    def _fail_open(self, sid: str, reason: str) -> None:
        processes: list[subprocess.Popen] = []
        with self._lock:
            if self._session_id == sid and self._state == "opening":
                processes = self._close_locked(reason)
        self._stop(processes)

    def _monitor(self, sid: str) -> None:
        while True:
            self._check()
            with self._lock:
                if self._state != "active" or self._session_id != sid:
                    return
            time.sleep(0.2)

    def validate(self, session_id: str) -> dict | None:
        self._check()
        with self._lock:
            if self._state != "active" or not self._session_id or session_id != self._session_id:
                return {"status": "unavailable", "error": "No matching approved native terminal session."}
        return None

    def execute(
        self, sid: str, command: str, timeout_seconds: int,
        cancel_event: threading.Event,
    ) -> dict:
        error = validate(command, timeout_seconds)
        if error:
            return {"status": "rejected", "error": error}
        bad = self.validate(sid)
        if bad:
            return bad
        with self._lock:
            if self._command_cancel is not None:
                return {"status": "error", "error": "Another native command is running."}
            self._command_cancel = cancel_event
            pipe = self._pipe_name
        assert pipe
        result: dict | None = None
        failure: list[Exception] = []
        done = threading.Event()

        def worker() -> None:
            nonlocal result
            try:
                result = _native_exchange(
                    pipe, command,
                    time.monotonic() + timeout_seconds,
                    cancel_event,
                )
            except Exception as exc:
                failure.append(exc)
            finally:
                done.set()

        threading.Thread(target=worker, daemon=True, name="termylo-native-command").start()
        deadline = time.monotonic() + timeout_seconds
        reason = None
        try:
            while not done.wait(.05):
                if cancel_event.is_set():
                    reason = "cancelled"
                    break
                if time.monotonic() >= deadline:
                    reason = "timeout"
                    break
                with self._lock:
                    if self._state != "active" or self._session_id != sid:
                        reason = "cancelled"
                        break
            if reason:
                self.close(sid, "Native command was " + reason + "; console revoked to stop execution.")
                return {"status": reason, "error": "Native session ended because the command was " + reason + "."}
            if cancel_event.is_set():
                self.close(sid, "Native command was cancelled; terminal authorization revoked.")
                return {"status": "cancelled"}
            if failure or result is None:
                self.close(sid, "PowerShell IPC failed or disconnected.")
                return {"status": "error", "error": "Native PowerShell IPC request failed."}
            return result
        finally:
            with self._lock:
                if self._command_cancel is cancel_event:
                    self._command_cancel = None

    def close(self, sid: str, reason: str = "Native terminal revoked by the user.") -> dict:
        with self._lock:
            if not self._session_id or sid != self._session_id:
                return {"status": "not_found", "error": "No matching native session."}
            processes = self._close_locked(reason)
        self._stop(processes)
        return {"status": "closed", "message": "Native PowerShell console closed and authorization revoked."}
