@echo off
echo Starting Jarvis WhatsApp Bridges...

REM Personal WhatsApp (port 5765)
start "WhatsApp Personal" /min cmd /c "cd /d C:\Users\samai\Desktop\Jarvis\Jarvis\whatsapp_bridge && node server.js"

REM Uni WhatsApp (port 5766)
start "WhatsApp Uni" /min cmd /c "cd /d C:\Users\samai\Desktop\Jarvis\Jarvis\whatsapp_bridge_uni && node server.js"

echo Both WhatsApp bridges started in background.
