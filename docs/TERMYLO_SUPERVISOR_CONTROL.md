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


## Windows Run links and desktop icons (November 15, 2026)

Windows Run (Win + R), paste exactly one of:
- termylo://start: launch the Termylo tunnel. No automatic owner approval.
- termylo://stop: show local Yes/No confirmation, then shut down Termylo.
- termylo://revoke: show local Yes/No confirmation, then revoke authorization.

Exact allowlisted URIs only, with no query, fragment or shell commands.
The existing current-user protocol handler points to scripts/uri_launch.py.

Desktop shortcut files created on this Windows account:
Termylo - Start.lnk; Termylo - Stop.lnk;
Termylo - Revoke Approval.lnk. Each runs the fixed local CLI script.

### Legacy MCP bridge compatibility

An old MCP worker can have an active in-memory grant when the new supervisor
reports a closed grant. In that case Termylo Revoke fails closed: it disconnects
the old secure tunnel rather than falsely claiming success. This cuts remote
access but leaves older local PowerShell windows open. Once the updated MCP
worker is activated, Revoke cancels the supervisor grant while leaving the
tunnel online. Stop shuts down the tunnel.

### Existing orphaned PowerShell windows

A read-only audit found six native-console PowerShell processes:
two owned by the current MCP worker, four attached to a dead old parent.
One of the orphaned shells has Axtario, Node.js and Chrome children, and
MUST NOT be killed blindly. The three remaining old shells have only their
console hosts, but may contain manually typed shell state; no cleanup was
performed. The new Job Object ownership prevents the same leak for shells
spawned after activation, not the older orphaned shells.

Windows autostart is still disabled. Clicking Start does not auto-click
or bypass the owner authorization prompt.

## Windows Terminal extra-window fix (v0.5.0a6)

On Windows systems configured to use Windows Terminal as their default
console, launching the independent broker with python.exe and
DETACHED_PROCESS still created a separate visible Windows Terminal window.
Repeated development starts left three broker windows open, despite having
only two native project PowerShell consoles. The broker is now launched
with pythonw.exe + CREATE_NO_WINDOW and does not add a visible terminal
when started. An isolated local broker startup test confirmed the number
of OpenConsole.exe hosts did not increase. Existing visible broker windows
must be closed once; this change cannot close old Windows Terminal windows
retroactively. Any old Termylo console hosting Axtario must be left running
or its visible window hidden without terminating Axtario.

The first activation of the new MCP worker still requires a new physical
Windows approval because its earlier in-process grant cannot be migrated
silently. The new worker reconnects to the separate supervisor on future
restarts.