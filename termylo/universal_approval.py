"""One owner-approved native lease shared by independent project terminals.

The lease is in-memory and tied to one MCP server process. Only the first
request opens the normal Windows approval window. Other projects reuse that
approval until its original absolute expiry, without resetting the clock.
"""
from __future__ import annotations

import math
import os
import secrets
import subprocess
import sys
import threading
import time

from .native import APPROVAL_SECONDS, MAX_SESSION_SECONDS
from .runner import _environment, _terminate_tree


class UniversalApproval:
    def __init__(self):
        self._lock = threading.RLock()
        self._state = "closed"
        self._reason = "No owner-approved native lease is active."
        self._opened_at = 0.0
        self._duration_seconds = MAX_SESSION_SECONDS
        self._grant_id: str | None = None
        self._consent_proc: subprocess.Popen | None = None
        self._event = threading.Event()
        self._request_id: str | None = None

    def _refresh_locked(self) -> None:
        if self._state == "active" and time.monotonic() - self._opened_at >= self._duration_seconds:
            self._state = "closed"
            self._reason = "Universal native approval expired."
            self._grant_id = None
            self._event.set()

    def status(self) -> dict:
        with self._lock:
            self._refresh_locked()
            result = {
                "status": self._state,
                "reason": self._reason,
                "grant_id": self._grant_id,
                "absolute_limit_seconds": self._duration_seconds,
                "idle_limit_seconds": None,
                "scope": "all native Termylo project terminals",
            }
            if self._state == "active":
                result["remaining_seconds"] = max(
                    0, int(self._duration_seconds - (time.monotonic() - self._opened_at)))
            return result

    def begin(self, duration_hours: float = 4) -> dict:
        if isinstance(duration_hours, bool) or not isinstance(duration_hours, (int, float)):
            return {"status": "rejected", "error": "Approval hours must be a positive number."}
        seconds = float(duration_hours) * 3600
        if not math.isfinite(seconds) or seconds <= 0:
            return {"status": "rejected", "error": "Approval hours must be positive and finite."}
        with self._lock:
            self._refresh_locked()
            if self._state in ("opening", "active"):
                return self.status()
            self._state = "opening"
            self._reason = "Waiting for one Windows approval covering all project terminals."
            self._duration_seconds = seconds
            self._grant_id = None
            self._event = threading.Event()
            self._request_id = secrets.token_urlsafe(12)
            request_id = self._request_id
            try:
                threading.Thread(target=self._request, args=(request_id, seconds),
                                 name="termylo-universal-approval", daemon=True).start()
            except (RuntimeError, OSError):
                self._state = "closed"
                self._reason = "Could not launch the approval request."
                self._request_id = None
                self._event.set()
                return {"status": "error", "error": self._reason}
            return {"status": "awaiting_approval", "message":
                    "Approve one universal native PowerShell lease on Windows."}

    def _request(self, request_id: str, seconds: float) -> None:
        consent = None
        approved = False
        try:
            consent = subprocess.Popen(
                [sys.executable, "-m", "termylo.native_approval", "--hours",
                 str(seconds / 3600), "--project", "ALL PROJECTS", "--universal"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, env=_environment(),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            with self._lock:
                if self._state != "opening" or self._request_id != request_id:
                    return
                self._consent_proc = consent
            deadline = time.monotonic() + APPROVAL_SECONDS + 5
            while consent.poll() is None and time.monotonic() < deadline:
                with self._lock:
                    if self._state != "opening" or self._request_id != request_id:
                        return
                time.sleep(0.05)
            approved = consent.poll() == 0
        except Exception:
            approved = False
        finally:
            with self._lock:
                if self._request_id == request_id and self._state == "opening":
                    self._consent_proc = None
                    self._request_id = None
                    if approved:
                        self._opened_at = time.monotonic()
                        self._grant_id = secrets.token_urlsafe(18)
                        self._state = "active"
                        self._reason = "Owner approved all native project terminals."
                    else:
                        self._state = "closed"
                        self._reason = "Universal native approval denied or timed out."
                    self._event.set()
            if consent is not None and consent.poll() is None:
                _terminate_tree(consent)

    def wait(self, cancel_event: threading.Event | None = None) -> dict | None:
        with self._lock:
            event = self._event
        deadline = time.monotonic() + APPROVAL_SECONDS + 10
        while time.monotonic() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                return None
            if event.wait(0.1):
                with self._lock:
                    self._refresh_locked()
                    if self._state == "active":
                        return {"grant_id": self._grant_id,
                                "opened_at": self._opened_at,
                                "duration_seconds": self._duration_seconds}
                    return None
        return None

    def valid(self, grant_id: str | None) -> bool:
        with self._lock:
            self._refresh_locked()
            return bool(grant_id and self._state == "active" and self._grant_id == grant_id)

    def revoke(self) -> dict:
        with self._lock:
            proc = self._consent_proc
            self._state = "closed"
            self._grant_id = None
            self._request_id = None
            self._consent_proc = None
            self._reason = "Universal native approval revoked by owner request."
            self._event.set()
        if proc is not None and proc.poll() is None:
            _terminate_tree(proc)
        return self.status()
