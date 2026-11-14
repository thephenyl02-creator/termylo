"""Project-keyed native terminals. Conversations in one project reuse one shell."""
from __future__ import annotations

import threading
from .native import NativeSession


class ProjectSessions:
    def __init__(self, default_session: NativeSession | None = None, approval=None):
        self._approval = approval
        self._lock = threading.RLock()
        self._sessions: dict[str, NativeSession] = {
            "default": default_session if default_session is not None else NativeSession(approval=approval)
        }
        self._directories: dict[str, str] = {}

    @staticmethod
    def normalize(project_id: str | None) -> str:
        """Stable routing key; names are case-insensitive, not conversation-specific."""
        return (str(project_id or "default").strip().casefold() or "default")

    def get(self, project_id: str | None = None) -> tuple[str, NativeSession]:
        key = self.normalize(project_id)
        with self._lock:
            if key not in self._sessions:
                self._sessions[key] = NativeSession(approval=self._approval)
            return key, self._sessions[key]

    def prepare(self, project_id: str | None = None, duration_hours: float = 4,
                working_directory: str | None = None
                ) -> tuple[str, NativeSession, dict | None]:
        key, native = self.get(project_id)
        # Reusing a currently approved project never changes the lease or shell state.
        if native.status()["status"] in ("active", "opening", "recovering"):
            return key, native, None
        with self._lock:
            directory = working_directory if working_directory is not None else self._directories.get(key)
        issue = native.configure(duration_hours, directory, project_id=key)
        if issue is None:
            with self._lock:
                configured_directory = native.status().get("working_directory")
                if configured_directory is not None:
                    self._directories[key] = configured_directory
        return key, native, issue

    def by_session_id(self, session_id: str) -> tuple[str, NativeSession] | None:
        with self._lock:
            sessions = list(self._sessions.items())
        for key, native in sessions:
            if native.status().get("session_id") == session_id:
                return key, native
        return None

    def close_all(self) -> dict:
        """Revoke universal approval and close each project terminal."""
        with self._lock:
            sessions = list(self._sessions.values())
        # Capture session IDs before global revocation disposes their IPC handles.
        targets = [(native, native.status().get("session_id")) for native in sessions]
        if self._approval is not None:
            self._approval.revoke()
        for native, sid in targets:
            if sid:
                native.close(sid)
        return {"status": "closed", "closed_projects": len(sessions)}

    def list_status(self) -> list[dict]:
        with self._lock:
            sessions = list(self._sessions.items())
        return [dict(project_id=key, **{k: v for k, v in native.status().items()
                                        if k != "project_id"})
                for key, native in sessions]
