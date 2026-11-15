"""Optional bounded metadata watcher tests; no upstream model is run."""
from __future__ import annotations

import time

from termylo.context_inventory import scan_roots
from termylo.context_watcher import ContextWatcher


def wait_for(predicate, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(.02)
    return False


def test_metadata_signature_tracks_changes_without_reading_content(tmp_path):
    base = tmp_path / "docs"
    base.mkdir()
    file = base / "final3.pdf"
    file.write_bytes(b"AAAA")
    first = scan_roots((base,))
    assert first["files_examined"] == 1
    file.write_bytes(b"CHANGED-WITH-DIFFERENT-SIZE")
    second = scan_roots((base,))
    assert first["metadata_signature"] != second["metadata_signature"]
    file.unlink()
    assert scan_roots((base,))["files_examined"] == 0


def test_metadata_signature_excludes_private_config(tmp_path):
    base = tmp_path / "root"
    base.mkdir()
    (base / "fine.pdf").write_bytes(b"ok")
    ignored = base / "private-index"
    ignored.mkdir()
    (ignored / "secret.sqlite3").write_bytes(b"private")
    result = scan_roots((base,), exclude=(ignored,))
    assert result["files_examined"] == 1
    assert result["candidate_counts_by_type"] == {"document": 1}


def test_watcher_only_indexes_after_real_metadata_change(tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    calls = []
    watcher = ContextWatcher(
        (folder,), exclude=(), interval_seconds=.08,
        allowed=lambda: True,
        index_changed=lambda: (calls.append("refresh") or {"status": "indexing"}),
    )
    assert watcher.state == "not_started"
    assert not calls
    assert watcher.start()["state"] == "watching"
    time.sleep(.2)
    assert not calls, "No startup indexing allowed"
    (folder / "new-document.pdf").write_text("new")
    assert wait_for(lambda: len(calls) >= 1)
    assert watcher.status()["refresh_requests"] >= 1
    watcher.stop()
    count = len(calls)
    (folder / "later-file.pdf").write_text("no further automatic work")
    time.sleep(.2)
    assert len(calls) == count


def test_watcher_stops_on_approval_expiry(tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    allowed = [True]
    calls = []
    watcher = ContextWatcher(
        (folder,), exclude=(), interval_seconds=.06,
        allowed=lambda: allowed[0],
        index_changed=lambda: (calls.append(1) or {"status": "indexing"}),
    )
    assert watcher.start()["state"] == "watching"
    allowed[0] = False
    assert wait_for(lambda: watcher.state == "approval_expired")
    (folder / "resume.pdf").write_text("new")
    assert not calls


def test_oversized_scope_disables_watcher_fail_closed(tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    for i in range(4):
        (folder / f"{i}.txt").write_text("sample")
    watcher = ContextWatcher(
        (folder,), exclude=(), interval_seconds=.05,
        allowed=lambda: True, index_changed=lambda: {"status": "indexing"},
        max_files=2,
    )
    report = watcher.start()
    assert report["state"] == "scope_too_large"
    assert report["active"] is False
    assert report["refresh_requests"] == 0

def test_watcher_retries_change_after_previous_index_finishes(tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    attempts = []
    def index():
        attempts.append(1)
        return ({"status": "indexing", "already_running": True}
                if len(attempts) == 1 else
                {"status": "indexing", "already_running": False})
    watcher = ContextWatcher(
        (folder,), exclude=(), interval_seconds=.06,
        allowed=lambda: True, index_changed=index)
    assert watcher.start()["state"] == "watching"
    (folder / "final.xlsx").write_text("new data")
    assert wait_for(lambda: len(attempts) >= 2, timeout=5)
    assert watcher.status()["refresh_requests"] == 1
    watcher.stop()
