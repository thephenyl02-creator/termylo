"""Native session approval/expiry and persistent command-dispatch tests.

No real desktop is opened during CI. scripts/native_console_smoke.py is
the explicit owner-device test for real powershell.exe and its named pipe.
"""
from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

import pytest
from termylo import native


class FakeProcess:
    def __init__(self, consent: bool):
        self.returncode = 0 if consent else None
        self.stopped = False
        self.pid = 987

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = -1
        self.stopped = True

    def kill(self):
        self.terminate()


def get_state(manager, expected, seconds=3):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        state = manager.status()
        if state["status"] == expected:
            return state
        time.sleep(.01)
    pytest.fail(f"Native session did not reach {expected}: {manager.status()}")


def configure(monkeypatch, *, approve=True):
    monkeypatch.setattr(native, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(native, "_is_admin", lambda: False)
    monkeypatch.setattr(native, "_system_powershell", lambda: "C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
    fake_consent = FakeProcess(consent=approve)
    fake_console = FakeProcess(consent=False)
    procs = []
    def launch(argv, **kwargs):
        proc = fake_consent if "termylo.native_approval" in argv else fake_console
        procs.append(proc)
        return proc
    monkeypatch.setattr(native.subprocess, "Popen", launch)
    monkeypatch.setattr(native, "_terminate_tree", lambda proc: proc.terminate())
    commands = []
    state = {"cwd": "C:\\Users\\Fenil", "var": None}
    def exchange(pipe, command, deadline, cancel_event):
        commands.append(command)
        if command.startswith("Set-Location"):
            state["cwd"] = "C:\\Users\\Fenil\\termylo"
            out = ""
        elif command == "Get-Location":
            out = state["cwd"] + "\r\n"
        elif command.startswith("$global:Saved="):
            state["var"] = "hello"
            out = ""
        elif command == "Write-Output $global:Saved":
            out = state["var"] + "\r\n"
        else:
            out = "Termylo native PowerShell ready\r\n"
        return {"status": "completed", "exit_code": 0, "stdout": out, "stderr": "",
                "stdout_truncated": False, "stderr_truncated": False}
    monkeypatch.setattr(native, "_native_exchange", exchange)
    return fake_consent, fake_console, commands


def test_no_windows_refuses_without_opening(monkeypatch):
    monkeypatch.setattr(native, "os", SimpleNamespace(name="posix"))
    assert native.NativeSession().start()["status"] == "unavailable"


def test_session_approval_commands_state_and_close(monkeypatch):
    consent, terminal, calls = configure(monkeypatch)
    manager = native.NativeSession()
    opening = manager.start()
    assert opening["status"] == "awaiting_approval"
    active = get_state(manager, "active")
    sid = active["session_id"]
    assert sid == opening["session_id"]
    assert len(calls) == 1  # readiness probe
    assert manager.validate(sid) is None
    assert manager.execute(sid, "Set-Location $HOME\\termylo", 10, threading.Event())["exit_code"] == 0
    assert "termylo" in manager.execute(sid, "Get-Location", 10, threading.Event())["stdout"]
    assert manager.execute(sid, "$global:Saved='hello'", 10, threading.Event())["exit_code"] == 0
    assert "hello" in manager.execute(sid, "Write-Output $global:Saved", 10, threading.Event())["stdout"]
    assert manager.close(sid)["status"] == "closed"
    assert terminal.stopped
    assert manager.validate(sid)["status"] == "unavailable"


def test_no_unapproved_console(monkeypatch):
    _, _, calls = configure(monkeypatch, approve=False)
    manager = native.NativeSession()
    opening = manager.start()
    assert opening["status"] == "awaiting_approval"
    # Mark a denied UI as finished; do not await the 65-second timeout.
    consent = manager._consent_proc
    end = time.monotonic() + 3
    while consent is None and time.monotonic() < end:
        time.sleep(.01)
        consent = manager._consent_proc
    assert consent is not None
    consent.returncode = 1
    get_state(manager, "closed")
    assert calls == []


def test_window_close_revokes_approval(monkeypatch):
    _, terminal, _ = configure(monkeypatch)
    manager = native.NativeSession()
    manager.start()
    sid = get_state(manager, "active")["session_id"]
    terminal.returncode = 0
    assert manager.validate(sid)["status"] == "unavailable"


def test_no_idle_timeout_even_near_four_hour_limit(monkeypatch):
    _, terminal, calls = configure(monkeypatch)
    manager = native.NativeSession()
    manager.start()
    sid = get_state(manager, "active")["session_id"]
    # No commands for almost four hours: expiration is based solely on
    # the time of approval, never on recent MCP activity.
    with manager._lock:
        manager._opened_at -= native.MAX_SESSION_SECONDS - 30
    status = manager.status()
    assert status["status"] == "active"
    assert status["idle_limit_seconds"] is None
    assert "idle_remaining_seconds" not in status
    assert 0 < status["remaining_seconds"] <= 30
    assert manager.validate(sid) is None
    assert not terminal.stopped
    assert "__TERMYLO_REVOKE_IPC__" not in calls
    
    
def test_absolute_max_enforced(monkeypatch):
    _, terminal, calls = configure(monkeypatch)
    manager = native.NativeSession()
    manager.start()
    sid = get_state(manager, "active")["session_id"]
    with manager._lock:
        manager._opened_at -= native.MAX_SESSION_SECONDS + 1
    assert manager.validate(sid)["status"] == "unavailable"
    assert not terminal.stopped
    assert "__TERMYLO_REVOKE_IPC__" in calls


def test_expiry_fails_closed_if_console_does_not_ack(monkeypatch):
    _, terminal, _ = configure(monkeypatch)
    manager = native.NativeSession()
    manager.start()
    sid = get_state(manager, "active")["session_id"]
    def refusing_revoke(pipe, command, deadline, cancel_event):
        raise RuntimeError("cannot detach pipe")
    monkeypatch.setattr(native, "_native_exchange", refusing_revoke)
    with manager._lock:
        manager._opened_at -= native.MAX_SESSION_SECONDS + 1
    assert manager.validate(sid)["status"] == "unavailable"
    assert terminal.stopped


def test_native_authorization_is_four_hours_without_idle_timeout():
    assert native.MAX_SESSION_SECONDS == 4 * 60 * 60
    assert not hasattr(native, "IDLE_SECONDS")


def test_expiry_boundary_and_session_id_revoked(monkeypatch):
    _, terminal, calls = configure(monkeypatch)
    manager = native.NativeSession()
    manager.start()
    sid = get_state(manager, "active")["session_id"]
    with manager._lock:
        manager._opened_at = time.monotonic() - native.MAX_SESSION_SECONDS
    expired = manager.status()
    assert expired["status"] == "closed"
    assert "four-hour maximum" in expired["reason"]
    assert expired["session_id"] is None
    assert manager.validate(sid)["status"] == "unavailable"
    assert "__TERMYLO_REVOKE_IPC__" in calls
    assert not terminal.stopped  # can still type locally after remote revoke


def test_cancel_stops_whole_native_shell(monkeypatch):
    _, terminal, _ = configure(monkeypatch)
    manager = native.NativeSession()
    manager.start()
    sid = get_state(manager, "active")["session_id"]
    entered = threading.Event()
    cancel = threading.Event()
    def blocked(*args):
        entered.set()
        cancel.wait(4)
        raise RuntimeError("Cancelled")
    monkeypatch.setattr(native, "_native_exchange", blocked)
    results = []
    thread = threading.Thread(target=lambda: results.append(manager.execute(sid, "Start-Sleep 20", 15, cancel)))
    thread.start()
    assert entered.wait(2)
    cancel.set()
    thread.join(3)
    assert results[0]["status"] == "cancelled"
    assert terminal.stopped


def test_invalid_commands_do_not_execute(monkeypatch):
    _, _, calls = configure(monkeypatch)
    manager = native.NativeSession()
    manager.start()
    sid = get_state(manager, "active")["session_id"]
    assert manager.execute(sid, "", 10, threading.Event())["status"] == "rejected"
    assert manager.execute(sid, "Get-Date", 999, threading.Event())["status"] == "rejected"
    assert len(calls) == 1


def test_repeated_start_uses_same_session(monkeypatch):
    configure(monkeypatch)
    manager = native.NativeSession()
    manager.start()
    sid = get_state(manager, "active")["session_id"]
    again = manager.start()
    assert again["status"] == "active"
    assert again["session_id"] == sid
