@echo off
echo MyCircle Automation Suite
echo ========================
echo.

echo Checking Python installation...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Python is not installed or not in PATH
    echo Please install Python from https://python.org
    echo After installation, run this script again
    echo.
    echo Installation steps:
    echo 1. Download Python from https://python.org/downloads/
    echo 2. Run the installer and check "Add Python to PATH"
    echo 3. Restart your command prompt
    echo 4. Run this script again
    pause
    exit /b 1
)

echo Python found! Installing dependencies...
pip install -r requirements.txt

echo.
echo Running MyCircle Automation Suite...
echo.

python mycircle_automation.py --action all

echo.
echo Automation complete! Check automation_report.md for results
pause
