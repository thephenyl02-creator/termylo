"""Persistent owner approval and local lifecycle controls."""
from __future__ import annotations
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import uuid
from multiprocessing import AuthenticationError
from multiprocessing.connection import Client

import pytest

from termylo import control, supervisor
from termylo.project_sessions import ProjectSessions


class FakeApproval:
    """Simulates a local Windows approval without opening a real consent UI."""
    def __init__(self):
        self.active = False
        self.grant_id = None
        self.opened_at = None
        self.duration = 0
        self.prompts = 0
        self.revoked = False

    def begin(self, hours=4):
        if not self.active:
            self.prompts += 1
            self.active = True
            self.grant_id = secrets.token_urlsafe(16)
            self.opened_at = time.monotonic()
            self.duration = float(hours) * 3600
        return self.status()

    def status(self):
        if self.active and time.monotonic() - self.opened_at >= self.duration:
            self.active = False
        return {"status": "active" if self.active else "closed",
                "grant_id": self.grant_id if self.active else None,
                "remaining_seconds": max(0, self.duration -
                    (time.monotonic()-self.opened_at)) if self.active else 0,
                "reason": "fake local approval for tests"}

    def valid(self, grant_id):
        return self.status()["status"] == "active" and grant_id == self.grant_id

    def wait(self, cancel_event=None):
        return {"grant_id": self.grant_id, "opened_at": self.opened_at,
                "duration_seconds": self.duration} if self.active else None

    def revoke(self):
        self.active = False
        self.revoked = True
        return self.status()


def _request(path, key, data):
    link = Client(path, family="AF_PIPE", authkey=key)
    try:
        link.send_bytes(json.dumps(data).encode())
        return json.loads(link.recv_bytes(4096).decode())
    finally:
        link.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows named pipes")
