# Termylo

**Your personal Windows PowerShell bridge for MCP clients.** No paid automation service, remote desktop, dashboard, browser, or subscription. Runs only while you start its MCP connection.

Termylo's workflow: **AI requests a command → you approve it in a Windows popup → Termylo runs it on your laptop → output and exit code return to the AI.** The server doesn't listen on a network port. Normal execution requires approval for each command; a separate opt-in visible session supports short-lived window-level approval.

## Tools

| Tool | What it does |
|---|---|
| `termylo_status` | Check whether local MCP agent responds. |
| `execute_powershell(command, timeout_seconds)` | Submit **one** command, returning a job ID immediately. |
| `powershell_result(job_id)` | Fetch result: stdout, stderr, exit code, truncation indicators. |
| `cancel_powershell(job_id)` | Request cancellation and best-effort termination of PowerShell process tree. |
| `open_visible_session` | Ask the laptop owner to grant time-limited approval for one visible window. |
| `visible_session_status` | Check approval state, lifetime and active session ID. |
| `execute_visible_powershell(session_id, command, timeout_seconds)` | Run command in a locally approved window **without individual popup**. |
| `close_visible_session(session_id)` | Close window and revoke session approval. |
| `open_native_session` | Request local approval, then open a real native Windows PowerShell console. |
| `native_session_status` | Inspect the native console state and its session ID. |
| `execute_native_powershell(session_id, command, timeout_seconds)` | Run commands in the same PowerShell process, preserving variables and working directory. |
| `close_native_session(session_id)` | Revoke the session and close the console. |

The two-step request/result process prevents MCP timeouts while you read the approval window. Only one command can be active; finished results expire after 15 minutes.

## Native interactive PowerShell console (v0.4.0)

Termylo v0.4 adds the functionality missing from the v0.3 Tkinter viewer:

- **This is a real native powershell.exe window**, not a Python output viewer.
- You can **type PowerShell commands yourself** inside the visible console and press Enter.
- ChatGPT can execute requested commands in **the same PowerShell process**, observe their structured output through the local named pipe, and reuse shell variables and the working directory.
- Clicking **APPROVE SESSION** on the **separate one-time consent popup** opens the native console. The popup then closes. No individual popup is needed for subsequent commands in that approved session.
- Close the PowerShell window, call close_native_session, or let the lease expire to revoke. The lease is **10 minutes without MCP commands** or **30 minutes total**.
- The native console contains a deliberately minimal custom single-line prompt (it does not offer full PSReadLine completion, multiline editing, or equivalent terminal history). Basic typing, Enter, Backspace and Escape are implemented. While manually entering a line, incoming MCP commands wait until the line is submitted.
- Native commands have the **same access as your Windows account**. They are not sandboxed. Revoke when not actively using Termylo.
- On cancellation or command timeout, Termylo may close the entire native console so a background command cannot continue outside the approved session.
- The command/control channel is a randomly named **local Windows named pipe**. It does not open a listening HTTP/TCP port or require a second LLM/API service.
- CI covers native authorization and session lifecycle with mock processes; the actual owner-device physical approval and typing must be verified after deployment.

The original execute_powershell per-command approval mode and the v0.3 open_visible_session viewer mode remain available for compatibility. Native session mode is preferred when you need an editable terminal.

## Optional visible session (v0.3.0)

**Default behavior has not changed:** `execute_powershell` requires local approval **for every command**.

An optional **visible session** is designed for the user who explicitly wants to approve once for a window. This is substantially broader permission than approving one command; while active, ChatGPT can submit further PowerShell commands **without another local popup**, subject to its tool permissions. Do not approve a session while untrusted instructions are influencing the chat.

