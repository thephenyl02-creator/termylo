"""Approval, environment, Windows real execution, unicode, truncation, timeouts."""
from __future__ import annotations
import os
import threading
import pytest
from termylo.runner import MAX_TIMEOUT, MAX_OUTPUT_BYTES, run_command, validate

def test_command_validation():
    assert validate("", 45)
    assert validate("   ", 45)
    assert validate(None, 45)
    assert validate("Get-Date", False)
    assert validate("Get-Date", 0)
    assert validate("Get-Date", MAX_TIMEOUT + 1)
    assert validate("x" * 2001, 15)
    assert validate("test\x00", 15)
    assert validate("Get-Date", 30) is None

def test_unsupported_os():
    assert run_command("Get-Date", platform="posix")["status"] == "unavailable"

def test_elevated_refused():
    assert run_command("Get-Date", platform="nt", elevated=True)["status"] == "unavailable"

def test_denial_prevents_subprocess(monkeypatch):
    import termylo.runner as runner
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **k: pytest.fail("must not execute"))
    assert run_command("Get-Date", platform="nt", elevated=False, approve=lambda c, e: False)["status"] == "denied"

def test_approval_exception_fails_closed(monkeypatch):
    import termylo.runner as runner
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **k: pytest.fail("must not execute"))
    assert run_command("Get-Date", platform="nt", elevated=False, approve=lambda c, e: 1 / 0)["status"] == "denied"

def test_cancel_before_approval(monkeypatch):
    import termylo.runner as runner
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **k: pytest.fail("must not execute"))
    ev = threading.Event()
    ev.set()
    assert run_command("Get-Date", platform="nt", elevated=False, approve=lambda c, e: True, cancel_event=ev)["status"] == "cancelled"

def test_bad_cwd(monkeypatch, tmp_path):
    monkeypatch.setenv("TERMYLO_WORKDIR", str(tmp_path / "absent"))
    assert run_command("Get-Date", platform="nt", elevated=False, approve=lambda c, e: True)["status"] == "rejected"

def test_missing_powershell(monkeypatch, tmp_path):
    import termylo.runner as runner
    monkeypatch.setenv("TERMYLO_WORKDIR", str(tmp_path))
    monkeypatch.setattr(runner.shutil, "which", lambda executable: None)
    assert run_command("Get-Date", platform="nt", elevated=False, approve=lambda c, e: True)["status"] == "unavailable"

def test_no_api_key_in_child_environment(monkeypatch):
    from termylo.runner import _environment
    monkeypatch.setenv("OPENAI_API_KEY", "fake_test_value")
    monkeypatch.setenv("TERMYLO_SECRET", "not_in_child")
    assert "OPENAI_API_KEY" not in _environment()
    assert "TERMYLO_SECRET" not in _environment()

@pytest.mark.skipif(os.name != "nt", reason="Real Windows PowerShell required")
def test_windows_real_execution_and_unicode(tmp_path, monkeypatch):
    monkeypatch.setenv("TERMYLO_WORKDIR", str(tmp_path))
    result = run_command("Write-Output 'Termylo OK – café'", platform="nt", elevated=False, approve=lambda c, e: True)
    assert result["status"] == "completed", result
    assert result["exit_code"] == 0
    assert "Termylo OK – café" in result["stdout"]
    assert result["stderr"] == ""

@pytest.mark.skipif(os.name != "nt", reason="Real Windows PowerShell required")
def test_windows_real_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("TERMYLO_WORKDIR", str(tmp_path))
    result = run_command("Write-Error 'test failure'; exit 23", platform="nt", elevated=False, approve=lambda c, e: True)
    assert result["status"] == "completed", result
    assert result["exit_code"] == 23
    assert "test failure" in result["stderr"]

@pytest.mark.skipif(os.name != "nt", reason="Real Windows PowerShell required")
def test_windows_large_output_bounded(tmp_path, monkeypatch):
    monkeypatch.setenv("TERMYLO_WORKDIR", str(tmp_path))
    result = run_command("'x' * 200000", platform="nt", elevated=False, approve=lambda c, e: True)
    assert result["status"] == "completed", result
    assert result["stdout_truncated"]
    assert len(result["stdout"].encode("utf-8")) <= MAX_OUTPUT_BYTES

@pytest.mark.skipif(os.name != "nt", reason="Real Windows PowerShell required")
def test_windows_real_timeout(tmp_path, monkeypatch):
    monkeypatch.setenv("TERMYLO_WORKDIR", str(tmp_path))
    result = run_command("Start-Sleep -Seconds 7", timeout_seconds=1, platform="nt", elevated=False, approve=lambda c, e: True)
    assert result["status"] == "timeout", result


def test_suppress_only_clixml_progress():
    from termylo.runner import _clean_stderr
    payload = b'#< CLIXML\r\n<Objs xmlns="http://schemas.microsoft.com/powershell/2004/04"><Obj S="progress"><S>initializing</S></Obj></Objs>'
    assert _clean_stderr(payload) == ""
    error_payload = b'#< CLIXML\n<Objs><Obj S="Error"><S>real failure</S></Obj></Objs>'
    assert "real failure" in _clean_stderr(error_payload)
    assert _clean_stderr(b"ordinary warning") == "ordinary warning"
