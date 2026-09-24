@echo off
title Auto-Accept Service (Antigravity)
echo.
echo  ========================================
echo   Auto-Accept Background Service
echo   Auto-clicks "Allow / Run / Confirm"
echo   in Antigravity
echo  ========================================
echo.
echo  Keep this window open while working.
echo  Press Ctrl+C to stop.
echo.

cd /d i:\Path\Projects\automation

:retry
python auto_accept.py --editor antigravity --interval 2.0
if %errorlevel% neq 0 (
    echo.
    echo  Python not found or error occurred.
    echo  Retrying with 'python3'...
    python3 auto_accept.py --editor antigravity --interval 2.0
)

echo.
echo  Service stopped. Press any key to restart...
pause >nul
goto retry
