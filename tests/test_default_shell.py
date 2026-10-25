"""A default command reuses one native shell with only one initial approval."""
from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from termylo.default_shell import execute_default_native


class FakeNative:
    def __init__(self, approved=False, deny=False):
        self.state = "active" if approved else "closed"
        self.deny = deny
        self.started = 0
        self.calls = []
        self.session_id = "approved-123"
        self.variables = {}

    def start(self):
        self.started += 1
        if self.state == "active":
            return {"status": "active", "session_id": self.session_id}
        self.state = "closed" if self.deny else "opening"
        return {"status": "awaiting_approval", "session_id": self.session_id}

    def status(self):
        if self.deny:
            return {"status": "closed", "reason": "approval denied"}
        if self.state == "opening":
            self.state = "active"
        return {"status": self.state, "session_id": self.session_id}

    def execute(self, sid, cmd, timeout, cancel):
        assert sid == self.session_id
        assert not cancel.is_set()
        self.calls.append(cmd)
        if cmd.startswith("$x="):
            self.variables["x"] = cmd.split("=", 1)[1]
            return {"status": "completed", "stdout": "", "stderr": "", "exit_code": 0}
        return {"status": "completed", "stdout": self.variables.get("x", ""), "stderr": "", "exit_code": 0}


def test_reuses_current_native_without_other_approval():
    native = FakeNative(approved=True)
    first = execute_default_native(native, "$x=hello", 15, threading.Event())
    second = execute_default_native(native, "Write-Output $x", 15, threading.Event())
    assert first["status"] == second["status"] == "completed"
    assert second["stdout"] == "hello"
    assert native.started == 2
    assert native.calls == ["$x=hello", "Write-Output $x"]
    assert native.session_id == "approved-123"


def test_opens_one_owner_approved_native_then_reuses():
    native = FakeNative()
    assert execute_default_native(native, "$x=hello", 15, threading.Event())["status"] == "completed"
    assert execute_default_native(native, "Write-Output $x", 15, threading.Event())["stdout"] == "hello"
    assert native.started == 2


def test_denied_approval_never_executes():
    native = FakeNative(deny=True)
    out = execute_default_native(native, "Remove-Item -Force important.txt", 5, threading.Event())
    assert out["status"] == "denied"
    assert native.calls == []


def test_cancel_before_launch_prevents_native_popup():
    native = FakeNative()
    cancel = threading.Event()
    cancel.set()
    assert execute_default_native(native, "Get-Date", 5, cancel)["status"] == "cancelled"
    assert native.started == 0


def test_invalid_open_state_fails_closed():
    native = FakeNative()
    native.start = lambda: {"status": "garbage"}
    assert execute_default_native(native, "Get-Date", 5, threading.Event())["status"] == "error"


def test_unavailable_machine_does_not_execute():
    native = FakeNative()
    native.start = lambda: {"status": "unavailable", "error": "no Windows"}
    result = execute_default_native(native, "Get-Date", 5, threading.Event())
    assert result == {"status": "unavailable", "error": "no Windows"}
    assert native.calls == []


def test_cancel_pending_approval_revokes_only_its_popup():
    native = FakeNative()
    def waiting():
        return {"status": "opening", "session_id": native.session_id}
    native.status = waiting
    closed = []
    native.close = lambda sid, reason: closed.append((sid, reason))
    cancel = threading.Event()
    timer = threading.Timer(0.035, cancel.set)
    timer.start()
    try:
        result = execute_default_native(native, "Get-Date", 5, cancel)
    finally:
        timer.join()
    assert result["status"] == "cancelled"
    assert closed and closed[0][0] == native.session_id
    assert native.calls == []


def test_cancel_does_not_revoke_separately_requested_session():
    native = FakeNative()
    native.start = lambda: {"status": "opening", "session_id": native.session_id}
    native.status = lambda: {"status": "opening", "session_id": native.session_id}
    closed = []
    native.close = lambda sid, reason: closed.append(sid)
    cancel = threading.Event()
    timer = threading.Timer(0.035, cancel.set)
    timer.start()
    try:
        result = execute_default_native(native, "Get-Date", 5, cancel)
    finally:
        timer.join()
    assert result["status"] == "cancelled"
    assert closed == []
