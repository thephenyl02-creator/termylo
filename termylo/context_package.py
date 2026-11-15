"""Termylo Context Engine internal runtime installer and verifier.

This is the Termylo package interface. TCE derives from MIT-licensed
source code and preserves license and notices. We install the TCE native CLI,
never execute or install any upstream executable or desktop application.
Model files are Apache-2.0 licensed upstream artifacts, obtained only on opt-in.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .context_assets import MODEL_ASSETS, MODEL_REPOSITORY, MODEL_REVISION, sha256_file

from .tce_runtime import VERSION, BINARY_SHA256, install_runtime, runtime_valid

def home() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Termylo" / "ContextEngine"

def install_native(directory: Path | None = None) -> dict:
    """Install source-built TCE inside Termylo, never the upstream application."""
    return install_runtime(Path(directory) if directory else home())

def model_state(directory: Path | None = None, *, verify: bool = False) -> dict:
    target = Path(directory) if directory else home()
    folder = target / "models"
    models = []
    complete = True
    for name, size, digest in MODEL_ASSETS:
        file = folder / name
        exists = file.is_file() and not file.is_symlink()
        present = exists and file.stat().st_size == size
        good = present and (not verify or sha256_file(file) == digest)
        complete &= good
        models.append({"file": name, "size": size, "verified": good if verify else False,
                       "present_expected_size": present,
                       "downloaded_bytes": file.stat().st_size if exists else 0})
    return {"installed": complete, "fully_verified": complete and verify,
            "models": models, "models_dir": str(folder),
            "expected_total_bytes": sum(size for _, size, _ in MODEL_ASSETS)}


def install_models(directory: Path | None = None, *, max_seconds: int = 100) -> dict:
    """Opt-in/resumable downloads. The caller can retry, no background worker."""
    target = Path(directory) if directory else home()
    target.joinpath("models").mkdir(parents=True, exist_ok=True)
    curl = shutil.which("curl.exe") or shutil.which("curl")
    if not curl:
        return {"status": "error", "reason": "curl.exe not found"}
    for name, expected_size, expected_sha in MODEL_ASSETS:
        dest = target / "models" / name
        if dest.is_file() and dest.stat().st_size == expected_size:
            if sha256_file(dest) == expected_sha:
                continue
            dest.unlink()
        partial = dest.with_suffix(dest.suffix + ".part")
        url = (f"https://huggingface.co/{MODEL_REPOSITORY}/resolve/"
               f"{MODEL_REVISION}/{name}")
        args = [curl, "-L", "--fail", "--silent", "--show-error",
                "--retry", "1", "--connect-timeout", "15", "--max-time",
                str(max_seconds), "-C", "-", "-o", str(partial), url]
        try:
            result = subprocess.run(args, timeout=max_seconds + 5,
                                    capture_output=True, text=True)
        except subprocess.TimeoutExpired:
            result = None
        if partial.is_file() and partial.stat().st_size == expected_size:
            if sha256_file(partial) != expected_sha:
                raise RuntimeError(f"Model SHA-256 mismatch: {name}")
            partial.replace(dest)
            continue
        return {"status": "partial", "package": "Terminal Context Engine",
                "file": name, "partial_bytes": partial.stat().st_size
                if partial.exists() else 0,
                "error": (result.stderr[:350] if result else "download timed out"),
                "next": "Rerun termylo-context install --with-model to resume."}
    return {"status": "installed", "package": "Terminal Context Engine",
            "model_status": model_state(target, verify=True)}


def status(directory: Path | None = None, *, verify: bool = False) -> dict:
    target = Path(directory) if directory else home()
    bin_file = target / "bin" / "tce.exe"
    manifest = target / "manifest.json"
    valid = False
    release = {}
    if manifest.exists():
        try:
            release = json.loads(manifest.read_text(encoding="utf-8"))
            valid = runtime_valid(target, verify=verify)
        except (OSError, ValueError):
            pass
    return {"package": "Terminal Context Engine", "status": "installed" if valid else "not_installed",
            "location": str(target), "executable": str(bin_file),
            "binary_verified": valid and verify,
            "search_component": release.get("engine_version"),
            "enabled_by_default": False,
            "model": model_state(target, verify=verify)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="termylo-context", description="Terminal Context Engine optional Windows package")
    parser.add_argument("action", choices=["install", "status", "models"],
                        nargs="?", default="status")
    parser.add_argument("--with-model", action="store_true",
                        help="Opt in to download 865 MB of model assets.")
    parser.add_argument("--verify", action="store_true",
                        help="Recalculate model and binary SHA-256.")
    parser.add_argument("--max-seconds", type=int, default=100,
                        help="Single download request time limit; retry resumes.")
    args = parser.parse_args(argv)
    try:
        if args.action == "install":
            answer = install_native()
            if args.with_model and answer.get("status") == "installed":
                answer = install_models(max_seconds=max(20, min(args.max_seconds, 240)))
        elif args.action == "models":
            answer = install_models(max_seconds=max(20, min(args.max_seconds, 240)))
        else:
            answer = status(verify=args.verify)
        print(json.dumps(answer, ensure_ascii=False, indent=2))
        return 0 if answer.get("status") in {"installed", "ready"} else 1
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)[:600]}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
