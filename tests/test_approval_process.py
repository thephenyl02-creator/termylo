"""Approval IPC regression tests: worker isolation, denial, failure and cancellation.

No actual GUI is opened in CI. The real GUI must still be approved on the
owner's Windows desktop using scripts/manual_smoke.py.
"""
from __future__ import annotations

import io
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest
from termylo import approval


class Sink:
    def __init__(self):
        self.data = b""
        self.closed = False

    def write(self, data):
        self.data += data
        return len(data)

    def close(self):
        self.closed = True


class ApprovalChild:
    def __init__(self, code=0, running=False):
        self.stdin = Sink()
        self.returncode = None if running else code
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


@pytest.mark.parametrize("code,expected", [(0, True), (1, False), (2, False), (-1, False)])
def test_approval_process_exit_codes_are_fail_closed(monkeypatch, code, expected):
    proc = ApprovalChild(code)
    captured = {}
    def popen(argv, **kwargs):
        captured.update({"argv": argv, "kwargs": kwargs})
        return proc
    monkeypatch.setattr(approval.subprocess, "Popen", popen)
    result = approval.ask_local_user("Write-Output 'hello'", threading.Event())
    assert result is expected
    assert proc.stdin.data == b"Write-Output 'hello'"
    assert proc.stdin.closed
    assert captured["argv"] == [sys.executable, "-m", "termylo.approval"]
    assert captured["kwargs"]["stdin"] == subprocess.PIPE
    assert captured["kwargs"]["stdout"] == subprocess.DEVNULL
    assert captured["kwargs"]["stderr"] == subprocess.DEVNULL
    assert captured["kwargs"]["env"].get("OPENAI_API_KEY") is None


def test_worker_thread_can_wait_for_approval_without_creating_tk(monkeypatch):
    proc = ApprovalChild(code=0)
    monkeypatch.setattr(approval.subprocess, "Popen", lambda *args, **kw: proc)
    observations = []
    def worker():
        observations.append(approval.ask_local_user("Get-Date", threading.Event()))
    thread = threading.Thread(target=worker, name="termylo-job-test")
    thread.start()
    thread.join(timeout=3)
    assert not thread.is_alive()
    assert observations == [True]
    assert proc.stdin.data == b"Get-Date"


def test_cancellation_terminates_approval_process(monkeypatch):
    proc = ApprovalChild(running=True)
    event = threading.Event()
    monkeypatch.setattr(approval.subprocess, "Popen", lambda *a, **kw: proc)
    # The parent polls cancellation without awaiting any GUI thread callback.
    monkeypatch.setattr(approval.time, "sleep", lambda _: event.set())
    assert approval.ask_local_user("Get-Date", event) is False
    assert proc.terminated and proc.returncode != 0


def test_approval_failure_or_oversized_command_never_executes(monkeypatch):
    def reject_launch(*args, **kwargs):
        raise OSError("cannot launch")
    monkeypatch.setattr(approval.subprocess, "Popen", reject_launch)
    assert approval.ask_local_user("Get-Date", threading.Event()) is False
    assert approval.ask_local_user("a" * (approval.MAX_COMMAND + 1), threading.Event()) is False
    event = threading.Event()
    event.set()
    assert approval.ask_local_user("Get-Date", event) is False


def test_tk_dialog_refuses_to_run_on_worker_thread():
    returned = []
    thread = threading.Thread(target=lambda: returned.append(approval._show_dialog("Get-Date")))
    thread.start()
    thread.join(timeout=3)
    assert not thread.is_alive()
    assert returned == [False]


@pytest.mark.parametrize("input_bytes,expected", [
    (b"", 1),
    (b"x" * (approval.MAX_INPUT_BYTES + 1), 1),
    (b"\xff", 1),
    (b"\x00", 1),
    (b"Get-Date", 0),
])
def test_child_main_validates_input_and_default_denies(monkeypatch, input_bytes, expected):
    monkeypatch.setattr(approval, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(approval, "_show_dialog", lambda command: command == "Get-Date")
    monkeypatch.setattr(approval, "sys", SimpleNamespace(stdin=SimpleNamespace(buffer=io.BytesIO(input_bytes))))
    assert approval.main() == expected


def test_child_main_denies_gui_crash(monkeypatch):
    monkeypatch.setattr(approval, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(approval, "sys", SimpleNamespace(stdin=SimpleNamespace(buffer=io.BytesIO(b"Get-Date"))))
    def crash(command):
        raise RuntimeError("Tcl cannot initialize")
    monkeypatch.setattr(approval, "_show_dialog", crash)
    assert approval.main() == 1


def test_real_child_subprocess_rejects_empty_request_without_loading_tk():
    # Actual Python -m termylo.approval handshake; headless-safe even on Windows.
    result = subprocess.run(
        [sys.executable, "-m", "termylo.approval"],
        input=b"", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=15, check=False,
    )
    assert result.returncode == 1
    assert b"Tcl_AsyncDelete" not in result.stderr
