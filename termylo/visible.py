"""Opt-in, time-limited visible session controller.

This is a local GUI session: the Tk window previews command text and results.
PowerShell is executed by the existing non-elevated runner, one process per
command. Command-local variables do NOT persist across calls. Existing
execute_powershell retains its per-command approval contract.
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import threading
import time
from typing import Callable

from .runner import _environment, _is_admin, run_command, validate

IDLE_SECONDS = 600
MAX_SESSION_SECONDS = 1800
APPROVAL_SECONDS = 60


class VisibleSession:
    def __init__(self, executor: Callable[..., dict] = run_command):
        self._executor = executor
        self._lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self._session_id: str | None = None
        self._state = "closed"
        self._reason = "No visible session is open."
        self._opened_at = 0.0
        self._last_activity = 0.0
        self._command_cancel: threading.Event | None = None

    def _expire_reason(self) -> str | None:
        if self._state != "active":
            return None
        if self._process is None or self._process.poll() is not None:
            return "Visible window was closed or its process exited."
        now = time.monotonic()
        if now - self._opened_at >= MAX_SESSION_SECONDS:
            return "Session reached its 30-minute maximum."
        if now - self._last_activity >= IDLE_SECONDS:
            return "Session was inactive for 10 minutes."
        return None

    def _close_locked(self, reason: str) -> subprocess.Popen | None:
        proc = self._process
        self._process = None
        self._session_id = None
        self._state = "closed"
        self._reason = reason
        if self._command_cancel is not None:
            self._command_cancel.set()
        self._command_cancel = None
        return proc

    @staticmethod
    def _stop_process(proc: subprocess.Popen | None) -> None:
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            pass
        try:
            if proc.stdin is not None:
                proc.stdin.close()
        except (OSError, ValueError):
            pass

    def _check_active(self) -> None:
        to_stop = None
        with self._lock:
            reason = self._expire_reason()
            if reason:
                to_stop = self._close_locked(reason)
        self._stop_process(to_stop)

    def status(self) -> dict:
        self._check_active()
        with self._lock:
            details = {
                "status": self._state,
                "reason": self._reason,
                "session_id": self._session_id,
                "approval": "one local approval per visible session, NOT per command",
                "execution": "one PowerShell process per command; shell variables do not persist",
                "idle_limit_seconds": IDLE_SECONDS,
                "absolute_limit_seconds": MAX_SESSION_SECONDS,
            }
            if self._state == "active":
                now = time.monotonic()
                details["idle_remaining_seconds"] = max(0, int(IDLE_SECONDS - (now - self._last_activity)))
                details["session_remaining_seconds"] = max(0, int(MAX_SESSION_SECONDS - (now - self._opened_at)))
            return details

    def start(self) -> dict:
        if os.name != "nt":
            return {"status": "unavailable", "error": "A visible Termylo session requires Windows."}
        if _is_admin():
            return {"status": "unavailable", "error": "Termylo must not run as Administrator."}
        self._check_active()
        with self._lock:
            if self._state in ("opening", "active"):
                return {"status": self._state, "session_id": self._session_id, "message": "Use visible_session_status to inspect the existing session."}
            sid = secrets.token_urlsafe(18)
            self._session_id = sid
            self._state = "opening"
            self._reason = "Waiting for local approval in the visible Windows window."
            try:
                threading.Thread(target=self._launch, args=(sid,), daemon=True, name="termylo-visible-start").start()
            except (RuntimeError, OSError):
                self._session_id = None
                self._state = "closed"
                self._reason = "Could not start visible-session worker."
                return {"status": "error", "error": self._reason}
        return {"status": "awaiting_approval", "session_id": sid, "message": "Approve or deny the visible session on your Windows desktop; then call visible_session_status."}

    def _launch(self, sid: str) -> None:
        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "termylo.visible_ui"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                env=_environment(),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError:
            with self._lock:
                if self._session_id == sid and self._state == "opening":
                    self._close_locked("Could not start the visible window.")
            return

        with self._lock:
            if self._session_id != sid or self._state != "opening":
                self._stop_process(proc)
                return
            self._process = proc

        # Never block forever on stdout.readline(): it is driven by a daemon.
        ack: list[bytes] = []
        ready = threading.Event()
        def read_ack() -> None:
            try:
                assert proc.stdout is not None
                ack.append(proc.stdout.readline(80))
            except (OSError, ValueError):
                pass
            finally:
                ready.set()
        threading.Thread(target=read_ack, daemon=True, name="termylo-session-ack").start()
        deadline = time.monotonic() + APPROVAL_SECONDS + 5
        while not ready.wait(timeout=0.1):
            if proc.poll() is not None or time.monotonic() >= deadline:
                break
            with self._lock:
                if self._session_id != sid or self._state != "opening":
                    break

        # Python text stdout on Windows may translate newline to CRLF.\n        # Match only the exact one-line consent token with either line ending.\n        approved = (\n            ready.is_set()\n            and len(ack) == 1\n            and ack[0] in (b"SESSION_APPROVED\n", b"SESSION_APPROVED\r\n")\n            and proc.poll() is None\n        )
        stop = None
        with self._lock:
            if self._session_id != sid or self._state != "opening":
                stop = proc
            elif approved:
                self._state = "active"
                self._reason = "Visible session approved locally and running."
                self._opened_at = time.monotonic()
                self._last_activity = self._opened_at
            else:
                stop = self._close_locked("Session approval denied, timed out, or its window failed.")
        self._stop_process(stop)
        if approved and stop is None:
            threading.Thread(target=self._monitor, args=(sid,), daemon=True, name="termylo-session-monitor").start()

    def _monitor(self, sid: str) -> None:
        while True:
            self._check_active()
            with self._lock:
                if self._state != "active" or self._session_id != sid:
                    return
            time.sleep(0.2)

    def validate_session(self, session_id: str) -> dict | None:
        self._check_active()
        with self._lock:
            if self._state != "active" or not self._session_id or session_id != self._session_id:
                return {"status": "unavailable", "error": "No matching locally approved visible session. Open a new session and approve it."}
        return None

    def _display(self, sid: str, kind: str, value: str) -> bool:
        message = json.dumps({"type": kind, "text": value}, ensure_ascii=False) + "\n"
        with self._write_lock:
            with self._lock:
                proc = self._process
                if self._state != "active" or self._session_id != sid or proc is None or proc.poll() is not None:
                    return False
            try:
                assert proc.stdin is not None
                proc.stdin.write(message.encode("utf-8"))
                proc.stdin.flush()
                return True
            except (OSError, ValueError):
                return False

    def execute(self, sid: str, command: str, timeout_seconds: int, cancel_event: threading.Event) -> dict:
        issue = validate(command, timeout_seconds)
        if issue:
            return {"status": "rejected", "error": issue}
        bad = self.validate_session(sid)
        if bad:
            return bad

        with self._lock:
            if self._command_cancel is not None:
                return {"status": "error", "error": "Another visible-session command is already running."}
            self._command_cancel = cancel_event
            self._last_activity = time.monotonic()
        try:
            if not self._display(sid, "command", command):
                return {"status": "unavailable", "error": "Visible window is not responding; command was not started."}
            # Session approval is explicitly local. The standard tool still calls
            # the original per-command approval mechanism without modification.
            result = self._executor(
                command, timeout_seconds, cancel_event=cancel_event,
                approve=lambda _command, event: not event.is_set() and self.validate_session(sid) is None,
            )
            if not isinstance(result, dict):
                result = {"status": "error", "error": "Unexpected PowerShell runner response."}
            output = (
                f"Status: {result.get('status')}; exit: {result.get('exit_code', 'N/A')}\n"
                + (result.get("stdout") or "")
                + (("\nSTDERR:\n" + result["stderr"]) if result.get("stderr") else "")
                + (("\n" + result["error"]) if result.get("error") else "")
            )
            self._display(sid, "result", output[:70000])
            return result
        finally:
            with self._lock:
                if self._session_id == sid and self._state == "active":
                    self._last_activity = time.monotonic()
                if self._command_cancel is cancel_event:
                    self._command_cancel = None

    def close(self, sid: str) -> dict:
        with self._lock:
            if not self._session_id or sid != self._session_id:
                return {"status": "not_found", "error": "No matching visible session."}
            proc = self._close_locked("Session revoked by ChatGPT request.")
        self._stop_process(proc)
        return {"status": "closed", "message": "The approved visible window was closed. Subsequent commands require a new approval."}
