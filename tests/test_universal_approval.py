"""One physical approval authorizes separate native project windows."""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from termylo import native
from termylo import universal_approval
from termylo.project_sessions import ProjectSessions


class FakeProcess:
    _next_pid = 30000

    def __init__(self, consent=False):
        type(self)._next_pid += 1
        self.pid = type(self)._next_pid
        self.returncode = 0 if consent else None
        self.stopped = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.stopped = True
        self.returncode = -1


def fake_laptop(monkeypatch):
    monkeypatch.setattr(native, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(native, "_is_admin", lambda: False)
    monkeypatch.setattr(native, "_system_powershell", lambda: "C:/Windows/powershell.exe")
    consoles, approvals, launches = [], [], []

    def popen(argv, **kwargs):
        is_approval = "termylo.native_approval" in argv
        proc = FakeProcess(consent=is_approval)
        launches.append((argv, kwargs, proc))
        (approvals if is_approval else consoles).append(proc)
        return proc

    monkeypatch.setattr(native.subprocess, "Popen", popen)
    monkeypatch.setattr(native, "_terminate_tree", lambda proc: proc.terminate())
    monkeypatch.setattr(universal_approval, "_terminate_tree", lambda proc: proc.terminate())
    monkeypatch.setattr(native, "_native_exchange", lambda *args:
                        {"status": "completed", "exit_code": 0,
                         "stdout": "ready", "stderr": ""})
    return consoles, approvals, launches


def wait_state(shell, expected="active"):
    end = time.monotonic() + 3
    while time.monotonic() < end:
        current = shell.status()
        if current["status"] == expected:
            return current
        time.sleep(.01)
    raise AssertionError(f"Expected {expected}: {shell.status()}")


def test_single_consent_covers_a_b_c_distinct_processes(tmp_path, monkeypatch):
    consoles, approvals, launches = fake_laptop(monkeypatch)
    grant = universal_approval.UniversalApproval()
    registry = ProjectSessions(approval=grant)
    paths = []
    shells = []
    for name in ("A", "B", "C"):
        path = tmp_path / name
        path.mkdir()
        key, shell, issue = registry.prepare(name, 4, str(path))
        assert issue is None
        response = shell.start()
        assert response["status"] in ("awaiting_approval", "opening")
        state = wait_state(shell)
        assert state["project_id"] == key
        paths.append(state["working_directory"])
        shells.append(shell)
    assert len(approvals) == 1
    assert len(consoles) == 3
    assert len(set(p.pid for p in consoles)) == 3
    assert len(set(shell.status()["session_id"] for shell in shells)) == 3
    assert len(set(paths)) == 3
    assert len(set(shell._project_environment()["TERMYLO_PROJECT_ID"] for shell in shells)) == 3
    assert len(set(shell._opened_at for shell in shells)) == 1
    assert grant.status()["absolute_limit_seconds"] == 14400
    assert grant.status()["idle_limit_seconds"] is None


def test_closing_one_project_does_not_revoke_universal_lease(monkeypatch):
    consoles, approvals, _ = fake_laptop(monkeypatch)
    grant = universal_approval.UniversalApproval()
    registry = ProjectSessions(approval=grant)
    _, a, _ = registry.prepare("a")
    a.start()
    sid = wait_state(a)["session_id"]
    assert a.close(sid)["status"] == "closed"
    assert grant.status()["status"] == "active"
    _, b, _ = registry.prepare("b")
    b.start()
    assert wait_state(b)["status"] == "active"
    assert len(approvals) == 1 and len(consoles) == 2


def test_ten_hour_lease_is_shared_and_cannot_be_extended_by_new_project(monkeypatch):
    _, approvals, _ = fake_laptop(monkeypatch)
    grant = universal_approval.UniversalApproval()
    registry = ProjectSessions(approval=grant)
    _, a, _ = registry.prepare("a", 10)
    a.start()
    wait_state(a)
    _, b, _ = registry.prepare("b", 4)
    b.start()
    wait_state(b)
    assert grant.status()["absolute_limit_seconds"] == 36000
    assert a.status()["absolute_limit_seconds"] == 36000
    assert b.status()["absolute_limit_seconds"] == 36000
    assert a._opened_at == b._opened_at
    assert len(approvals) == 1


def test_global_expiry_invalidates_every_session_without_new_consent(monkeypatch):
    consoles, approvals, _ = fake_laptop(monkeypatch)
    grant = universal_approval.UniversalApproval()
    registry = ProjectSessions(approval=grant)
    sessions = []
    for key in ("a", "b"):
        _, native_session, _ = registry.prepare(key)
        native_session.start()
        sessions.append((native_session, wait_state(native_session)["session_id"]))
    with grant._lock:
        grant._opened_at -= 14401
    assert grant.status()["status"] == "closed"
    for shell, sid in sessions:
        assert shell.validate(sid)["status"] == "unavailable"
    assert len(approvals) == 1
    # All expired project windows close rather than staying local-only.
    assert all(proc.stopped for proc in consoles)


def test_explicit_global_revoke_closes_all_windows(monkeypatch):
    consoles, approvals, _ = fake_laptop(monkeypatch)
    grant = universal_approval.UniversalApproval()
    registry = ProjectSessions(approval=grant)
    for key in ("a", "b"):
        _, shell, _ = registry.prepare(key)
        shell.start()
        wait_state(shell)
    result = registry.close_all()
    assert result["status"] == "closed"
    assert grant.status()["status"] == "closed"
    assert len(approvals) == 1
    assert all(proc.stopped for proc in consoles)
    assert all(item["status"] == "closed" for item in registry.list_status())

def test_expiry_monitor_closes_idle_windows_without_status_poll(monkeypatch):
    consoles, approvals, _ = fake_laptop(monkeypatch)
    grant = universal_approval.UniversalApproval()
    registry = ProjectSessions(approval=grant)
    for name in ('a', 'b'):
        _, shell, _ = registry.prepare(name)
        shell.start()
        wait_state(shell)
    assert len(approvals) == 1
    with grant._lock:
        grant._opened_at -= 14401
    end = time.monotonic() + 3
    while not all(p.stopped for p in consoles) and time.monotonic() < end:
        time.sleep(.02)
    assert all(p.stopped for p in consoles)
    assert all(x['status'] == 'closed' for x in registry.list_status())
    _, new_shell, _ = registry.prepare('a')
    new_shell.start()
    assert wait_state(new_shell)['status'] == 'active'
    assert len(approvals) == 2
    assert len(consoles) == 3
    assert consoles[-1].stopped is False
def test_explicit_replacement_of_four_hours_with_six_requires_new_one_time_consent(monkeypatch):
    consoles, approvals, _ = fake_laptop(monkeypatch)
    grant = universal_approval.UniversalApproval()
    registry = ProjectSessions(approval=grant)
    active = []
    for name in ("alpha", "beta"):
        key, shell, issue = registry.prepare(name, 4)
        assert issue is None
        assert shell.start()["status"] in ("awaiting_approval", "opening")
        state = wait_state(shell)
        active.append((key, shell, state["session_id"]))
    original_grant = grant.status()["grant_id"]
    assert len(approvals) == 1
    assert len(consoles) == 2

    replaced = registry.replace_approval("alpha", duration_hours=6)
    assert replaced["previous_approval_revoked"] is True
    assert replaced["requested_hours"] == 6
    assert replaced["status"] in ("awaiting_approval", "opening")
    new_state = wait_state(active[0][1])
    assert new_state["session_id"] != active[0][2]
    assert grant.status()["absolute_limit_seconds"] == 21600
    assert grant.status()["idle_limit_seconds"] is None
    assert len(approvals) == 2  # new physical Windows approval
    assert len(consoles) == 3
    assert consoles[0].stopped and consoles[1].stopped
    assert not grant.valid(original_grant)
    assert grant.status()["grant_id"] != original_grant

    # The second project reattaches under the new ONE six-hour grant.
    _, beta, issue = registry.prepare("beta", 6)
    assert issue is None
    assert beta.start()["status"] in ("awaiting_approval", "opening")
    assert wait_state(beta)["session_id"] != active[1][2]
    assert len(approvals) == 2
    assert len(consoles) == 4


def test_bad_replacement_parameters_do_not_terminate_the_current_grant(monkeypatch):
    consoles, approvals, _ = fake_laptop(monkeypatch)
    grant = universal_approval.UniversalApproval()
    registry = ProjectSessions(approval=grant)
    _, shell, _ = registry.prepare("alpha", 4)
    shell.start()
    sid = wait_state(shell)["session_id"]
    token = grant.status()["grant_id"]
    for bad in (0, -1, float("inf"), float("nan"), True, "6"):
        assert registry.replace_approval("alpha", bad)["status"] == "rejected"
    assert registry.replace_approval(
        "alpha", 6, working_directory="C:/__termylo_nonexistent_directory__"
    )["status"] == "rejected"
    assert shell.status()["session_id"] == sid
    assert grant.valid(token)
    assert len(approvals) == 1
    assert not consoles[0].stopped
