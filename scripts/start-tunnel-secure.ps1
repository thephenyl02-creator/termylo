# Start Termylo Secure MCP Tunnel using per-user encrypted key.
# Never include secrets on the command line or print them.
[CmdletBinding()]
param([switch]$VerifyOnly)

$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { throw 'This launcher requires Windows.' }

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$client = Join-Path $root 'tunnel-client\tunnel-client.exe'
$keyFile = Join-Path $env:APPDATA 'Termylo\secrets\tunnel-key.dpapi'
if (-not (Test-Path -LiteralPath $client -PathType Leaf)) {
    throw 'Tunnel client executable is missing.'
}
if (-not (Test-Path -LiteralPath $keyFile -PathType Leaf)) {
    throw 'Key is not saved. Run: .\scripts\tunnel-key.ps1 -Action Store -FromEnvironment'
}

$secret = $null
$clearText = $null
try {
    $secret = ConvertTo-SecureString -String ([System.IO.File]::ReadAllText($keyFile).Trim()) -ErrorAction Stop
    if ($secret.Length -le 0) { throw 'Encrypted key is empty.' }
    if ($VerifyOnly) {
        Write-Output 'TUNNEL_LAUNCHER=READY'
        Write-Output 'SECRET_STORAGE=WINDOWS_DPAPI_CURRENT_USER'
        return
    }

    # Never launch two tunnel clients for the same local MCP profile.
    $running = Get-CimInstance Win32_Process -Filter "Name='tunnel-client.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match '(?i)\brun\b.*--profile\s+termylo\b' }
    if ($running) {
        Write-Output 'TUNNEL_LAUNCHER=ALREADY_RUNNING'
        return
    }

    # Put the key in the CHILD process environment only. No global/user
    # environment variable, plaintext file, argument, or log entry.
    $clearText = (New-Object System.Net.NetworkCredential('', $secret)).Password
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $client
    $info.Arguments = 'run --profile termylo'
    $info.WorkingDirectory = $root
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $false
    $info.EnvironmentVariables['CONTROL_PLANE_API_KEY'] = $clearText
    $proc = [System.Diagnostics.Process]::Start($info)
    $info.EnvironmentVariables.Remove('CONTROL_PLANE_API_KEY')
    $clearText = $null
    if ($null -eq $proc) { throw 'Tunnel client failed to start.' }
    Write-Output ('TUNNEL_LAUNCHER=STARTED_PID_' + $proc.Id)
    Write-Host 'Keep this terminal open while using Termylo. Ctrl+C to stop.'
    $proc.WaitForExit()
    Write-Output ('TUNNEL_EXIT_CODE=' + $proc.ExitCode)
} finally {
    $clearText = $null
    if ($null -ne $secret) { $secret.Dispose() }
}