1. In ChatGPT, explicitly request `open_visible_session`. A separate Termylo window opens on Windows.
2. Read the full permission warning and click **APPROVE SESSION** (or DENY). Call `visible_session_status` to confirm that the session is active and obtain its `session_id`.
3. Only for your intended tasks, call `execute_visible_powershell(session_id, command)` and fetch the output with `powershell_result(job_id)`. The window displays commands and results.
4. **Close that window or call `close_visible_session(session_id)` to revoke.** Approval expires automatically after **10 minutes without commands** or **30 minutes total**, whichever comes first. Expiration/cancellation stops active commands on a best-effort basis.

**Implementation boundary:** The persistent window is a terminal-style viewer, not an interactive PowerShell REPL. Each command still runs in a separate PowerShell process, and shell variables and current directory changes do **not** persist between commands. The session approval belongs to that single GUI window, not to every Termylo client or future window.

The new visible-session flow is covered by simulated lifecycle, revocation and timeout tests. It is **not** physically verified until the owner pulls v0.3.0, restarts the tunnel and approves the new visible GUI. The previously verified per-command mode remains available throughout.

## Security boundaries

**Not a sandbox.** An approved PowerShell command runs with your Windows account privileges. It can access or change any files that the user can, launch programs, or contact remote services. Do not approve commands suggested by untrusted websites, repository text, or terminal output without inspection.

- The original one-command mode needs a local **APPROVE ONCE** click every time. The optional visible-session mode requires a separate **APPROVE SESSION** click, and then permits commands without more prompts until revocation or expiry.
- **Tkinter runs in a separate, short-lived Windows process**, on that process's main thread. The MCP worker can wait for approval without owning or destroying Tcl objects. Closing the popup, process failure or cancellation denies execution.
- Session activation is never unattended, but subsequent commands within an approved session run without individual prompts. There is no public HTTP endpoint.
- Refuses to run in an elevated Administrator process.
- Uses Windows PowerShell without profiles or interactive stdin; max command length 2,000; default command timeout 90 seconds and maximum timeout 120 seconds.
- Captured stdout/stderr use bounded 32-KiB buffers each.
- Child PowerShell environment strips most variables to avoid inheriting API keys.
- If GUI unavailable, execution is denied. Stopping the tunnel disconnects the AI.
- Working directory is **not a directory access restriction**. Cancellation and child-process termination are best-effort. Abruptly terminating Termylo or the tunnel does **not** guarantee any previously started child processes are stopped.
- Command output can contain secrets; do not request private credentials or keys.
- **Data sharing:** When used with ChatGPT, the command text and returned stdout/stderr necessarily pass through the connected MCP client and OpenAI-hosted tunnel. The command executes locally, but the request and its output are **not purely local**. Avoid commands that print credentials or confidential files.

## Windows installation

Use a regular PowerShell session (NOT Run as Administrator). Clone this repo onto your laptop, then:

```powershell
.\scripts\setup.ps1
```

