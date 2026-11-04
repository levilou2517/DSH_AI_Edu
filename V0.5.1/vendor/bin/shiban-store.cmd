@echo off
REM shiban-store - Windows launcher (v0.5.1, cross-platform, no hard-coded paths)
REM
REM Python resolution order (same as the bash launcher):
REM   1. %SHIBAN_PY% (explicit)
REM   2. %PKG%\.venv\Scripts\python.exe
REM   3. python / py on PATH
REM   4. DSH bundled runtime under %USERPROFILE%\.dsh\dsh-runtimes\*\dependencies\python\python.exe
REM
REM Requires Python >= 3.10. Fails loudly instead of surfacing a SyntaxError later.
setlocal EnableDelayedExpansion

set "SELF=%~dp0"
set "PKG=%~dp0..\.."
for %%I in ("%PKG%") do set "PKG=%%~fI"
set "CLI=%PKG%\vendor\services\shiban_cli.py"
set "MIN_MAJOR=3"
set "MIN_MINOR=10"

if not exist "%CLI%" (
  echo [error] Missing CLI: "%CLI%" ^(package may be incompletely extracted^) 1>&2
  exit /b 2
)

set "PY="

REM 1. explicit
if defined SHIBAN_PY (
  "%SHIBAN_PY%" -c "" >nul 2>&1 && set "PY=%SHIBAN_PY%"
  if not defined PY (
    echo [error] SHIBAN_PY="%SHIBAN_PY%" cannot be executed 1>&2
    exit /b 2
  )
)

REM 2. package-local venv
if not defined PY (
  if exist "%PKG%\.venv\Scripts\python.exe" (
    "%PKG%\.venv\Scripts\python.exe" -c "" >nul 2>&1 && set "PY=%PKG%\.venv\Scripts\python.exe"
  )
)

REM 3. PATH
if not defined PY (
  for %%C in (python py) do (
    if not defined PY (
      where %%C >nul 2>&1 && %%C -c "" >nul 2>&1 && set "PY=%%C"
    )
  )
)

REM 4. DSH bundled runtime
if not defined PY (
  for /d %%D in ("%USERPROFILE%\.dsh\dsh-runtimes\*") do (
    if not defined PY (
      if exist "%%D\dependencies\python\python.exe" (
        "%%D\dependencies\python\python.exe" -c "" >nul 2>&1 && set "PY=%%D\dependencies\python\python.exe"
      )
    )
  )
)

if not defined PY (
  echo [error] Python 3 not found. Install Python 3.10+ or set SHIBAN_PY to an interpreter. 1>&2
  exit /b 2
)

REM Version gate: fail loudly, never let Python raise SyntaxError later.
set "PYVER=0.0"
for /f "delims=" %%V in ('"%PY%" -c "import sys;print(str(sys.version_info[0])+'.'+str(sys.version_info[1]))" 2^>nul') do set "PYVER=%%V"
for /f "tokens=1,2 delims=." %%A in ("!PYVER!") do (
  set "PYMAJ=%%A"
  set "PYMIN=%%B"
)
if not defined PYMAJ set "PYMAJ=0"
if not defined PYMIN set "PYMIN=0"

set "TOOOLD="
if !PYMAJ! LSS %MIN_MAJOR% set "TOOOLD=1"
if !PYMAJ! EQU %MIN_MAJOR% if !PYMIN! LSS %MIN_MINOR% set "TOOOLD=1"
if defined TOOOLD (
  echo [error] Requires Python ^>= %MIN_MAJOR%.%MIN_MINOR%, current is !PYVER! ^(%PY%^). 1>&2
  echo         Upgrade Python, or set SHIBAN_PY to a 3.10+ interpreter. 1>&2
  exit /b 2
)

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PYTHONLEGACYWINDOWSSTDIO=0

"%PY%" "%CLI%" %*
exit /b %ERRORLEVEL%
