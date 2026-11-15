"""Small, local metadata-only job journal. No commands or outputs are stored."""
from __future__ import annotations

import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path

FINISHED = frozenset({"completed", "denied", "cancelled", "timeout", "rejected",
                      "unavailable", "error", "outcome_unknown", "approval_expired"})


class JobJournal:
    def __init__(self, path: str | Path | None = None):
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        self.path = Path(path) if path is not None else base / "Termylo" / "jobs.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = secrets.token_hex(12)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        with self._conn:
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created REAL NOT NULL,
                    started REAL,
                    finished REAL,
                    updated REAL NOT NULL,
                    exit_code INTEGER
                )
            """)
            self._conn.execute("CREATE INDEX IF NOT EXISTS jobs_updated ON jobs(updated DESC)")

    def record(self, job_id: str, project_id: str, status: str, *,
               kind: str = "command", exit_code: int | None = None) -> None:
        now = time.time()
        started = now if status == "running" else None
        finished = now if status in FINISHED else None
        with self._lock, self._conn:
            self._conn.execute("""
                INSERT INTO jobs (id,kind,project_id,owner,status,created,started,finished,updated,exit_code)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status,
                    started=COALESCE(jobs.started, excluded.started),
                    finished=excluded.finished,
                    updated=excluded.updated,
                    exit_code=excluded.exit_code
            """, (job_id, kind, project_id, self.run_id, status,
                  now, started, finished, now, exit_code))
            self._conn.execute("""
                DELETE FROM jobs WHERE updated < ?
            """, (now - 30 * 86400,))
            self._conn.execute("""
                DELETE FROM jobs WHERE id IN (
                    SELECT id FROM jobs ORDER BY updated DESC LIMIT -1 OFFSET 1000
                )
            """)

    def _render(self, row: tuple) -> dict:
        jid, kind, project, owner, status, created, started, finished, updated, exit_code = row
        stale = owner != self.run_id and status not in FINISHED
        return {
            "job_id": jid, "kind": kind, "project_id": project,
            "status": "outcome_unknown" if stale else status,
            "last_known_status": status if stale else None,
            "exit_code": exit_code, "created_at": created,
            "started_at": started, "finished_at": finished, "updated_at": updated,
            "output_available": False,
            "message": ("Previous bridge instance ended without a confirmed outcome. "
                        "Inspect the real files/processes before retrying; no automatic replay."
                        if stale else "Metadata only; output was not persisted."),
        }

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            return self._render(row) if row else None

    def recent(self, project_id: str | None = None, limit: int = 20) -> list[dict]:
        count = max(1, min(int(limit), 100))
        with self._lock:
            if project_id is None:
                rows = self._conn.execute(
                    "SELECT * FROM jobs ORDER BY updated DESC LIMIT ?", (count,)).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM jobs WHERE project_id=? ORDER BY updated DESC LIMIT ?",
                    (project_id, count)).fetchall()
            return [self._render(row) for row in rows]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