If scripts are blocked, run commands directly instead of weakening execution policy:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m termylo.doctor
```

The setup script checks native command exit codes and fails on missing prerequisites. The doctor is read-only: confirm `powershell_found`, `tkinter_found`, `mcp_sdk_found` and `workdir_exists` are true. Importing `tkinter` does **not** prove an actual on-screen approval popup works.

Optional command starting directory (not a security sandbox):

```powershell
$env:TERMYLO_WORKDIR = "$HOME\Axtario"
```

## Test directly from `main` on your Windows laptop

No ZIP or separate build artifact is needed. Install Git and Python 3.12, then open a **normal (non-administrator)** Windows PowerShell window.

If you haven't cloned the repository:

```powershell
git clone https://github.com/thephenyl02-creator/termylo.git
cd termylo
```

If your local Termylo folder already exists, open it and run:

```powershell
git switch main
git pull --ff-only origin main
```

Now run the **single full local test command**:

```powershell
.\scripts\test-local.ps1
```

The script installs/checks the project, runs the complete automated tests, simulates request→approval→output, and finally displays a real desktop approval popup launched in its own Python process with the harmless `Write-Output 'Termylo GUI approval verified'` command. Review the text and click **APPROVE ONCE**. The final line must say `PASS: All selected Termylo verification steps succeeded.`

A failed, missing or denied dialog is correctly reported as a failed/incomplete *acceptance test*; the script never grants permission automatically. If PowerShell blocks execution of local scripts, follow your organization's execution policy or manually run the commands under the next heading; do not silently disable security settings.

**This verifies the local Windows path, not the ChatGPT tunnel.** Test the actual ChatGPT connection only after local acceptance and tunnel permission checks.

## Verification and simulation

```powershell
.\.venv\Scripts\python.exe -m pip install pytest
.\.venv\Scripts\python.exe -m pytest -v
.\.venv\Scripts\python.exe scripts\simulate.py
```

CI tests Windows PowerShell execution, Unicode output, failure exit codes, truncation, timeouts, real MCP client/server stdio handshake, mocked GUI approval/denial/timeout/cancellation, and the simulated command lifecycle. CI also checks the subprocess approval protocol and rejects malformed or failed approval subprocesses. Simulation never uses actual PowerShell or your personal files.

### Check the actual Windows approval popup (manual)

Run this from a **normal, non-administrator Windows desktop session** only after setup:

```powershell
.\.venv\Scripts\python.exe scripts\manual_smoke.py
```

It will show a popup containing one harmless `Write-Output` command. Click **APPROVE ONCE** and confirm that the script reports PASS. This on-screen Windows test is **not** automated by headless GitHub CI.

## Native terminal v0.4.1: local continuity and optional history

ChatGPT's remote authorization expires after **20 minutes of MCP inactivity** or **40 minutes total**. On normal expiry, Termylo asks the console to dispose its local IPC pipe and **leaves the Windows PowerShell window open for local keyboard use**. A new ChatGPT session requires another physical approval and opens a **new console**, not a continuation of the former process. Explicit session closure, command cancellation/timeout, a disconnected pipe, or failure to acknowledge revocation may still terminate the window for safety.

Local command history is **OFF by default**, lives in memory only and records up to **40 manual commands** with bounded output/errors. Type these directly in the native PowerShell window:

- `:history on` — opt in to temporary history capture
- `:history status`, `:history show` — inspect locally
- `:history clear` — erase existing entries
- `:history off` — stop capture **and erase** existing entries

Only when explicitly requested by the owner, ChatGPT may use `execute_native_powershell` to run `Get-TermyloHistory -Last 10`. Termylo does **not** automatically retrieve or upload history. Likely sensitive entries are withheld as a unit, but pattern detection is not comprehensive: **never type passwords, keys, or other sensitive material while history is on**. Switch history off first. No history file is written to disk. The old per-command approval tool remains unchanged.

## Local error-sharing permission and opt-in auto review (v0.4.4)

Termylo retains **only the most recent error** from commands typed into its native PowerShell window, in memory, automatically. **No terminal shortcut, general history setting, or auto-review toggle is required.** When you explicitly say **"There's an error—check it"** in ChatGPT, ChatGPT may run `Get-TermyloLatestError` in your **already-approved native session** to retrieve that last redacted error and diagnose it. It does not automatically upload errors or watch your terminal in the background. If the session is no longer approved, a new approval is required; an expired local-only terminal is not silently reattached.

You can optionally use the older granular queue controls below if you want to share a sequence of errors. Those controls must be typed locally:

| Native terminal command | Effect |
|---|---|
| `:review last` | Explicitly queue the most recent manually typed command's error for ChatGPT review. General history can stay OFF. |
| `:review auto on` | Opt in to automatically **queue errors only**, from future keyboard commands in **this native window**. Does not auto-upload or grant remote access. |
| `:review auto off` | Stop auto-queuing and erase the queue and most recent error. |
| `:review show` | Display the queue locally. |
| `:review status` | Show current auto mode and queued error count. |
| `:review clear` | Erase review queue and most recent error (leaves auto mode unchanged). |

When you say **"Check the error"** in ChatGPT after using `:review last` or opting into `:review auto on`, ChatGPT can run:

```powershell
Get-TermyloSharedErrors -Last 5 -Consume
```

This retrieves the **shared error queue only**, not the general manual command history. It clears the entries after retrieval. The queue contains at most 10 errors in RAM; local commands with no error are not queued. Errors possibly containing secrets are replaced with a redacted placeholder. **Redaction is heuristic, not guaranteed**, so avoid entering real credentials or secrets in a terminal with capture enabled. To opt out and erase local pending entries, type `:review auto off` and `:history off`.

**Scope:** Auto review is OFF by default and resets when the native window closes. It does **not** mean launch at Windows sign-in. A separately approved Termylo native session (20 minutes idle / 40 minutes total) is still required for ChatGPT to retrieve shared errors. A terminal shortcut does not proactively send messages to ChatGPT or authorize unattended debugging. The manually shared queue is not a security sandbox: an already-approved native session has its normal PowerShell permissions; use ChatGPT only for the tasks you authorize and close/revoke when finished.

## One-click start from ChatGPT (Windows custom URI)

A completely stopped tunnel **cannot receive MCP commands**, but Windows can launch a local app from a user-clicked `termylo://start` link. This is the *one-click* solution for Chrome: no manually running terminal or always-on service is required beforehand.

