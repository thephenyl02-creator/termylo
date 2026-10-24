# Store the OpenAI Secure MCP Tunnel key for the current Windows user only.
# Secret never appears in logs, script arguments, repository, or command output.
[CmdletBinding()]
param(
    [ValidateSet('Store','Status','Remove')]
    [string]$Action = 'Status',
    [switch]$FromEnvironment
)

$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Windows DPAPI storage is required.' }

$folder = Join-Path $env:APPDATA 'Termylo\secrets'
$file = Join-Path $folder 'tunnel-key.dpapi'
$printStatus = {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
        Write-Output 'TUNNEL_KEY_STATUS=NOT_CONFIGURED'
        return
    }
    try {
        $cipher = [System.IO.File]::ReadAllText($file).Trim()
        $check = ConvertTo-SecureString -String $cipher -ErrorAction Stop
        if ($check.Length -le 0) { throw 'Key was empty.' }
        $check.Dispose()
        Write-Output 'TUNNEL_KEY_STATUS=READY_CURRENT_WINDOWS_USER'
    } catch {
        Write-Output 'TUNNEL_KEY_STATUS=UNREADABLE'
        throw 'Encrypted tunnel key cannot be unlocked by this Windows user.'
    }
}

switch ($Action) {
    'Status' { & $printStatus; break }
    'Remove' {
        if (Test-Path -LiteralPath $file -PathType Leaf) {
            Remove-Item -LiteralPath $file -Force
        }
        Write-Output 'TUNNEL_KEY_STATUS=REMOVED'
        break
    }
    'Store' {
        $secret = $null
        try {
            if ($FromEnvironment -and -not [string]::IsNullOrWhiteSpace($env:CONTROL_PLANE_API_KEY)) {
                # The key already exists in the USER's PowerShell process.
                $secret = ConvertTo-SecureString -String $env:CONTROL_PLANE_API_KEY -AsPlainText -Force
            } else {
                Write-Host 'Enter your restricted OpenAI tunnel key. Characters will not display.'
                $secret = Read-Host -Prompt 'Tunnel API key' -AsSecureString
            }
            if ($null -eq $secret -or $secret.Length -lt 8) {
                throw 'No valid-looking key was entered.'
            }
            New-Item -ItemType Directory -Path $folder -Force | Out-Null
            # No -Key option: Windows DPAPI encrypts for this user and computer.
            $protected = ConvertFrom-SecureString -SecureString $secret
            $temp = Join-Path $folder ([Guid]::NewGuid().ToString('n') + '.tmp')
            try {
                [System.IO.File]::WriteAllText($temp, $protected, [System.Text.Encoding]::ASCII)
                $acl = Get-Acl -LiteralPath $temp
                $acl.SetAccessRuleProtection($true, $false)
                $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
                $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
                    $identity,
                    [System.Security.AccessControl.FileSystemRights]::FullControl,
                    [System.Security.AccessControl.AccessControlType]::Allow
                )
                $acl.SetAccessRule($rule)
                Set-Acl -LiteralPath $temp -AclObject $acl
                Move-Item -LiteralPath $temp -Destination $file -Force
            } finally {
                if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force }
            }
            & $printStatus
        } finally {
            if ($null -ne $secret) { $secret.Dispose() }
        }
        break
    }
}
