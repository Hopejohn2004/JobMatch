@echo off
title Hope John Sunday - Daily Job Scan
cd /d "%~dp0"
set "LOG=%~dp0logs\daily_scan.log"
echo ============================================>> "%LOG%"
echo  Daily Job Scan Started: %date% %time%>> "%LOG%"
echo ============================================>> "%LOG%"
python job_scraper.py>> "%LOG%" 2>&1
echo  Scan finished: %date% %time%>> "%LOG%"