@echo off
cd /d "%~dp0"

echo ============================================================
echo  HD Clearance Tracker - Release (Windows)
echo ============================================================
echo.

set /p CURRENT=<version.txt
echo Current version: %CURRENT%
echo.
set /p VERSION=Enter new version (e.g. 1.0.1):
if "%VERSION%"=="" (
    echo ERROR: Version cannot be empty.
    pause
    exit /b 1
)

set TAG=v%VERSION%

echo.
echo Updating version.txt to %VERSION%...
echo %VERSION%> version.txt

echo Committing version bump...
git add version.txt
git commit -m "Release %TAG%"

echo Tagging %TAG%...
git tag %TAG%

echo Pushing to GitHub...
git push origin main
git push origin %TAG%

echo.
echo ============================================================
echo  Tag %TAG% pushed.
echo  GitHub Actions will now:
echo    1. Build HD-Tracker.app  (macOS)
echo    2. Build HD-Tracker.exe  (Windows)
echo    3. Publish a GitHub Release with both zips
echo.
echo  Track progress:
echo  https://github.com/DOM-LAB-X/claude-HD-checker/actions
echo ============================================================
echo.
start "" "https://github.com/DOM-LAB-X/claude-HD-checker/actions"
pause
