# Safe test: uses a disposable dummy key in a temporary APPDATA folder.
# Never touches the real encrypted tunnel credential.
$ErrorActionPreference = 'Stop'
$keyScript = Join-Path $PSScriptRoot 'tunnel-key.ps1'
$launchScript = Join-Path $PSScriptRoot 'start-tunnel-secure.ps1'
$originalAppData = $env:APPDATA
$originalKey = $env:CONTROL_PLANE_API_KEY
$temp = Join-Path $env:TEMP ('termylo-dpapi-test-' + [guid]::NewGuid().ToString('n'))
try {
    New-Item -Path $temp -ItemType Directory -Force | Out-Null
    $env:APPDATA = $temp
    $env:CONTROL_PLANE_API_KEY = 'TEST_ONLY_DUMMY_KEY_NOT_REAL_123456'
    $saved = & $keyScript -Action Store -FromEnvironment
    if ($saved -notmatch 'READY_CURRENT_WINDOWS_USER') { throw 'Secure save failed' }
    $path = Join-Path $temp 'Termylo\secrets\tunnel-key.dpapi'
    if (-not (Test-Path $path)) { throw 'Encrypted key file missing' }
    $disk = [System.IO.File]::ReadAllText($path)
    if ($disk -match 'TEST_ONLY_DUMMY' -or $disk.Length -lt 100) { throw 'Unencrypted key detected' }
    $ready = & $launchScript -VerifyOnly
    if ($ready -notmatch 'TUNNEL_LAUNCHER=READY') { throw 'Secure startup readiness failed' }
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
