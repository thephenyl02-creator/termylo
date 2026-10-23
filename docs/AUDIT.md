# Termylo v0.2 line-by-line verification audit

This audit reviews each tracked source, installation, test and documentation file. It distinguishes **source review**, **simulations**, **real Windows headless subprocess tests**, and **unverified owner-device/ChatGPT connectivity**.

## Scope and method

- Baseline: the exact merged Termylo v0.2 on GitHub `main` (not previously downloadable ZIP files).
- Each function, top-level constant, executable entry point, subprocess boundary, exception path and external dependency was reviewed.
- Added regression tests for failures not previously covered; exercised the Windows and Linux CI matrix.
- External claim check: OpenAI's Secure MCP Tunnel documentation confirms outbound-only transport, Platform organization access, required tunnel IDs/keys, and workspace-specific permissions. **It does not establish that your ChatGPT Plus plan includes this at no additional cost.**
- Limitations: no physical Windows GUI automation, no real ChatGPT tool invocation on the owner's machine, no independent red-team audit.

## File-by-file checks

| File | Reviewed control surface | Result / caveat |
|---|---|---|
| `termylo/__init__.py` | package metadata and version | Clean. |
| `termylo/server.py` | MCP FastMCP registration, four tool schemas, stdio entry point | Real client/server stdio handshake and discovery tested. No HTTP listener in this module. |
| `termylo/jobs.py` | job IDs, validation, one-command scheduling, cancellation, retention, worker exceptions and result types | Fixed unrecoverable busy state when thread startup fails; validated worker return type and terminal status. Added regression tests. |
| `termylo/runner.py` | input validation, elevation refusal, approval, cancellation checks, environment allowlist, command encoding, PowerShell binary selection, subprocess lifecycle, bounded stream capture, exit code, timeout and CLIXML | Real Windows CI exercises execution, error code, Unicode, large output and timeout. Fixed PATH-selected executable to system PowerShell. Still **not** a sandbox; cancellation best effort. |
| `termylo/approval.py` | Windows Tk dialog, displayed command, Approve Once, Deny, timeout, cancel, close and fail-closed errors | Fake-GUI tests now cover approval, denial, timeout and cancellation. Physical on-screen Windows GUI **not** tested. |
| `termylo/doctor.py` | diagnostic imports, Windows PowerShell path, workdir and platform | No command is executed. Importing Tk does not prove a visible interactive desktop. |
| `scripts/setup.ps1` | Python venv creation, editable install, diagnostics, exit status | Corrected missing nonzero native exit-code handling; checked PowerShell syntax in Windows CI; full setup exercised on Windows Python 3.12 runner. |
| `scripts/simulate.py` | simulated AI-request → synthetic approval → synthetic command result | Passes without any OS modifications; not evidence that ChatGPT or the Windows GUI connected. |
| `scripts/manual_smoke.py` | explicit owner-triggered single real GUI approval and harmless PowerShell output | Compiled in CI. Requires owner to run it on an interactive laptop. Not auto-executed in GitHub Actions. |
| `tests/test_runner.py` | malformed commands, elevated denial, canceled/denied execution, missing executable/dir, environment, real Windows process tests, CLIXML | Covered; Windows tests genuinely launch system PowerShell but deliberately mock human approval. |
| `tests/test_jobs.py` | approval-to-result mock, denial, cancellation, busy lock, errors, retention | Covered simulated job lifecycle. |
| `tests/test_mcp.py` | stdio protocol initialization, tool discovery, safe tool call results | Genuine MCP subprocess handshake; doesn't submit an authorized real command. |
| `tests/test_audit.py` | job startup failure, invalid worker responses, GUI callback flows, error/progress filtering | Added for this audit. Fake Tk UI; not a physical on-screen test. |
| `.github/workflows/tests.yml` | Python 3.12/3.13 × Windows/Ubuntu; installation, bytecode, pytest coverage, simulation, doctor, setup PowerShell parser | All 4 matrix targets must pass on final commit before merge. This is shared CI, not the owner's computer. |
| `pyproject.toml` | Python requirement, package discovery, entrypoints, MCP dependency | Installation confirmed in CI. Broad `mcp>=1.28,<2` permits future dependency changes; builds are not hash-locked. |
| `.gitignore` | caches, environment files and build artifacts | Excludes common local secrets/artifacts; does not replace secrets scanning. |
| `README.md` | capability, installation, user approval, privacy, cost and secure tunnel instructions | Updated to distinguish proven code behavior from unverified real desktop/ChatGPT connectivity. |

## Defects found and fixed

1. **Unrecoverable busy state:** `JobManager.submit` did not handle thread startup failures. Now drops the failed job and returns a recoverable error.
2. **Unexpected worker result could crash caller or wedge the job:** Worker responses are now checked for a dict and terminal status; invalid values become a sanitized error.
3. **Windows installer false positive:** PowerShell's native program failures were not checked through `$LASTEXITCODE`. Setup now checks creation/install/diagnostic failures and required prerequisites.
4. **Executable path hijack:** PowerShell was discovered by `PATH`; now resolved from the Windows system directory. `doctor` uses the same check.
5. **Missing approval regression coverage:** Added fake-GUI test paths for approve/deny/timeout/cancel plus an explicit interactive Windows test script.
6. **Privacy and disconnect disclosures:** Clarified that ChatGPT/tunnel handle command text and returned output and that already-running detached children may survive abrupt disconnect.

## Test evidence requirements

- Local Python unit and simulated tests: PASS in isolated Linux environment; Windows-only tests are correctly skipped there.
- GitHub Actions: Windows and Ubuntu jobs at Python 3.12 and 3.13 exercise real MCP stdio handshake, mock approval lifecycle and genuine Windows PowerShell execution.
- Windows PowerShell setup script is checked syntactically; Windows 3.12 runner executes full setup.
- Keep the PR unmerged if any final SHA's check matrix reports a failure; review the individual logs.

## Residual risks / NOT verified

- **Interactive Tk popup on the owner's Windows laptop** is unverified until running `scripts/manual_smoke.py` and clicking Approve Once.
- **Normal ChatGPT → OpenAI-hosted secure tunnel → Windows Termylo** is unverified. Account-specific custom write-capable MCP permissions, tunnel access and billing remain unverified.
- Approved PowerShell commands are arbitrary code execution within the user's permissions. No directory sandbox, network restriction, or guaranteed descendant cleanup exists. Approval is the trust boundary.
- Killing the tunnel does not guarantee cancellation of commands already running.
- Public repository/old ZIPs may differ from audited source; use the latest GitHub `main`, not an older artifact.
- No external penetration test, package supply-chain audit, installer code-signing, or reproducible dependency lock was completed.
- No claim of 100% coverage, zero vulnerabilities, unlimited ChatGPT actions or zero Platform charges is warranted.

## Owner-device acceptance gate

1. Install from the audited GitHub `main` branch in non-elevated Windows PowerShell; confirm `termylo-doctor` prerequisite flags.
2. Run `scripts/manual_smoke.py`, approve its harmless `Write-Output` command, and verify its expected output/exit code.
3. Confirm permitted tunnel access/costs before using credentials. Start tunnel-client with Termylo stdio.
4. From normal ChatGPT, call `termylo_status`, request an innocuous `Write-Output`, approve locally, and retrieve its job output.
5. Test Deny and Cancel from that actual connection, then disconnect and verify no new commands are accepted.

Only completion of these acceptance gates supports the statement **fully verified end-to-end on the owner's device and account**.
