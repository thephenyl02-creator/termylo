"""Default, consent-gated persistent native PowerShell command routing.

An approved native session is reused. When none exists, one local native
session approval is requested. Neither a new process per command nor a
per-command approval dialog is needed while that session remains valid.
"""
from __future__ import annotations

import threading
import time
from .native import APPROVAL_SECONDS, NativeSession


def execute_default_native(
    native: NativeSession,
    command: str,
    timeout_seconds: int,
    cancel_event: threading.Event,
) -> dict:
    """Launch or reuse a physical-approval-gated session and execute a command.

    Does not bypass 20-minute idle / 40-minute total authorization limits,
    revive a revoked pipe, or fall back to unapproved command execution.
    """
    if cancel_event.is_set():
        return {"status": "cancelled"}
    opening = native.start()
    status = opening.get("status")
    if status in ("error", "unavailable", "rejected", "denied"):
        return {"status": status if status != "error" else "error",
                "error": opening.get("error") or "Native session could not be opened."}
    if status not in ("active", "awaiting_approval", "opening"):
        return {"status": "error", "error": "Unexpected native session state."}

    deadline = time.monotonic() + APPROVAL_SECONDS + 8
    while not cancel_event.is_set() and time.monotonic() < deadline:
        state = native.status()
        if state["status"] == "active":
            sid = state.get("session_id")
            if not sid:
                return {"status": "error", "error": "Approved native session ID unavailable."}
            # Do not skip validation after an approval expires during the wait.
            return native.execute(sid, command, timeout_seconds, cancel_event)
        if state["status"] == "closed":
            return {"status": "denied",
                    "error": "Native session approval was denied, expired or closed."}
        if state["status"] != "opening":
            return {"status": "error", "error": "Unexpected native approval state."}
        cancel_event.wait(0.1)
    if cancel_event.is_set():
        return {"status": "cancelled"}
    return {"status": "denied", "error": "Native session approval timed out."}
