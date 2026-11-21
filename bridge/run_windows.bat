@echo off
rem Tester + CANoe 12 over COM.  Optional: set CANOE_CFG to the .cfg to open,
rem or put {"canoe":{"config_path":"...cfg"}} in bridge\config.local.json.
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
if defined CANOE_CFG (
  %PY% "bridge\launcher.py" canoe --canoe-config "%CANOE_CFG%" %*
) else (
  %PY% "bridge\launcher.py" canoe %*
)
if errorlevel 1 pause
