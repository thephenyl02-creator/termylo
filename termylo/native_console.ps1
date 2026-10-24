# Experimental true native PowerShell console for Termylo.
# This is a REAL powershell.exe console, not a Python/Tkinter display.
# Only a random per-process local named pipe receives remote commands.
# The foreground event loop also accepts commands typed into this window.
# Not installed as an MCP tool until interactive Windows tests pass.
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9_-]{24,80}$')]
    [string]$PipeName
)

$ErrorActionPreference = "Stop"
$script:TermyloRunning = $true

function Read-ExactBytes {
    param([System.IO.Stream]$Stream, [int]$Length)
    $data = New-Object byte[] $Length
    $offset = 0
    while ($offset -lt $Length) {
        $read = $Stream.Read($data, $offset, $Length - $offset)
        if ($read -le 0) { throw "IPC peer disconnected." }
        $offset += $read
    }
    return ,$data
}

function Write-NativePrompt {
    [Console]::Write("PS " + (Get-Location).Path + "> ")
}

function Write-NativeText {
    param([string]$Content)
    if ($Content.Length -gt 0) { [Console]::WriteLine($Content.TrimEnd()) }
}

$pipe = $null
try {
    $pipe = [System.IO.Pipes.NamedPipeServerStream]::new(
        $PipeName,
        [System.IO.Pipes.PipeDirection]::InOut,
        1,
        [System.IO.Pipes.PipeTransmissionMode]::Byte,
        [System.IO.Pipes.PipeOptions]::Asynchronous
    )
    $pending = $pipe.BeginWaitForConnection($null, $null)

    $Host.UI.RawUI.WindowTitle = "Termylo - Real Windows PowerShell (close to revoke)"
    Write-Host "Termylo native PowerShell session" -ForegroundColor Cyan
    Write-Host "Type commands directly here, or request commands through ChatGPT." -ForegroundColor Gray
    Write-Host "Closing this console revokes terminal access." -ForegroundColor Yellow
    Write-NativePrompt
    $typed = ""

    while ($script:TermyloRunning) {
        # Process ChatGPT commands only when no manual input is partially typed.
        if (($typed.Length -eq 0) -and $pending.IsCompleted) {
            try {
                $pipe.EndWaitForConnection($pending)
                $header = Read-ExactBytes -Stream $pipe -Length 4
                $length = [BitConverter]::ToInt32($header, 0)
                if ($length -lt 1 -or $length -gt 16000) { throw "Invalid IPC request length." }
                $payload = Read-ExactBytes -Stream $pipe -Length $length
                $req = [Text.Encoding]::UTF8.GetString($payload) | ConvertFrom-Json
                if ($null -eq $req.command -or -not ($req.command -is [string]) -or $req.command.Length -gt 2000) {
                    throw "Invalid command."
                }
                $command = [string]$req.command
                [Console]::WriteLine("")
                [Console]::WriteLine("PS> " + $command)
                $output = ""
                $errorText = ""
                $exitCode = 0
                try {
                    # Executes in this script's persistent scope; Set-Location and
                    # script-level variables carry over between requests.
                    $oldErrorPreference = $ErrorActionPreference
                    $ErrorActionPreference = "Continue"
                    $Error.Clear()
                    $global:LASTEXITCODE = 0
                    $captured = Invoke-Expression $command *>&1 | Out-String -Width 240
                    $output = [string]$captured
                    Write-NativeText $output
                    if ($Error.Count -gt 0) {
                        $exitCode = 1
                        $errorText = ($Error | Select-Object -First 3 | Out-String -Width 240)
                    } elseif ($global:LASTEXITCODE -ne 0) {
                        $exitCode = [int]$global:LASTEXITCODE
                    }
                } catch {
                    $exitCode = 1
                    $errorText = $_.ToString()
                    [Console]::WriteLine("ERROR: " + $errorText)
                } finally {
                    $ErrorActionPreference = $oldErrorPreference
                }
                $response = @{
                    status = "completed"
                    exit_code = $exitCode
                    stdout = $output.Substring(0, [Math]::Min($output.Length, 32768))
                    stderr = $errorText.Substring(0, [Math]::Min($errorText.Length, 32768))
                    stdout_truncated = ($output.Length -gt 32768)
                    stderr_truncated = ($errorText.Length -gt 32768)
                } | ConvertTo-Json -Compress -Depth 5
                $reply = [Text.Encoding]::UTF8.GetBytes($response)
                $responseHeader = [BitConverter]::GetBytes([int]$reply.Length)
                $pipe.Write($responseHeader, 0, $responseHeader.Length)
                $pipe.Write($reply, 0, $reply.Length)
                $pipe.Flush()
                $pipe.WaitForPipeDrain()
            } catch {
                [Console]::WriteLine("Termylo IPC error: " + $_.Exception.Message)
            } finally {
                if ($pipe.IsConnected) { $pipe.Disconnect() }
                if ($script:TermyloRunning) {
                    $pending = $pipe.BeginWaitForConnection($null, $null)
                    Write-NativePrompt
                }
            }
            continue
        }

        if ([Console]::KeyAvailable) {
            $key = [Console]::ReadKey($true)
            if ($key.Key -eq [ConsoleKey]::Enter) {
                [Console]::WriteLine("")
                $manual = $typed
                $typed = ""
                if ($manual.Trim() -eq "exit") {
                    $script:TermyloRunning = $false
                    break
                }
                if ($manual.Trim().Length -gt 0) {
                    try {
                        Invoke-Expression $manual *>&1 | Out-Host
                    } catch {
                        [Console]::WriteLine("ERROR: " + $_.ToString())
                    }
                }
                Write-NativePrompt
            } elseif ($key.Key -eq [ConsoleKey]::Backspace) {
                if ($typed.Length -gt 0) {
                    $typed = $typed.Substring(0, $typed.Length - 1)
                    [Console]::Write([char]8)
                    [Console]::Write(" ")
                    [Console]::Write([char]8)
                }
            } elseif ($key.Key -eq [ConsoleKey]::Escape) {
                while ($typed.Length -gt 0) {
                    $typed = $typed.Substring(0, $typed.Length - 1)
                    [Console]::Write([char]8)
                    [Console]::Write(" ")
                    [Console]::Write([char]8)
                }
            } elseif ($key.KeyChar -ge [char]32) {
                $typed += $key.KeyChar
                [Console]::Write($key.KeyChar)
            }
        } else {
            Start-Sleep -Milliseconds 40
        }
    }
} catch {
    Write-Host ("Termylo native console error: " + $_.Exception.Message) -ForegroundColor Red
    Start-Sleep -Seconds 3
} finally {
    if ($null -ne $pipe) { $pipe.Dispose() }
}
