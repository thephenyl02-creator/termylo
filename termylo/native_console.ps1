# Experimental true native PowerShell console for Termylo.
# This is a REAL powershell.exe console, not a Python/Tkinter display.
# Only a random per-process local named pipe receives remote commands.
# The foreground event loop also accepts commands typed into this window.
# Native MCP tool. Keyboard access continues when remote approval expires.
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9_-]{24,80}$')]
    [string]$PipeName
)

$ErrorActionPreference = "Stop"
$script:TermyloRunning = $true
$script:TermyloRemoteEnabled = $true
# History is owner-opt-in, RAM-only and never automatically reported.
$script:TermyloHistoryEnabled = $false
$script:TermyloHistory = [System.Collections.Generic.List[object]]::new()
$script:TermyloHistoryLimit = 40
# Local-only review queue. Error capture does not grant remote access.
# Manual sharing or :review auto on places a bounded redacted error
# into this queue; ChatGPT must still have a separately approved session
# and ask for the queue explicitly.
$script:TermyloReviewAutoEnabled = $false
$script:TermyloLastError = $null
$script:TermyloReviewQueue = [System.Collections.Generic.List[object]]::new()
$script:TermyloReviewLimit = 10


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


function Test-TermyloSensitive {
    param([AllowEmptyString()][string]$Text)
    # Conservative detection; it cannot recognize every possible secret.
    $pattern = '(?i)(pass(word|phrase)?|secret|token|api[_ -]?key|credential|authorization|bearer|cookie|private[_ -]?key|securestring|read-host|ssh|env:|get-credential|otp|pin\b|sk-[a-z0-9_-]{8,}|-----BEGIN|[a-z0-9+/]{48,}={0,2})'
    return [regex]::IsMatch($Text, $pattern)
}

function Save-TermyloHistory {
    param([string]$Command, [string]$Output, [string]$ErrorText)
    if (-not $script:TermyloHistoryEnabled) { return }
    if (Test-TermyloSensitive ($Command + [Environment]::NewLine + $Output + [Environment]::NewLine + $ErrorText)) {
        $Command = "[omitted: possible sensitive content]"
        $Output = ""
        $ErrorText = ""
    }
    $entry = [pscustomobject]@{
        time_utc = [DateTime]::UtcNow.ToString("o")
        command = $Command.Substring(0, [Math]::Min($Command.Length, 400))
        stdout = $Output.Substring(0, [Math]::Min($Output.Length, 2000))
        stderr = $ErrorText.Substring(0, [Math]::Min($ErrorText.Length, 1200))
    }
    $script:TermyloHistory.Add($entry)
    while ($script:TermyloHistory.Count -gt $script:TermyloHistoryLimit) {
        $script:TermyloHistory.RemoveAt(0)
    }
}

function Get-TermyloHistory {
    param([ValidateRange(1, 40)][int]$Last = 10)
    if ($script:TermyloHistory.Count -eq 0) { return "No manually typed commands recorded." }
    return ($script:TermyloHistory | Select-Object -Last $Last | Format-List | Out-String -Width 240)
}


function Save-TermyloErrorCandidate {
    param([string]$Command, [AllowEmptyString()][string]$ErrorText)
    # Retain only the most recent error from commands physically typed
    # at the native console. Successful commands are not retained here.
    if ([string]::IsNullOrWhiteSpace($ErrorText)) { return }
    $possiblySensitive = Test-TermyloSensitive ($Command + [Environment]::NewLine + $ErrorText)
    $safeCommand = $Command.Substring(0, [Math]::Min($Command.Length, 400))
    $safeError = $ErrorText.Substring(0, [Math]::Min($ErrorText.Length, 1800))
    if ($possiblySensitive) {
        $safeCommand = "[omitted: possible sensitive content]"
        $safeError = "[omitted: possible sensitive content]"
    }
    $entry = [pscustomobject]@{
        time_utc = [DateTime]::UtcNow.ToString('o')
        command = $safeCommand
        error = $safeError
    }
    $script:TermyloLastError = $entry
    if ($script:TermyloReviewAutoEnabled) { Add-TermyloReviewEntry $entry }
}

function Get-TermyloLatestError {
    param([switch]$Clear)
    # No :review command or history opt-in is needed: an explicit request
    # in ChatGPT authorizes retrieving this one already-redacted error.
    # Only errors from commands manually typed into this native window
    # are eligible; nothing is proactively uploaded or written to disk.
    if ($null -eq $script:TermyloLastError) {
        return "No manually typed command errors captured in this terminal."
    }
    $result = ($script:TermyloLastError | Format-List | Out-String -Width 200)
    if ($Clear) { $script:TermyloLastError = $null }
    return $result
}

function Add-TermyloReviewEntry {
    param([Parameter(Mandatory=$true)][psobject]$Entry)
    $script:TermyloReviewQueue.Add($Entry)
    while ($script:TermyloReviewQueue.Count -gt $script:TermyloReviewLimit) {
        $script:TermyloReviewQueue.RemoveAt(0)
    }
}

