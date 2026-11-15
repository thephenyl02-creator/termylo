# Terminal Context Engine - Windows add-on package

User-facing product: **Terminal Context Engine**, installed through Termylo.
It is NOT an installation of the upstream desktop search application.

- Install: `powershell -File scripts/install-terminal-context.ps1 -WithModel`
- Verify: `powershell -File scripts/install-terminal-context.ps1 -Verify`
- Command: `python -m termylo.context_package status --verify`
- Optional model: `python -m termylo.context_package models` (resumes downloads)
- Install directory: `%LOCALAPPDATA%\Termylo\ContextEngine`
- Model directory: `%LOCALAPPDATA%\Termylo\ContextEngine\models`
- Internal command-line engine: `bin\digup.exe` (not exposed as a separate desktop app)
- Default: search/indexing/watchers all DISABLED until the user selects roots and enables.

After activating the updated Termylo MCP service, use `context_setup`
to configure only approved folders, then `context_preflight`, `context_enable`,
`context_index`, `context_search`, and `context_verify`.
The active Termylo service is not restarted by this installation.

### Verified user-device installation, November 15, 2026

- Official Windows CLI archive SHA-256: 013ee9bdc08eb1256cb1b49b0ec11549ae7929f07536e18fbc14fe46d6059fe1
- Extracted internal CLI SHA-256: 8b8055bb6a5218f994d44fecc0564843efd3128af95551e9be36c686d2b54f2a
- Two model files: 309,855,456 and 554,821,024 bytes; both full SHA-256 verified.
- Real local indexing and keyword+semantic search passed on a synthetic sample.
- JSONL search-service handshake, encoder loading and result returned successfully.

### Attribution

The native CLI is a component of DigUp by Abdur Rahim, released under MIT.
Its MIT license is preserved at `bin\SEARCH-ENGINE-MIT-LICENSE.txt`, and the
upstream `THIRD-PARTY-NOTICES.txt` is included. EmbeddingGemma 2 model
assets originate from `ggml-org/embeddinggemma-2-GGUF` pinned revision,
with their own applicable open licenses. This is a Termylo-packaged add-on,
not an original rewrite of that upstream search implementation.

Do not bundle model weights in the base Termylo pip package. Downloads are
opt-in and validated before acceptance. Installer and index do not install
or launch any separate graphical search application.

### Large folder indexing
Pass optional `limit=20` to `context_index` for a safe first batch. This limits embedding work per indexing pass but initial folder enumeration still scans the requested root. Full Downloads indexing may take multiple hours and should not be described as complete after one batch.
