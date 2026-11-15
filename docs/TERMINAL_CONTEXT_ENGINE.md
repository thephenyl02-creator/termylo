# Terminal Context Engine (TCE) — build-stage specification

**Status: source built; real DigUp installation and on-device semantic inference NOT completed.**
This is an optional Termylo capability, not a replacement for native PowerShell.

## Scope

- Keep ChatGPT -> Termylo -> PowerShell for ordinary commands, files and Git.
- Add one optional local DigUp/EmbeddingGemma 2 engine, controlled by Termylo MCP tools.
- Index user-selected folders into the upstream engine's existing local index.
- Search text, PDFs, DOCX, PPTX, XLSX, images, screenshots, audio and video
  according to the upstream Windows CLI's supported readers.
- Return file path/name, modification timestamp, size, filesystem locator,
  SHA-256 of contents when within the bounded search-hash threshold,
  content excerpt, page or media timestamp if provided by the engine.
- Verify the exact selected file before file actions, with a full SHA-256 and
  filesystem identity check.
- No voice, BGE/CLIP duplicate models, separate desktop UI or second web port.
- No automatic downloads, installation, startup at login or plugin publication.

## MCP controls

- context_status(project_id) — local configuration/index status. Requires approval.
- context_configure(executable, roots, project_id, models_dir, enabled) —
  explicitly select an absolute trusted CLI executable and approved directories.
  This saves local configuration but DOES NOT install or download the model.
- context_index(project_id) — trigger upstream incremental indexing as a
  lease-bound background subprocess. Repeating while indexing is a no-op.
- context_search(query, project_id, meaning, limit) — search approved
  content through the upstream search-service JSON-lines protocol.
- context_verify(reference, project_id) — verify selected result's exact
  path, filesystem identity and full SHA-256. Never chooses by filename.
- context_disable(project_id) — stop subprocesses, retain local index.

## Safety and privacy

- Requires an existing locally approved project PowerShell session. Never
  self-approves, extends authorization or opens an unapproved terminal.
  Search and indexing processes stop when the grant expires.
- Each stable project ID has separate roots, index directory and service.
  File references cannot cross project boundaries.
- Paths are canonicalized and checked against current approved directories
  at result time. Symlinks outside allowed roots are rejected.
- Search is read-only; a verified result is not authorization for file edits.
- SHA-256 on search is deferred for files above 64 MiB; the full hash is
  computed on verification. A deferred search-time digest cannot establish
  historical content if filesystem metadata was deliberately falsified.
- Result references expire after 15 minutes or bridge restart; do not
  re-query by filename to recover a reference.
- TCE does not maintain another content database. The upstream index stores
  vectors/keyword evidence locally. Snippets returned to ChatGPT leave device.
- Executable selection is explicit. Never run an arbitrary DigUp on PATH.
- Symlink/junction behavior of upstream indexing must be checked before
  indexing sensitive directories; result filtering alone is not enough.

## Installation phase (later; NOT executed in this build)

1. Pin/verify a compatible DigUp Windows CLI (upstream currently advertises
   v0.7.0-beta.3; Chameleon originally pinned v0.7.0-beta.2).
2. Validate native libraries and index/search-service JSON-lines protocol.
3. Install and verify EmbeddingGemma 2 model files (~865 MB).
4. Explicitly select folders and index them.
5. Benchmark PDF, PPTX, XLSX, images, audio, videos; duplicate filenames,
   modified/moved files, no-match cases, CPU/RAM/battery and freshness.
6. Separately plan startup behavior and plugin submission.

Upstream search engine: https://github.com/ARahim3/DigUp (MIT).
Chameleon integration reference: https://github.com/SarthakPattnaik1/Chameleon/pull/7
\nIndex refresh: a successful indexing run reloads any active search process.\n