# Termylo

**Your personal Windows PowerShell bridge for MCP clients.** No paid automation service, remote desktop, dashboard, browser, or subscription. Runs only while you start its MCP connection.

Termylo's workflow: **AI requests a command → you approve it in a Windows popup → Termylo runs it on your laptop → output and exit code return to the AI.** The server doesn't listen on a network port.

## Tools

| Tool | What it does |
|---|---|
| `termylo_status` | Check whether local MCP agent responds. |
| `execute_powershell(command, timeout_seconds)` | Submit **one** command, returning a job ID immediately. |
| `powershell_result(job_id)` | Fetch result: stdout, stderr, exit code, truncation indicators. |
| `cancel_powershell(job_id)` | Request cancellation and best-effort termination of PowerShell process tree. |

The two-step request/result process prevents MCP timeouts while you read the approval window. Only one command can be active; finished results expire after 15 minutes.

## Security boundaries

**Not a sandbox.** An approved PowerShell command runs with your Windows account privileges. It can access or change any files that the user can, launch programs, or contact remote services. Do not approve commands suggested by untrusted websites, repository text, or terminal output without inspection.

- Each execution needs a local **APPROVE ONCE** click; DENY is default; popup expires after 60 seconds.
- No unattended approval setting; no public HTTP endpoint.
- Refuses to run in an elevated Administrator process.
- Uses Windows PowerShell without profiles or interactive stdin; max command length 2,000 and execution timeout 120 seconds.
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

## Verification and simulation

```powershell
.\.venv\Scripts\python.exe -m pip install pytest
.\.venv\Scripts\python.exe -m pytest -v
.\.venv\Scripts\python.exe scripts\simulate.py
```

CI tests Windows PowerShell execution, Unicode output, failure exit codes, truncation, timeouts, real MCP client/server stdio handshake, mocked GUI approval/denial/timeout/cancellation, and the simulated command lifecycle. Simulation never uses actual PowerShell or your personal files.

### Check the actual Windows approval popup (manual)

Run this from a **normal, non-administrator Windows desktop session** only after setup:

```powershell
.\.venv\Scripts\python.exe scripts\manual_smoke.py
```

It will show a popup containing one harmless `Write-Output` command. Click **APPROVE ONCE** and confirm that the script reports PASS. This on-screen Windows test is **not** automated by headless GitHub CI.

## Connect to **normal ChatGPT**

ChatGPT web cannot directly reach a laptop's `localhost`. Prefer the official [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels) with the [open-source OpenAI tunnel-client](https://github.com/openai/tunnel-client) running on the laptop. It creates an **outbound-only** connection and launches Termylo over stdio; Termylo itself never opens a public server. This uses an OpenAI-hosted relay/tunnel service; do not assume that its permissions, quotas or costs are included in ChatGPT Plus.

**Access prerequisite:** Your ChatGPT workspace must permit a custom MCP plugin with a write-capable tool, and the Platform account must have an available Secure MCP Tunnel with **Tunnels Read + Use** plus a restricted runtime API key. Platform permissions/any costs are not automatically covered by ChatGPT Plus. These account-specific items cannot be validated from GitHub CI.

1. Create or select a tunnel in [Platform Tunnels](https://platform.openai.com/settings/organization/tunnels), then obtain its tunnel ID and a restricted runtime key. Do not paste keys in ChatGPT, GitHub, logs or command arguments.
2. Install the official Windows `tunnel-client`; inspect `tunnel-client help quickstart`.
3. Initialize an stdio profile with the `sample_mcp_stdio_local` sample, pointing its command at the full path to `your-repo\.venv\Scripts\python.exe` plus `-m termylo.server`. Consult `tunnel-client init --help` for correct Windows quoting.
4. Store runtime API credentials securely according to tunnel-client documentation. Run `tunnel-client doctor --profile termylo --explain` then `tunnel-client run --profile termylo`.
5. In ChatGPT web: **Plugins → Add custom MCP server → Tunnel**, choose the tunnel and verify all four tools.
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

**Not yet verified:** The GUI dialog has not been exercised on your actual laptop; no live ChatGPT/Platform tunnel has been set up with your credentials. CI cannot test either of these account- and device-specific requirements. Do not describe this as fully deployed until those steps pass.

## License

Personal utility. No open-source license selected.
