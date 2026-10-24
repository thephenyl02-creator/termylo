"""Regression tests from line-by-line security and robustness review."""
from __future__ import annotations
import sys
import threading
import time
import types
from unittest.mock import patch
import pytest
from termylo.jobs import JobManager
from termylo.runner import _clean_stderr

def _finish(manager, jid):
    for _ in range(250):
        result = manager.result(jid)
        if result["status"] != "awaiting_approval_or_running":
            return result
        time.sleep(.01)
    pytest.fail("Job never finished")

def test_thread_start_failure_leaves_no_stuck_job(monkeypatch):
    monkeypatch.setattr("termylo.jobs.os.name", "nt")
    manager = JobManager(lambda *a, **kw: {"status": "denied"})
    class BrokenThread:
        def __init__(self, *args, **kw): pass
        def start(self): raise RuntimeError("thread exhausted")
    with patch("termylo.jobs.threading.Thread", BrokenThread):
        assert manager.submit("Get-Date")["status"] == "error"
    assert manager.status()["active_job"] is None
    jid = manager.submit("Get-Date")["job_id"]
    assert _finish(manager, jid)["status"] == "denied"

@pytest.mark.parametrize("invalid", [None, "oops", [], {}, {"status": "pending"}, {"status": None}])
def test_worker_invalid_return_is_rejected(monkeypatch, invalid):
    monkeypatch.setattr("termylo.jobs.os.name", "nt")
    manager = JobManager(lambda *a, **kw: invalid)
    jid = manager.submit("Get-Date")["job_id"]
    assert _finish(manager, jid)["status"] == "error"
    assert manager.status()["active_job"] is None

def test_progress_xml_only_removed_and_errors_preserved():
    progress = b'#< CLIXML\r\n<Objs><Obj S="progress"><S>initializing</S></Obj></Objs>'
    assert _clean_stderr(progress) == ""
    mixed = b'#< CLIXML\r\n<Objs><Obj S="progress"/><Obj S="error"><S>failed</S></Obj></Objs>'
    assert "failed" in _clean_stderr(mixed)
    assert _clean_stderr(b"#< CLIXML\n<Objs>malformed") != ""

class FakeWindow:
    def __init__(self, action, cancel):
        self.action, self.cancel = action, cancel
        self.buttons, self.scheduled = {}, []
        self.closed = False
        self.on_close = None
    def title(self, *a): pass
    def geometry(self, *a): pass
    def minsize(self, *a): pass
    def attributes(self, *a): pass
    def protocol(self, event, cb): self.on_close = cb
    def after(self, ms, cb): self.scheduled.append((ms, cb))
    def quit(self): self.closed = True
    def destroy(self): pass
    def mainloop(self):
        if self.action == "approve":
            self.buttons["APPROVE ONCE"]()
        elif self.action == "deny":
            self.buttons["DENY"]()
        elif self.action == "timeout":
            next(cb for ms, cb in self.scheduled if ms == 60000)()
        else:
            self.on_close()
        assert self.closed

@pytest.mark.parametrize("action,approved", [("approve", True), ("deny", False), ("timeout", False), ("cancel", False)])
def test_gui_approval_denial_timeout_and_cancel(monkeypatch, action, approved):
    from termylo.approval import _show_dialog
    event = threading.Event()
    root = FakeWindow(action, event)
    class Widget:
        def __init__(self, *a, **kw):
            if "text" in kw and "command" in kw:
                root.buttons[kw["text"]] = kw["command"]
        def pack(self, *a, **kw): pass
        def insert(self, *a): pass
        def configure(self, *a, **kw): pass
    module = types.ModuleType("tkinter")
    module.Tk = lambda: root
    module.Frame = Widget
    module.Label = Widget
    module.Button = Widget
    submodule = types.ModuleType("tkinter.scrolledtext")
    submodule.ScrolledText = Widget
    monkeypatch.setitem(sys.modules, "tkinter", module)
    monkeypatch.setitem(sys.modules, "tkinter.scrolledtext", submodule)
    assert _show_dialog("Write-Output 'test'") is approved
