@echo off
cd /d "%~dp0"
call venv\Scripts\activate.bat

echo Building HD-Tracker.exe (this can take a minute)...
pyinstaller --noconfirm --onedir --windowed --name "HD-Tracker" --icon icon.ico ^
    --add-data "config.yaml;." ^
    --add-data "watchlist.txt;." ^
    --add-data "icon.ico;." ^
    --add-data "version.txt;." ^
    --collect-all greenlet ^
    --collect-all playwright ^
    src\tray_app.py

if errorlevel 1 (
    echo Build failed - see errors above.
    pause
    exit /b 1
)

echo.
echo Build complete: dist\HD-Tracker.exe
echo Creating desktop shortcut...
cscript //nologo create_shortcut.vbs

echo.
echo Done! Look for "HD Clearance Tracker" on your Desktop.
pause
