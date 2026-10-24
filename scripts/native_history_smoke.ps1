# PowerShell-only smoke test of opt-in, memory-only native terminal history.
$ErrorActionPreference = 'Stop'
$path = Join-Path $PSScriptRoot '..\termylo\native_console.ps1'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path $path), [ref]$tokens, [ref]$errors)
if ($errors.Count -gt 0) { throw 'Native console has syntax errors.' }

$names = @('Test-TermyloSensitive', 'Save-TermyloHistory', 'Get-TermyloHistory')
$nodes = $ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst]
}, $true)
foreach ($name in $names) {
    $node = $nodes | Where-Object Name -eq $name | Select-Object -First 1
    if (-not $node) { throw "Missing function: $name" }
    . ([scriptblock]::Create($node.Extent.Text))
}

$script:TermyloHistoryEnabled = $false
$script:TermyloHistory = [System.Collections.Generic.List[object]]::new()
$script:TermyloHistoryLimit = 40
Save-TermyloHistory -Command 'Get-Date' -Output 'OK' -ErrorText ''
if ($script:TermyloHistory.Count -ne 0) { throw 'Default-off history recorded data.' }
$script:TermyloHistoryEnabled = $true
Save-TermyloHistory -Command 'Get-Date' -Output 'OK' -ErrorText ''
Save-TermyloHistory -Command 'Does-Not-Exist' -Output '' -ErrorText 'CommandNotFoundException'
Save-TermyloHistory -Command '$env:API_KEY' -Output 'sk-supersecretmaterial' -ErrorText ''
if ($script:TermyloHistory.Count -ne 3) { throw 'Missing history entries.' }
$all = Get-TermyloHistory -Last 10
if ($all -notmatch 'Does-Not-Exist' -or $all -notmatch 'CommandNotFoundException') { throw 'Error not retrievable.' }
if ($all -match 'supersecretmaterial' -or $all -match 'API_KEY') { throw 'Secret leaked into history.' }
if ($all -notmatch 'omitted: possible sensitive content') { throw 'Secret redaction not applied.' }
$script:TermyloHistoryEnabled = $false
$script:TermyloHistory.Clear()
if ($script:TermyloHistory.Count -ne 0) { throw 'History not cleared.' }
Write-Output 'PASS: default off, manual command/error history, basic redaction, clear.'
