"""Journal durability and managed-process smoke tests."""
from __future__ import annotations
import os
import time
import threading

import pytest

from termylo.journal import JobJournal
from termylo.jobs import JobManager
from termylo.managed_processes import ManagedProcesses


def test_journal_persists_without_storing_commands_or_output(tmp_path, monkeypatch):
    path = tmp_path / "jobs.sqlite3"
    journal = JobJournal(path)
    journal.record("one", "axtario", "running")
    journal.record("one", "axtario", "completed", exit_code=0)
    journal.close()
    reread = JobJournal(path)
    entry = reread.get("one")
    assert entry["status"] == "completed"
    assert entry["exit_code"] == 0
    assert entry["output_available"] is False
    raw = path.read_bytes()
    assert b"password123" not in raw
    reread.close()


def test_old_inflight_command_reports_uncertainty(tmp_path):
    path = tmp_path / "jobs.sqlite3"
    journal = JobJournal(path)
    journal.record("mid-run", "termylo", "running")
    journal.close()
    recovered = JobJournal(path)
    entry = recovered.get("mid-run")
    assert entry["status"] == "outcome_unknown"
    assert entry["last_known_status"] == "running"
    assert "no automatic replay" in entry["message"]
    recovered.close()


def test_job_manager_uses_persistent_summary_after_memory_pruning(tmp_path, monkeypatch):
    monkeypatch.setattr("termylo.jobs.os.name", "nt")
    journal = JobJournal(tmp_path / "journal.db")
    def runner(cmd, timeout, cancel_event):
        return {"status": "completed", "exit_code": 0, "stdout": "private output"}
    mgr = JobManager(runner, journal=journal)
    job = mgr.submit("Write-Output 'private output'")
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and mgr.result(job["job_id"])["status"] != "completed":
        time.sleep(.01)
    assert mgr.result(job["job_id"])["status"] == "completed"
    mgr._jobs[job["job_id"]].created -= 1000
    summary = mgr.result(job["job_id"])
    assert summary["status"] == "completed"
    assert summary["output_available"] is False
    assert mgr.recent("termylo") == []
    assert mgr.recent("default")[0]["exit_code"] == 0
    journal.close()


class Approval:
    def __init__(self):
        self.active = True
        self.grant = "approved-grant"
    def status(self):
        return {"status": "active" if self.active else "closed",
                "grant_id": self.grant, "remaining_seconds": 120}


class Shell:
    def __init__(self, directory):
        self.directory = str(directory)
    def status(self):
        return {"status": "active", "working_directory": self.directory}


class Projects:
    def __init__(self, directory):
        self.shell = Shell(directory)
    def get(self, project_id):
        return project_id.strip().casefold(), self.shell


def poll(manager, pid, expected, seconds=8):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = manager.status(pid)
        if result["status"] == expected:
            return result
        time.sleep(.05)
    pytest.fail("Managed process did not reach "+expected+": "+str(manager.status(pid)))


@pytest.mark.skipif(os.name != "nt", reason="Requires Windows PowerShell")
def test_managed_background_process_output_and_project(tmp_path):
    mgr = ManagedProcesses(Approval(), Projects(tmp_path))
    job = mgr.start("Write-Output 'managed success'", "test-project", 20)
    assert job["status"] == "running"
    assert job["project_id"] == "test-project"
    result = poll(mgr, job["process_id"], "completed")
    assert result["exit_code"] == 0
    deadline = time.monotonic() + 2
    while "managed success" not in mgr.status(job["process_id"])["stdout_tail"] and time.monotonic() < deadline:
        time.sleep(.05)
    assert "managed success" in mgr.status(job["process_id"])["stdout_tail"]


@pytest.mark.skipif(os.name != "nt", reason="Requires Windows PowerShell")
def test_managed_stop_is_tracked(tmp_path):
    mgr = ManagedProcesses(Approval(), Projects(tmp_path))
    job = mgr.start("Start-Sleep -Seconds 15", "test-project", 30)
    assert job["status"] == "running"
    assert mgr.stop(job["process_id"])["status"] == "stopping"
    assert poll(mgr, job["process_id"], "cancelled")["status"] == "cancelled"


@pytest.mark.skipif(os.name != "nt", reason="Requires Windows PowerShell")
def test_managed_lease_revocation_stops_process(tmp_path):
    approval = Approval()
    mgr = ManagedProcesses(approval, Projects(tmp_path))
    job = mgr.start("Start-Sleep -Seconds 15", "test-project", 30)
    assert job["status"] == "running"
    approval.active = False
    assert poll(mgr, job["process_id"], "approval_expired")["status"] == "approval_expired"


@pytest.mark.skipif(os.name != "nt", reason="Requires Windows PowerShell")
def test_managed_requires_current_native_approval(tmp_path):
    approval = Approval()
    approval.active = False
    mgr = ManagedProcesses(approval, Projects(tmp_path))
    assert mgr.start("Write-Output 'no'", "test-project")["status"] == "unavailable"
