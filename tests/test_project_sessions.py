"""Project-scoped native terminal routing and configurable lease regression tests."""
from __future__ import annotations

import threading
import time

from termylo.native import NativeSession
from termylo.project_sessions import ProjectSessions
from termylo.jobs import JobManager
import termylo.jobs as jobs_module


def test_project_keys_share_within_project_and_isolate_others():
    legacy = NativeSession()
    registry = ProjectSessions(legacy)
    assert registry.get()[1] is legacy
    key, a = registry.get("Axtario")
    assert key == "axtario"
    assert registry.get(" AXTaRiO ")[1] is a
    assert registry.get("Akira")[1] is not a
    assert len(registry.list_status()) == 3


def test_custom_duration_and_project_directory_survive_reconnection(tmp_path, monkeypatch):
    registry = ProjectSessions()
    key, a, error = registry.prepare("Axtario", 10, str(tmp_path))
    assert error is None
    assert a.status()["absolute_limit_seconds"] == 36000
    assert a.status()["idle_limit_seconds"] is None
    assert a.status()["working_directory"] == str(tmp_path.resolve())
    original_status = a.status
    monkeypatch.setattr(a, "status", lambda: {"status": "active", "session_id": "running"})
    key2, same, error = registry.prepare("AXTARIO", 4)
    assert key2 == key and same is a and error is None
    assert a._max_session_seconds == 36000
    monkeypatch.setattr(a, "status", original_status)
    _, after_expiry, error = registry.prepare("axtario", 4)
    assert after_expiry is a and error is None
    assert after_expiry.status()["absolute_limit_seconds"] == 14400
    assert after_expiry.status()["working_directory"] == str(tmp_path.resolve())


def test_custom_duration_must_be_positive():
    native = NativeSession()
    assert native.configure(10) is None
    assert native.status()["absolute_limit_seconds"] == 36000
    assert native.configure(0)["status"] == "rejected"
    assert native.configure(float("inf"))["status"] == "rejected"


def test_independent_working_directories_and_process_environments(tmp_path):
    alpha_path = tmp_path / "alpha"
    beta_path = tmp_path / "beta"
    alpha_path.mkdir()
    beta_path.mkdir()
    registry = ProjectSessions()
    _, alpha, issue = registry.prepare("Alpha", 4, str(alpha_path))
    assert issue is None
    _, beta, issue = registry.prepare("Beta", 4, str(beta_path))
    assert issue is None
    assert alpha is not beta
    assert alpha.status()["working_directory"] != beta.status()["working_directory"]
    alpha_env = alpha._project_environment()
    beta_env = beta._project_environment()
    assert alpha_env["TERMYLO_PROJECT_ID"] == "alpha"
    assert beta_env["TERMYLO_PROJECT_ID"] == "beta"
    alpha_env["MY_CUSTOM_VARIABLE"] = "alpha-only"
    assert "MY_CUSTOM_VARIABLE" not in beta_env


def test_fifo_within_project_and_parallel_between_projects(monkeypatch):
    monkeypatch.setattr(jobs_module.os, "name", "nt")
    manager = JobManager()
    release_a = threading.Event()
    started_a = threading.Event()
    started_b = threading.Event()
    calls = []
    call_lock = threading.Lock()

    def worker(command, timeout, cancel_event):
        if command == "a-first":
            started_a.set()
            assert release_a.wait(3)
        if command == "b-first":
            started_b.set()
        with call_lock:
            calls.append(command)
        return {"status": "completed", "exit_code": 0, "stdout": command, "stderr": ""}

    try:
        first = manager.submit("a-first", 10, project_id="axtario", runner=worker)
        assert first["job_id"] and started_a.wait(2)
        queued = manager.submit("a-second", 10, project_id="axtario", runner=worker)
        assert queued["status"] == "queued" and queued["queue_position"] == 2
        assert manager.result(queued["job_id"])["status"] == "queued"
        other = manager.submit("b-first", 10, project_id="akira", runner=worker)
        assert other["job_id"] != first["job_id"]
        assert started_b.wait(2)
        assert "a-second" not in calls
    finally:
        release_a.set()

    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and any(
        manager.result(job["job_id"])["status"] != "completed"
        for job in (first, queued, other)
    ):
        time.sleep(.01)
    assert all(manager.result(job["job_id"])["status"] == "completed"
               for job in (first, queued, other))
    assert calls.index("a-first") < calls.index("a-second")


def test_cancel_queued_command_does_not_execute(monkeypatch):
    monkeypatch.setattr(jobs_module.os, "name", "nt")
    manager = JobManager()
    entered = threading.Event()
    release = threading.Event()
    executed = []

    def worker(command, timeout, cancel_event):
        if command == "first":
            entered.set()
            assert release.wait(3)
        executed.append(command)
        return {"status": "completed", "exit_code": 0}

    first = manager.submit("first", 10, project_id="x", runner=worker)
    assert entered.wait(2)
    queued = manager.submit("second", 10, project_id="x", runner=worker)
    assert queued["status"] == "queued"
    assert manager.cancel(queued["job_id"])["status"] == "cancellation_requested"
    assert manager.result(queued["job_id"])["status"] == "cancelled"
    release.set()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and manager.result(first["job_id"])["status"] != "completed":
        time.sleep(.01)
    assert manager.result(first["job_id"])["status"] == "completed"
    assert executed == ["first"]
