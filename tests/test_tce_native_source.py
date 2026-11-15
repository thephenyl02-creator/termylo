"""Static TCE native-source completeness gates.

These checks do not claim a successful Swift build or functional parity.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "tce-native"
COMMANDS = (
    "estimate", "index", "search", "status", "speed", "eval",
    "index-service", "worker", "search-service", "download-model",
)


def test_native_package_is_rebranded_and_covers_engine_targets():
    package = (ROOT / "Package.swift").read_text(encoding="utf-8")
    for phrase in ('name: "TCE"', 'name: "tce"',
                   'name: "TCEKit"', 'name: "TCEKitTests"',
                   'name: "LlamaRuntime"'):
        assert phrase in package
    assert 'name: "digup"' not in package.lower()
    for folder in ("Sources/TCEKit", "Sources/tce", "Sources/LlamaRuntime",
                   "Sources/TCEApp", "Tests/TCEKitTests", "Tests/LlamaRuntimeTests"):
        assert (ROOT / folder).is_dir(), folder


def test_native_cli_commands_and_modalities_are_preserved():
    text = (ROOT / "Sources/tce/main.swift").read_text(encoding="utf-8")
    for command in COMMANDS:
        assert f"tce {command}" in text, command
    for kind in ("image", "pdf", "doc", "audio", "video"):
        assert kind in text
    for file in ("SearchService.swift", "IndexService.swift",
                 "DownloadModel.swift", "WorkerService.swift"):
        assert (ROOT / "Sources/tce" / file).is_file()
    kit = ROOT / "Sources/TCEKit"
    assert any("Searcher" in p.name for p in kit.rglob("*.swift"))
    assert (kit / "Platform" / "Media+Portable.swift").exists() or any(p.name == "Media+Portable.swift" for p in kit.rglob("*.swift"))


def test_license_and_original_runtime_names_are_kept_distinct():
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "MIT License" in license_text
    assert "Copyright (c) 2026 Abdur Rahim" in license_text
    assert "this permission notice" in license_text
    for directory in (ROOT / "Sources", ROOT / "Tests"):
        for file in directory.rglob("*.swift"):
            content = file.read_text(encoding="utf-8")
            assert "import DigUpKit" not in content
            assert "DIGUP_MODELS" not in content
    assert (ROOT / "scripts/licenses").is_dir()


def test_no_upstream_update_feed_is_enabled():
    import json
    config = json.loads((ROOT / "shell/src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    assert config["plugins"]["updater"]["endpoints"] == []
    for p in (ROOT / "updates").glob("*.json"):
        assert "github.com/ARahim3/" not in p.read_text(encoding="utf-8")
    assert "github.com/ARahim3/" not in (
        ROOT / "shell/src-tauri/src/updates.rs").read_text(encoding="utf-8")


def test_native_source_tree_does_not_contain_old_executable():
    assert not list(ROOT.rglob("digup.exe"))
    assert not list(ROOT.rglob("digup"))
    assert (ROOT / "Sources/tce/main.swift").is_file()
