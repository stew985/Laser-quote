@echo off
cd /d "%~dp0"
title Nova Laser Quote v0.6 - PORT 8081
if not exist .venv\Scripts\python.exe (
  py -3 -m venv .venv
  if errorlevel 1 (echo Python 3 not found. Install Python 3.11+ and retry.& pause & exit /b 1)
)
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (echo Dependency installation failed.& pause & exit /b 1)
set NOVA_PORT=8081
echo.
echo ===================================================
echo NOVA LASER QUOTE v0.6 - MATERIALS DATABASE
echo Open http://localhost:8081
 echo This version uses port 8081 to avoid the old server.
echo ===================================================
start "" "http://localhost:8081"
.venv\Scripts\python.exe app.py
pause
