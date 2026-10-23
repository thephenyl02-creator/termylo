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
