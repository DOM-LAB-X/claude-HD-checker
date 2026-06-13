@echo off
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found. Install Python 3.10+ from https://www.python.org/downloads/
    echo and check "Add python.exe to PATH" during install, then re-run this script.
    pause
    exit /b 1
)

echo Creating virtual environment...
python -m venv venv

echo Installing dependencies...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt

echo Installing WebKit browser for Playwright...
playwright install webkit

echo.
echo Setup complete. Use run_once.bat to test a single check,
echo or run.bat to start the 3x/day scheduler.
pause
