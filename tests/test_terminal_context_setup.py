"""Offline opt-in and installation planning tests (no model downloads)."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from termylo import context_assets, context_engine
from termylo.context_engine import TerminalContextEngine


class Approval:
    def __init__(self):
        self.active = True
    def status(self):
        return {"status": "active" if self.active else "closed",
                "grant_id": "local-only" if self.active else None,
                "remaining_seconds": 400 if self.active else 0}


class Shell:
    def status(self):
        return {"status": "active"}


class Projects:
    def get(self, name):
        return name.strip().casefold(), Shell()


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    root = tmp_path / "examples"
    root.mkdir()
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    program = tmp_path / "trusted-digup.exe"
    program.write_bytes(b"FAKE-TRUSTED-EXE")
    text = b"text-weights"
    media = b"media-weights"
    assets = (
        ("embeddinggemma-2-Q8_0.gguf", len(text), hashlib.sha256(text).hexdigest()),
        ("mmproj-embeddinggemma-2-Q8_0.gguf", len(media), hashlib.sha256(media).hexdigest()),
    )
    monkeypatch.setattr(context_assets, "MODEL_ASSETS", assets)
    monkeypatch.setattr(context_engine, "MODEL_ASSETS", assets)
    monkeypatch.setattr(context_assets, "TOTAL_MODEL_BYTES",
                        sum(asset[1] for asset in assets))
    for (name, _, _), content in zip(assets, [text, media]):
        (model_dir / name).write_bytes(content)
    approval = Approval()
    engine = TerminalContextEngine(approval, Projects(), tmp_path / "config")
    try:
        yield engine, approval, root, model_dir, program, assets
    finally:
        engine.close()


def settings(engine, root, model_dir, program, **kwargs):
    return engine.configure(
        "alpha", str(program), [str(root)], models_dir=str(model_dir),
        binary_sha256=hashlib.sha256(program.read_bytes()).hexdigest(),
        **kwargs,
    )


def test_default_is_disabled_and_configure_never_enables(prepared):
    engine, _, root, model_dir, program, _ = prepared
    assert engine.status("alpha")["enabled"] is False
    assert settings(engine, root, model_dir, program)["status"] == "configured"
    assert engine.status("alpha")["enabled"] is False
    assert engine.search("alpha", "query")["status"] == "disabled"
    assert settings(engine, root, model_dir, program, enabled=True)["status"] == "rejected"


def test_preflight_read_only_and_explicit_enable(prepared):
    engine, _, root, model_dir, program, _ = prepared
    assert settings(engine, root, model_dir, program)["status"] == "configured"
    assert engine.preflight("alpha", verify_hashes=False)["status"] == "unverified"
    full = engine.preflight("alpha", verify_hashes=True)
    assert full["status"] == "ready"
    assert full["ready"]
    assert full["additional_model_bytes"] == 0
    assert all(model["state"] == "verified" for model in full["models"])
    assert engine.enable("alpha")["status"] == "enabled"
    status = engine.status("alpha")
    assert status["enabled"] is True
    assert status["service_running"] is False
    assert not Path(status["index_directory"]).exists()
    assert engine.disable("alpha")["status"] == "disabled"
    assert engine.status("alpha")["enabled"] is False


def test_missing_and_corrupted_files_block_enable(prepared):
    engine, _, root, model_dir, program, assets = prepared
    settings(engine, root, model_dir, program)
    path = model_dir / assets[1][0]
    path.write_bytes(b"other-weights")  # same length but different SHA
    failed = engine.preflight("alpha")
    assert failed["status"] == "not_ready"
    assert any("wrong_digest" in code for code in failed["problems"])
    assert engine.enable("alpha")["status"] == "not_ready"
    assert engine.status("alpha")["enabled"] is False
    path.unlink()
    assert any("missing" in code for code in engine.preflight("alpha")["problems"])


def test_executable_digest_required_and_mismatch_rejected(prepared):
    engine, _, root, model_dir, program, _ = prepared
    result = engine.configure("alpha", str(program), [str(root)],
                              models_dir=str(model_dir))
    assert result["status"] == "configured"
    assert "executable_digest_not_pinned" in engine.preflight("alpha")["problems"]
    assert engine.enable("alpha")["status"] == "not_ready"
    program_hash = "0" * 64
    engine.configure("alpha", str(program), [str(root)],
                     models_dir=str(model_dir), binary_sha256=program_hash)
    assert "executable_digest_mismatch" in engine.preflight("alpha")["problems"]


def test_model_modified_after_enable_blocks_next_search(prepared):
    engine, _, root, model_dir, program, assets = prepared
    settings(engine, root, model_dir, program)
    assert engine.enable("alpha")["status"] == "enabled"
    (model_dir / assets[0][0]).write_bytes(b"tampered")
    assert engine.search("alpha", "example")["status"] == "not_ready"
    assert engine.status("alpha")["service_running"] is False


def test_preflight_does_not_create_model_files(prepared):
    engine, _, root, model_dir, program, _ = prepared
    empty = model_dir / "not-yet-installed"
    result = engine.configure("alpha", str(program), [str(root)],
                              models_dir=str(empty),
                              binary_sha256=hashlib.sha256(program.read_bytes()).hexdigest())
    assert result["status"] == "configured"
    assert engine.preflight("alpha")["status"] == "not_ready"
    assert not empty.exists()
    assert engine.enable("alpha")["status"] == "not_ready"


def test_read_only_inventory_with_engine_disabled(prepared):
    engine, _, root, model_dir, program, _ = prepared
    folder = root / "older"
    folder.mkdir()
    (root / "final1.pdf").write_bytes(b"some text")
    (root / "final2.pdf").write_bytes(b"updated text")
    (folder / "deck.pptx").write_bytes(b"slides")
    (folder / "budget.xlsx").write_bytes(b"spreadsheet")
    (folder / "photo.png").write_bytes(b"picture")
    (folder / "voice.mp3").write_bytes(b"audio")
    (folder / "clip.mp4").write_bytes(b"video")
    settings(engine, root, model_dir, program)
    report = engine.inventory("alpha")
    assert report["status"] == "ok"
    assert report["files_examined"] == 7
    assert report["candidate_counts_by_type"] == {
        "audio": 1, "document": 2, "image": 1,
        "presentation": 1, "spreadsheet": 1, "video": 1,
    }
    assert not engine._project("alpha")[2].index_path.exists()
    assert engine.status("alpha")["enabled"] is False


def test_inventory_caps_scan_and_permission(prepared):
    engine, approval, root, model_dir, program, _ = prepared
    for n in range(30):
        (root / f"file{n}.pdf").write_text("test")
    settings(engine, root, model_dir, program)
    report = engine.inventory("alpha", max_files=3)
    assert report["files_examined"] == 3
    assert report["truncated"]
    approval.active = False
    assert engine.inventory("alpha")["status"] == "approval_required"
    assert engine.enable("alpha")["status"] == "approval_required"


def test_config_rejects_invalid_sha_pin(prepared):
    engine, _, root, model_dir, program, _ = prepared
    result = engine.configure("alpha", str(program), [str(root)],
                              models_dir=str(model_dir), binary_sha256="abcdef")
    assert result["status"] == "rejected"

def test_explicit_project_watcher_start_stop(prepared):
    engine, _, root, model_dir, program, _ = prepared
    settings(engine, root, model_dir, program)
    assert engine.watch("alpha", enabled=True)["status"] == "disabled"
    assert engine.enable("alpha")["status"] == "enabled"
    assert engine.watch("alpha", enabled=True, interval_seconds=0)["status"] == "rejected"
    status = engine.watch("alpha", enabled=True, interval_seconds=90)
    assert status["state"] == "watching", status
    assert engine.status("alpha")["watcher"]["active"]
    assert engine.watch("alpha", enabled=False)["status"] == "stopped"
    assert engine.status("alpha")["watcher"]["active"] is False
    assert not engine._project("alpha")[2].index_path.exists()


def test_enabled_configuration_does_not_start_watcher_automatically(prepared):
    engine, _, root, model_dir, program, _ = prepared
    settings(engine, root, model_dir, program)
    assert engine.enable("alpha")["status"] == "enabled"
    assert engine.status("alpha")["watcher"]["state"] == "off"


def test_context_setup_tools_exposed_by_mcp_with_approval_checks(tmp_path):
    import asyncio
    import sys
    import json
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    async def check():
        env = dict(os.environ)
        env["LOCALAPPDATA"] = str(tmp_path / "separate-local-config")
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "termylo.server"],
            cwd=str(Path(__file__).resolve().parents[1]), env=env,
        )
        async with stdio_client(params) as (r,w):
            async with ClientSession(r,w) as session:
                await session.initialize()
                names={t.name for t in (await session.list_tools()).tools}
                assert {"context_preflight","context_enable",
                        "context_inventory","context_watch"} <= names
                for name, args in [
                    ("context_enable", {"project_id":"isolated"}),
                    ("context_preflight", {"project_id":"isolated"}),
                    ("context_inventory", {"project_id":"isolated"}),
                    ("context_watch", {"project_id":"isolated", "enabled":True}),
                ]:
                    result=await session.call_tool(name,args)
                    data=result.structuredContent
                    if data is None:
                        data=json.loads(result.content[0].text)
                    if isinstance(data,dict) and "result" in data:
                        data=data["result"]
                    assert data["status"]=="approval_required",(name,data)
    asyncio.run(check())
