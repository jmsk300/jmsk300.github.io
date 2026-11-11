@echo off
cd /d "%~dp0"
python fishing_integrated.py
if errorlevel 1 pause
