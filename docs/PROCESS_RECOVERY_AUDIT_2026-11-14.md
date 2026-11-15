# Termylo 0.4.9 — Process and recovery audit

**Date:** 2026-11-14
**Platform:** Owner's Windows computer, Python 3.12.10.
**Baseline:** local `main` commit `c246629` (process manager and SQLite journal).
**Scope:** process start/status/list/stop, project-specific routing, Windows Job Object cleanup, output capture, lease expiry, journal persistence, failure handling, and MCP compatibility. DigUp excluded.

## Results

- Full local pytest suite: **145 passed in 66.10 seconds**.
- Expanded process/recovery tests: **19 new cases** beyond the original 126-test baseline.
- Python `compileall`: passed.
- `git diff --check`: passed.
- Isolated MCP stdio handshake and newly added MCP tools: passed.
- Physical Windows PowerShell subprocesses: exercised by integration tests.
- Controller force-kill: managed PowerShell child terminated when controlling Python process was killed.
- 24 sequential short-lived managed processes: passed without startup failures.
- Global capacity of six and per-project capacity of three: enforced.
- 16 KiB output-tail truncation: verified for both stdout and stderr.
- Unicode command output: verified for stdout and stderr.
- Database persistence, concurrent recording, retention limits, and no command/output text in SQLite: verified.

## Defects found and corrected

1. **Non-ASCII stdout corruption:** Windows PowerShell used a legacy output encoding. Managed commands now explicitly configure UTF-8 before execution.
2. **Journal corruption blocking startup:** If the optional SQLite directory/database was inaccessible or invalid, the entire MCP server failed to import. Startup now fails open for journaling and reports `job_journal=unavailable`.
3. **Runtime journal corruption disrupting queries:** Previously a storage error could break historical result lookup and process status. Storage errors now degrade gracefully instead of stopping shell operations.
4. **Project filter inconsistency in in-memory history:** When journaling was disabled, `recent_jobs(project_id)` could include other projects. Filtering and ordering are now correct.
5. **Case-sensitive process list filtering:** `list_managed_processes(project_id)` now normalizes project keys consistently.

All listed defects have targeted regression tests.

## Boundaries and release gates

- **The existing live Termylo MCP process was not restarted.** New tools are present in the local source, but need an authorized service restart before they appear on the active ChatGPT connector.
- A second isolated stdio server was exercised, including authorization rejection; **an actual newly approved end-to-end ChatGPT-managed process on the restarted primary service remains to be tested**.
- Four-hour expiry was exercised through simulated/shortened lease conditions, not by waiting four real hours.
- Disconnect/reboot restoration and independent real-world performance benchmarking were not performed.
- Journal preserves metadata, **not command text or full output**. In-flight results after a restart are `outcome_unknown`, never replayed automatically.
- Termylo commands still execute with the Windows user's permissions. These changes are **not** a filesystem security sandbox.
- `%SystemDrive%/` and `tunnel-client/` were pre-existing untracked paths; they are excluded from this change.

## Deployment decision

**Locally tested; staged for restart-time activation.** Do not claim full live validation before restarting the MCP bridge and checking the five new tool calls under the owner's approved session. Do not disrupt the current four-hour lease without explicit authorization. No DigUp changes.
