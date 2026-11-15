"""Internal Termylo Context Engine (TCE) Windows runtime.

The runtime is built from the source in tce-native/. It is never an
installation of a separate upstream desktop application.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from .context_assets import sha256_file

VERSION = "0.1.0"
ASSET = "termylo-tce-windows-x64-0.1.0.zip"
RELEASE_TAG = "tce-native-v0.1.0"
URL = f"https://github.com/thephenyl02-creator/termylo/releases/download/{RELEASE_TAG}/{ASSET}"
ARCHIVE_SHA256 = "e85a9edfd34d4a13106acb2b60323eea54e8e59195d546d28aae44fa67561f7c"
BINARY_SHA256 = "c2dd6b5d1ef74eb27cfb8044a46f55ccb05869756bde682b258f056707babad2"
REQUIRED = {"tce.exe", "llama.dll", "ggml.dll", "ggml-base.dll",
            "pdfium.dll", "ffmpeg.exe", "ffprobe.exe",
            "SEARCH-ENGINE-MIT-LICENSE.txt", "THIRD-PARTY-NOTICES.txt"}
MAX_UNPACKED = 450 * 1024 * 1024


def runtime_valid(target: Path, *, verify: bool) -> bool:
    exe = target / "bin" / "tce.exe"
    manifest = target / "manifest.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        basic = (data.get("engine") == "TCE" and
                 data.get("internal_helper_sha256") == BINARY_SHA256 and
                 exe.is_file() and not exe.is_symlink() and
                 not (target / "bin" / "digup.exe").exists())
        if not basic or not verify:
            return bool(basic)
        digests = data.get("runtime_files", {})
        return (isinstance(digests, dict) and REQUIRED <= set(digests) and
                digests.get("tce.exe") == BINARY_SHA256 and
                all(isinstance(name, str) and name not in {"", ".", ".."} and
                    "/" not in name and "\\" not in name and
                    isinstance(digest, str) and len(digest) == 64 and
                    (target / "bin" / name).is_file() and
                    not (target / "bin" / name).is_symlink() and
                    sha256_file(target / "bin" / name) == digest
                    for name, digest in digests.items()))
    except (OSError, ValueError, TypeError):
        return False


def _fetch_bundle(target: Path) -> Path:
    cache = target / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    bundle = cache / ASSET
    if bundle.is_file() and sha256_file(bundle) == ARCHIVE_SHA256:
        return bundle
    partial = cache / (ASSET + ".download")
    partial.unlink(missing_ok=True)
    try:
        request = urllib.request.Request(
            URL, headers={"User-Agent": "Termylo-TCE-Installer/0.1"})
        with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as output:
            count = 0
            while chunk := response.read(1024 * 1024):
                count += len(chunk)
                if count > 160 * 1024 * 1024:
                    raise RuntimeError("TCE archive exceeds size limit.")
                output.write(chunk)
        if sha256_file(partial) != ARCHIVE_SHA256:
            raise RuntimeError("TCE archive SHA-256 verification failed.")
        partial.replace(bundle)
        return bundle
    finally:
        partial.unlink(missing_ok=True)


def _unpack_verified(bundle: Path, stage: Path) -> dict:
    with zipfile.ZipFile(bundle) as archive:
        metadata = json.loads(archive.read("runtime.json"))
        if metadata.get("engine") != "TCE" or metadata.get("version") != VERSION:
            raise RuntimeError("Not a compatible Termylo Context Engine release.")
        digests = metadata.get("runtime_files")
        if not isinstance(digests, dict) or not REQUIRED <= set(digests):
            raise RuntimeError("Incomplete TCE runtime manifest.")
        entries = [item for item in archive.infolist() if item.filename != "runtime.json"]
        seen = set()
        total = 0
        for item in entries:
            path = item.filename
            if (not path.startswith("bin/") or item.is_dir() or
                "/" in path[4:] or "\\" in path or path[4:] in {"", ".", ".."}):
                raise RuntimeError("Unsafe TCE archive entry.")
            name = path[4:]
            if name.lower() in seen or name not in digests:
                raise RuntimeError("Duplicate or unlisted TCE runtime file.")
            seen.add(name.lower())
            total += item.file_size
            if total > MAX_UNPACKED or stat.S_ISLNK(item.external_attr >> 16):
                raise RuntimeError("Unsafe TCE runtime size or symlink.")
        if set(digests) != {item.filename[4:] for item in entries}:
            raise RuntimeError("TCE archive manifest mismatch.")
        for item in entries:
            name = item.filename[4:]
            expected = digests[name]
            if not isinstance(expected, str) or len(expected) != 64:
                raise RuntimeError("Invalid TCE file digest.")
            destination = stage / "bin" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(item) as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            if sha256_file(destination) != expected:
                raise RuntimeError(f"TCE file integrity failure: {name}")
    if sha256_file(stage / "bin" / "tce.exe") != BINARY_SHA256:
        raise RuntimeError("TCE executable differs from source-built release.")
    if (stage / "bin" / "digup.exe").exists():
        raise RuntimeError("Legacy binary must not be distributed.")
    return metadata


def install_runtime(target: Path, *, bundle_path: Path | None = None) -> dict:
    if os.name != "nt":
        return {"status": "unsupported", "error": "Windows x64 only."}
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    if runtime_valid(target, verify=True):
        return {"status": "installed", "package": "Terminal Context Engine",
                "executable": str(target / "bin" / "tce.exe"),
                "models_dir": str(target / "models"), "sha256": BINARY_SHA256}
    bundle = Path(bundle_path) if bundle_path else _fetch_bundle(target)
    if not bundle.is_file() or sha256_file(bundle) != ARCHIVE_SHA256:
        raise RuntimeError("Untrusted TCE archive; installation denied.")
    with tempfile.TemporaryDirectory(prefix=".tce-stage-", dir=target) as stage_dir:
        stage = Path(stage_dir)
        release_metadata = _unpack_verified(bundle, stage)
        live = target / "bin"
        backup = target / ("bin-before-tce-" + os.urandom(4).hex())
        if live.exists():
            live.rename(backup)
        try:
            (stage / "bin").rename(live)
        except Exception:
            if backup.exists() and not live.exists():
                backup.rename(live)
            raise
        manifest = {
            "package": "Terminal Context Engine", "engine": "TCE",
            "engine_version": VERSION, "runtime_source": "Termylo native TCE fork",
            "runtime_release": URL, "archive_sha256": ARCHIVE_SHA256,
            "internal_helper_sha256": BINARY_SHA256,
            "runtime_files": release_metadata["runtime_files"],
            "source_license": "MIT", "enabled_by_default": False,
            "desktop_application": False,
        }
        manifest_path = target / "manifest.json"
        prior = manifest_path.read_bytes() if manifest_path.exists() else None
        tmp = target / "manifest.json.tmp"
        try:
            tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            tmp.replace(manifest_path)
            if not runtime_valid(target, verify=True):
                raise RuntimeError("Installed TCE runtime verification failed.")
        except Exception:
            tmp.unlink(missing_ok=True)
            if live.exists():
                shutil.rmtree(live)
            if backup.exists():
                backup.rename(live)
            if prior is None:
                manifest_path.unlink(missing_ok=True)
            else:
                manifest_path.write_bytes(prior)
            raise
        if backup.exists():
            shutil.rmtree(backup)  # No original runtime or fallback retained.
    (target / "models").mkdir(exist_ok=True)
    return {"status": "installed", "package": "Terminal Context Engine",
            "executable": str(target / "bin" / "tce.exe"),
            "models_dir": str(target / "models"), "sha256": BINARY_SHA256}
