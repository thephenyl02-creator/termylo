> **Update: native migration complete in source and package.**
> The sections below record earlier migration decisions and initial blockers.
> They are historical, not the current runtime status.
>
> The modified TCE source now builds on Windows x64 with Swift 6.3.3.
> Its optimized `tce.exe` has been built and tested with real multimodal indexes.
> The Termylo adapter uses `TCE_MODELS` and the persistent TCE search
> service; its old video subprocess fallback has been removed. The
> Termylo-owned runtime ZIP is signed by pinned SHA-256 integrity metadata,
> installed to the internal ContextEngine directory, and does not include the
> upstream executable. Both command-line and video retrieval have been verified.
> 112 native Swift tests passed; 230 Python tests passed, with one Windows
> symlink permission skip. The historical statements below about missing
> Swift builds or the old bridge no longer apply to the current source.
># TCE native-source migration and parity gate

**Date:** November 15, 2026
**Branch:** feature/tce-native-full-migration
**Decision:** TCE owns the entire native search implementation. DigUp must not
remain an executable fallback, separate install, or required runtime once
parity is verified. Original copyright and license attribution remain.

## Source baseline
- Original: Abdur Rahim/DigUp, MIT license, v0.7.0-beta.3,
  commit 0943225c2690c0631c01041e5dcb77c53e04395e.
- New source: tce-native/, package TCE, library TCEKit,
  CLI executable tce, TCEApp shell source, test modules renamed.
- 231 upstream source/assets/config files copied.
- 134 text files changed by a deterministic symbol rename.
- Initial source-to-source parity check: 231/231 accounted for,
  zero unexplained content differences (new README changed afterwards).
- Original LICENSE and third-party license notices retained.

**This does not certify executable behavior or model-vector parity.**

## Feature comparison

| Capability | Existing Python TCE | Native TCE source |
|---|---|---|
| PDF/image/audio/video/Office indexing | External executable | Complete readers/indexer source |
| Multimodal embeddings/semantic matching | External executable | TCEKit + LlamaRuntime source |
| Video relevance thresholds | Slow separate CLI retry | SearchService/Searcher source |
| Incremental indexing | External binary plus Python watcher | Native index-service/crawler |
| Code-specific search/index | Not fully exposed | Native source available |
| Estimate/speed/evaluation CLI | Not fully exposed | Original CLI implementation copied |
| Video/audio timestamps and previews | Partial API | Native render/search source |
| Model download and query worker | Package bridge | Native downloader and worker source |
| Shell GUI and notifications | No equivalent in Python API | App/shell sources copied |
| File ownership and approval checks | Hardened Python wrapper | Keep TCE wrapper as orchestration |

**Native source available is not equivalent to runtime parity.** The
original CLI exposed estimate, index, search, status, speed, eval,
index-service, worker, search-service and download-model. The TCE fork
must compile and pass these commands on the same fixtures.

## Release gates — all mandatory

1. Build native TCE locally with Swift 6.4, Windows C++ tools and pinned
   vendor dependencies, generating a genuine `tce.exe` from TCE sources.
2. Run native Swift test suite and reference-vector tests; preserve
   embedding/index compatibility and the same model output.
3. Verify command/interface equivalence for estimate, index, search,
   status, speed, eval, worker, index-service, search-service, download-model.
4. Re-run the existing mixed-media audit (20 real files), labeled video
   positives/negatives, 25 relevance queries, 100 request repetitions,
   incremental reindex, time markers, security and concurrent load.
5. Change TCE installer and Python bridge to use only verified native
   `tce.exe`, with no legacy executable fallback; test user approval,
   on-demand lifecycle and per-project isolation.
6. Replace upstream update feeds/signing and branding with owned TCE
   distribution; verify no path can fetch an original upstream installer.
7. Remove the legacy DigUp executable and unneeded separate cache only
   from known Termylo-owned paths after a successful migration and backup.
8. Re-run full Python and native regression, verify GitHub/local sync,
   and deploy via a non-disruptive service transition.

## Current blocker

On this laptop, Swift was not installed. Its official Windows installer
is approximately 2,001 MB. The Winget installation attempt stalled and
was canceled; the orphaned process was explicitly terminated. No native
TCE binary was built. Native vendor dependencies and app build toolchains
must also be prepared and verified. No legacy binary has been deleted.

This migration source is intentionally on a separate development branch,
not on production main. The working Termylo supervisor/approved terminal
and Context Engine installation were not restarted or replaced.

## Validation completed in this session

- Verified source-copy parity before integration metadata changes:
  231/231 files, no unexplained differences after deterministic renaming.
- Static TCE source checks: 5 passed (renamed package/module/CLI,
  required commands, modality readers, attribution, disabled updater).
- Python regression: 192 passed, 1 Windows symlink skip; independent
  recovery/project-state tests: 32 passed. Combined: 224 passed, 1 skipped.
- No Swift native binary was built or executed. Full runtime parity
  remains **unverified**. The existing 20-file media index was not removed.
- The existing Termylo Context Engine is still the old integration until
  an explicitly tested source-built TCE runtime replaces it.

## Important cutover details

The Python bridge and installer still refer to the original executable
and the DIGUP_MODELS environment variable. A later atomic cutover must
switch them to the source-built `tce.exe`, the `TCE_MODELS` variable,
and TCE-owned directories without silently discarding existing indexes.
No fallback to the old binary is permitted after successful cutover.
The 4-hour universal terminal grant and other project consoles must
survive any deployment. Upstream release feeds are disabled in the new
TCE source; new update signing is needed before enabling them.
