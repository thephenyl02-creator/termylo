"""Safety tests for the user-gesture-only termylo://start protocol."""
from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path

import pytest


MODULE = Path(__file__).resolve().parents[1] / "scripts" / "uri_launch.py"
spec = importlib.util.spec_from_file_location("termylo_uri_launch", MODULE)
assert spec and spec.loader
uri_launch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(uri_launch)


@pytest.mark.parametrize("uri", [
    "termylo://start",
    "termylo://start/",
    "TERMYLO://START",
])
def test_allowlisted_uri(uri):
    assert uri_launch.valid_uri(uri)


@pytest.mark.parametrize("uri", [
    "",
    "https://example.com",
    "termylo://stop",
    "termylo://start?command=whoami",
    "termylo://start#cmd",
    "termylo://start/anything",
    "termylo://start/%22",
    "termylo://start?password=hello",
    "termylo://evil/start",
    "termylo://start" + "x" * 100,
])
def test_rejects_other_actions_and_untrusted_payloads(uri):
    assert not uri_launch.valid_uri(uri)
    assert uri_launch.main([uri]) == 2


def test_rejects_additional_arguments():
    assert uri_launch.main(["termylo://start", "Get-ChildItem"]) == 2


def test_handler_cannot_run_any_url_input_as_shell_command(tmp_path):
    repo = tmp_path / "termylo"
    launcher = repo / "scripts" / "start-tunnel-secure.ps1"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("# dummy only")
    windows = tmp_path / "Windows"
    powershell = windows / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    powershell.parent.mkdir(parents=True)
    powershell.write_text("# dummy only")
    cmd = uri_launch.launcher_command(repo, windows)
    assert cmd[0] == str(powershell)
    assert cmd[-1] == str(launcher)
    assert "-File" in cmd
    assert "termylo://start" not in " ".join(cmd)
    assert "cmd.exe" not in " ".join(cmd)


@pytest.mark.skipif(os.name != "nt", reason="Windows STARTUPINFO requires Windows")
def test_real_windows_launch_arguments_never_include_untrusted_uri(monkeypatch):
    spawned = []
    def fake_popen(cmd, **options):
        spawned.append((cmd, options))
        return object()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    assert uri_launch.main(["termylo://start"]) == 0
    assert len(spawned) == 1
    cmd, opts = spawned[0]
    assert cmd[-1].endswith("start-tunnel-secure.ps1")
    assert "termylo://start" not in " ".join(cmd)
    assert opts["creationflags"] & subprocess.CREATE_NEW_CONSOLE
    assert opts["startupinfo"].wShowWindow == 2
