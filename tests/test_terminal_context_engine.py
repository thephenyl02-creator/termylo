"""Terminal Context Engine build tests: no real model or installer required."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

import pytest

from termylo import context_engine as module
from termylo.context_engine import (
    ContextProject, TerminalContextEngine, MAX_EXCERPT,
)


class Approval:
    def __init__(self):
        self.active = True
        self.grant = "one-local-lease"

    def status(self):
        return {
            "status": "active" if self.active else "closed",
            "grant_id": self.grant if self.active else None,
            "remaining_seconds": 120 if self.active else 0,
        }


class Shell:
    def __init__(self):
        self.active = True

    def status(self):
        return {"status": "active" if self.active else "closed"}


class Projects:
    def __init__(self):
        self.shells = {}

    def get(self, key):
        key = str(key).strip().casefold()
        if key not in self.shells:
            self.shells[key] = Shell()
        return key, self.shells[key]


@pytest.fixture
def engine(tmp_path):
    approval, projects = Approval(), Projects()
    tce = TerminalContextEngine(approval, projects, home=tmp_path / "context")
    try:
        yield tce, approval, projects
    finally:
        tce.close()


def configured(tce, root: Path, project="alpha", executable=None):
    result = tce.configure(project, executable or sys.executable, [str(root)])
    assert result["status"] == "configured", result
    # Existing protocol tests intentionally use a fake executable without
    # model assets. Simulate completed opt-in only in this test fixture.
    current = tce._project(project)[2]
    current._config["enabled"] = True
    current._verified_stamp = ("fake-assets-for-protocol-test",)
    current._asset_stamp = lambda: ("fake-assets-for-protocol-test",)
    current.save()
    return {"enabled": True, **result}


def inject_hits(monkeypatch, tce, project_id, hits):
    key, _, current = tce._project(project_id)
    current._index_last = time.monotonic()
    monkeypatch.setattr(current, "request", lambda data, roots: {"hits": hits})
    return current


def test_engine_defaults_to_disabled_and_requires_local_consent(engine, tmp_path):
    tce, approval, projects = engine
    root = tmp_path / "files"
    root.mkdir()
    assert tce.status("alpha")["enabled"] is False
    assert tce.search("alpha", "resume")["status"] == "disabled"
    approval.active = False
    assert tce.status("alpha")["status"] == "approval_required"
    assert tce.configure("alpha", sys.executable, [str(root)])["status"] == "approval_required"
    assert tce.index("alpha")["status"] == "approval_required"
    assert tce.verify("alpha", "guess")["status"] == "approval_required"
    assert tce.disable("alpha")["status"] == "approval_required"


def test_config_validation_and_persistence(engine, tmp_path):
    tce, approval, projects = engine
    root = tmp_path / "explicit"
    root.mkdir()
    assert tce.configure("alpha", "digup", [str(root)])["status"] == "rejected"
    assert tce.configure("alpha", sys.executable, [])["status"] == "rejected"
    assert tce.configure("alpha", sys.executable, [str(tmp_path / "absent")])["status"] == "rejected"
    assert tce.configure("alpha", sys.executable, [str(root)], models_dir="relative")["status"] == "rejected"
    assert configured(tce, root)["installed"] is True
    fresh = TerminalContextEngine(approval, projects, home=tce.home)
    assert fresh.status("alpha")["configured_roots"] == [str(root.resolve())]
    assert fresh.status("alpha")["enabled"] is True
    assert fresh.status("alpha")["service_running"] is False
    fresh.close()


def test_disabled_and_not_installed_states(engine, tmp_path):
    tce, _, _ = engine
    root = tmp_path / "files"
    root.mkdir()
    configured(tce, root)
    assert tce.disable("alpha")["status"] == "disabled"
    assert tce.search("alpha", "anything")["status"] == "disabled"
    missing = tmp_path / "no-search-engine.exe"
    result = tce.configure("alpha", str(missing), [str(root)])
    assert result["status"] == "configured"
    assert result["installed"] is False
    assert tce.search("alpha", "anything")["status"] == "disabled"
    assert tce.preflight("alpha")["status"] == "not_ready"


def test_search_by_content_includes_metadata_sha_and_exact_reference(engine, tmp_path, monkeypatch):
    tce, _, _ = engine
    root = tmp_path / "files"
    root.mkdir()
    target = root / "final3.pdf"
    target.write_text("resume business analyst", encoding="utf-8")
    configured(tce, root)
    inject_hits(monkeypatch, tce, "alpha", [
        {"path": str(target), "kind": "pdf", "loc": 3,
         "excerpt": "experience collecting business requirements", "score": .99},
    ])
    result = tce.search("alpha", "my business analyst resume")
    assert result["status"] == "ok"
    assert result["meaning"] is True
    assert len(result["hits"]) == 1
    hit = result["hits"][0]
    assert hit["filename"] == "final3.pdf"
    assert hit["location"] == 3
    assert hit["sha256"] == hashlib.sha256(target.read_bytes()).hexdigest()
    assert hit["bytes"] == target.stat().st_size
    assert len(hit["file_id"]) == 24
    assert tce.verify("alpha", hit["reference"])["status"] == "verified"


def test_duplicate_filenames_have_distinct_references_and_hashes(engine, tmp_path, monkeypatch):
    tce, _, _ = engine
    root = tmp_path / "files"
    left, right = root / "2025", root / "2026"
    left.mkdir(parents=True)
    right.mkdir()
    old, new = left / "final.pdf", right / "final.pdf"
    old.write_text("old version")
    new.write_text("new version and experience")
    configured(tce, root)
    inject_hits(monkeypatch, tce, "alpha", [
        {"path": str(old), "excerpt": "2025"},
        {"path": str(new), "excerpt": "2026"},
    ])
    hits = tce.search("alpha", "resume", limit=2)["hits"]
    assert len(hits) == 2
    assert hits[0]["filename"] == hits[1]["filename"]
    assert hits[0]["file_id"] != hits[1]["file_id"]
    assert hits[0]["reference"] != hits[1]["reference"]
    assert hits[0]["sha256"] != hits[1]["sha256"]
    for hit in hits:
        assert tce.verify("alpha", hit["reference"])["status"] == "verified"


def test_changed_file_is_stale_even_when_size_and_mtime_match(engine, tmp_path, monkeypatch):
    tce, _, _ = engine
    root = tmp_path / "files"
    root.mkdir()
    file = root / "final.pdf"
    file.write_bytes(b"AAAA")
    configured(tce, root)
    inject_hits(monkeypatch, tce, "alpha", [{"path": str(file)}])
    hit = tce.search("alpha", "final")["hits"][0]
    stat = file.stat()
    file.write_bytes(b"BBBB")
    os.utime(file, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert tce.verify("alpha", hit["reference"])["status"] == "stale"


def test_renaming_or_deleting_invalidates_reference(engine, tmp_path, monkeypatch):
    tce, _, _ = engine
    root = tmp_path / "files"
    root.mkdir()
    file = root / "final.pdf"
    file.write_text("content")
    configured(tce, root)
    inject_hits(monkeypatch, tce, "alpha", [{"path": str(file)}])
    ref = tce.search("alpha", "final")["hits"][0]["reference"]
    file.rename(root / "renamed.pdf")
    assert tce.verify("alpha", ref)["status"] == "stale"


def test_cross_project_reference_and_expiration(engine, tmp_path, monkeypatch):
    tce, _, _ = engine
    folder = tmp_path / "shared"
    folder.mkdir()
    file = folder / "resume.pdf"
    file.write_text("resume")
    configured(tce, folder, project="alpha")
    configured(tce, folder, project="beta")
    inject_hits(monkeypatch, tce, "alpha", [{"path": str(file)}])
    ref = tce.search("alpha", "resume")["hits"][0]["reference"]
    assert tce.verify("beta", ref)["status"] == "not_found"
    assert tce.verify("alpha", ref)["status"] == "verified"
    tce._refs[ref].created -= module.REF_LIFETIME + 1
    assert tce.verify("alpha", ref)["status"] == "not_found"


def test_symlink_escape_is_filtered(engine, tmp_path, monkeypatch):
    tce, _, _ = engine
    root = tmp_path / "approved"
    root.mkdir()
    secret = tmp_path / "secret.pdf"
    secret.write_text("private contents")
    link = root / "look-here.pdf"
    try:
        link.symlink_to(secret)
    except (OSError, NotImplementedError):
        pytest.skip("symlink unavailable on this filesystem")
    configured(tce, root)
    inject_hits(monkeypatch, tce, "alpha", [
        {"path": str(link), "excerpt": "outside"},
        {"path": str(secret), "excerpt": "outside"},
    ])
    assert tce.search("alpha", "secret")["hits"] == []


def test_large_file_digest_is_deferred_but_verified(engine, tmp_path, monkeypatch):
    tce, _, _ = engine
    root = tmp_path / "files"
    root.mkdir()
    file = root / "clip.mp4"
    file.write_bytes(b"video content bytes")
    configured(tce, root)
    monkeypatch.setattr(module, "MAX_HASH_ON_SEARCH", 2)
    inject_hits(monkeypatch, tce, "alpha", [
        {"path": str(file), "kind": "video", "loc": 35.2,
         "excerpt": "person demonstrating a concept"},
    ])
    hit = tce.search("alpha", "demonstration")["hits"][0]
    assert hit["sha256"] is None
    assert hit["sha256_state"] == "deferred_large_file"
    checked = tce.verify("alpha", hit["reference"])
    assert checked["status"] == "verified"
    assert checked["sha256"] == hashlib.sha256(file.read_bytes()).hexdigest()


def test_invalid_query_limit_and_malformed_hits(engine, tmp_path, monkeypatch):
    tce, _, _ = engine
    root = tmp_path / "files"
    root.mkdir()
    configured(tce, root)
    inject_hits(monkeypatch, tce, "alpha", [])
    for query in ("", " ", "X" * 501):
        assert tce.search("alpha", query)["status"] == "rejected"
    for count in (0, 13, True, "3"):
        assert tce.search("alpha", "search", limit=count)["status"] == "rejected"
    project = tce._project("alpha")[2]
    monkeypatch.setattr(project, "request", lambda data, roots: {"hits": "bad"})
    assert tce.search("alpha", "valid")["status"] == "error"


def test_untrusted_excerpts_bounded_and_missing_file_ignored(engine, tmp_path, monkeypatch):
    tce, _, _ = engine
    root = tmp_path / "files"
    root.mkdir()
    file = root / "notes.txt"
    file.write_text("valid")
    configured(tce, root)
    inject_hits(monkeypatch, tce, "alpha", [
        {"path": str(root / "missing.pdf"), "excerpt": "missing"},
        {"path": str(file), "excerpt": "x" * 9000, "kind": "text"},
    ])
    hits = tce.search("alpha", "notes")["hits"]
    assert len(hits) == 1
    assert len(hits[0]["excerpt"]) == MAX_EXCERPT


def test_revoke_permission_blocks_future_search_and_verify(engine, tmp_path, monkeypatch):
    tce, approval, _ = engine
    root = tmp_path / "files"
    root.mkdir()
    file = root / "resume.pdf"
    file.write_text("resume")
    configured(tce, root)
    inject_hits(monkeypatch, tce, "alpha", [{"path": str(file)}])
    ref = tce.search("alpha", "resume")["hits"][0]["reference"]
    approval.active = False
    assert tce.verify("alpha", ref)["status"] == "approval_required"
    assert tce.search("alpha", "resume")["status"] == "approval_required"

def test_outside_root_result_is_filtered_without_symlink(engine, tmp_path, monkeypatch):
    tce, _, _ = engine
    root = tmp_path / "safe"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("private")
    configured(tce, root)
    inject_hits(monkeypatch, tce, "alpha", [{"path": str(outside), "excerpt": "private"}])
    assert tce.search("alpha", "private")["hits"] == []


def _fake_cli_script(tmp_path):
    script = tmp_path / "fake_multimodal_cli.py"
    script.write_text(
        "import json,sys,time\n"
        "from pathlib import Path\n"
        "cmd=sys.argv[1]\n"
        "if cmd=='index':\n"
        "    time.sleep(.08)\n"
        "    sys.exit(0)\n"
        "if cmd!='search-service':\n"
        "    sys.exit(4)\n"
        "root=Path(sys.argv[-1])\n"
        "print(json.dumps({'event':'ready'}),flush=True)\n"
        "for line in sys.stdin:\n"
        "    req=json.loads(line)\n"
        "    if req.get('op')=='reload':\n"
        "        marker=root/'reload_marker.txt'\n"
        "        marker.write_text(str(int(marker.read_text())+1) if marker.exists() else '1')\n"
        "        print(json.dumps({'id':req['id'],'ok':True,'vectors':12}),flush=True)\n"
        "        continue\n"
        "    print('NOT JSON',flush=True)\n"
        "    print(json.dumps({'id':'unrelated-request','hits':[]}),flush=True)\n"
        "    files=list(root.rglob('*.pdf'))\n"
        "    hits=[] if req['q']=='find nothing' else ["
        "{'path':str(p),'kind':'pdf','loc':4,'score':.95,"
        "'excerpt':'requirements and experience'} for p in files]\n"
        "    print(json.dumps({'id':req['id'],'ok':True,'meaning':req.get('meaning'),"
        "'hits':hits}),flush=True)\n",
        encoding="utf-8",
    )
    return script


def _use_fake_cli(monkeypatch, script):
    original = ContextProject._launch
    def launcher(self, args, *, pipes=False):
        return original(self, [sys.executable, "-u", str(script), *args[1:]], pipes=pipes)
    monkeypatch.setattr(ContextProject, "_launch", launcher)


def test_real_jsonl_search_service_and_index_lifecycle(engine, tmp_path, monkeypatch):
    tce, _, _ = engine
    root = tmp_path / "approved"
    root.mkdir()
    first = root / "final.pdf"
    first.write_text("experience and business requirements")
    second = root / "extra.pdf"
    second.write_text("other resume")
    configured(tce, root)
    _use_fake_cli(monkeypatch, _fake_cli_script(tmp_path))
    started = tce.index("alpha")
    assert started["status"] == "indexing"
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and tce.status("alpha")["index_status"] == "indexing":
        time.sleep(.05)
    assert tce.status("alpha")["index_status"] == "ready"
    result = tce.search("alpha", "business requirements", limit=5)
    assert result["status"] == "ok", result
    assert len(result["hits"]) == 2
    assert all(hit["location"] == 4 for hit in result["hits"])
    assert all(tce.verify("alpha", hit["reference"])["status"] == "verified"
               for hit in result["hits"])
    assert tce.status("alpha")["service_running"]
    assert tce.search("alpha", "find nothing")["hits"] == []
    assert tce.disable("alpha")["status"] == "disabled"
    assert not tce.status("alpha")["service_running"]


def test_real_service_is_killed_when_approval_expires_without_polling(engine, tmp_path, monkeypatch):
    tce, approval, projects = engine
    root = tmp_path / "approved"
    root.mkdir()
    (root / "resume.pdf").write_text("draft")
    configured(tce, root)
    _use_fake_cli(monkeypatch, _fake_cli_script(tmp_path))
    assert tce.search("alpha", "resume")["status"] == "ok"
    project = tce._project("alpha")[2]
    assert project._process is not None
    proc = project._process
    assert proc.poll() is None
    approval.active = False
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline and proc.poll() is None:
        time.sleep(.1)
    assert proc.poll() is not None
    assert tce.search("alpha", "resume")["status"] == "approval_required"


def test_real_service_restarts_after_unexpected_exit(engine, tmp_path, monkeypatch):
    tce, _, _ = engine
    root = tmp_path / "approved"
    root.mkdir()
    (root / "resume.pdf").write_text("content")
    configured(tce, root)
    _use_fake_cli(monkeypatch, _fake_cli_script(tmp_path))
    first = tce.search("alpha", "resume")
    assert first["status"] == "ok"
    project = tce._project("alpha")[2]
    old = project._process
    old.kill()
    old.wait(timeout=3)
    second = tce.search("alpha", "resume")
    assert second["status"] == "ok", second
    assert project._process is not old


def test_project_content_indexes_are_physically_separate(engine, tmp_path):
    tce, _, _ = engine
    root = tmp_path / "files"
    root.mkdir()
    configured(tce, root, project="alpha")
    configured(tce, root, project="beta")
    a = tce._project("alpha")[2]
    b = tce._project("beta")[2]
    assert a.index_path != b.index_path
    assert a.config_path != b.config_path


def test_invalid_jsonl_response_is_not_accepted_as_a_file(engine, tmp_path, monkeypatch):
    tce, _, _ = engine
    root = tmp_path / "files"
    root.mkdir()
    configured(tce, root)
    project = inject_hits(monkeypatch, tce, "alpha", [])
    monkeypatch.setattr(project, "request", lambda d, r: {"hits": [{"path": 42}, None]})
    assert tce.search("alpha", "resume")["hits"] == []

def test_reconfiguration_removes_old_index_and_old_scope(engine, tmp_path, monkeypatch):
    tce, _, _ = engine
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    old_root.mkdir()
    new_root.mkdir()
    file = old_root / "resume.pdf"
    file.write_text("old content")
    configured(tce, old_root)
    current = tce._project("alpha")[2]
    current.index_path.mkdir()
    (current.index_path / "old-index-record.txt").write_text("private old vectors")
    inject_hits(monkeypatch, tce, "alpha", [{"path": str(file)}])
    ref = tce.search("alpha", "resume")["hits"][0]["reference"]
    updated = tce.configure("alpha", sys.executable, [str(new_root)])
    assert updated["status"] == "configured"
    assert not current.index_path.exists()
    assert updated["configured_roots"] == [str(new_root)]
    assert tce.verify("alpha", ref)["status"] == "disabled"


def test_hash_mutation_during_search_is_not_trusted(engine, tmp_path, monkeypatch):
    tce, _, _ = engine
    root = tmp_path / "files"
    root.mkdir()
    file = root / "clip.pdf"
    file.write_bytes(b"AAAA")
    configured(tce, root)
    inject_hits(monkeypatch, tce, "alpha", [{"path": str(file)}])
    original = module._sha256
    def change_file_during_hash(path):
        digest = original(path)
        path.write_bytes(b"BBBBB")
        return digest
    monkeypatch.setattr(module, "_sha256", change_file_during_hash)
    assert tce.search("alpha", "clip")["hits"] == []


def test_nonfinite_scores_cannot_leak_into_mcp_json(engine, tmp_path, monkeypatch):
    tce, _, _ = engine
    root = tmp_path / "files"
    root.mkdir()
    file = root / "resume.pdf"
    file.write_text("content")
    configured(tce, root)
    inject_hits(monkeypatch, tce, "alpha", [{"path": str(file), "score": float("nan")}])
    result = tce.search("alpha", "resume")
    assert result["hits"][0]["score"] is None
    json.dumps(result, allow_nan=False)


def test_index_setup_error_is_reported(engine, tmp_path, monkeypatch):
    tce, _, _ = engine
    root = tmp_path / "files"
    root.mkdir()
    configured(tce, root)
    project = tce._project("alpha")[2]
    def fail_index():
        raise module.ContextError("redirected index directory")
    monkeypatch.setattr(project, "_ensure_index_dir", fail_index)
    assert tce.index("alpha")["status"] == "error"
    assert tce.search("alpha", "resume")["status"] == "error"


def test_mcp_tools_are_exposed_without_starting_an_unapproved_search(tmp_path):
    import asyncio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    async def check():
        env = dict(os.environ)
        env["LOCALAPPDATA"] = str(tmp_path / "sandbox-home")
        args = StdioServerParameters(
            command=sys.executable, args=["-m", "termylo.server"],
            cwd=str(Path(__file__).resolve().parents[1]), env=env,
        )
        async with stdio_client(args) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                named = {t.name for t in (await session.list_tools()).tools}
                assert {"context_status", "context_configure", "context_disable",
                        "context_index", "context_search", "context_verify"} <= named
                for method, args in [
                    ("context_status", {"project_id": "private-project"}),
                    ("context_search", {"project_id": "private-project", "query": "secret"}),
                    ("context_index", {"project_id": "private-project"}),
                    ("context_verify", {"project_id": "private-project", "reference": "guess"}),
                    ("context_configure", {"project_id": "private-project",
                                           "executable": sys.executable,
                                           "roots": [str(tmp_path)]}),
                ]:
                    response = await session.call_tool(method, args)
                    data = response.structuredContent
                    if data is None:
                        data = json.loads(response.content[0].text)
                    if isinstance(data, dict) and "result" in data:
                        data = data["result"]
                    assert data["status"] == "approval_required", (method, data)
    asyncio.run(check())

def test_reconfig_and_disable_invalidate_old_references(engine, tmp_path, monkeypatch):
    tce, _, _ = engine
    root = tmp_path / "files"
    root.mkdir()
    file = root / "resume.pdf"
    file.write_text("content")
    configured(tce, root)
    inject_hits(monkeypatch, tce, "alpha", [{"path": str(file)}])
    reference = tce.search("alpha", "resume")["hits"][0]["reference"]
    assert tce.configure("alpha", sys.executable, [str(root)])["status"] == "configured"
    assert tce.verify("alpha", reference)["status"] == "disabled"
    configured(tce, root)
    reference = tce.search("alpha", "resume")["hits"][0]["reference"]
    assert tce.disable("alpha")["status"] == "disabled"
    assert tce.verify("alpha", reference)["status"] == "disabled"


def test_expiry_mid_hash_cannot_return_verified_file(engine, tmp_path, monkeypatch):
    tce, approval, _ = engine
    root = tmp_path / "files"
    root.mkdir()
    file = root / "resume.pdf"
    file.write_text("payload")
    configured(tce, root)
    inject_hits(monkeypatch, tce, "alpha", [{"path": str(file)}])
    token = tce.search("alpha", "resume")["hits"][0]["reference"]
    original = module._sha256
    def hash_and_revoke(path):
        result = original(path)
        approval.active = False
        return result
    monkeypatch.setattr(module, "_sha256", hash_and_revoke)
    assert tce.verify("alpha", token)["status"] == "approval_required"

def test_index_cancels_on_disable_and_approval_expiry(engine, tmp_path, monkeypatch):
    tce, approval, _ = engine
    root = tmp_path / "approved"
    root.mkdir()
    configured(tce, root)
    script = _fake_cli_script(tmp_path)
    script.write_text(script.read_text().replace("time.sleep(.08)", "time.sleep(30)"))
    _use_fake_cli(monkeypatch, script)
    assert tce.index("alpha")["status"] == "indexing"
    project = tce._project("alpha")[2]
    proc = project._index
    assert proc is not None and proc.poll() is None
    assert tce.disable("alpha")["status"] == "disabled"
    proc.wait(timeout=5)
    assert project._index_status == "stopped"
    configured(tce, root)
    assert tce.index("alpha")["status"] == "indexing"
    proc = project._index
    approval.active = False
    proc.wait(timeout=5)
    assert proc.poll() is not None
    assert tce.index("alpha")["status"] == "approval_required"
def test_index_refresh_reloads_active_search_service(engine, tmp_path, monkeypatch):
    tce, _, _ = engine
    root = tmp_path / "approved"
    root.mkdir()
    (root / "proposal.pdf").write_text("business proposal")
    configured(tce, root)
    _use_fake_cli(monkeypatch, _fake_cli_script(tmp_path))
    assert tce.search("alpha", "proposal")["status"] == "ok"
    project = tce._project("alpha")[2]
    marker = root / "reload_marker.txt"
    # An explicit subsequent indexing pass must refresh the already open searcher.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and project._index is not None:
        time.sleep(.05)
    marker.unlink(missing_ok=True)
    assert tce.index("alpha")["status"] == "indexing"
    deadline = time.monotonic() + 7
    while time.monotonic() < deadline and not marker.exists():
        time.sleep(.05)
    assert marker.exists(), "Updated search index was not reloaded"
    assert tce.status("alpha")["service_running"]
    assert tce.search("alpha", "proposal")["status"] == "ok"
