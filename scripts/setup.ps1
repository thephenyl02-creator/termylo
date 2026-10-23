$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$python = Join-Path $repo '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    & py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $python)) {
        throw 'Python 3.12 virtual environment creation failed.'
    }
}

& $python -m pip install -e .
if ($LASTEXITCODE -ne 0) {
    throw 'Termylo dependency installation failed.'
}
$report = (& $python -m termylo.doctor) | Out-String
if ($LASTEXITCODE -ne 0) {
    throw 'Termylo doctor failed.'
}
$doctor = $report | ConvertFrom-Json
if ($doctor.platform -ne 'win32' -or -not $doctor.powershell_found -or -not $doctor.tkinter_found -or -not $doctor.mcp_sdk_found -or -not $doctor.workdir_exists) {
    Write-Host $report
    throw 'Termylo prerequisites not satisfied. Review the diagnostic report.'
}

Write-Host 'Termylo installed. The local approval popup still requires an interactive Windows check.'
Write-Host 'No network listener, tunnel, or permanent remote service has been started.'
Write-Host "MCP executable: $repo\.venv\Scripts\termylo-mcp.exe"
