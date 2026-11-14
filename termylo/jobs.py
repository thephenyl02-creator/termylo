"""Project-scoped FIFO command queues with asynchronous Windows approval/execution."""
from __future__ import annotations
import os
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable
from .runner import run_command, validate

TERMINAL = frozenset({"completed", "denied", "cancelled", "timeout", "rejected", "unavailable", "error"})
RETAIN_SECONDS = 900
MAX_FINISHED = 30

@dataclass
class Job:
    id: str
    created: float = field(default_factory=time.monotonic)
    status: str = "awaiting_approval"
    project_id: str = "default"
    result: dict | None = None
    cancel: threading.Event = field(default_factory=threading.Event)

class JobManager:
    def __init__(self, runner: Callable[..., dict] = run_command):
        self._runner = runner
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._queues: dict[str, deque] = {}
        self._workers: set[str] = set()
        self._running: dict[str, str] = {}

    def _prune(self) -> None:
        now = time.monotonic()
        for jid, job in list(self._jobs.items()):
            if job.status in TERMINAL and now - job.created > RETAIN_SECONDS:
                del self._jobs[jid]
        finished = sorted((j for j in self._jobs.values() if j.status in TERMINAL), key=lambda j: j.created)
        for j in finished[:-MAX_FINISHED]:
            self._jobs.pop(j.id, None)

    def status(self) -> dict:
        with self._lock:
            self._prune()
            active = next((j for j in self._jobs.values() if j.status not in TERMINAL), None)
            return {"name": "Termylo", "online": True, "windows": os.name == "nt",
                    "active_job": active.id if active else None,
                    "approval": "physical Windows approval for each command",
                    "project_queues": {key: len(queue) + int(key in self._running)
                                       for key, queue in self._queues.items()
                                       if queue or key in self._running}}

    def submit(self, command: str, timeout_seconds: int = 90, *,
               runner: Callable[..., dict] | None = None,
               project_id: str = "default") -> dict:
        issue = validate(command, timeout_seconds)
        if issue:
            return {"status": "rejected", "error": issue}
        if os.name != "nt":
            return {"status": "unavailable", "error": "Windows PowerShell is required."}
        with self._lock:
            self._prune()
            job = Job(id=secrets.token_urlsafe(18), project_id=project_id)
            self._jobs[job.id] = job
            queue = self._queues.setdefault(project_id, deque())
            ahead = len(queue) + int(project_id in self._running)
            queue.append((job, command, timeout_seconds, runner))
            queued = project_id in self._workers
            if queued:
                job.status = "queued"
            else:
                self._workers.add(project_id)
                try:
                    threading.Thread(target=self._drain, args=(project_id,),
                                     daemon=True, name="termylo-project-queue").start()
                except (RuntimeError, OSError):
                    queue.pop()
                    self._jobs.pop(job.id, None)
                    self._workers.remove(project_id)
                    if not queue:
                        self._queues.pop(project_id, None)
                    return {"status": "error", "error": "Could not start the local command worker."}
        if queued:
            return {"status": "queued", "job_id": job.id, "queue_position": ahead + 1,
                    "message": "Command queued for this project; use powershell_result(job_id)."}
        if runner is not None:
            return {"status": "running", "job_id": job.id,
                    "message": "Command submitted to the locally approved session; use powershell_result(job_id)."}
        return {"status": "awaiting_approval", "job_id": job.id,
                "message": "Approve or deny the command in the Windows popup, then call powershell_result(job_id)."}

    def _drain(self, project_id: str) -> None:
        while True:
            with self._lock:
                queue = self._queues.get(project_id)
                if not queue:
                    self._queues.pop(project_id, None)
                    self._workers.discard(project_id)
                    self._running.pop(project_id, None)
                    return
                job, command, timeout_seconds, runner = queue.popleft()
                if job.result is not None:
                    continue
                self._running[project_id] = job.id
                job.status = "running"
            try:
                self._run(job, command, timeout_seconds, runner)
            finally:
                with self._lock:
                    if self._running.get(project_id) == job.id:
                        self._running.pop(project_id, None)

    def _run(self, job: Job, command: str, timeout_seconds: int, runner: Callable[..., dict] | None = None) -> None:
        try:
            result = (runner or self._runner)(command, timeout_seconds, cancel_event=job.cancel)
        except Exception:
            result = {"status": "error", "error": "The local execution agent encountered an error."}
        if not isinstance(result, dict) or result.get("status") not in TERMINAL:
            result = {"status": "error", "error": "The local command worker returned an invalid result."}
        with self._lock:
            job.result = result
            job.status = result["status"]

    def result(self, job_id: str) -> dict:
        with self._lock:
            self._prune()
            job = self._jobs.get(job_id)
            if job is None:
                return {"status": "not_found", "error": "Unknown or expired job ID."}
            if job.result is None:
                if job.status == "queued":
                    queue = self._queues.get(job.project_id, ())
                    position = next((i for i, entry in enumerate(queue)
                                     if entry[0].id == job.id), None)
                    if position is not None:
                        return {"status": "queued", "job_id": job.id,
                                "queue_position": position + 1 + int(job.project_id in self._running)}
                return {"status": "awaiting_approval_or_running", "job_id": job.id,
                        "message": "Check the laptop for an approval popup or wait for execution."}
            return {"job_id": job.id, **job.result}

    def cancel(self, job_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return {"status": "not_found", "error": "Unknown or expired job ID."}
            if job.status in TERMINAL:
                return {"status": job.status, "job_id": job.id, "message": "Already finished."}
            job.cancel.set()
            if job.status == "queued":
                job.result = {"status": "cancelled"}
                job.status = "cancelled"
            return {"status": "cancellation_requested", "job_id": job.id}
