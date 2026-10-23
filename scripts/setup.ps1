$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    py -3.12 -m venv .venv
}
& '.venv\Scripts\python.exe' -m pip install -e .
& '.venv\Scripts\termylo-doctor.exe'
Write-Host 'Termylo installed. No network listener or remote service has been started.'
Write-Host "MCP executable: $repo\.venv\Scripts\termylo-mcp.exe"
