@echo off
echo ========================================
echo   Auto-Prompt Workflow Runner
echo   MyCircle Automation Suite
echo ========================================
echo.

REM Navigate to automation directory
cd /d "%~dp0"

REM Check Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python not found. Please install Python 3.8+
    pause
    exit /b 1
)

echo Starting Auto-Prompt Workflow GUI...
echo.
python auto_prompt_gui.py
if %errorlevel% neq 0 (
    echo.
    echo GUI exited with errors. Check the output above.
    pause
)