def test_local_broker_survives_two_worker_connections_and_preserves_exact_deadline():
    name = r"\\.\pipe\TermyloSupervisorTest-" + uuid.uuid4().hex
    secret = secrets.token_bytes(32)
    fake = FakeApproval()
    broker = supervisor.Broker(fake)
    thread = threading.Thread(target=broker.serve, args=(name, secret), daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while True:
        try:
            first = _request(name, secret, {"op": "status"})
            break
        except (OSError, EOFError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(.05)
    assert first["status"] == "closed"
    created = _request(name, secret, {"op": "begin", "hours": .01})
    assert created["status"] == "active"
    token = created["grant_id"]
    first_lease = _request(name, secret, {"op": "lease"})
    original_opened = first_lease["opened_at"]
    time.sleep(.07)
    # New connection is analogous to an MCP worker coming back after restart.
    second = _request(name, secret, {"op": "status"})
    assert second["grant_id"] == token
    assert second["supervisor_instance"] == first["supervisor_instance"]
    assert second["remaining_seconds"] < created["remaining_seconds"]
    second_lease = _request(name, secret, {"op": "lease"})
    assert second_lease["opened_at"] == original_opened
    assert second_lease["duration_seconds"] == first_lease["duration_seconds"]
    assert fake.prompts == 1
    assert _request(name, secret, {"op": "valid", "grant_id": token})["valid"]
    # A wrong authentication key must never crash or restart the lease.
    with pytest.raises(AuthenticationError):
        _request(name, secrets.token_bytes(32), {"op": "status"})
    assert _request(name, secret, {"op": "status"})["grant_id"] == token
    _request(name, secret, {"op": "revoke"})
    assert not _request(name, secret, {"op": "valid", "grant_id": token})["valid"]
    assert fake.prompts == 1
    assert _request(name, secret, {"op": "stop"})["status"] == "stopped"
    try:
        _request(name, secret, {"op": "ping"})
    except (OSError, EOFError):
        pass
    thread.join(timeout=3)
    assert not thread.is_alive()


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI")
def test_windows_dpapi_secret_survives_new_python_process(tmp_path):
    home = tmp_path / "auth"
    key = supervisor.authkey(home)
    assert len(key) == 32
    assert supervisor.authkey(home) == key
    program = ("from termylo.supervisor import authkey;from pathlib import Path;"
               "print(authkey(Path(" + repr(str(home)) + ")).hex())")
    result = subprocess.run([sys.executable, "-c", program],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == key.hex()
    assert key.hex().encode() not in (home / "auth.dpapi").read_bytes()


def test_broker_never_reuses_a_revoked_lease():
    fake = FakeApproval()
    b = supervisor.Broker(fake)
    grant = b.handle({"op": "begin", "hours": .01})["grant_id"]
    assert b.handle({"op": "valid", "grant_id": grant})["valid"]
    b.handle({"op": "revoke"})
    assert not b.handle({"op": "valid", "grant_id": grant})["valid"]
    new = b.handle({"op": "begin", "hours": .01})["grant_id"]
    assert new != grant
    assert fake.prompts == 2


def test_expiry_is_absolute_not_extended_by_new_worker():
    fake = FakeApproval()
    b = supervisor.Broker(fake)
    b.handle({"op": "begin", "hours": .00004})
    old = b.handle({"op": "lease"})["opened_at"]
    time.sleep(.18)
    assert b.handle({"op": "status"})["status"] == "closed"
    assert not b.handle({"op": "valid", "grant_id": fake.grant_id})["valid"]
    assert old == fake.opened_at


def test_cli_revoke_does_not_stop_the_tunnel(monkeypatch):
    operations = []
    monkeypatch.setattr(control, "rpc",
        lambda op, **kwargs: (operations.append(op) or
                              {"status": "active" if op == "status" else "closed"}))
    assert control.revoke()["status"] == "revoked"
    assert operations == ["status", "revoke"]


def test_cli_stop_revokes_then_stops_tunnel_then_supervisor(monkeypatch):
    events = []
    monkeypatch.setattr(control, "rpc",
        lambda op, **kw: (events.append(op) or
                          {"status": "active" if op == "status" else "closed"}))
    monkeypatch.setattr(control, "stop_tunnel",
                        lambda: (events.append("tunnel-stop") or 1))
    assert control.stop()["status"] == "stopped"
    assert events == ["status", "revoke", "tunnel-stop", "stop", "ping"]


def test_restart_is_delegated_to_supervisor(monkeypatch):
    operations = []
    monkeypatch.setattr(control, "rpc",
        lambda op, **kw: (operations.append(op) or {"status": "scheduled"}))
    assert control.restart()["status"] == "scheduled"
    assert operations == ["restart"]


def test_supervisor_restart_preserves_lease(monkeypatch):
    fake = FakeApproval()
    broker = supervisor.Broker(fake)
    token = broker.handle({"op": "begin", "hours": 4})["grant_id"]
    signal = threading.Event()
    monkeypatch.setattr(control, "restart_worker", lambda: signal.set())
    result = broker.handle({"op": "restart"})
    assert result["status"] == "scheduled"
    assert signal.wait(2)
    assert broker.handle({"op": "status"})["grant_id"] == token
    assert fake.prompts == 1


def test_project_shell_cleanup_does_not_revoke_global_approval():
    class Fake:
        def __init__(self):
            self.closed = False
        def status(self):
            return {"session_id": "shell-1"}
        def close(self, sid):
            self.closed = True
    class Grant:
        def __init__(self):
            self.revocations = 0
        def revoke(self):
            self.revocations += 1
    grant = Grant()
    fake = Fake()
    projects = ProjectSessions(default_session=fake, approval=grant)
    result = projects.close_terminals_only()
    assert result["closed_terminals"] == 1
    assert fake.closed
    assert grant.revocations == 0

@pytest.mark.skipif(os.name != "nt", reason="Windows named pipe")
def test_two_independent_python_clients_share_one_active_grant(tmp_path):
    pipe = r"\\.\pipe\TermyloCrossProcess-" + uuid.uuid4().hex
    key = secrets.token_bytes(32)
    fake = FakeApproval()
    broker = supervisor.Broker(fake)
    listener = threading.Thread(target=broker.serve, args=(pipe, key), daemon=True)
    listener.start()
    for _ in range(70):
        try:
            first = _request(pipe, key, {"op": "begin", "hours": .1})
            break
        except (OSError, EOFError):
            time.sleep(.05)
    else:
        pytest.fail("Supervisor pipe did not start.")
    script = ("import json,sys;from multiprocessing.connection import Client;"
              "p=sys.argv[1];k=bytes.fromhex(sys.argv[2]);"
              "c=Client(p,family='AF_PIPE',authkey=k);"
              "c.send_bytes(b'{\"op\":\"status\"}');"
              "print(c.recv_bytes().decode());c.close()")
    child = subprocess.run([sys.executable, "-c", script, pipe, key.hex()],
                           capture_output=True, text=True, timeout=12)
    assert child.returncode == 0, child.stderr
    observed = json.loads(child.stdout)
    assert observed["grant_id"] == first["grant_id"]
    assert observed["supervisor_instance"] == broker.instance
    assert fake.prompts == 1
    _request(pipe, key, {"op": "stop"})
    try:
        _request(pipe, key, {"op": "ping"})
    except (OSError, EOFError):
        pass  # The supervisor may have exited before the wakeup ping.
    listener.join(timeout=3)
    assert not listener.is_alive()

def test_cancel_all_clears_queued_commands_at_session_replacement():
    from termylo.jobs import JobManager
    manager = JobManager()
    entered = threading.Event()
    old_queued_command_ran = threading.Event()
    def first_runner(command, timeout, cancel_event):
        entered.set()
        assert cancel_event.wait(3)
        return {"status": "cancelled"}
    def queued_runner(command, timeout, cancel_event):
        old_queued_command_ran.set()
        return {"status": "completed", "exit_code": 0}
    first = manager.submit("Write-Output 'old job'", project_id="alpha",
                           runner=first_runner)
    assert entered.wait(2)
    second = manager.submit("Write-Output 'must not run'", project_id="alpha",
                            runner=queued_runner)
    assert second["status"] == "queued"
    canceled = manager.cancel_all()
    assert canceled["job_count"] == 2
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and manager.result(first["job_id"])["status"] not in (
            "cancelled", "completed"):
        time.sleep(.02)
    assert manager.result(first["job_id"])["status"] == "cancelled"
    assert manager.result(second["job_id"])["status"] == "cancelled"
    assert not old_queued_command_ran.is_set()


def test_mcp_replace_tool_validates_before_any_cleanup(monkeypatch):
    import termylo.server as server
    events = []
    monkeypatch.setattr(server.jobs, "cancel_all", lambda: events.append("jobs"))
    monkeypatch.setattr(server.managed, "stop_all", lambda: events.append("managed"))
    monkeypatch.setattr(server.context, "close", lambda: events.append("context"))
    monkeypatch.setattr(server.projects, "replace_approval",
                        lambda project_id, duration_hours, working_directory=None:
                        (events.append(("replace", project_id, duration_hours)) or
                         {"status": "awaiting_approval", "project_id": project_id}))
    monkeypatch.setattr(server.universal_approval, "status",
                        lambda: {"status": "opening", "absolute_limit_seconds": 21600})
    assert server.replace_universal_native_approval(
        duration_hours=0)["status"] == "rejected"
    assert server.replace_universal_native_approval(
        duration_hours=-3)["status"] == "rejected"
    assert server.replace_universal_native_approval(
        duration_hours=6,
        working_directory="Z:/this_directory_never_exists")["status"] == "rejected"
    assert events == []
    data = server.replace_universal_native_approval(
        duration_hours=6, project_id="alpha")
    assert data["status"] == "awaiting_approval"
    assert data["universal_approval"]["status"] == "opening"
    assert events == ["jobs", "managed", "context", ("replace", "alpha", 6)]


@pytest.mark.skipif(os.name != "nt", reason="Windows MCP stdio")
def test_mcp_lists_explicit_six_hour_replacement_tool(tmp_path):
    import asyncio
    from pathlib import Path
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    async def check():
        env = dict(os.environ)
        env["LOCALAPPDATA"] = str(tmp_path / "mcp-sandbox")
        args = StdioServerParameters(
            command=sys.executable, args=["-m", "termylo.server"],
            cwd=str(Path(__file__).resolve().parents[1]), env=env,
        )
        async with stdio_client(args) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                names = {tool.name for tool in (await session.list_tools()).tools}
                assert "replace_universal_native_approval" in names
    asyncio.run(check())


def test_legacy_approval_revoke_disconnects_tunnel_instead_of_false_success(monkeypatch):
    active = [True]
    events = []
    monkeypatch.setattr(control, "rpc",
                        lambda op, **kw: (events.append(op) or {"status": "closed"}))
    monkeypatch.setattr(control, "tunnel_pids",
                        lambda: [101] if active[0] else [])
    def stop_legacy():
        active[0] = False
        events.append("tunnel-stop")
        return 1
    monkeypatch.setattr(control, "stop_tunnel", stop_legacy)
    result = control.revoke()
    assert result["status"] == "legacy_access_disconnected"
    assert events == ["status", "revoke", "tunnel-stop"]
    assert not active[0]


def test_revoke_no_approval_and_no_tunnel_is_noop(monkeypatch):
    monkeypatch.setattr(control, "rpc",
                        lambda op, **kw: {"status": "closed"})
    monkeypatch.setattr(control, "tunnel_pids", lambda: [])
    assert control.revoke()["status"] == "already_closed"

def test_supervisor_spawn_uses_pythonw_without_visible_console(monkeypatch, tmp_path):
    """The Windows broker must never create additional Terminal taskbar windows."""
    from termylo import supervisor as module
    from multiprocessing import AuthenticationError
    monkeypatch.setattr(module, "authkey", lambda folder: b"x" * 32)
    class RefusesConnection:
        def __init__(self, *args, **kwargs):
            raise OSError("No test broker")
    monkeypatch.setattr(module, "Client", RefusesConnection)
    calls = []
    class Fake:
        pass
    monkeypatch.setattr(module.subprocess, "Popen",
                        lambda *args, **kwargs: (calls.append((args,kwargs)) or Fake()))
    monkeypatch.setattr(module.time, "monotonic",
                        iter((1, 10)).__next__)
    monkeypatch.setattr(module.os, "name", "nt", raising=False)
    monkeypatch.setattr(module.sys, "executable", str(tmp_path / "python.exe"))
    (tmp_path / "pythonw.exe").touch()
    with pytest.raises(module.Unavailable):
        module.rpc("status", start=True, folder=tmp_path)
    assert len(calls) == 1
    argv = calls[0][0][0]
    kwargs = calls[0][1]
    assert argv[0].lower().endswith("pythonw.exe")
    assert kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW
    assert not kwargs["creationflags"] & subprocess.DETACHED_PROCESS
