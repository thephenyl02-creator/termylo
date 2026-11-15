"""Optional bounded polling watcher for local content-index freshness.

Only metadata is sampled, never document contents. No watcher is started
unless explicitly requested and approved by the owner.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from .context_inventory import scan_roots


class ContextWatcher:
    def __init__(self, roots: tuple[Path, ...], *, exclude: tuple[Path, ...],
                 interval_seconds: int, allowed: Callable[[], bool],
                 index_changed: Callable[[], dict],
                 max_files: int = 20000):
        self.roots = roots
        self.exclude = exclude
        self.interval = interval_seconds
        self.allowed = allowed
        self.index_changed = index_changed
        self.max_files = max_files
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.state = "not_started"
        self.last_error: str | None = None
        self.refresh_requests = 0
        self.last_signature: str | None = None

    def _snapshot(self) -> dict:
        return scan_roots(self.roots, max_files=self.max_files,
                          max_dirs=3000, max_seconds=8, exclude=self.exclude)

    def start(self) -> dict:
        if self._thread and self._thread.is_alive():
            return self.status()
        if not self.allowed():
            self.state = "approval_required"
            return self.status()
        try:
            initial = self._snapshot()
        except (OSError, ValueError) as exc:
            self.state = "error"
            self.last_error = str(exc)[:160]
            return self.status()
        if initial["truncated"]:
            self.state = "scope_too_large"
            self.last_error = "Folder inventory incomplete; choose smaller roots or index manually."
            return self.status()
        self.last_signature = initial["metadata_signature"]
        self._stop.clear()
        self.state = "watching"
        self.last_error = None
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="termylo-context-file-watcher")
        self._thread.start()
        return self.status()

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            if not self.allowed():
                self.state = "approval_expired"
                return
            try:
                snapshot = self._snapshot()
                if snapshot["truncated"]:
                    self.state = "scope_too_large"
                    self.last_error = "Folder scan exceeded safety limits."
                    return
                signature = snapshot["metadata_signature"]
                if signature != self.last_signature:
                    if not self.allowed():
                        self.state = "approval_expired"
                        return
                    result = self.index_changed()
                    # Do not lose a change while a prior index is still busy.
                    # Retry the same signature next poll once indexing is idle.
                    if result.get("already_running"):
                        continue
                    if result.get("status") in {"indexing", "ready"}:
                        self.last_signature = signature
                        self.refresh_requests += 1
                    else:
                        self.last_error = str(result.get("error", result.get("status")))[:160]
            except (OSError, ValueError) as exc:
                self.last_error = str(exc)[:160]
        self.state = "stopped"

    def stop(self) -> dict:
        self._stop.set()
        self.state = "stopped"
        return self.status()

    def status(self) -> dict:
        return {
            "state": self.state, "active": self.state == "watching" and
            bool(self._thread and self._thread.is_alive()),
            "interval_seconds": self.interval,
            "refresh_requests": self.refresh_requests,
            "last_error": self.last_error,
        }
