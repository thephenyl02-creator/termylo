"""Offline-only installation readiness checks for the optional Terminal Context Engine.

Expected model digests are from upstream DigUp ModelFiles.swift, pinned
revision bfcd298762cc34d0357ece5ebdd31791a3a374d8.
Nothing here downloads, installs, executes or starts a search process.
"""
from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

MODEL_REPOSITORY = "ggml-org/embeddinggemma-2-GGUF"
MODEL_REVISION = "bfcd298762cc34d0357ece5ebdd31791a3a374d8"
MODEL_ASSETS = (
    ("embeddinggemma-2-Q8_0.gguf", 309855456,
     "2188ac1deca4b77dffefd603c2776a9d76d9d74ec01841392982ebb840b09135"),
    ("mmproj-embeddinggemma-2-Q8_0.gguf", 554821024,
     "c4a8a52691ecef40618438928bdf9e68379b854e24166f292592353db0aab64f"),
)
TOTAL_MODEL_BYTES = sum(item[1] for item in MODEL_ASSETS)


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def _disk_free_near(folder: Path) -> int | None:
    try:
        current = folder
        while not current.exists() and current != current.parent:
            current = current.parent
        return shutil.disk_usage(current).free
    except (OSError, ValueError):
        return None


def inspect_assets(
    executable: str,
    models_dir: str,
    binary_sha256: str = "",
    *,
    verify_hashes: bool = True,
) -> dict:
    """Return setup state, missing bytes, and deterministic problems.

    This is intentionally a read-only preflight. A valid binary digest is
    required to activate a new installation: without a trusted release
    manifest a similarly named malicious executable must not be launched.
    """
    problems: list[str] = []
    executable_report: dict = {"configured": bool(executable), "exists": False,
                               "sha256_verified": False}
    path = Path(executable) if executable else None
    pinned = binary_sha256.lower().strip() if isinstance(binary_sha256, str) else ""
    if not path or not path.is_absolute():
        problems.append("executable_not_configured")
    elif not path.is_file() or path.is_symlink():
        problems.append("executable_missing_or_redirected")
    else:
        executable_report["exists"] = True
        if len(pinned) != 64 or any(c not in "0123456789abcdef" for c in pinned):
            problems.append("executable_digest_not_pinned")
        elif verify_hashes:
            try:
                executable_report["sha256_verified"] = sha256_file(path) == pinned
                if not executable_report["sha256_verified"]:
                    problems.append("executable_digest_mismatch")
            except OSError:
                problems.append("executable_unreadable")

    model_report = []
    remaining = 0
    model_folder = Path(models_dir) if models_dir else None
    if not model_folder or not model_folder.is_absolute():
        problems.append("model_folder_not_configured")
        remaining = TOTAL_MODEL_BYTES
        for name, expected_size, _ in MODEL_ASSETS:
            model_report.append({"name": name, "bytes": expected_size,
                                 "state": "not_configured"})
    else:
        for name, size, digest in MODEL_ASSETS:
            model = model_folder / name
            state = "missing"
            try:
                if model.is_symlink():
                    state = "redirected"
                elif model.is_file():
                    if model.stat().st_size != size:
                        state = "wrong_size"
                    elif verify_hashes:
                        state = "verified" if sha256_file(model) == digest else "wrong_digest"
                    else:
                        state = "present_unverified"
            except OSError:
                state = "unreadable"
            if state != "verified":
                if verify_hashes:
                    problems.append("model_" + name.replace(".", "_") + "_" + state)
                remaining += size
            model_report.append({"name": name, "bytes": size, "state": state})
    free = _disk_free_near(model_folder) if model_folder else None
    if free is not None and remaining > free:
        problems.append("insufficient_disk_for_models")

    if not verify_hashes:
        # A lightweight report is never grounds for enabling the engine.
        return {
            "status": "unverified", "ready": False, "model_repository": MODEL_REPOSITORY,
            "model_revision": MODEL_REVISION, "total_model_bytes": TOTAL_MODEL_BYTES,
            "additional_model_bytes": remaining, "disk_free_bytes": free,
            "executable": executable_report, "models": model_report,
            "problems": problems, "downloads_started": False,
        }
    return {
        "status": "ready" if not problems else "not_ready",
        "ready": not problems, "model_repository": MODEL_REPOSITORY,
        "model_revision": MODEL_REVISION, "total_model_bytes": TOTAL_MODEL_BYTES,
        "additional_model_bytes": remaining, "disk_free_bytes": free,
        "executable": executable_report, "models": model_report,
        "problems": problems, "downloads_started": False,
    }
