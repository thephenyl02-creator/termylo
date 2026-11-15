"""Opt-in, lease-bound background PowerShell process management.

Commands run in a separate PowerShell process, not the interactive native shell.
No automatic approval is granted here, and no process is automatically restarted.
"""
from __future__ import annotations
import sqlite3

import base64
import os
import secrets
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .runner import _environment, _system_powershell, _terminate_tree
from .windows_job import attach_kill_on_close

MAX_TAIL = 16384
MAX_RUNNING = 6
MAX_PER_PROJECT = 3
MAX_LIFETIME = 43200


@dataclass
class Managed:
    id: str
    project_id: str
    process: subprocess.Popen
    lease_id: str
    lifetime: int
    started: float = field(default_factory=time.monotonic)
    created: float = field(default_factory=time.time)
    state: str = "running"
    exit_code: int | None = None
    stdout: bytes = b""
    stderr: bytes = b""
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    stop_event: threading.Event = field(default_factory=threading.Event)
    job_handle: object | None = None


class ManagedProcesses:
    def __init__(self, approval, projects, journal=None):
        self.approval = approval
        self.projects = projects
        self.journal = journal
        self._lock = threading.RLock()
        self._items: dict[str, Managed] = {}

    def _record(self, item: Managed) -> None:
        if self.journal is not None:
            try:
                self.journal.record(item.id, item.project_id, item.state,
                                    kind="managed_process", exit_code=item.exit_code)
            except Exception:
                pass  # Logging must not affect authorization or execution.

    def _lease_valid(self, grant_id: str) -> bool:
        state = self.approval.status()
        return (state.get("status") == "active" and
                state.get("grant_id") == grant_id and
                state.get("remaining_seconds", 0) > 0)

    def _trim(self) -> None:
        finished = sorted(
            (item for item in self._items.values() if item.state != "running"),
            key=lambda item: item.created, reverse=True)
        for item in finished[30:]:
            self._items.pop(item.id, None)

    def start(self, command: str, project_id: str = "default",
              timeout_seconds: int = 600) -> dict:
        if os.name != "nt":
            return {"status": "unavailable", "error": "Windows required."}
        if not isinstance(command, str) or not command.strip() or len(command) > 2000 or "\x00" in command:
            return {"status": "rejected", "error": "Nonempty PowerShell command (maximum 2000 characters) required."}
        if (not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool)
                or not 1 <= timeout_seconds <= MAX_LIFETIME):
            return {"status": "rejected", "error": "timeout_seconds must be 1..43200."}
        key, shell = self.projects.get(project_id)
        shell_state = shell.status()
        lease = self.approval.status()
        if (shell_state.get("status") != "active" or lease.get("status") != "active"
                or not lease.get("grant_id") or lease.get("remaining_seconds", 0) <= 3):
            return {"status": "unavailable", "error": "An active, locally approved native project session is required."}
        effective = min(timeout_seconds, max(1, int(lease["remaining_seconds"]) - 2))
        cwd = shell_state.get("working_directory") or str(Path.home())
        powershell = _system_powershell()
        if not powershell:
            return {"status": "unavailable", "error": "PowerShell executable unavailable."}
        with self._lock:
            self._trim()
            active = [p for p in self._items.values() if p.state == "running"]
            if len(active) >= MAX_RUNNING or sum(p.project_id == key for p in active) >= MAX_PER_PROJECT:
                return {"status": "rejected", "error": "Managed-process capacity reached."}
            prepared = '[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)\n' + command
            encoded = base64.b64encode(prepared.encode("utf-16-le")).decode("ascii")
            try:
                process = subprocess.Popen(
                    [powershell, "-NoLogo", "-NoProfile", "-NonInteractive",
                     "-EncodedCommand", encoded],
                    cwd=cwd, env=_environment(),
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) |
                                   getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)))
            except (OSError, ValueError) as exc:
                return {"status": "error", "error": "Unable to start PowerShell: " + str(exc)[:120]}
            try:
                job_handle = attach_kill_on_close(process)
            except Exception as exc:
                _terminate_tree(process)
                return {"status": "error", "error": "Windows process containment unavailable: " + str(exc)[:130]}
            item = Managed(secrets.token_urlsafe(16), key, process, lease["grant_id"], effective)
            item.job_handle = job_handle
            self._items[item.id] = item
            self._record(item)
            if not self._lease_valid(item.lease_id):
                item.stop_event.set()
            for name in ("stdout", "stderr"):
                thread = threading.Thread(target=self._drain, args=(item, name),
                                          daemon=True, name="termylo-managed-output")
                thread.start()
            threading.Thread(target=self._watch, args=(item,), daemon=True,
                             name="termylo-managed-monitor").start()
            return self._view(item)

    def _drain(self, item: Managed, name: str) -> None:
        stream = getattr(item.process, name)
        if stream is None:
            return
        try:
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    break
                with self._lock:
                    current = getattr(item, name) + chunk
                    if len(current) > MAX_TAIL:
                        setattr(item, name + "_truncated", True)
                        current = current[-MAX_TAIL:]
                    setattr(item, name, current)
        except (OSError, ValueError):
            pass
        finally:
            try:
                stream.close()
            except OSError:
                pass

    @staticmethod
    def _stop_process(proc: subprocess.Popen) -> None:
        if proc.poll() is not None:
            return
        try:
            if os.name == "nt" and hasattr(signal, "CTRL_BREAK_EVENT"):
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                proc.terminate()
            proc.wait(timeout=2)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
        if proc.poll() is None:
            _terminate_tree(proc)

    def _watch(self, item: Managed) -> None:
        reason = None
        while item.process.poll() is None:
            if item.stop_event.is_set():
                reason = "cancelled"
                break
            if not self._lease_valid(item.lease_id):
                reason = "approval_expired"
                break
            if time.monotonic() - item.started >= item.lifetime:
                reason = "timeout"
                break
            time.sleep(.2)
        if reason:
            self._stop_process(item.process)
        try:
            code = item.process.wait(timeout=4)
        except subprocess.TimeoutExpired:
            self._stop_process(item.process)
            code = item.process.poll()
        if item.job_handle is not None:
            item.job_handle.close()  # Also kills any descendants still running.
        with self._lock:
            item.exit_code = code
            item.state = reason or ("completed" if code == 0 else "error")
            self._record(item)

    def _view(self, item: Managed, include_output: bool = False) -> dict:
        result = {
            "process_id": item.id, "project_id": item.project_id,
            "pid": item.process.pid, "status": item.state,
            "elapsed_seconds": round(time.monotonic() - item.started, 1),
            "timeout_seconds": item.lifetime, "exit_code": item.exit_code,
        }
        if include_output:
            result.update({
                "stdout_tail": item.stdout.decode("utf-8", "replace"),
                "stderr_tail": item.stderr.decode("utf-8", "replace"),
                "stdout_truncated": item.stdout_truncated,
                "stderr_truncated": item.stderr_truncated,
            })
        return result

    def status(self, process_id: str) -> dict:
        with self._lock:
            item = self._items.get(process_id)
            if item is None:
                try:
                    past = self.journal.get(process_id) if self.journal is not None else None
                except (OSError, ValueError, sqlite3.Error):
                    past = None
                return past if past is not None else {"status": "not_found"}
            return self._view(item, include_output=True)

    def list(self, project_id: str | None = None) -> dict:
        with self._lock:
            self._trim()
            key = str(project_id).strip().casefold() if project_id is not None else None
            items = [self._view(p) for p in self._items.values()
                     if key is None or p.project_id == key]
            return {"processes": sorted(items, key=lambda p: -p["elapsed_seconds"])}

    def stop(self, process_id: str) -> dict:
        with self._lock:
            item = self._items.get(process_id)
            if item is None:
                return {"status": "not_found", "error": "Unknown process ID."}
            if item.state != "running":
                return self._view(item)
            item.stop_event.set()
            return {"status": "stopping", "process_id": process_id, "project_id": item.project_id}

    def stop_all(self) -> None:
        with self._lock:
            items = [p for p in self._items.values() if p.state == "running"]
        for item in items:
            item.stop_event.set()
        for item in items:
            self._stop_process(item.process)
