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


def test_parallel_jobs_for_different_projects_and_busy_same_project(monkeypatch):
    monkeypatch.setattr(jobs_module.os, "name", "nt")
    manager = JobManager()
    release = threading.Event()
    started = threading.Event()

    def worker(command, timeout, cancel_event):
        started.set()
        release.wait(2)
        return {"status": "completed", "exit_code": 0, "stdout": command, "stderr": ""}

    try:
        first = manager.submit("Get-Date", 10, project_id="axtario", runner=worker)
        assert first["job_id"] and started.wait(2)
        blocked = manager.submit("Get-Date", 10, project_id="axtario", runner=worker)
        assert blocked["status"] == "busy"
        second = manager.submit("Get-Date", 10, project_id="akira", runner=worker)
        assert second["job_id"] != first["job_id"]
    finally:
        release.set()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and (
        manager.result(first["job_id"])["status"] != "completed"
        or manager.result(second["job_id"])["status"] != "completed"
    ):
        time.sleep(.01)
    assert manager.result(first["job_id"])["status"] == "completed"
    assert manager.result(second["job_id"])["status"] == "completed"
