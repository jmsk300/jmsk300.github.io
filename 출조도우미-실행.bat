@echo off
cd /d "%~dp0"
python outing_helper.py
if errorlevel 1 pause
