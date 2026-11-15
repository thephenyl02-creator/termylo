"""Terminal Context Engine's Windows add-on installer and verifier.

This is the *Termylo* package interface. The search helper is third-party MIT
software redistributed with license and notices. We extract only its CLI,
never execute the upstream graphical installer or register another desktop app.
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

SEARCH_VERSION = "0.7.0-beta.3"
SEARCH_ASSET = f"DigUp_{SEARCH_VERSION}_x64-setup.exe"
SEARCH_URL = ("https://github.com/ARahim3/DigUp/releases/download/"
              f"v{SEARCH_VERSION}/{SEARCH_ASSET}")
SEARCH_SHA256 = "013ee9bdc08eb1256cb1b49b0ec11549ae7929f07536e18fbc14fe46d6059fe1"
ZIP_VERSION = "26.05"
ZIP_EXTRACT_URL = f"https://github.com/ip7z/7zip/releases/download/{ZIP_VERSION}/7zr.exe"
ZIP_EXTRACT_SHA256 = "9bf582b894dfa665f852d7e9112b02290a1c303c2d95a21fcdc41ffcb03143b7"
ZIP_INSTALL_URL = f"https://github.com/ip7z/7zip/releases/download/{ZIP_VERSION}/7z2605-x64.exe"
ZIP_INSTALL_SHA256 = "fd99e86f57d8f429ef5ed045bf98315af962e2309b0f1ba87a147a44c71647d0"
MIT_LICENSE_URL = "https://raw.githubusercontent.com/ARahim3/DigUp/v0.7.0-beta.3/LICENSE"


def home() -> Path:
    return (Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) /
            "Termylo" / "ContextEngine")


def _download_small(url: str, destination: Path, expected: str) -> None:
    """Download a pinned release asset, without using or executing it first."""
    if destination.is_file():
        try:
            if sha256_file(destination) == expected:
                return
        except OSError:
            pass
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(destination.suffix + ".download")
    if tmp.exists():
        tmp.unlink()
    curl = shutil.which("curl.exe") or shutil.which("curl")
    if not curl:
        raise RuntimeError("Windows curl.exe is required for package installation.")
    cmd = [curl, "-L", "--fail", "--silent", "--show-error", "--retry", "2",
           "--connect-timeout", "15", "--max-time", "110", "-o", str(tmp), url]
    result = subprocess.run(cmd, timeout=115, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"Download failed: {destination.name}: {result.stderr[:250]}")
    actual = sha256_file(tmp)
    if actual != expected:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"SHA-256 verification failed for {destination.name}.")
    tmp.replace(destination)


def _extract(archive: Path, out: Path, exe: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [str(exe), "x", str(archive), "-o" + str(out), "-y"],
        capture_output=True, text=True, timeout=70,
    )
    if result.returncode:
        raise RuntimeError("Cannot extract verified archive: " + result.stderr[-250:])


def _verify_helper(binary: Path) -> str:
    if not binary.is_file() or binary.is_symlink():
        raise RuntimeError("Missing trusted internal context search helper.")
    for filename in ("pdfium.dll", "ffmpeg.exe", "ffprobe.exe",
                     "llama.dll", "ggml.dll"):
        if not (binary.parent / filename).is_file():
            raise RuntimeError(f"Incomplete search runtime: {filename}")
    return sha256_file(binary)


def install_native(directory: Path | None = None) -> dict:
    """Stage the bundled CLI only, without installing DigUp as a separate app."""
    if os.name != "nt":
        return {"status": "unsupported", "error": "Windows x64 package only."}
    target = Path(directory) if directory else home()
    cache = target / "cache"
    tools = target / "tools"
    stage = target / "stage"
    binary = target / "bin" / "digup.exe"
    cache.mkdir(parents=True, exist_ok=True)
    if binary.is_file() and (target / "manifest.json").is_file():
        manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
        if (manifest.get("source_sha256") == SEARCH_SHA256 and
            manifest.get("internal_helper_sha256") == _verify_helper(binary)):
            return {"status": "installed", "package": "Terminal Context Engine",
                    "executable": str(binary), "models_dir": str(target / "models"),
                    "sha256": manifest["internal_helper_sha256"]}
    seven = cache / "7zr.exe"
    zip_installer = cache / "7z2605-x64.exe"
    release = cache / SEARCH_ASSET
    _download_small(ZIP_EXTRACT_URL, seven, ZIP_EXTRACT_SHA256)
    _download_small(ZIP_INSTALL_URL, zip_installer, ZIP_INSTALL_SHA256)
    _download_small(SEARCH_URL, release, SEARCH_SHA256)
    sevenexe = tools / "7z.exe"
    if not sevenexe.is_file():
        _extract(zip_installer, tools, seven)
    if not (tools / "7z.dll").is_file():
        raise RuntimeError("Verified archive tool was incomplete.")
    helper = stage / "helper" / "digup.exe"
    if not helper.is_file():
        _extract(release, stage, sevenexe)
    _verify_helper(helper)
    notices = stage / "THIRD-PARTY-NOTICES.txt"
    if not notices.is_file():
        raise RuntimeError("Required third-party license notices were not found.")
    target_bin = target / "bin"
    target_bin.mkdir(parents=True, exist_ok=True)
    for item in (stage / "helper").iterdir():
        if item.is_file():
            shutil.copy2(item, target_bin / item.name)
    shutil.copy2(notices, target_bin / notices.name)
    license_path = target_bin / "SEARCH-ENGINE-MIT-LICENSE.txt"
    # License attribution is mandatory. Download source text, not executable.
    import urllib.request
    try:
        with urllib.request.urlopen(MIT_LICENSE_URL, timeout=25) as response:
            license_bytes = response.read(12000)
        if b"MIT License" not in license_bytes or b"Abdur Rahim" not in license_bytes:
            raise RuntimeError("Search engine license could not be verified.")
        license_path.write_bytes(license_bytes)
    except Exception as exc:
        raise RuntimeError(f"Cannot preserve required license notice: {exc}") from exc
    digest = _verify_helper(binary)
    manifest = {
        "package": "Terminal Context Engine", "package_type": "Termylo optional addon",
        "source_component": "DigUp", "source_version": SEARCH_VERSION,
        "source_repository": "https://github.com/ARahim3/DigUp",
        "source_license": "MIT", "source_sha256": SEARCH_SHA256,
        "internal_helper_sha256": digest, "enabled_by_default": False,
        "voice": False, "desktop_application": False,
        "model_repository": MODEL_REPOSITORY, "model_revision": MODEL_REVISION,
        "model_downloaded": False,
    }
    tmp = target / "manifest.json.tmp"
    tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    tmp.replace(target / "manifest.json")
    (target / "models").mkdir(exist_ok=True)
    return {"status": "installed", "package": "Terminal Context Engine",
            "executable": str(binary), "models_dir": str(target / "models"),
            "sha256": digest, "model_installed": False}


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
    bin_file = target / "bin" / "digup.exe"
    manifest = target / "manifest.json"
    valid = False
    release = {}
    if manifest.exists():
        try:
            release = json.loads(manifest.read_text(encoding="utf-8"))
            valid = bin_file.is_file() and (not verify or
                    sha256_file(bin_file) == release.get("internal_helper_sha256"))
        except (OSError, ValueError):
            pass
    return {"package": "Terminal Context Engine", "status": "installed" if valid else "not_installed",
            "location": str(target), "executable": str(bin_file),
            "binary_verified": valid and verify,
            "search_component": release.get("source_version"),
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
