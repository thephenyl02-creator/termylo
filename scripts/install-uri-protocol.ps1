# Register termylo://start for the CURRENT Windows user. No admin rights needed.
# The URI handler can launch Termylo, but never execute URL-provided commands.
[CmdletBinding()]
param(
    [ValidateSet('Install','Status','Remove')]
    [string]$Action = 'Status'
)

$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'Windows protocol registration is supported only on Windows.'
}

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$handler = Join-Path $repo 'scripts\uri_launch.py'
$pythonw = Join-Path $repo '.venv\Scripts\pythonw.exe'
$key = 'HKCU:\Software\Classes\termylo'
$commandKey = Join-Path $key 'shell\open\command'
$expected = '"' + $pythonw + '" "' + $handler + '" "%1"'

function Get-RegisteredCommand {
    if (-not (Test-Path -LiteralPath $commandKey)) { return $null }
    return (Get-Item -LiteralPath $commandKey).GetValue('')
}

switch ($Action) {
    'Status' {
        $found = Get-RegisteredCommand
        if ($found -ceq $expected -and (Test-Path -LiteralPath $handler) -and
            (Test-Path -LiteralPath $pythonw)) {
            Write-Output 'TERMYLO_URI=READY'
            Write-Output 'URI=termylo://start'
        } elseif ($null -eq $found) {
            Write-Output 'TERMYLO_URI=NOT_INSTALLED'
        } else {
            Write-Output 'TERMYLO_URI=OTHER_OR_OUTDATED_REGISTRATION'
        }
    }
    'Install' {
        if (-not (Test-Path -LiteralPath $handler -PathType Leaf)) {
            throw 'Termylo URI handler is missing.'
        }
        if (-not (Test-Path -LiteralPath $pythonw -PathType Leaf)) {
            throw 'Python windowless executable not found. Set up .venv with Python 3.12 first.'
        }
        $existing = Get-RegisteredCommand
        if ($existing -and $existing -cne $expected) {
            throw 'The termylo:// protocol is registered to another application. Refusing to overwrite.'
        }
        New-Item -Path $key -Force | Out-Null
        Set-Item -LiteralPath $key -Value 'URL:Termylo Secure Tunnel Launcher'
        New-ItemProperty -Path $key -Name 'URL Protocol' -PropertyType String -Value '' -Force | Out-Null
        New-Item -Path $commandKey -Force | Out-Null
        Set-Item -LiteralPath $commandKey -Value $expected
        if ((Get-RegisteredCommand) -cne $expected) {
            throw 'Protocol registration did not verify.'
        }
        Write-Output 'TERMYLO_URI=INSTALLED'
        Write-Output 'URI=termylo://start'
    }
    'Remove' {
        $existing = Get-RegisteredCommand
        if ($existing -and $existing -cne $expected) {
            throw 'Registry handler does not match this installation; refusing to remove.'
        }
        if (Test-Path -LiteralPath $key) {
            Remove-Item -LiteralPath $key -Recurse -Force
        }
        Write-Output 'TERMYLO_URI=REMOVED'
    }
}
