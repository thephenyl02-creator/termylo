# Termylo

Private, personal PowerShell execution through MCP. Not a remote desktop product, not part of Axtario, and no paid relay is built into the software.

## Features

- `termylo_status`: read-only check that the MCP server is online.
- `execute_powershell`: accepts a single command and returns exit code, stdout and stderr.
- Every command requires an APPROVE ONCE click in a Windows desktop dialog. No interactive UI means deny.
- A fresh approval for every command; approval window expires after 60 seconds.
- PowerShell starts without profiles or interactive stdin. Max command length 500, max execution timeout 120 seconds, output truncated to 16,000 characters.
- MCP stdio transport, no public HTTP listener.

**Security:** A command approved by the user has all the permissions of that Windows user. The approval dialog is not a sandbox. Commands may access private files or invoke network operations. The working directory is NOT a filesystem access restriction. Review every command and stop the connection when not needed.

## Windows setup (Python 3.12)

Clone the repo. Open ordinary (non-admin) PowerShell in the project folder and run `./scripts/setup.ps1`.

Or install manually:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

Optional working directory for your project:

```powershell
$env:TERMYLO_WORKDIR = "$HOME\Axtario"
```

Your MCP **stdio subprocess command** is the absolute path to `.venv\Scripts\python.exe` with arguments `-m termylo.server`. Do not directly run this as an interactive shell—it speaks MCP over stdin/stdout.

## Connect to ChatGPT securely

ChatGPT web cannot reach laptop localhost on its own. Prefer [OpenAI Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels): use an outbound-only local tunnel-client to launch Termylo's stdio MCP server. You will need the right Platform tunnel permissions, a tunnel ID, and a runtime API key; availability and any Platform billing are **not included** in ChatGPT Plus.

1. Install and configure the [official tunnel-client](https://github.com/openai/tunnel-client). See `tunnel-client help quickstart`.
2. Create a **stdio** tunnel profile that launches Termylo using the absolute venv Python path with `-m termylo.server`.
3. Run `tunnel-client doctor`, then `tunnel-client run` using that profile.
4. In ChatGPT web: Plugins -> Add custom MCP server -> Tunnel. Select the tunnel, configure it, install, and call `termylo_status` first.
5. Then request `execute_powershell` with `Get-Date`; the command should only run after your Windows approval.

This only creates the **local utility**. End-to-end ChatGPT invocation and the Windows approval popup have **not been tested** on the owner's laptop. Account-specific restrictions may block write-capable tools.

### Run tests

```powershell
.\.venv\Scripts\python.exe -m pip install pytest
.\.venv\Scripts\python.exe -m pytest -q
```

## Deliberately excluded

No automated approvals, paid remote relay, dashboard, persistent service, cloud browser, file-management tools, or public HTTP command endpoint.

## License

Private personal project. No license selected.
