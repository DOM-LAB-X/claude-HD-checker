@echo off
cd /d "%~dp0"
call venv\Scripts\activate.bat
echo Starting scheduler. Keep this window open - closing it stops the tracker.
python src\scheduler.py
pause
