"""Visible-session regression tests without opening a desktop or executing PowerShell."""
from __future__ import annotations

import io
import json
import threading
import time
from types import SimpleNamespace

import pytest
from termylo import visible
from termylo.jobs import JobManager

APPROVED = b"SESSION_APPROVED\n"


class FakeProcess:
    def __init__(self, acknowledgement=APPROVED):
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO(acknowledgement)
        self.returncode = None
        self.stopped = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.stopped = True
        self.returncode = -1

    def kill(self):
        self.stopped = True
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


def wait_status(session, expected, seconds=3):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = session.status()
        if result["status"] == expected:
            return result
        time.sleep(.01)
    pytest.fail(f"visible session never became {expected}: {session.status()}")


def configure_windows(monkeypatch, process):
    # Do not change os.name globally; pathlib on Linux would be affected.
    monkeypatch.setattr(visible, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(visible, "_is_admin", lambda: False)
    monkeypatch.setattr(visible.subprocess, "Popen", lambda *args, **kwargs: process)


def test_nonwindows_refuses_session(monkeypatch):
    monkeypatch.setattr(visible, "os", SimpleNamespace(name="posix"))
    assert visible.VisibleSession().start()["status"] == "unavailable"


@pytest.mark.parametrize("ack", [b"SESSION_APPROVED\n", b"SESSION_APPROVED\r\n"])
def test_explicit_approval_single_window_multiple_commands_and_close(monkeypatch, ack):
    proc = FakeProcess(ack)
    configure_windows(monkeypatch, proc)
    approvals = []
    def executor(command, timeout, cancel_event, approve):
        approvals.append(approve(command, cancel_event))
        return {"status": "completed", "exit_code": 0, "stdout": command + "\n", "stderr": ""}
    session = visible.VisibleSession(executor)
    opening = session.start()
    assert opening["status"] == "awaiting_approval"
    current = wait_status(session, "active")
    sid = current["session_id"]
    assert sid == opening["session_id"]
    assert session.validate_session(sid) is None

    result1 = session.execute(sid, "Write-Output 'hello'", 10, threading.Event())
    result2 = session.execute(sid, "Get-Date", 10, threading.Event())
    assert [result1["status"], result2["status"]] == ["completed", "completed"]
    assert approvals == [True, True]

    lines = [json.loads(line) for line in proc.stdin.getvalue().decode("utf-8").splitlines()]
    assert [m["type"] for m in lines] == ["command", "result", "command", "result"]
    assert lines[0]["text"] == "Write-Output 'hello'"
    assert lines[2]["text"] == "Get-Date"
    assert session.close(sid)["status"] == "closed"
    assert proc.stopped
    assert session.validate_session(sid)["status"] == "unavailable"


def test_close_window_revokes_session(monkeypatch):
    proc = FakeProcess()
    configure_windows(monkeypatch, proc)
    session = visible.VisibleSession()
    session.start()
    sid = wait_status(session, "active")["session_id"]
    proc.returncode = 0  # Simulated clicking the Windows X button
    assert session.validate_session(sid)["status"] == "unavailable"
    assert session.status()["session_id"] is None


def test_idle_expiry_revokes_session(monkeypatch):
    proc = FakeProcess()
    configure_windows(monkeypatch, proc)
    session = visible.VisibleSession()
    session.start()
    sid = wait_status(session, "active")["session_id"]
    with session._lock:
        session._last_activity -= visible.IDLE_SECONDS + 1
    assert session.validate_session(sid)["status"] == "unavailable"
    assert proc.stopped


def test_absolute_expiry_revokes_even_with_recent_activity(monkeypatch):
    proc = FakeProcess()
    configure_windows(monkeypatch, proc)
    session = visible.VisibleSession()
    session.start()
    sid = wait_status(session, "active")["session_id"]
    with session._lock:
        session._opened_at -= visible.MAX_SESSION_SECONDS + 1
    assert session.validate_session(sid)["status"] == "unavailable"
    assert proc.stopped


@pytest.mark.parametrize("invalid_ack", [b"SESSION_DENIED\n", b"SESSION_APPROVED extra\n", b"SESSION_APPROVED\r"])
def test_refused_window_does_not_grant_approval(monkeypatch, invalid_ack):
    proc = FakeProcess(invalid_ack)
    configure_windows(monkeypatch, proc)
    session = visible.VisibleSession()
    opening = session.start()
    wait_status(session, "closed")
    assert proc.stopped
    assert session.validate_session(opening["session_id"])["status"] == "unavailable"


def test_busy_visible_command_cannot_run_second_concurrently(monkeypatch):
    proc = FakeProcess()
    configure_windows(monkeypatch, proc)
    waiting = threading.Event()
    begin = threading.Event()
    def executor(command, timeout, cancel_event, approve):
        assert approve(command, cancel_event)
        begin.set()
        waiting.wait(2)
        return {"status": "completed", "exit_code": 0, "stdout": command, "stderr": ""}
    session = visible.VisibleSession(executor)
    sid = session.start()["session_id"]
    wait_status(session, "active")
    results = []
    thread = threading.Thread(target=lambda: results.append(session.execute(sid, "Get-Date", 10, threading.Event())))
    thread.start()
    assert begin.wait(2)
    assert session.execute(sid, "Get-Location", 10, threading.Event())["status"] == "error"
    waiting.set()
    thread.join(3)
    assert not thread.is_alive()
    assert results[0]["status"] == "completed"
    session.close(sid)


def test_revoking_active_session_requests_cancel(monkeypatch):
    proc = FakeProcess()
    configure_windows(monkeypatch, proc)
    begin = threading.Event()
    def executor(command, timeout, cancel_event, approve):
        begin.set()
        assert cancel_event.wait(3)
        return {"status": "cancelled"}
    session = visible.VisibleSession(executor)
    session.start()
    sid = wait_status(session, "active")["session_id"]
    results = []
    thread = threading.Thread(target=lambda: results.append(session.execute(sid, "Start-Sleep 4", 10, threading.Event())))
    thread.start()
    assert begin.wait(2)
    assert session.close(sid)["status"] == "closed"
    thread.join(3)
    assert results[0]["status"] == "cancelled"


def test_async_job_runner_override_preserves_default_approval_mode(monkeypatch):
    import termylo.jobs as jobs_module
    monkeypatch.setattr(jobs_module, "os", SimpleNamespace(name="nt"))
    normal = []
    visible_calls = []
    def default_run(c, t, cancel_event):
        normal.append(c)
        return {"status": "denied"}
    def session_run(c, t, cancel_event):
        visible_calls.append(c)
        return {"status": "completed", "exit_code": 0, "stdout": "ok"}
    mgr = JobManager(default_run)
    first = mgr.submit("Write-Output 'normal'", timeout_seconds=10)
    assert first["status"] == "awaiting_approval"
    for _ in range(100):
        if mgr.result(first["job_id"])["status"] == "denied":
            break
        time.sleep(.01)
    second = mgr.submit("Write-Output 'session'", timeout_seconds=10, runner=session_run)
    assert second["status"] == "running"
    for _ in range(100):
        if mgr.result(second["job_id"])["status"] == "completed":
            break
        time.sleep(.01)
    assert normal == ["Write-Output 'normal'"]
    assert visible_calls == ["Write-Output 'session'"]
