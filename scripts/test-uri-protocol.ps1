# Windows-only disposable registration test. No tunnel connection is started.
$ErrorActionPreference = 'Stop'
$key = 'HKCU:\Software\Classes\termylo'
$installer = Join-Path $PSScriptRoot 'install-uri-protocol.ps1'
if (Test-Path -LiteralPath $key) {
    throw 'Refusing to overwrite an existing URI registration during tests.'
}
try {
    $install = & $installer -Action Install
    if ($install -notcontains 'TERMYLO_URI=INSTALLED') {
        throw "URI installation failed."
    }
    $status = & $installer -Action Status
    if ($status -notcontains 'TERMYLO_URI=READY') {
        throw "URI registration isn't ready."
    }
    $command = (Get-Item -LiteralPath (Join-Path $key 'shell\open\command')).GetValue('')
    if ($command -notmatch 'pythonw\.exe' -or
        $command -notmatch 'uri_launch\.py' -or
        $command -notmatch '"%1"' -or
        $command -match 'CONTROL_PLANE_API_KEY') {
        throw 'Registry handler command is incorrect.'
    }
    Write-Output 'PASS: current-user URL registration uses fixed Python handler.'
} finally {
    & $installer -Action Remove | Out-Null
    if (Test-Path -LiteralPath $key) { throw 'URI handler was not removed.' }
}