**One-time install** (after the encrypted key is saved and `.venv` installed):

```powershell
cd "$HOME\termylo"
git pull --ff-only origin main
.\scripts\install-uri-protocol.ps1 -Action Install
.\scripts\install-uri-protocol.ps1 -Action Status
```

Expected status: `TERMYLO_URI=READY`. This installs a **current-Windows-user-only** registry handler under `HKCU:\Software\Classes\termylo` (no Administrator prompt), pointing to the fixed Python windowless launcher `scripts\uri_launch.py`.

**Start it with a user gesture**: click a `termylo://start` link (subject to ChatGPT/Chrome allowing custom-scheme links and browser permission prompts), or press **Win + R**, enter `termylo://start` and Enter as a reliable fallback. It starts the Secure MCP Tunnel completely headless using your DPAPI-encrypted key; **no blank PowerShell window** appears. The real interactive native PowerShell window is opened separately through ChatGPT's `open_native_session`, with your physical approval. **Neither the link nor URL parameters grant arbitrary PowerShell execution.** After the tunnel reconnects, ChatGPT can call `open_native_session`, which still requires a physical approval popup.

You can close all terminals before clicking the link. Since the tunnel is headless, it stays running until you end the tunnel-client process or Windows signs you out/restarts; the link can be used again after shutdown. This is on-demand, **not automatic startup**. The browser may require an external-application confirmation; that is expected. ChatGPT may also reject custom URL schemes; if so, use Win+R or a local Windows shortcut.

**Security**: any website/application can *attempt* to open registered URI schemes. This handler accepts **only** `termylo://start` (optional trailing slash) and rejects every other URL, parameter and extra argument. It cannot run URL-supplied commands. The separate local MCP approval controls are unchanged. To uninstall the link handler:

```powershell
.\scripts\install-uri-protocol.ps1 -Action Remove
```

## Secure tunnel key storage on Windows

Termylo's MCP server **does not need an API key itself**. The official Secure MCP Tunnel client uses a restricted \`CONTROL_PLANE_API_KEY\` to connect to the OpenAI control plane. Never put this key in GitHub, shell command-line arguments, a plaintext YAML profile, or PowerShell history.

Once, in the **original Windows PowerShell terminal that already has the key in its environment**, run:

```powershell
cd "$HOME\termylo"
.\scripts\tunnel-key.ps1 -Action Store -FromEnvironment
```

