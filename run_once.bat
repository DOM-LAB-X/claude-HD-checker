@echo off
cd /d "%~dp0"
call venv\Scripts\activate.bat
python src\run_cycle.py
pause
