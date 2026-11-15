"""Termylo's bundled TCE runtime installer security and migration tests."""
import hashlib
import json
import os
import zipfile
from pathlib import Path

import pytest

from termylo import tce_runtime as runtime
from termylo.context_assets import sha256_file


def bundle(tmp_path, monkeypatch, *, extra=None):
    contents = {name: ("TCE-source-" + name).encode()
                for name in runtime.REQUIRED}
    contents["tce.exe"] = b"source-built-TCE"
    digest = hashlib.sha256(contents["tce.exe"]).hexdigest()
    archive = tmp_path / "source-built.zip"
    metadata = {
        "product": "Termylo", "engine": "TCE", "version": runtime.VERSION,
        "runtime_files": {k: hashlib.sha256(v).hexdigest()
                          for k, v in contents.items()},
    }
    with zipfile.ZipFile(archive, "w") as z:
        for name, data in contents.items():
            z.writestr("bin/" + name, data)
        z.writestr("runtime.json", json.dumps(metadata))
        if extra:
            z.writestr(extra, b"malicious")
    monkeypatch.setattr(runtime, "BINARY_SHA256", digest)
    monkeypatch.setattr(runtime, "ARCHIVE_SHA256", sha256_file(archive))
    return archive


@pytest.mark.skipif(os.name != "nt", reason="TCE runtime is Windows-only")
def test_source_built_bundle_install_is_internal_and_idempotent(tmp_path, monkeypatch):
    source = bundle(tmp_path, monkeypatch)
    target = tmp_path / "termylo" / "ContextEngine"
    result = runtime.install_runtime(target, bundle_path=source)
    assert result["status"] == "installed"
    assert runtime.runtime_valid(target, verify=True)
    assert not (target / "bin" / "digup.exe").exists()
    assert (target / "models").is_dir()
    assert json.loads((target / "manifest.json").read_text())["engine"] == "TCE"
    assert runtime.install_runtime(target, bundle_path=tmp_path / "missing.zip")["status"] == "installed"


@pytest.mark.skipif(os.name != "nt", reason="TCE runtime is Windows-only")
def test_unpinned_runtime_bundle_rejected(tmp_path, monkeypatch):
    source = bundle(tmp_path, monkeypatch)
    source.write_bytes(source.read_bytes() + b"altered")
    target = tmp_path / "install"
    with pytest.raises(RuntimeError, match="Untrusted"):
        runtime.install_runtime(target, bundle_path=source)
    assert not (target / "bin").exists()


@pytest.mark.skipif(os.name != "nt", reason="TCE runtime is Windows-only")
def test_runtime_archive_path_traversal_rejected(tmp_path, monkeypatch):
    source = bundle(tmp_path, monkeypatch, extra="bin/../outside.exe")
    target = tmp_path / "install"
    with pytest.raises(RuntimeError, match="Unsafe"):
        runtime.install_runtime(target, bundle_path=source)
    assert not (tmp_path / "outside.exe").exists()


def test_legacy_executable_is_not_accepted_as_tce(tmp_path):
    target = tmp_path / "ContextEngine"
    (target / "bin").mkdir(parents=True)
    (target / "bin" / "digup.exe").write_bytes(b"legacy")
    (target / "manifest.json").write_text(
        json.dumps({"package": "Terminal Context Engine",
                    "internal_helper_sha256": "old"}))
    assert not runtime.runtime_valid(target, verify=True)


@pytest.mark.skipif(os.name != "nt", reason="TCE runtime is Windows-only")
def test_tampered_native_dependency_is_detected(tmp_path, monkeypatch):
    source = bundle(tmp_path, monkeypatch)
    target = tmp_path / "installed"
    runtime.install_runtime(target, bundle_path=source)
    assert runtime.runtime_valid(target, verify=True)
    (target / "bin" / "llama.dll").write_bytes(b"tampered")
    assert not runtime.runtime_valid(target, verify=True)


@pytest.mark.skipif(os.name != "nt", reason="TCE runtime is Windows-only")
def test_upgrading_legacy_runtime_does_not_leave_fallback(tmp_path, monkeypatch):
    source = bundle(tmp_path, monkeypatch)
    target = tmp_path / "upgrade"
    (target / "bin").mkdir(parents=True)
    (target / "bin" / "digup.exe").write_bytes(b"legacy engine")
    (target / "manifest.json").write_text(json.dumps({"old": "manifest"}))
    result = runtime.install_runtime(target, bundle_path=source)
    assert result["status"] == "installed"
    assert runtime.runtime_valid(target, verify=True)
    assert not (target / "bin" / "digup.exe").exists()
    assert not list(target.glob("bin-before-tce-*"))
    assert (target / "manifest.json").read_text().count('"engine": "TCE"') == 1
