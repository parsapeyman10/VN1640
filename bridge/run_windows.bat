@echo off
rem ===========================================================================
rem  NBCM CAN tester - one-click start on Windows
rem   1) starts the bridge (CANoe + COM + WebSocket + HTTP)
rem   2) opens the tester in a compact app-mode window
rem  Edit the CONFIG lines below once, then just double-click this file.
rem ===========================================================================
setlocal

rem ---- CONFIG ---------------------------------------------------------------
set CANOE_CFG=C:\CANoe\NBCM\NBCM.cfg
set PORT=8770
set WINDOW=1200x900
rem --------------------------------------------------------------------------

cd /d "%~dp0.."

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] python not found in PATH. Install Python 3.9+ and retry.
  pause & exit /b 1
)

echo [1/2] starting bridge on port %PORT% ...
start "NBCM Bridge" cmd /k python bridge\nbcm_bridge.py --canoe --port %PORT% --canoe-config "%CANOE_CFG%"

echo [2/2] waiting for the tester ...
timeout /t 4 /nobreak >nul
python bridge\nbcm_window.py --port %PORT% --size %WINDOW% --always-on-top

echo tester closed. The bridge window is still open; close it to stop CANoe access.
endlocal
