"""Directly verify MCP function delegation and diagnostics; subprocess MCP also tested separately."""
from __future__ import annotations

def test_status_delegates_to_manager(monkeypatch):
    import termylo.server as server
    monkeypatch.setattr(server.jobs, "status", lambda: {"online": True, "name": "Termylo"})
    assert server.termylo_status() == {"online": True, "name": "Termylo"}

def test_safe_tool_delegation_without_execution(monkeypatch):
    import termylo.server as server
    calls = []
    def fake_submit(cmd, timeout):
        calls.append(("submit", cmd, timeout))
        return {"status": "awaiting_approval", "job_id": "test-job"}
    monkeypatch.setattr(server.jobs, "submit", fake_submit)
    monkeypatch.setattr(server.jobs, "result", lambda jid: {"status": "denied", "job_id": jid})
    monkeypatch.setattr(server.jobs, "cancel", lambda jid: {"status": "cancellation_requested", "job_id": jid})
    assert server.execute_powershell("Get-Date", 3)["job_id"] == "test-job"
    assert calls == [("submit", "Get-Date", 3)]
    assert server.powershell_result("test-job")["status"] == "denied"
    assert server.cancel_powershell("test-job")["status"] == "cancellation_requested"

def test_doctor_is_read_only_and_reports_platform(monkeypatch, tmp_path):
    import termylo.doctor as doctor
    monkeypatch.setenv("TERMYLO_WORKDIR", str(tmp_path))
    monkeypatch.setattr(doctor, "_system_powershell", lambda: "/fake/system/powershell.exe")
    report = doctor.report()
    assert report["workdir_exists"]
    assert report["powershell_found"]
    assert report["mcp_sdk_found"]
    assert report["network_listener"] == "none (stdio only)"

def test_doctor_missing_system_powershell(monkeypatch, tmp_path):
    import termylo.doctor as doctor
    monkeypatch.setenv("TERMYLO_WORKDIR", str(tmp_path))
    monkeypatch.setattr(doctor, "_system_powershell", lambda: None)
    assert doctor.report()["powershell_found"] is False


def test_default_timeout_is_consistent_across_mcp_queue_and_runner():
    from inspect import signature
    from termylo.runner import run_command
    from termylo.jobs import JobManager
    from termylo.server import execute_powershell
    for function in (execute_powershell, JobManager.submit, run_command):
        assert signature(function).parameters["timeout_seconds"].default == 90


def test_manual_smoke_exercises_job_submission_and_result(monkeypatch, capsys):
    from scripts import manual_smoke
    monkeypatch.setattr(manual_smoke.os, "name", "nt")

    class FakeManager:
        def submit(self, command, timeout_seconds):
            assert command == manual_smoke.COMMAND
            assert timeout_seconds == 60
            return {"status": "awaiting_approval", "job_id": "test-job"}

        def result(self, job_id):
            assert job_id == "test-job"
            return {"status": "completed", "exit_code": 0, "stdout": manual_smoke.EXPECTED, "stderr": ""}

    monkeypatch.setattr(manual_smoke, "JobManager", FakeManager)
    assert manual_smoke.main() == 0
    assert "PASS:" in capsys.readouterr().out


def test_manual_smoke_reports_denial_without_false_success(monkeypatch, capsys):
    from scripts import manual_smoke
    monkeypatch.setattr(manual_smoke.os, "name", "nt")

    class FakeManager:
        def submit(self, command, timeout_seconds):
            return {"status": "awaiting_approval", "job_id": "test-job"}
        def result(self, job_id):
            return {"status": "denied", "error": "Denied"}

    monkeypatch.setattr(manual_smoke, "JobManager", FakeManager)
    assert manual_smoke.main() == 1
    assert "NOT VERIFIED" in capsys.readouterr().out
