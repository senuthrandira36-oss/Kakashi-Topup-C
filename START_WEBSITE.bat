@echo off
title Kakashi Topup Center
cd /d "%~dp0"
echo ==========================================
echo      KAKASHI TOPUP CENTER
echo ==========================================
echo.
where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py"
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (set "PY=python") else (
        echo Python is not installed.
        echo Install Python from https://www.python.org/downloads/
        pause
        exit /b 1
    )
)
echo Installing required packages...
%PY% -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo Package installation failed.
    pause
    exit /b 1
)
echo.
echo Starting website...
echo Keep this window open while using the website.
echo.
%PY% app.py
pause
