@echo off
title Hope - Portal Job Applications (Prefill assistant)
cd /d "%~dp0"
setlocal enabledelayedexpansion

:menu
cls
echo ============================================================
echo   PICK A JOB - browser opens, form pre-fills, YOU submit
echo   (python prefill_apply.py --url ... --cv ...)
echo ============================================================
echo.
echo   [1]  Norrenberger IT Support  (Port Harcourt)
echo   [2]  Kenex IT Officer          (Port Harcourt)
echo   [3]  Royal Resource IT Support  (Abuja)
echo   [4]  Moniepoint IT Support     (Lagos)
echo   [5]  Jumia IT Support Rep      (Abuja)
echo   [6]  Kolomolo Junior AWS       (Remote - Cloud CV)
echo   [7]  Ubiminds IT Help Desk     (Remote)
echo   [8]  Careerswift IT Support    (Remote, $48-62k)
echo   [9]  Hire Hangar Help Desk MSP  (Remote)
echo  [10]  Apiphani Junior IT Eng    (Remote)
echo  [11]  Serrala Junior IT Support (Remote)
echo  [12]  Empire Mgmt SysAdmin      (Remote)
echo  [13]  Aquila Helpdesk           (Remote/US)
echo  [14]  Data2Bots Junior Dev ERP  (Abuja - Developer CV)
echo  [15]  EasyPay DBA/Network Admin (Port Harcourt)
echo.
echo   [q]  Quit
echo.
set "choice="
set /p choice="Pick a number (1-15): "

set "url="
set "cv=cv_pdfs\Hope_John_Sunday_CV_IT_Support.pdf"
if "%choice%"=="1" set "url=https://www.myjobmag.com/job/it-support-officer-norrenberger-financial-group"
if "%choice%"=="2" set "url=https://www.jobberman.com/listings/it-officer-rrn7rg"
if "%choice%"=="3" set "url=https://www.jobberman.com/listings/it-support-entry-level-j6pkne"
if "%choice%"=="4" set "url=https://www.myjobmag.com/job/it-support-officer-lagos-moniepoint"
if "%choice%"=="5" set "url=https://www.myjobmag.com/job/it-support-representative-jumia-nigeria-2"
if "%choice%"=="6" set "cv=cv_pdfs\Hope_John_Sunday_CV_Cloud_AWS.pdf" & set "url=https://jobs.kolomolo.com/jobs/7080951-junior-aws-engineer"
if "%choice%"=="7" set "url=https://jobera.com/job/ubiminds-it-help-desk-technician-568-45c6dfff/"
if "%choice%"=="8" set "url=https://jobs.ashbyhq.com/careerswift.ai/e1c8712b-6499-40e0-932a-aba0a2adfcd9"
if "%choice%"=="9" set "url=https://talentpulse.66ghz.com/remote-jobs/help-desk-support-technician-msp-2"
if "%choice%"=="10" set "url=https://joblume.totalh.net/job/junior-it-support-engineer"
if "%choice%"=="11" set "url=https://joblume.totalh.net/job/junior-it-support-specialist-3"
if "%choice%"=="12" set "url=https://hiring.camp/job/ZpA67L"
if "%choice%"=="13" set "url=https://hirenixa.10001mb.com/job/junior-helpdesk-support-technician-2"
if "%choice%"=="14" set "cv=cv_pdfs\Hope_John_Sunday_CV_Developer.pdf" & set "url=https://www.myjobmag.com/job/junior-software-developer-erp-python-javascript-data2bots"
if "%choice%"=="15" set "url=https://www.myjobmag.com/job/database-system-and-network-administrator-easypay"
if /i "%choice%"=="q" exit /b

if "%url%"=="" (
  echo Invalid choice: "%choice%"
  timeout /t 2 >nul
  goto menu
)

echo.
echo Opening: %url%
echo CV: %cv%
echo.
echo  ^>^> Fill the form, then press Enter in the assistant window to refill.
set "PYTHONIOENCODING=utf-8"
python prefill_apply.py --url "%url%" --cv "%cv%"
echo.
echo Done with this one - mark it in applications.csv.
pause
goto menu