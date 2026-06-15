@echo off
cd /d "%~dp0"

echo ============================================================
echo HD Clearance Tracker - Release builder
echo ============================================================
echo.

if not exist "venv\Scripts\activate.bat" (
    echo ERROR: Virtual environment not found. Run setup.bat first.
    pause
    exit /b 1
)

set /p VERSION=Enter version number (e.g. 1.0.1):
if "%VERSION%"=="" (
    echo ERROR: Version cannot be empty.
    pause
    exit /b 1
)

echo %VERSION%> version.txt
echo Version set to %VERSION%.

echo.
echo Building exe...
call venv\Scripts\activate.bat
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
echo Zipping release...
if exist "HD-Tracker.zip" del "HD-Tracker.zip"
powershell -Command "Compress-Archive -Path 'dist\HD-Tracker' -DestinationPath 'HD-Tracker.zip'"

if errorlevel 1 (
    echo Zip failed.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo Release built: HD-Tracker.zip
echo ============================================================
echo.
echo Next steps:
echo  1. Commit and push your changes to GitHub
echo  2. Go to: https://github.com/DOM-LAB-X/claude-HD-checker/releases/new
echo  3. Tag: v%VERSION%
echo  4. Attach: HD-Tracker.zip  (from this folder)
echo  5. Publish the release
echo.
echo The app will notify users to update automatically.
echo.
start "" "https://github.com/DOM-LAB-X/claude-HD-checker/releases/new"
pause
