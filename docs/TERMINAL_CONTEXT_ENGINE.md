# Termylo Context Engine (TCE)

**Status:** Native TCE source is under `tce-native/` and belongs to the Termylo repository. Its compiled executable, dependencies and model integration are internal to Termylo, not a separate user-installed application.

## Architecture

Termylo MCP authorizes roots and actions. Its TCE adapter handles indexing, search, result verification and lifecycle; it starts one persistent native `tce.exe` search-service process and bounded index operations. Source is compiled from the TCE fork. There is no call to the original external binary and no second-process video search fallback.

Search modalities: text, PDF, Office documents, images, audio and video sampled frames. Video semantic search uses `zgate=1.25` within the warm persistent service. Accuracy is not perfect; results, including timestamps, are candidates for verification.

## Security and defaults

- No automatic indexing, watcher, model load or folder access upon normal Termylo startup.
- User-approved roots, active approval lease, metadata and hash checks protect file operations.
- TCE is enabled and disabled through explicit Termylo MCP tools.
- Model weights download separately on opt-in; archive and native files are pinned and verified.
- Termylo manages the internal native runtime and does not register any separate desktop application.

See [installation and verification](TERMINAL_CONTEXT_ENGINE_INSTALLATION.md) and [native migration audit](TCE_NATIVE_MIGRATION.md).
Original DigUp MIT license and copyrights remain preserved as required; they are source attribution only.
