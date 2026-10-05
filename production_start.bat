@echo off
REM production_start.bat - Start JobMatch with production settings (Windows)

echo ==========================================
echo   JobMatch Production Startup
echo ==========================================

REM Load environment variables from .env if exists
if exist .env (
    for /f "usebackq delims=" %%a in (".env") do (
        set "%%a"
    )
    echo Loaded .env
) else (
    echo WARNING: No .env file found. Using defaults.
)

REM Check required environment variables
if not defined PAYSTACK_SECRET_KEY echo WARNING: PAYSTACK_SECRET_KEY not set - billing will not work
if not defined PAYSTACK_PUBLIC_KEY echo WARNING: PAYSTACK_PUBLIC_KEY not set - billing will not work

REM Check for at least one LLM provider
set LLM_SET=false
if defined GEMINI_API_KEY (echo LLM Provider configured: GEMINI_API_KEY & set LLM_SET=true)
if defined GROQ_API_KEY (echo LLM Provider configured: GROQ_API_KEY & set LLM_SET=true)
if defined OPENROUTER_API_KEY (echo LLM Provider configured: OPENROUTER_API_KEY & set LLM_SET=true)
if defined OPENAI_API_KEY (echo LLM Provider configured: OPENAI_API_KEY & set LLM_SET=true)

if "%LLM_SET%"=="false" echo WARNING: No LLM provider configured - CV tailoring will not work

REM Check email provider
if defined RESEND_API_KEY (
    echo Email provider: Resend
) else if defined HOPE_GMAIL_USER if defined HOPE_GMAIL_APP_PASS (
    echo Email provider: Gmail SMTP
) else (
    echo WARNING: No email provider configured - email sending will not work
)

REM Check Redis
if defined REDIS_URL (
    echo Rate limiting: Redis (%REDIS_URL%)
) else (
    echo Rate limiting: In-memory (not suitable for production scaling)
)

REM Initialize database
echo.
echo Initializing database...
python -c "import database; database.init_db(); print('Database ready')"

REM Start the application
echo.
echo Starting JobMatch on port 5000...
echo Cloudflare Tunnel: cloudflared tunnel --url http://localhost:5000
echo ==========================================

REM Check if gunicorn is available
where gunicorn >nul 2>nul
if %ERRORLEVEL% equ 0 (
    echo Using gunicorn (production)
    gunicorn --bind 0.0.0.0:5000 --workers 4 --threads 2 --timeout 1800 web_app:app
) else (
    echo gunicorn not found, using Flask dev server (not for production)
    python web_app.py
)