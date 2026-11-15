@echo off
setlocal EnableExtensions
set "ROOT=%~dp0.."
if defined TCE_SWIFT_BIN set "PATH=%TCE_SWIFT_BIN%;%PATH%"
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist "%VSWHERE%" (
 echo ERROR: Visual Studio Build Tools required. 1>&2
 exit /b 2
)
for /f "usebackq delims=" %%I in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VSINSTALL=%%I"
if not defined VSINSTALL exit /b 2
call "%VSINSTALL%\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 2
where swift.exe >nul 2>&1
if errorlevel 1 (
 echo ERROR: Install Swift 6.3.3 or define TCE_SWIFT_BIN. 1>&2
 exit /b 2
)
pushd "%ROOT%"
swift build -c release -j 4 --product tce
set "RC=%ERRORLEVEL%"
popd
exit /b %RC%