If that terminal no longer holds the key, the script instead prompts for it using hidden input (do **not** paste it into ChatGPT). The key is saved as a Windows DPAPI CurrentUser-encrypted file under \`%APPDATA%\Termylo\secrets\`, with a restricted file ACL. It can be decrypted only in the same Windows user context on the same machine (subject to Windows account/DPAPI security). Local malware with sufficient privileges remains a risk.

Validate storage without exposing the key:

```powershell
.\scripts\tunnel-key.ps1 -Action Status
.\scripts\start-tunnel-secure.ps1 -VerifyOnly
```

After stopping the previous tunnel process, restart it using:

```powershell
.\scripts\start-tunnel-secure.ps1
```

The launcher restores the credential into the child tunnel-client process environment only and keeps it out of console output. It intentionally refuses to start a duplicate Termylo tunnel for this profile. This startup is **manual**; nothing is added to Windows startup without the user's explicit request. To erase the locally encrypted credential, run \`.\scripts\tunnel-key.ps1 -Action Remove\`.

## Connect to **normal ChatGPT**

ChatGPT web cannot directly reach a laptop's `localhost`. Prefer the official [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels) with the [open-source OpenAI tunnel-client](https://github.com/openai/tunnel-client) running on the laptop. It creates an **outbound-only** connection and launches Termylo over stdio; Termylo itself never opens a public server. This uses an OpenAI-hosted relay/tunnel service; do not assume that its permissions, quotas or costs are included in ChatGPT Plus.

**Access prerequisite:** Your ChatGPT workspace must permit a custom MCP plugin with a write-capable tool, and the Platform account must have an available Secure MCP Tunnel with **Tunnels Read + Use** plus a restricted runtime API key. Platform permissions/any costs are not automatically covered by ChatGPT Plus. These account-specific items cannot be validated from GitHub CI.

1. Create or select a tunnel in [Platform Tunnels](https://platform.openai.com/settings/organization/tunnels), then obtain its tunnel ID and a restricted runtime key. Do not paste keys in ChatGPT, GitHub, logs or command arguments.
2. Install the official Windows `tunnel-client`; inspect `tunnel-client help quickstart`.
3. Initialize an stdio profile with the `sample_mcp_stdio_local` sample, pointing its command at the full path to `your-repo\.venv\Scripts\python.exe` plus `-m termylo.server`. Consult `tunnel-client init --help` for correct Windows quoting.
4. Store runtime API credentials securely according to tunnel-client documentation. Run `tunnel-client doctor --profile termylo --explain` then `tunnel-client run --profile termylo`.
5. In ChatGPT web: **Plugins → Add custom MCP server → Tunnel**, choose the tunnel and verify all twelve tools.
6. Call `termylo_status`. Then request `execute_powershell(command="Write-Output 'Termylo connected'")`, click **APPROVE ONCE** on the laptop and call `powershell_result(job_id=...)`.

Only one active `tunnel-client` instance should use an stdio tunnel ID, because each instance would have its own in-memory job state. If normal ChatGPT can't access write-capable custom MCP tools on your plan, do NOT publish an unauthenticated PowerShell command endpoint. A local MCP-capable development client remains a safe fallback.

## Architecture

```text
Normal ChatGPT (or authorized MCP client)
    <--> Secure MCP Tunnel (if supported and configured)
Official tunnel-client on Windows (outbound connection)
    <--> Termylo MCP process (stdio; no HTTP listener)
    --> on-device confirmation: APPROVE ONCE or DENY
    --> Windows PowerShell process, non-elevated
    <-- bounded stdout + stderr + exit code
    <-- powershell_result(job_id)
```

**Owner re-verification required:** The old Tkinter implementation crashed after successful approval on the user's laptop. The subprocess isolation fix has CI checks, but the corrected GUI must be retested on the laptop; no live ChatGPT/Platform tunnel has been set up with your credentials. CI cannot test either of these account- and device-specific requirements. Do not describe this as fully deployed until those steps pass.

## License

Personal utility. No open-source license selected.
