# TCE native cutover audit — November 15, 2026

**Product:** Termylo. **Engine:** Termylo Context Engine (TCE). No standalone upstream application.

## Build and provenance

- Native source: `tce-native/` in Termylo; compiled with Swift 6.3.3 (Windows x64, optimized release).
- Native source commit: `68497af2fd73befe8c36e1b34f6ac7d0e9db42b7`.
- Internal runtime release: `tce-native-v0.1.0` under this Termylo GitHub repository.
- Archive: `termylo-tce-windows-x64-0.1.0.zip`, 64,912,931 bytes, SHA-256 `e85a9edfd34d4a13106acb2b60323eea54e8e59195d546d28aae44fa67561f7c`.
- Source-built TCE executable SHA-256: `c2dd6b5d1ef74eb27cfb8044a46f55ccb05869756bde682b258f056707babad2`.
- Remote GitHub asset digest matches archive pin; anonymous release installation verified.
- File-by-file runtime SHA-256 verification and malicious archive-path checks pass.

## Local installation

- Live runtime: `%LOCALAPPDATA%\Termylo\ContextEngine\bin\tce.exe`.
- Original binary, original setup cache, extracted staging directory, and unused upstream source checkout removed.
- Both GGUF model files preserved and verified. Existing indexes preserved.
- `tce.exe --help`, indexed database status and semantic search all executed successfully.
- No TCE search or indexing process was active during the runtime swap.

## Tests

- 112 Swift native engine tests passed (16 suites); Windows symlink-only test omitted due filesystem privilege limitation.
- 198 Python integration/installer/context tests passed and one symlink test skipped.
- 32 additional terminal/project recovery tests passed. Total Python: 230 passed, 1 skipped.
- 13/13 synthetic known-answer queries ranked expected content first on the optimized TCE build.
- Fresh native index: 3 MP4 files, each indexed. Controlled red/blue and green/yellow video queries returned correct clips at zgate=1.25; strict zgate=2.0 missed a clip; an unrelated horse query returned no hits.
- After model startup, persistent search requests completed in about 0.00–0.08s in the controlled corpus.
- API acceptance with approved supervisor: configure, preflight, enable, search PDF/image/DOCX, exact-file verification, stale-file denial, cross-project and approval gating.

## Limits and activation boundary

- Negative-query rejection remains weak (10/12 unrelated queries returned candidates); ranking on a small synthetic sample is not production-quality proof.
- Full audio transcription and comprehensive video understanding were not established.
- **The already-running Termylo MCP Python service was not restarted.** Its in-memory old code may remain loaded until a fresh service connection. Restarting it closes the currently approved native project terminals (`server.py` atexit cleanup). The verified local runtime and on-disk adapter now contain only TCE; no source or executable fallback to the original engine exists.
- Live terminal session and universal approval remained active after cutover. No user project working files, model files, or indexes were deleted.
