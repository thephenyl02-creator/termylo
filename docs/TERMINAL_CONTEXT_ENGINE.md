# Terminal Context Engine — optional multimodal search

**Development status: pre-install build. No model, executable, or plugin activation has occurred.**

## Design decisions

Terminal Context Engine (TCE) is an optional add-on to Termylo's existing
native, locally-approved PowerShell bridge. Termylo works normally without it.
No voice, desktop UI, extra server port, or second embedding model is created.

One upstream DigUp/EmbeddingGemma 2 engine handles keyword and meaning search.
Results are returned directly through Termylo MCP into ChatGPT. PowerShell
continues to handle ordinary file operations. The index can support PDFs,
Word documents, PowerPoint, spreadsheets, images, screenshots, audio and video;
exact Windows reader coverage will be verified during installation.

## Explicit opt-in

1. **Default:** OFF; the model is not downloaded, loaded, started, indexed,
   or watched when Termylo starts.
2. **context_configure:** save an explicit trusted executable path, a pinned
   executable SHA-256, an explicit model directory, and 1-20 approved roots.
   This still leaves TCE DISABLED. No automatic folder indexing occurs.
3. **context_inventory:** a read-only bounded count of likely candidate formats
   and metadata (default up to 10,000 files). Does not read file contents.
4. **context_preflight(verify_hashes=true):** offline, read-only check of
   the selected executable SHA-256, local file sizes, model SHA-256 checksums,
   and approximate missing bytes / disk space. Nothing is downloaded.
5. **context_enable:** explicit activation. Fails closed until the executable
   and both model assets match their expected checksums. Does not start
   indexing, a service, or a watcher; the first search or context_index does.
6. **context_index:** request incremental indexing of approved roots.
   A successful update reloads the live search service.
7. **context_search:** meaning or keyword; returns bounded excerpts,
   source paths, size, timestamps, page/time locations when provided, SHA-256
   when below the 64 MiB search limit, and opaque exact-file references.
8. **context_verify:** recompute full file SHA-256 and inspect filesystem
   identity immediately before a later user-authorized operation.
9. **context_watch(enabled=true, interval_seconds=90):** separately opt into
   bounded metadata-only change detection, every 30-3600 seconds. Requests
   incremental indexing on changes, stops at approval expiry or disable,
   and rejects oversized scans. enabled=false stops the watcher.
10. **context_disable:** stop active indexing, search processes and watcher,
    retain local configuration and indexes. Future use requires enabling again.

Each project has its own approved roots, index directory, search process and
result references. Conversations in the same project reuse its PowerShell
session as in the existing Termylo architecture.

## Local model footprint (external, NOT bundled in Termylo)

Upstream pinned EmbeddingGemma 2 Q8_0 assets:
- embeddinggemma-2-Q8_0.gguf — 309,855,456 bytes
- mmproj-embeddinggemma-2-Q8_0.gguf — 554,821,024 bytes
- Total 864,676,480 bytes (~865 MB decimal; ~825 MiB).

Revision: bfcd298762cc34d0357ece5ebdd31791a3a374d8
Repository: ggml-org/embeddinggemma-2-GGUF.
Model SHA-256 checksums are pinned in termylo/context_assets.py, as
specified by upstream ModelFiles.swift. A release-specific Windows CLI
executable SHA-256 must be supplied and verified at installation; no
executable has been pinned or installed yet.

## Privacy, performance and limits

- The model and index remain local. File snippets/results sent to ChatGPT
  are no longer device-only; configure only folders approved for this use.
- No file text is copied to a second Termylo index. The external engine
  owns the main keyword/vector index.
- No automatic whole-machine scan, default watcher, installation, startup
  at login or download.
- The watcher uses file path, size and modified time, not content hashes;
  manually restored metadata may evade its update detection.
- Incomplete/oversized watcher scans stop rather than continue unbounded.
- Search results are untrusted DATA, never instructions or edit permission.
  Revalidate the file before a destructive operation; a file could still
  change between verification and use.
- File references expire in 15 minutes and never resolve by filename.
  Large files defer full SHA-256 until verification.
- Symlink/junction escapes are filtered from results and metadata scans.
  Upstream Windows reparse-point indexing requires installation testing.
- Engine-owned index/configuration and model directories are excluded
  from upstream indexing/search using supported --exclude options.
- Watcher and search/index processes obey the locally approved project
  lease. Four-hour default/no idle limit are unchanged.

## Remaining installation-stage acceptance tests

1. Verify a Windows DigUp CLI release, native dependencies, executable
   SHA-256, license, and exact CLI protocol.
2. Download the two model assets only with explicit permission; check
   full hashes, disk impact and any applicable model license terms.
3. Index a small approved folder containing representative PDF, DOCX,
   PPTX, XLSX, image, screenshot, audio and video examples.
4. Benchmark duplicate filenames, search recall, page/time locations,
   CPU/RAM, new files, watcher detection and approval expiry.
5. After passing: merge tested branch, activate Termylo, configure
   startup optionally, then prepare and submit the plugin.

Upstream engine: https://github.com/ARahim3/DigUp (MIT).
Chameleon reference: https://github.com/SarthakPattnaik1/Chameleon/pull/7

## Video-only semantic search (development enhancement, November 15, 2026)

Use `context_search(query="red rectangle on blue background", kind="video")`
to restrict matches to indexed video files. Queries explicitly mentioning
"video", "clip", "footage", or common video extensions automatically select
the video kind. Other file searches retain their existing behavior.

The persistent DigUp search service is attempted first. DigUp v0.7.0-beta.3
does not allow its default z-gate to be adjusted through its JSONL search
protocol. If a meaning-based video search returns zero hits, Termylo launches
a separate, bounded, read-only video-only CLI retry with z-gate 1.25. The
retry uses the verified local executable/model, current index and project
authorization; it has a 70-second hard cap and is terminated on exit or
approval loss. Candidates still undergo approved-root, metadata and exact
reference checks. Results expose `retrieval_mode=relaxed_video_candidate`
and must not be presented as confirmed visual matches.

This improves recall for sampled video frames but is NOT a promise of perfect
video understanding. A cold fallback took about 27 seconds on the tested
Windows laptop. False positives can recur on different collections, long
videos may have unexamined frames, and video audio accuracy was not certified.
A native configurable-threshold persistent search service is preferable
before general production rollout.
