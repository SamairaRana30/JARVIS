@echo off
title Jarvis Startup
echo Starting Jarvis AI System...

REM Request admin rights
net session >nul 2>&1
if %errorLevel% neq 0 (
    PowerShell -Command "Start-Process '%~f0' -Verb RunAs"
    exit
)

REM 1. Start Ollama (if not already running)
tasklist /FI "IMAGENAME eq ollama.exe" 2>NUL | find /I "ollama.exe" >NUL
if errorlevel 1 (
    echo Starting Ollama...
    start "" /min "C:\Users\samai\AppData\Local\Programs\Ollama\ollama.exe" serve
    timeout /t 4 /nobreak >NUL
)

REM 2. Start WhatsApp Personal bridge
echo Starting WhatsApp Personal...
start "WhatsApp Personal" /min cmd /c "cd /d C:\Users\samai\Desktop\Jarvis\Jarvis\whatsapp_bridge && node server.js"
timeout /t 2 /nobreak >NUL

REM 3. Start WhatsApp Uni bridge
echo Starting WhatsApp Uni...
start "WhatsApp Uni" /min cmd /c "cd /d C:\Users\samai\Desktop\Jarvis\Jarvis\whatsapp_bridge_uni && node server.js"
timeout /t 2 /nobreak >NUL

REM 4. Start Jarvis (shows HUD automatically)
echo Starting Jarvis...
cd /d C:\Users\samai\Desktop\Jarvis\Jarvis
start "" "C:\Users\samai\AppData\Local\Programs\Python\Python313\python.exe" tray_icon.py

echo All systems started. Jarvis is loading...
timeout /t 3 /nobreak >NUL
exit
