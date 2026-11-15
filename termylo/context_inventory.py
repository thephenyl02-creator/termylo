"""Bounded, read-only inventory for Terminal Context Engine setup.

No file content, model, search service, or installer is accessed here.
Symlinks and Windows junctions are skipped rather than followed.
"""
from __future__ import annotations

import hashlib
import os
import time
from collections import Counter
from pathlib import Path

GROUPS = {
    "document": frozenset({".pdf", ".doc", ".docx", ".odt", ".rtf"}),
    "presentation": frozenset({".ppt", ".pptx", ".odp"}),
    "spreadsheet": frozenset({".xls", ".xlsx", ".xlsm", ".ods"}),
    "image": frozenset({".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp",
                        ".heic", ".heif", ".tif", ".tiff", ".svg"}),
    "audio": frozenset({".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac"}),
    "video": frozenset({".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}),
    "text_code": frozenset({".txt", ".md", ".csv", ".json", ".yaml", ".yml",
                            ".py", ".js", ".ts", ".html", ".xml", ".log"}),
}


def _kind(name: str) -> str:
    suffix = Path(name).suffix.casefold()
    for group, extensions in GROUPS.items():
        if suffix in extensions:
            return group
    return "other"


def _redirected(path: Path) -> bool:
    try:
        return path.is_symlink() or bool(
            hasattr(path, "is_junction") and path.is_junction()
        )
    except (OSError, ValueError):
        return True


def scan_roots(roots: tuple[Path, ...], *, max_files: int = 10000,
               max_dirs: int = 2000, max_seconds: float = 8.0,
               exclude: tuple[Path, ...] = ()) -> dict:
    if not 1 <= max_files <= 100000:
        raise ValueError("max_files must be between 1 and 100000")
    begin = time.monotonic()
    end = begin + max_seconds
    counts = Counter()
    examined = 0
    directories = 0
    skipped = 0
    total_bytes = 0
    signature = 0
    truncated = False
    stack = [root for root in roots if root.is_dir() and not _redirected(root)]
    excludes = tuple(p.resolve() for p in exclude)
    while stack:
        if examined >= max_files or directories >= max_dirs or time.monotonic() >= end:
            truncated = True
            break
        folder = stack.pop()
        if any(folder == ex or ex in folder.parents for ex in excludes):
            continue
        directories += 1
        try:
            with os.scandir(folder) as iterator:
                for entry in iterator:
                    if examined >= max_files or time.monotonic() >= end:
                        truncated = True
                        break
                    path = Path(entry.path)
                    if _redirected(path):
                        skipped += 1
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(path)
                        elif entry.is_file(follow_symlinks=False):
                            st = entry.stat(follow_symlinks=False)
                            counts[_kind(entry.name)] += 1
                            examined += 1
                            total_bytes += st.st_size
                            part = hashlib.blake2s(
                                (str(path) + "|" + str(st.st_size) + "|" +
                                 str(st.st_mtime_ns)).encode("utf-8"),
                                digest_size=16).digest()
                            signature ^= int.from_bytes(part, "big")
                    except (OSError, ValueError):
                        skipped += 1
        except (OSError, ValueError):
            skipped += 1
    return {
        "status": "ok", "files_examined": examined,
        "directories_examined": directories,
        "candidate_counts_by_type": dict(sorted(counts.items())),
        "total_candidate_file_bytes": total_bytes,
        "skipped_unreadable_or_redirected": skipped,
        "truncated": truncated or bool(stack),
        "metadata_signature": f"{signature:032x}",
        "max_files": max_files,
        "note": ("Read-only metadata estimate, not a claim of successful indexing. "
                 "Large folders and unsupported formats need real-engine testing."),
    }
