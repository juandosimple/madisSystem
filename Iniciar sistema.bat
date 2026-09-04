@echo off
cd /d "%~dp0motor"
python app.py
if errorlevel 1 pause
