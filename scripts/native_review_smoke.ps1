# Windows smoke test: inspect AST functions only; no terminal or tunnel opened.
$ErrorActionPreference = 'Stop'
$path = Join-Path $PSScriptRoot '..\termylo\native_console.ps1'
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    (Resolve-Path $path), [ref]$tokens, [ref]$errors
)
if ($errors.Count -gt 0) { throw 'Native terminal PowerShell syntax invalid.' }
$names = @(
    'Test-TermyloSensitive',
    'Add-TermyloReviewEntry',
    'Save-TermyloErrorCandidate',
    'Get-TermyloSharedErrors'
)
$nodes = $ast.FindAll({
    param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst]
}, $true)
foreach ($name in $names) {
    $node = $nodes | Where-Object Name -eq $name | Select-Object -First 1
    if (-not $node) { throw "Missing function $name" }
    . ([scriptblock]::Create($node.Extent.Text))
}
$script:TermyloReviewAutoEnabled = $false
$script:TermyloLastError = $null
$script:TermyloReviewQueue = [System.Collections.Generic.List[object]]::new()
$script:TermyloReviewLimit = 10
# Default: capture recent error locally, but never expose automatically.
Save-TermyloErrorCandidate -Command 'nonexistent-cmd' -ErrorText 'CommandNotFoundException'
if ($script:TermyloReviewQueue.Count -ne 0) { throw 'Default-off leaked error.' }
if ($null -eq $script:TermyloLastError) { throw 'Latest error unavailable.' }
if ((Get-TermyloSharedErrors -Consume) -notmatch 'No locally shared errors') {
    throw 'Unapproved error became remotely available.'
}
# Explicit physical :review last action.
Add-TermyloReviewEntry $script:TermyloLastError
$approved = Get-TermyloSharedErrors -Last 5 -Consume
if ($approved -notmatch 'nonexistent-cmd' -or $approved -notmatch 'CommandNotFoundException') {
    throw 'Explicitly shared error not retrievable.'
}
if ($script:TermyloReviewQueue.Count -ne 0) { throw 'Consume did not clear queue.' }
# Auto on: opt in for the current process, NOT Windows startup.
$script:TermyloReviewAutoEnabled = $true
Save-TermyloErrorCandidate -Command 'Get-Date' -ErrorText ''
if ($script:TermyloReviewQueue.Count -ne 0) { throw 'Successful command queued.' }
Save-TermyloErrorCandidate -Command 'nonexistent-again' -ErrorText 'CommandNotFoundException'
if ($script:TermyloReviewQueue.Count -ne 1) { throw 'Auto-on did not queue error.' }
# Possible sensitive contents should be entirely withheld, including command and error.
Save-TermyloErrorCandidate -Command '$env:API_KEY' -ErrorText 'sk-secretmaybepassword'
$queueText = Get-TermyloSharedErrors -Last 10
if ($queueText -match 'secretmaybepassword' -or $queueText -match 'API_KEY') {
    throw 'Sensitive error leaked to review queue.'
}
if ($queueText -notmatch 'omitted: possible sensitive content') {
    throw 'Secret redaction not working.'
}
# Bound the queue and clear on OFF.
1..20 | ForEach-Object {
    Save-TermyloErrorCandidate -Command ("err" + $_) -ErrorText "CommandNotFoundException"
}
if ($script:TermyloReviewQueue.Count -ne 10) { throw 'Queue cap failed.' }
$script:TermyloReviewAutoEnabled = $false
$script:TermyloReviewQueue.Clear()
$script:TermyloLastError = $null
if ($script:TermyloReviewQueue.Count -ne 0 -or $null -ne $script:TermyloLastError) {
    throw 'Auto-off did not clear.'
}
Write-Output 'PASS: error review default-off, manual share, auto-on, redaction, bounded queue, consume and clear.'
