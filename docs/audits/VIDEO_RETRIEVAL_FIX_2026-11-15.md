# Video retrieval patch verification — November 15, 2026

**Scope:** Termylo Context Engine's DigUp v0.7.0-beta.3 video search,
not a replacement model, not a full-video comprehension benchmark.
**Branch:** feature/video-search-relevance (from main 2d30bed).
**Status:** Candidate retrieval corrected on controlled tests; quality
and latency limitations remain.

## Root cause

DigUp 0.7.0-beta.3 has a fixed 2.0 semantic z-gate in its persistent
SearchService JSONL path. The standalone CLI supports --zgate. Termylo
previously sent no kind filter or alternate video path, so two indexed
MP4 files were invisible under a strict video query. Source was checked
against the matching upstream release.

## Change

- `context_search` accepts an optional allowlisted `kind` and recognizes
  explicit natural-language video intent.
- Fast search passes `kinds:["video"]` to the resident search service.
- On a zero-hit semantic video search, a locally verified video-only
  command retries with `--zgate 1.25`, bounded by 70 seconds, current
  approval and the same local project index.
- The fallback process is owned and cleaned up through Termylo's Windows
  job handling, with approved-root and exact-reference checks preserved.
- Responses label fallback hits `relaxed_video_candidate`; no claim of
  verified scene understanding is made.

## Evidence

- Three synthetic 5-second MP4 clips of clearly different colored
  rectangles were generated with local FFmpeg; all indexed successfully
  in a private 3-file collection (3 vectors/3 segments). Original user
  media and production indexes were not modified.
- Real Termylo API test: "red rectangle against blue background"
  returned the correct `clip_01.mp4`, top 1, in 26.59 seconds on the
  initial 1.0 threshold.
- Negative "horse galloping through a snow-covered valley" incorrectly
  returned `clip_03.mp4` at 1.0; measured z=1.088.
- Positive red and green matches measured z=1.407 and z=1.414.
- After raising the gate to 1.25: positive returned `clip_01.mp4`
  in 27.61 seconds; negative returned zero in 27.99 seconds.
- Unit tests cover kind inference, allowlist, project-root filtering,
  fallback selection, CLI arguments, cleanup and revocation rejection.
- Fresh full suite: **219 passed, one skipped** (Windows symlink privilege).
  Python compilation passed.

## Unresolved release gates

1. The fallback is 27 seconds in these live runs, not interactive-speed.
   Improve upstream persistent SearchService to accept a per-request
   z-gate before calling video search fast.
2. The gate is an experimental calibration on only three synthetic clips
   and one negative query. Larger labeled real-world video benchmarks,
   variable clip lengths, motion, speech and mixed media are required.
3. Frame sampling does not mean every frame or spoken sentence was
   understood. Verify timestamp accuracy and sound coverage separately.
4. A dedicated high-load, crash/restart and cross-project privacy review
   is still required for production claims.
5. Preserve user approval and other project terminals during deployment.

Private test videos, model logs and per-file paths remain only under
%LOCALAPPDATA%/Termylo/Audits/video-retrieval-2026-11-15/.

## Final isolated MCP validation

After the patch was committed, an independently initialized MCP client
enumerated all 31 tools and confirmed `context_search.kind` appears in
the tool input schema. Its disposable video project reused the existing
local owner grant, completed setup/preflight/enable, finished indexing,
and searched by visual description. `clip_01.mp4` ranked first; the
end-to-end MCP search took 28.78 seconds. The test disabled context and
closed only its own temporary native terminal.

A separate API run on the previous mixed-media sample retrieved
`real_mp4_02.mp4` as the only video candidate at top rank (27.98 s).
This validates file retrieval, not independently labeled scene meaning.

The fixed code is published on GitHub main, but the existing shared
MCP worker has NOT been restarted: another active `default` project
terminal would risk losing in-memory PowerShell state. Live activation
therefore remains pending a safe, explicitly authorized service restart
that preserves the supervisor approval deadline.
