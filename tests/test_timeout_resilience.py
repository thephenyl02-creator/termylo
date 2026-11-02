"""Regression tests: slow commands must not revoke four-hour approval."""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from termylo import native, server, jobs


class FakeProcess:
    def __init__(self):
        self.returncode = None
        self.stopped = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = -1
        self.stopped = True


def test_native_command_response_timeout_does_not_revoke_session(monkeypatch):
    # Prepare a previously approved console without opening a GUI.
    manager = native.NativeSession()
    console = FakeProcess()
    with manager._lock:
        manager._state = "active"
        manager._reason = "Owner approved"
        manager._session_id = "approved-session"
        manager._pipe_name = "fake-test-pipe"
        manager._console_proc = console
        manager._opened_at = time.monotonic()

    begun, release = threading.Event(), threading.Event()

    def slow_exchange(pipe, command, deadline, cancel):
        if command == "Slow-Command":
            begun.set()
            release.wait(5)
        return {"status": "completed", "exit_code": 0,
                "stdout": "done", "stderr": "",
                "stdout_truncated": False, "stderr_truncated": False}

    monkeypatch.setattr(native, "_native_exchange", slow_exchange)
    try:
        result = manager.execute("approved-session", "Slow-Command", 1, threading.Event())
        assert begun.is_set()
        assert result["status"] == "timeout"
        assert result["session_preserved"] is True
        assert manager.status()["status"] == "active"
        assert manager.status()["command_running"] is True
        assert not console.stopped
        busy = manager.execute("approved-session", "Get-Date", 2, threading.Event())
        assert busy["status"] == "error"
        assert "Another native command" in busy["error"]
    finally:
        release.set()

    end = time.monotonic() + 2
    while manager.status()["command_running"] and time.monotonic() < end:
        time.sleep(.01)
    assert manager.status()["command_running"] is False
    assert manager.execute("approved-session", "Get-Date", 2, threading.Event())["exit_code"] == 0
    assert manager.status()["status"] == "active"
    assert manager.status()["session_id"] == "approved-session"
    assert not console.stopped


def test_isolated_runner_timeout_does_not_revoke_approved_session(monkeypatch):
    class Approved:
        def __init__(self):
            self.active = True

        def validate(self, session_id):
            return None if self.active and session_id == "approved" else {
                "status": "unavailable", "error": "No approved session"}

    approved = Approved()
    called = []

    def fake_run(command, timeout_seconds, *, approve, cancel_event):
        assert approve(command, cancel_event) is True
        assert cancel_event.is_set() is False
        called.append((command, timeout_seconds))
        # The real runner terminates its isolated subprocess at this point.
        return {"status": "timeout", "error": "Child command timed out"}

    monkeypatch.setattr(server, "native", approved)
    monkeypatch.setattr(server, "run_command", fake_run)
    monkeypatch.setattr(server, "jobs", jobs.JobManager())
    monkeypatch.setattr(jobs, "os", SimpleNamespace(name="nt"))
    request = server.execute_isolated_powershell("approved", "Slow-Command", 1)
    assert request["job_id"]
    end = time.monotonic() + 2
    result = server.jobs.result(request["job_id"])
    while result["status"] == "awaiting_approval_or_running" and time.monotonic() < end:
        time.sleep(.01)
        result = server.jobs.result(request["job_id"])
    assert result["status"] == "timeout"
    assert approved.active
    assert called == [("Slow-Command", 1)]


def test_isolated_runner_without_approval_is_rejected(monkeypatch):
    class Denied:
        def validate(self, session_id):
            return {"status": "unavailable", "error": "No approved session"}
    monkeypatch.setattr(server, "native", Denied())
    result = server.execute_isolated_powershell("unapproved", "Get-Date", 1)
    assert result["status"] == "unavailable"
