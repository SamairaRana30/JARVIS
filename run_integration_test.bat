@echo off
echo =============================================
echo  Jarvis Integration Tests
echo =============================================
echo.

cd /d "%~dp0"

echo Running full test suite...
python -m pytest tests/ -v --tb=short

echo.
echo =============================================
echo  Before running Jarvis for real:
echo  1. All tests above should pass
echo  2. Then start: python tray_icon.py
echo =============================================
pause
