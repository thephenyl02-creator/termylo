# Termylo persistent approval and local exit controls

## Commands

Run from PowerShell after Termylo has been installed:
- .\.venv\Scripts\termylo.exe start — launch the secure local MCP tunnel.
  Does NOT grant remote PowerShell access.
- .\.venv\Scripts\termylo.exe status — inspect tunnel and approval state.
- .\.venv\Scripts\termylo.exe revoke — end the current four-hour approval
  early; project windows close and new commands require owner approval.
- .\.venv\Scripts\termylo.exe stop — revoke approval and shut down the
  Termylo tunnel and independent supervisor.
- .\.venv\Scripts\termylo.exe restart — restart only the MCP tunnel using
  the independent supervisor. The original lease deadline is unchanged.
  Shell windows may be recreated; unsaved shell variables may be lost.

For convenience, scripts/Start-Termylo.cmd, scripts/Stop-Termylo.cmd, and
scripts/Revoke-Termylo.cmd can be double-clicked locally. Windows Run can
launch their full paths. No startup task or desktop shortcut is installed yet.

## Security and persistence

One approval remains active for its original requested duration (default
four hours, zero idle timeout). Its origin and expiry live exclusively
inside a separate local supervisor process. Restarting the MCP worker
does not grant, copy, extend or renew the lease. A stopped supervisor
or Windows reboot discards its in-memory grant and requires fresh
physical approval. Manual revocation is immediate and applies across
all project terminals. Each MCP worker owns its project-specific native
PowerShell windows in Windows Job Objects, so an unexpectedly stopped
worker cannot leave those old shells running untracked.

The broker accepts only a fixed set of control operations over a local
Windows named pipe, with challenge-response authentication. The
authentication key is DPAPI-encrypted to the current Windows account,
not transmitted via remote tool results. A compromised Windows account
still requires normal OS protections; this does not defend against an
attacker already able to execute arbitrary code as that account.

The secure tunnel launcher starts the independent supervisor *before*
the MCP worker. There is no HTTP listener, no model download, and no
Windows login startup by default.

## Future startup choices (NOT enabled)

A desktop shortcut is the recommended next convenience feature: one click
runs Start-Termylo.cmd. Optionally, a per-user Windows Task Scheduler task
can launch Termylo on sign-in. That must remain explicit opt-in, and
must never silently grant a PowerShell approval or refresh a prior lease.

## Activation

Version 0.5.0a4 must be installed into the Python environment and the
existing MCP service restarted once to activate the new architecture.
The prior in-process grant cannot be migrated to the new supervisor
without bypassing the original owner approval. Therefore the first
activation requires one fresh physical approval; *subsequent* worker
restarts reuse the remaining approval time.


## Explicitly replace a running four-hour approval with six hours

From ChatGPT, use the MCP command
replace_universal_native_approval(duration_hours=6, project_id="termylo")
when the owner specifically requests "restart the session for six hours".
It deliberately differs from the CLI command termylo restart, which
restarts the MCP service and MUST preserve the current approval expiry.

Replacement first validates the requested duration and working directory,
cancels pending command jobs, stops managed processes and context searches,
revokes the previous universal approval and closes ALL old project PowerShell
windows. It then opens a fresh PowerShell for the selected project and
requests ONE NEW local Windows approval for six hours. Other projects can
reopen their windows under that one new grant. No old clock is extended.

This is development-branch code. It is not yet running in the active bridge.

## Verification before activation
Development tests: 148 existing Termylo tests passed (three batches); 13 supervisor/control tests passed; 46 Context Engine tests passed, one symlink test skipped. This includes 4h-to-6h replacement, closing old windows, unchanged service-restart deadline, cross-process supervisor reconnection, and cancellation of old pending jobs. No actual 6h approval was requested on the owner's live service. Initial activation still requires one new Windows approval because the pre-supervisor grant cannot be transferred safely.
