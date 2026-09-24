@echo off
title Auto-Retry Service (Antigravity)
echo.
echo  ========================================
echo   Auto-Retry Background Service
echo   Auto-clicks "Retry" on agent errors
echo  ========================================
echo.
echo  Keep this window open while working.
echo  Press Ctrl+C to stop.
echo.

cd /d "%~dp0"

set PYTHON_PATH="C:\Users\xxixw\AppData\Local\Programs\Python\Python310\python.exe"

if exist %PYTHON_PATH% (
    %PYTHON_PATH% antigravity_retry_clicker.py
) else (
    echo Python 3.10 path not found. Trying default 'python'...
    python antigravity_retry_clicker.py
    if %errorlevel% neq 0 (
        echo.
        echo Default python failed. Trying 'python3'...
        python3 antigravity_retry_clicker.py
    )
)

echo.
echo  Service stopped. Press any key to restart...
pause >nul
goto :retry
