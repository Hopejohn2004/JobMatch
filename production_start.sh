#!/usr/bin/env bash
# production_start.sh - Start JobMatch with production settings
# Usage: ./production_start.sh

set -e

echo "=========================================="
echo "  JobMatch Production Startup"
echo "=========================================="

# Load environment variables
if [ -f .env ]; then
    export $(cat .env | xargs)
    echo "Loaded .env"
else
    echo "WARNING: No .env file found. Using defaults."
fi

# Check required environment variables
REQUIRED_VARS=("PAYSTACK_SECRET_KEY" "PAYSTACK_PUBLIC_KEY")
for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var}" ]; then
        echo "WARNING: $var not set - billing will not work"
    fi
done

# Check for at least one LLM provider
LLM_VARS=("GEMINI_API_KEY" "GROQ_API_KEY" "OPENROUTER_API_KEY" "OPENAI_API_KEY")
LLM_SET=false
for var in "${LLM_VARS[@]}"; do
    if [ -n "${!var}" ]; then
        LLM_SET=true
        echo "LLM Provider configured: $var"
    fi
done

if [ "$LLM_SET" = false ]; then
    echo "WARNING: No LLM provider configured - CV tailoring will not work"
fi

# Check email provider
if [ -n "$RESEND_API_KEY" ]; then
    echo "Email provider: Resend"
elif [ -n "$HOPE_GMAIL_USER" ] && [ -n "$HOPE_GMAIL_APP_PASS" ]; then
    echo "Email provider: Gmail SMTP"
else
    echo "WARNING: No email provider configured - email sending will not work"
fi

# Check Redis
if [ -n "$REDIS_URL" ]; then
    echo "Rate limiting: Redis ($REDIS_URL)"
else
    echo "Rate limiting: In-memory (not suitable for production scaling)"
fi

# Initialize database
echo ""
echo "Initializing database..."
python -c "import database; database.init_db(); print('Database ready')"

# Start the application
echo ""
echo "Starting JobMatch on port 5000..."
echo "Cloudflare Tunnel: cloudflared tunnel --url http://localhost:5000"
echo "=========================================="

# Run with gunicorn for production (or python for dev)
if command -v gunicorn &> /dev/null; then
    exec gunicorn --bind 0.0.0.0:5000 --workers 4 --threads 2 --timeout 1800 web_app:app
else
    echo "gunicorn not found, using Flask dev server (not for production)"
    exec python web_app.py
fi