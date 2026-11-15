# Terminal Context Engine optional per-user Windows package.
# No administrator rights and no separate search desktop application.
[CmdletBinding()]
param([switch]$WithModel,[switch]$Verify)
$ErrorActionPreference='Stop'
$Root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Python=Join-Path $Root '.venv\Scripts\python.exe'
if(-not(Test-Path -LiteralPath $Python)){throw 'Install Termylo first.'}
if($Verify){& $Python -m termylo.context_package status --verify}
elseif($WithModel){& $Python -m termylo.context_package install --with-model}
else{& $Python -m termylo.context_package install}
if($LASTEXITCODE -ne 0){throw 'Terminal Context Engine installation incomplete.'}