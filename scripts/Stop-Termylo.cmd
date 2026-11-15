@echo off
setlocal
set "TERMYLO=%~dp0..\.venv\Scripts\termylo.exe"
if not exist "%TERMYLO%" (
  echo Termylo is not installed. Run scripts\setup.ps1 first.
  exit /b 1
)
"%TERMYLO%" stop
