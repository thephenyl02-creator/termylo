import subprocess
from unittest.mock import patch
from termylo.runner import execute, validate

def test_invalid_and_empty():
    assert validate("", 45)
    assert validate("Get-Date", 0)
    assert validate("Get-Date", 121)
    assert validate("x" * 501, 30)
    assert validate("Get-Date", True)

def test_reject_on_nonwindows():
    assert execute("Get-Date", windows=False)["status"] == "unavailable"

def test_user_denies():
    assert execute("Get-Date", approval=lambda _: False, windows=True)["status"] == "denied"

def test_missing_gui_fails_closed():
    def failure(_):
        raise RuntimeError("No display")
    assert execute("Get-Date", approval=failure, windows=True)["status"] == "denied"

def test_success_and_output(monkeypatch, tmp_path):
    monkeypatch.setenv("TERMYLO_WORKDIR", str(tmp_path))
    completed = subprocess.CompletedProcess(args=["powershell.exe"], returncode=2, stdout="output", stderr="problem")
    with patch("termylo.runner.subprocess.run", return_value=completed) as run:
        result = execute("Get-Date", approval=lambda _: True, windows=True)
    assert result["status"] == "completed"
    assert result["exit_code"] == 2
    assert result["stdout"] == "output"
    assert result["stderr"] == "problem"
    assert run.call_args.args[0][0] == "powershell.exe"
    assert run.call_args.kwargs["stdin"] == subprocess.DEVNULL
    assert run.call_args.kwargs.get("shell", False) is False

def test_timeout(monkeypatch, tmp_path):
    monkeypatch.setenv("TERMYLO_WORKDIR", str(tmp_path))
    with patch("termylo.runner.subprocess.run", side_effect=subprocess.TimeoutExpired("powershell.exe", 3)):
        assert execute("Start-Sleep -Seconds 100", 3, approval=lambda _: True, windows=True)["status"] == "timeout"

def test_bad_workdir(monkeypatch, tmp_path):
    monkeypatch.setenv("TERMYLO_WORKDIR", str(tmp_path / "absent"))
    assert execute("Get-Date", approval=lambda _: True, windows=True)["status"] == "rejected"
