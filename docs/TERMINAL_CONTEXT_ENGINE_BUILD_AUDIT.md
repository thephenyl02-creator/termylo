# Terminal Context Engine — build and test audit

Date: 2026-11-14 / 2026-11-15 local
Branch: feature/terminal-context-engine
Build: Termylo 0.5.0a1 (development; no installation or activation)

## What was built

- Optional one-model multimodal content-search adapter using the upstream DigUp
  search-service JSON-lines protocol. No secondary BGE/CLIP models or voice/UI.
- Six MCP commands: context_configure, context_status, context_index,
  context_search, context_verify, context_disable.
- Explicit trusted absolute executable path, selected project folders and
  per-project upstream index directories.
- Background indexing; on search, refresh is requested at most once per
  120 seconds. No continuous filesystem watcher in this build.
- Search candidates include file name/path, size, modification time, stable-ish
  local file locator, SHA-256 (up to 64 MiB during search), excerpt, and location.
- Opaque 15-minute project-bound selection references and full SHA-256 check on
  verification. No filename re-query after selecting a result.
- Reconfigure/disable invalidates selected references. Changing approved roots
  clears the previous Termylo-owned index. Reject redirected index directories.
- Local approval is required. Live subprocesses are tied to original approval.
  No automatic downloads, installation, Windows startup or plugin publication.

## Tests

- Existing Termylo regression suite: **146 passed**, 111.31 seconds, in a
  separately executed batch.
- Terminal Context Engine suite: **27 passed, 1 skipped**, 9.23 seconds.
- Combined count across the two verified test batches: **173 passed, 1 skipped**.
- Python module compilation and PEP 621/TOML parse: passed.
- Isolated MCP stdio handshake: the six tools are exposed; unauthorized calls
  fail closed without installing or launching an external executable.
- Fake CLI full JSONL subprocess handshake, search, index, no-match, restart,
  process cleanup and lease revocation: passed.
- Identity tests: duplicate filenames, distinct file IDs/hashes, stale renamed
  files, changed content despite restored modification time, cross-project
  reference rejection, and 15-minute expiry: passed.
- Permissions: outside-root path filtering, disabled/not-installed rejection,
  folder changes and obsolete index cleanup: passed.
- SHA-256: streaming hash, mid-hash mutation detection, deferred large-file
  hash followed by full verification, and approval loss during hashing: passed.
- Process lifetime: index cancellation on disable/expiry; service termination
  on expiry without a follow-up search; all passed.

## Limits

- One Windows symlink escape test was skipped because the current Windows user
  could not create a symlink. A separate outside-root traversal test passed.
- Actual DigUp CLI beta, native libraries, model GGUF assets, and semantic
  inference are **not installed**. The protocol tests use a local fake CLI.
- PDF/PPTX/XLSX/image/audio/video search relevance, index freshness in
  practice, performance and memory use await the installation phase.
- An initial combined 120-second test command timed out because this Windows
  machine's existing 146-test batch took 111 seconds. The batches were then
  run separately to completion and both passed. The timed-out project console
  was replaced under the original active universal approval; Termylo service
  itself was not restarted.
- Search-time SHA-256 is deferred above 64 MiB; verification computes full
  SHA-256, but files with deferred hashes do not have a search-time
  cryptographic content snapshot.
- The upstream indexer's treatment of nested Windows junctions and external
  symlinks must be checked before indexing sensitive folder trees.
- This code is a development branch, NOT yet in the running MCP server.

## Next phases (NOT performed)

1. Install a pinned compatible DigUp CLI and model, with binary/asset hashes.
2. Real Windows indexing and multimodal search-quality tests.
3. Decide on installation/startup configuration.
4. Plugin packaging, security review and submission.

## Re-verification, November 15, 2026

- Reviewed the committed Termylo local source and upstream DigUp CLI source,
  including Sources/digup/main.swift and SearchService.swift.
- Confirmed the upstream index, search-service JSONL, and reload protocols.
  Found and fixed missing reload after a successful incremental index; a
  fake-CLI regression test now verifies the open search process receives reload.
- Re-ran the original tests in two safely timed batches: 64 + 82 = 146 passed.
  Re-ran the context tests: 27 passed, 1 skipped (Windows symlink privilege).
- Current adapter supports one upstream semantic model and one primary index
  for each project, without voice, a new desktop UI or a second local port.
- Upstream beta.3 documentation lists PDF, DOCX, PPTX, XLSX, photo, image,
  screenshot, audio, and video content readers. Their Windows behavior has
  NOT yet been tested on this machine.
- The search CLI and EmbeddingGemma GGUF assets remain uninstalled. The
  configured executable status checks only for the existence of a file;
  the installer must enforce executable/model integrity and protocol version.
- The index is refreshed on explicit request and when searching (120-second
  minimum between automatic attempts), not from a continuous filesystem
  watcher. This is a remaining implementation gap if near-real-time indexing
  is required.
- Selection references expire and are verified against content hash, stat,
  location and project scope. Large files defer hashing until verification.
- Real Windows end-to-end indexing, model accuracy, performance, filesystem
  reparse-point handling and signed/pinned asset verification remain release
  gates. Startup configuration and plugin submission were not attempted.
- The active Termylo service is still running its old imported code; this
  development branch was neither merged nor used to restart the service.


## Pre-install optionality and readiness build (November 15, 2026)

- Development version 0.5.0a2, branch feature/terminal-context-engine.
- Explicit opt-in: context_configure always leaves engine disabled.
  context_enable validates pinned executable and two model SHA-256 checksums,
  without downloads or starting the search engine.
- Offline read-only preflight reports missing assets, mismatched checksums,
  required bytes and disk capacity. Release-specific CLI binary SHA-256
  must be provided during the separate installation phase.
- Read-only bounded project inventory counts candidate PDFs, presentations,
  spreadsheets, images, audio, video and other files without parsing content.
- Optional metadata-only context_watch, OFF by default. Polls only after
  explicit opt-in; stops at approval expiry/disable, uses bounded scans,
  and retries changes that arrive during an existing index run.
- Search/index exclude TCE-owned configuration/index and model directories,
  including when a user selects a broad parent folder.
- No Windows CLI, model weights, desktop app, watcher or external service
  was installed or activated in the live production bridge.
- All newly introduced code should be validated against both isolated
  tests and the existing Termylo regression suite before merging.

## Final pre-install verification (November 15, 2026)

- Version: 0.5.0a2 (development branch, not installed into live bridge).
- New context-engine tests: **45 passed, 1 skipped** (Windows account
  cannot create test symlink). Includes optional activation, offline binary
  and model digest checks, dry-run inventory, bounded file watcher, watcher
  retry during an active index, project permissions and isolated MCP tools.
- Existing Termylo tests: **146 passed**, in three timed batches (64+32+50).
- Total verified: **191 passed, 1 skipped**, no failed assertions.
- Python compileall passed. No model assets, CLI binaries or search service
  were installed, downloaded or activated in the current Termylo bridge.
- Automatic file watcher is OFF by default, separate from explicit
  context_enable. Existing PowerShell approval behavior was not changed.
- Upstream index and model are still awaiting the separate installation,
  checksum/source validation, and real multimodal search acceptance tests.
