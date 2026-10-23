"""Simulated full path: submission, approval, output, denial, cancellation."""
from __future__ import annotations
import threading
import time
import pytest
from termylo.jobs import JobManager

def until_finished(manager, jid, seconds=3):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        value = manager.result(jid)
        if value["status"] != "awaiting_approval_or_running":
            return value
        time.sleep(0.005)
    pytest.fail("Job did not finish")

def test_approved_command_roundtrip(monkeypatch):
    monkeypatch.setattr("termylo.jobs.os.name", "nt")
    approved = threading.Event()
    def fake_powershell(command, timeout, cancel_event):
        approved.wait(1)
        if cancel_event.is_set():
            return {"status": "cancelled"}
        return {"status": "completed", "exit_code": 0, "stdout": "simulated output", "stderr": ""}
    mgr = JobManager(fake_powershell)
    req = mgr.submit("Write-Output 'simulated output'", 30)
    assert req["status"] == "awaiting_approval"
    jid = req["job_id"]
    assert mgr.result(jid)["status"] == "awaiting_approval_or_running"
    assert mgr.submit("Get-Date")["status"] == "busy"
    assert mgr.status()["active_job"] == jid
    approved.set()
    result = until_finished(mgr, jid)
    assert result["status"] == "completed"
    assert result["stdout"] == "simulated output"
    assert result["exit_code"] == 0
    assert mgr.status()["active_job"] is None

def test_denial_roundtrip(monkeypatch):
    monkeypatch.setattr("termylo.jobs.os.name", "nt")
    mgr = JobManager(lambda c, t, cancel_event: {"status": "denied"})
    assert until_finished(mgr, mgr.submit("Get-Date")["job_id"])["status"] == "denied"

def test_cancel_pending_job(monkeypatch):
    monkeypatch.setattr("termylo.jobs.os.name", "nt")
    started = threading.Event()
    def fake_powershell(command, timeout, cancel_event):
        started.set()
        assert cancel_event.wait(1)
        return {"status": "cancelled"}
    mgr = JobManager(fake_powershell)
    jid = mgr.submit("Start-Sleep -Seconds 7")["job_id"]
    assert started.wait(1)
    assert mgr.cancel(jid)["status"] == "cancellation_requested"
    assert until_finished(mgr, jid)["status"] == "cancelled"

def test_invalid_and_unsupported(monkeypatch):
    monkeypatch.setattr("termylo.jobs.os.name", "nt")
    mgr = JobManager(lambda *a, **k: pytest.fail("Must not execute"))
    assert mgr.submit("")["status"] == "rejected"
    assert mgr.submit("x" * 5000)["status"] == "rejected"
    monkeypatch.setattr("termylo.jobs.os.name", "posix")
    assert mgr.submit("Get-Date")["status"] == "unavailable"

def test_unknown_job_and_exception(monkeypatch):
    monkeypatch.setattr("termylo.jobs.os.name", "nt")
    mgr = JobManager(lambda *a, **k: 1 / 0)
    assert mgr.result("not-a-job")["status"] == "not_found"
    assert mgr.cancel("not-a-job")["status"] == "not_found"
    jid = mgr.submit("Get-Date")["job_id"]
    result = until_finished(mgr, jid)
    assert result["status"] == "error"
    assert "ZeroDivisionError" not in result["error"]

def test_prunes_expired(monkeypatch):
    monkeypatch.setattr("termylo.jobs.os.name", "nt")
    mgr = JobManager(lambda c, t, cancel_event: {"status": "completed", "exit_code": 0})
    jid = mgr.submit("Get-Date")["job_id"]
    until_finished(mgr, jid)
    mgr._jobs[jid].created -= 1000
    assert mgr.result(jid)["status"] == "not_found"
