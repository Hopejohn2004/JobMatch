@echo off
title Hope - Job Toolkit Web App (phone access)
cd /d "%~dp0"
echo ============================================================
echo  Starting web app - keep this window open, then use your
echo  phone on the same Wi-Fi to open the address shown below.
echo ============================================================
set "PYTHONIOENCODING=utf-8"
python web_app.py
pause