@echo off
REM shiban-store — Windows 启动器（v0.5.0）
setlocal
set "SELF=%~dp0"
set "PKG=%SELF%..\.."
set "CLI=%PKG%\vendor\services\shiban_cli.py"

if defined SHIBAN_PY (
  set "PY=%SHIBAN_PY%"
) else (
  where python >nul 2>&1 && (set "PY=python") || (set "PY=py")
)
if not exist "%CLI%" (
  echo [error] 缺少 CLI: %CLI% 1>&2
  exit /b 2
)
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
"%PY%" "%CLI%" %*
exit /b %ERRORLEVEL%
