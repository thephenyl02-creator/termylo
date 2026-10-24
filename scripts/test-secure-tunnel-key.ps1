# Safe test: uses a disposable dummy key in a temporary APPDATA folder.
# Never touches the real encrypted tunnel credential.
$ErrorActionPreference = 'Stop'
# Use disposable scripts and a dummy client executable, never the live installation.
$keyScript = $null
$launchScript = $null
$originalAppData = $env:APPDATA
$originalKey = $env:CONTROL_PLANE_API_KEY
$temp = Join-Path $env:TEMP ('termylo-dpapi-test-' + [guid]::NewGuid().ToString('n'))
try {
    $testScripts = Join-Path $temp 'project\scripts'
    $mockTunnelDir = Join-Path $temp 'project\tunnel-client'
    New-Item -Path $testScripts,$mockTunnelDir -ItemType Directory -Force | Out-Null
    $keyScript = Join-Path $testScripts 'tunnel-key.ps1'
    $launchScript = Join-Path $testScripts 'start-tunnel-secure.ps1'
    Copy-Item (Join-Path $PSScriptRoot 'tunnel-key.ps1') $keyScript
    Copy-Item (Join-Path $PSScriptRoot 'start-tunnel-secure.ps1') $launchScript
    [System.IO.File]::WriteAllText((Join-Path $mockTunnelDir 'tunnel-client.exe'), 'DUMMY_NOT_EXECUTABLE')
    $env:APPDATA = Join-Path $temp 'appdata'
    New-Item $env:APPDATA -ItemType Directory -Force | Out-Null
    $env:CONTROL_PLANE_API_KEY = 'TEST_ONLY_DUMMY_KEY_NOT_REAL_123456'
    $saved = & $keyScript -Action Store -FromEnvironment
    if ($saved -notmatch 'READY_CURRENT_WINDOWS_USER') { throw 'Secure save failed' }
    $path = Join-Path $env:APPDATA 'Termylo\secrets\tunnel-key.dpapi'
    if (-not (Test-Path $path)) { throw 'Encrypted key file missing' }
    $disk = [System.IO.File]::ReadAllText($path)
    if ($disk -match 'TEST_ONLY_DUMMY' -or $disk.Length -lt 100) { throw 'Unencrypted key detected' }
    $ready = & $launchScript -VerifyOnly
    if (($ready -join [Environment]::NewLine) -notmatch 'TUNNEL_LAUNCHER=READY') { throw 'Secure startup readiness failed' }
    $removed = & $keyScript -Action Remove
    if ($removed -notmatch 'REMOVED' -or (Test-Path $path)) { throw 'Key deletion failed' }
    Write-Output 'PASS: DPAPI encrypted key, secure launcher readiness, and key removal.'
} finally {
    $env:APPDATA = $originalAppData
    if ($null -eq $originalKey) {
        Remove-Item Env:\CONTROL_PLANE_API_KEY -ErrorAction SilentlyContinue
    } else {
        $env:CONTROL_PLANE_API_KEY = $originalKey
    }
    Remove-Item $temp -Recurse -Force -ErrorAction SilentlyContinue
}
