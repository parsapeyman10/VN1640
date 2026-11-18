@echo off
rem Start the tester WITHOUT CANoe - for designing scenarios at the desk.
cd /d "%~dp0.."
start "NBCM Bridge (sim)" cmd /k python bridge\nbcm_bridge.py --sim
timeout /t 3 /nobreak >nul
start "" "http://127.0.0.1:8771/"
endlocal
