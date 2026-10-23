"""Single-command asynchronous executor: MCP requests don't block on desktop approval."""
from __future__ import annotations
import os
import secrets
import threading
import time
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
    result: dict | None = None
    cancel: threading.Event = field(default_factory=threading.Event)

class JobManager:
    def __init__(self, runner: Callable[..., dict] = run_command):
        self._runner = runner
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

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
            return {"name": "Termylo", "online": True, "windows": os.name == "nt", "active_job": active.id if active else None, "approval": "physical Windows approval for each command"}

    def submit(self, command: str, timeout_seconds: int = 45) -> dict:
        issue = validate(command, timeout_seconds)
        if issue:
            return {"status": "rejected", "error": issue}
        if os.name != "nt":
            return {"status": "unavailable", "error": "Windows PowerShell is required."}
        with self._lock:
            self._prune()
            if any(j.status not in TERMINAL for j in self._jobs.values()):
                return {"status": "busy", "error": "Finish or cancel the previous command first."}
            job = Job(id=secrets.token_urlsafe(18))
            self._jobs[job.id] = job
        threading.Thread(target=self._run, args=(job, command, timeout_seconds), daemon=True, name="termylo-job").start()
        return {"status": "awaiting_approval", "job_id": job.id, "message": "Approve or deny the command in the Windows popup, then call powershell_result(job_id)."}

    def _run(self, job: Job, command: str, timeout_seconds: int) -> None:
        try:
            result = self._runner(command, timeout_seconds, cancel_event=job.cancel)
        except Exception:
            result = {"status": "error", "error": "The local execution agent encountered an error."}
        with self._lock:
            job.result = result
            job.status = result.get("status", "error")

    def result(self, job_id: str) -> dict:
        with self._lock:
            self._prune()
            job = self._jobs.get(job_id)
            if job is None:
                return {"status": "not_found", "error": "Unknown or expired job ID."}
            if job.result is None:
                return {"status": "awaiting_approval_or_running", "job_id": job.id, "message": "Check the laptop for an approval popup or wait for execution."}
            return {"job_id": job.id, **job.result}

    def cancel(self, job_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return {"status": "not_found", "error": "Unknown or expired job ID."}
            if job.status in TERMINAL:
                return {"status": job.status, "job_id": job.id, "message": "Already finished."}
            job.cancel.set()
            return {"status": "cancellation_requested", "job_id": job.id}
