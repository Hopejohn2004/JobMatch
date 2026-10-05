@echo off
title Hope John Sunday - Daily Job Scan
cd /d "%~dp0"
echo ============================================
echo  Daily Job Scan Started: %date% %time%
echo ============================================
python job_scraper.py
echo.
echo Scan complete. Review these files:
echo   - data\new_jobs_alert.json (NEW jobs since yesterday)
echo   - data\scanned_jobs.json   (full results)
echo   - data\daily_scans\        (dated snapshots)
echo.
pause