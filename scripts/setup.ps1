$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    py -3.12 -m venv .venv
}
& ".venv\Scripts\python.exe" -m pip install --upgrade pip
& ".venv\Scripts\python.exe" -m pip install -e .
Write-Host "Termylo installed in .venv. Do not expose PowerShell through public HTTP."
Write-Host "MCP command: $((Resolve-Path '.venv\Scripts\python.exe').Path) -m termylo.server"
