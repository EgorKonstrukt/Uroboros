@echo off
chcp 65001 >nul
title Uroboros Server

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found.
    echo Run: python -m venv .venv
    echo Then: .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

echo ^>^> Uroboros Server ^<^<
echo.
echo [1] Run full server (auth + admin dashboard)
echo [2] Start Minecraft server only
echo [3] Stop Minecraft server
echo [4] Show server status
echo [Q] Quit
echo.
choice /c 1234Q /n /m "Select action: "

if errorlevel 5 exit /b 0
if errorlevel 4 goto status
if errorlevel 3 goto stop
if errorlevel 2 goto start
if errorlevel 1 goto run

:run
echo.
echo Starting server at http://127.0.0.1:25581 ...
echo Admin dashboard: http://127.0.0.1:25581/admin/
echo.
.venv\Scripts\python.exe -m server run
pause
exit /b 0

:start
echo.
echo Starting Minecraft server ...
echo.
.venv\Scripts\python.exe -m server start
pause
exit /b 0

:stop
echo.
.venv\Scripts\python.exe -m server stop
pause
exit /b 0

:status
echo.
.venv\Scripts\python.exe -m server status
pause
exit /b 0
