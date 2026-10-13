@echo off
setlocal
set "APP_ROOT=%~dp0"
set "DATA_ROOT=%LOCALAPPDATA%\EvidenceOps\data"
if exist "%ProgramFiles%\PowerShell\7\pwsh.exe" set "PWSH=%ProgramFiles%\PowerShell\7\pwsh.exe"
if not defined PWSH for /f "delims=" %%P in ('where pwsh 2^>nul') do if not defined PWSH set "PWSH=%%P"
if not defined PWSH (
  echo 未找到 PowerShell 7，请重新运行安装程序。
  pause
  exit /b 1
)
"%PWSH%" -NoProfile -File "%APP_ROOT%\scripts\start_installed.ps1" -DataDirectory "%DATA_ROOT%"
endlocal
