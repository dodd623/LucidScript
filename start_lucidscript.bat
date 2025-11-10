@echo off
title LucidScript Launcher
echo Starting LucidScript server...
start cmd /k "uvicorn main:app --reload --port 8001"
timeout /t 3 >nul
echo Starting Cloudflare tunnel...
start cmd /k "cloudflared tunnel --url http://127.0.0.1:8001"
echo Done! You can now share the Cloudflare link shown in the second window.
pause
