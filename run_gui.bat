@echo off
title MyCircle Automation Suite
echo ========================================
echo    MyCircle Automation GUI
echo ========================================
echo.

echo Checking Python installation...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Python is not installed or not in PATH
    echo.
    echo Please install Python from https://python.org
    echo After installation, run this script again
    echo.
    echo Installation steps:
    echo 1. Download Python from https://python.org/downloads/
    echo 2. Run the installer and check "Add Python to PATH"
    echo 3. Restart this script
    echo.
    pause
    exit /b 1
)

echo Python found! Starting GUI...
echo.

REM Check if tkinter is available (should come with Python)
python -c "import tkinter" >nul 2>&1
if %errorlevel% neq 0 (
    echo tkinter module not found. Installing...
    pip install tk
)

echo Installing required packages...
pip install -r requirements.txt >nul 2>&1

echo.
echo Starting MyCircle Automation GUI...
echo.

python automation_gui.py

echo.
echo GUI closed. Thank you for using MyCircle Automation!
pause
