# One-command local verification; run only in a non-elevated Windows PowerShell window.
# This script never opens a network listener and never installs a background service.
param([switch]$SkipGui)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$python = Join-Path $repo '.venv\Scripts\python.exe'

Write-Host '[1/5] Check or install Termylo from this checked-out repository...'
& (Join-Path $PSScriptRoot 'setup.ps1')
if (-not (Test-Path $python)) { throw 'Termylo virtual environment was not created.' }

Write-Host '[2/5] Install local test dependencies...'
& $python -m pip install pytest pytest-cov
if ($LASTEXITCODE -ne 0) { throw 'Test dependency installation failed.' }

Write-Host '[3/5] Run the complete test suite (including actual Windows PowerShell executions)...'
& $python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'Automated tests failed.' }

Write-Host '[4/5] Simulate the approval -> command -> result lifecycle...'
& $python scripts/simulate.py
if ($LASTEXITCODE -ne 0) { throw 'Lifecycle simulation failed.' }

if ($SkipGui) {
    Write-Host '[5/5] Interactive GUI test was deliberately skipped.'
} else {
    Write-Host '[5/5] A local Windows approval popup will appear. Review the harmless command.'
    & $python scripts/manual_smoke.py
    if ($LASTEXITCODE -ne 0) { throw 'Physical Windows approval test did not pass.' }
}
Write-Host 'PASS: All selected Termylo verification steps succeeded.'