function Get-TermyloSharedErrors {
    param(
        [ValidateRange(1, 10)][int]$Last = 5,
        [switch]$Consume
    )
    # Reading this function via MCP is a deliberate ChatGPT action.
    # It cannot reach errors not placed in the approved review queue.
    if ($script:TermyloReviewQueue.Count -eq 0) {
        return "No locally shared errors. Type :review last or :review auto on."
    }
    $result = ($script:TermyloReviewQueue | Select-Object -Last $Last | Format-List | Out-String -Width 200)
    if ($Consume) { $script:TermyloReviewQueue.Clear() }
    return $result
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
    Write-Host "Remote access: 20 minutes idle / 40 minutes total. Local window remains open." -ForegroundColor Yellow
    Write-Host "History commands: :history on | off | clear | show | status" -ForegroundColor Gray
    Write-Host "Error review: :review last | auto on | auto off | show | clear | status" -ForegroundColor Gray
    Write-Host "No errors are shared unless explicitly queued for review." -ForegroundColor Gray
    Write-Host "History may contain secrets. Keep it OFF during sensitive work." -ForegroundColor Yellow
    Write-NativePrompt
    $typed = ""

    while ($script:TermyloRunning) {
        # Process ChatGPT commands only when no manual input is partially typed.
        if ($script:TermyloRemoteEnabled -and ($typed.Length -eq 0) -and $pending.IsCompleted) {
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
                if ($command -ceq "__TERMYLO_REVOKE_IPC__") {
                    $script:TermyloRemoteEnabled = $false
                    $output = "ChatGPT remote access expired. This terminal is now LOCAL ONLY."
                    Write-NativeText $output
                } else {
                    try {
                        # Executes in this persistent shell scope.
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
                if ($null -ne $pipe -and $pipe.IsConnected) { $pipe.Disconnect() }
                if (-not $script:TermyloRemoteEnabled) {
                    $pipe.Dispose()
                    $pipe = $null
                } elseif ($script:TermyloRunning) {
                    $pending = $pipe.BeginWaitForConnection($null, $null)
                }
                if ($script:TermyloRunning) { Write-NativePrompt }
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
                if ($manual.Trim() -match '^:history\s+(on|off|clear|show|status)$') {
                    $mode = $Matches[1].ToLowerInvariant()
                    switch ($mode) {
                        "on" {
                            $script:TermyloHistoryEnabled = $true
                            Write-Host "History ON (40 entries max, RAM only). May contain sensitive data." -ForegroundColor Yellow
                        }
                        "off" {
                            $script:TermyloHistoryEnabled = $false
                            $script:TermyloHistory.Clear()
                            Write-Host "History OFF and CLEARED."
                        }
                        "clear" { $script:TermyloHistory.Clear(); Write-Host "History CLEARED." }
                        "show" { Write-NativeText (Get-TermyloHistory -Last 10) }
                        "status" {
                            Write-Host ("History enabled: " + $script:TermyloHistoryEnabled + " | entries: " + $script:TermyloHistory.Count)
                        }
                    }
                } elseif ($manual.Trim() -match '^:review\s+(last|show|clear|status|auto\s+(on|off))$') {
                    $mode = $Matches[1].ToLowerInvariant()
                    switch ($mode) {
                        "last" {
                            if ($null -eq $script:TermyloLastError) {
                                Write-Host "No recent manual command error available to share."
                            } else {
                                Add-TermyloReviewEntry $script:TermyloLastError
                                Write-Host "Most recent error queued for ChatGPT review (RAM only)." -ForegroundColor Yellow
                            }
                        }
                        "show" { Write-NativeText (Get-TermyloSharedErrors -Last 5) }
                        "clear" {
                            $script:TermyloReviewQueue.Clear()
                            $script:TermyloLastError = $null
                            Write-Host "Review queue and most recent error CLEARED."
                        }
                        "status" {
                            Write-Host ("Review auto: " + $script:TermyloReviewAutoEnabled + " | queued: " + $script:TermyloReviewQueue.Count + " | latest manual error: " + ($null -ne $script:TermyloLastError))
                        }
                        "auto on" {
                            $script:TermyloReviewAutoEnabled = $true
                            Write-Host "Auto error review ON for this window only (RAM, 10 errors max)." -ForegroundColor Yellow
                            Write-Host "Errors are queued locally; ChatGPT cannot see them unless it requests the queue."
                        }
                        "auto off" {
                            $script:TermyloReviewAutoEnabled = $false
                            $script:TermyloReviewQueue.Clear()
                            $script:TermyloLastError = $null
                            Write-Host "Auto error review OFF. Pending reviews CLEARED."
                        }
                    }
                } elseif ($manual.Trim().Length -gt 0) {
                    # Collect *error records* even when general history is OFF.
                    # Do not retain stdout or successful commands for error review.
                    $Error.Clear()
                    $manualError = ""
                    $global:LASTEXITCODE = 0
                    if ($script:TermyloHistoryEnabled) {
                        $historyOutput = ""
                        try {
                            $historyOutput = [string](Invoke-Expression $manual *>&1 | Out-String -Width 240)
                            Write-NativeText $historyOutput
                        } catch {
                            $manualError = $_.ToString()
                            [Console]::WriteLine("ERROR: " + $manualError)
                        }
                        if ($Error.Count -gt 0 -and -not $manualError) {
                            $manualError = ($Error | Select-Object -First 3 | Out-String -Width 200)
                        } elseif ($global:LASTEXITCODE -ne 0 -and -not $manualError) {
                            $manualError = "External command exited with code " + $global:LASTEXITCODE
                        }
                        Save-TermyloHistory -Command $manual -Output $historyOutput -ErrorText $manualError
                    } else {
                        try {
                            Invoke-Expression $manual *>&1 | Out-Host
                        } catch {
                            $manualError = $_.ToString()
                            [Console]::WriteLine("ERROR: " + $manualError)
                        }
                        if ($Error.Count -gt 0 -and -not $manualError) {
                            $manualError = ($Error | Select-Object -First 3 | Out-String -Width 200)
                        } elseif ($global:LASTEXITCODE -ne 0 -and -not $manualError) {
                            $manualError = "External command exited with code " + $global:LASTEXITCODE
                        }
                    }
                    Save-TermyloErrorCandidate -Command $manual -ErrorText $manualError
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
