@echo off
rem Tester only - no CANoe needed.  For designing scenarios at the desk.
rem All the logic lives in launcher.py; this file just finds Python and calls it.
cd /d "%~dp0.."
set "PY="
for %%C in ("py -3" "python" "python3") do if not defined PY (
  %%~C -c "import sys;sys.exit(0 if sys.version_info>=(3,8) else 1)" >nul 2>nul
  if not errorlevel 1 set "PY=%%~C"
)
if not defined PY (
  echo [ERROR] Python 3.8+ not found. Install it from python.org
  echo         and tick "Add python.exe to PATH".
  pause & exit /b 1
)
%PY% "bridge\launcher.py" sim %*
if errorlevel 1 pause
