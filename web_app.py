"""
web_app.py - Phone-friendly control panel for the job-hunting toolkit.

Runs on the laptop (Flask development server) and serves a mobile-first
dashboard you can open from your phone on the same Wi-Fi network.

Actions available from the phone:
  - Run the full job scan          (job_scraper.py)
  - Run the worldwide career crawl (career_crawler.py)
  - Import new jobs to tracker     (import_scanned_jobs.py)
  - Prepare / preview email apps   (extract_email_targets.py + dry-run)
  - Send the email batch           (send_applications.py --send)  [PIN required]
  - Update tracker statuses        (applications.csv)

Access:
  - On the laptop itself:        http://127.0.0.1:5000
  - From your phone (same Wi-Fi): http://<this computer's LAN IP>:5000
      (allow Python through Windows Firewall when prompted the first time)

PIN: the sending of emails is protected by a PIN stored in  web_pin.env
     (auto-created with a random PIN on first run - it is printed once in this console).
"""
import csv
import json
import logging
import os
import random
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
from functools import wraps

from flask import Flask, jsonify, redirect, render_template_string, request, send_file, session, g
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

import database
import auth

BASE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE, 'applications.csv')
PIN_PATH = os.path.join(BASE, 'web_pin.env')
ADMIN_PATH = os.path.join(BASE, 'web_admin.env')
SESSION_KEY_PATH = os.path.join(BASE, 'web_secret.env')
SCANNED_PATH = os.path.join(BASE, 'data', 'scanned_jobs.json')
NEWJOBS_PATH = os.path.join(BASE, 'data', 'new_jobs_alert.json')
CAREER_PATH = os.path.join(BASE, 'data', 'career_jobs.json')
TARGETS_PATH = os.path.join(BASE, 'data', 'email_targets.json')
DASHBOARD_PATH = os.path.join(BASE, 'web_dashboard.html')
RESULTS_PATH = os.path.join(BASE, 'data', 'customer_results.json')

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024

# Trust Cloudflare Tunnel / reverse proxy headers for HTTPS detection
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1, x_prefix=1)

# ---------------------------------------------------------------- logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s'
)
logger = logging.getLogger('jobmatch')

# ---------------------------------------------------------------- rate limiting
if os.environ.get('PYTEST_DISABLE_RATELIMIT') == '1':
    # Disable rate limiting for tests
    class NoOpLimiter:
        def limit(self, *args, **kwargs):
            def decorator(f):
                return f
            return decorator
    limiter = NoOpLimiter()
else:
    # Use Redis for production rate limiting, memory:// for local dev
    redis_url = os.environ.get('REDIS_URL', 'memory://')
    limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=["200 per day", "50 per hour"],
        storage_uri=redis_url,
    )

# ---------------------------------------------------------------- auth
def get_secret():
    try:
        with open(SESSION_KEY_PATH, encoding='utf-8') as f:
            key = f.read().strip()
        if len(key) >= 16:
            return key
    except Exception:
        pass
    key = os.urandom(24).hex()
    with open(SESSION_KEY_PATH, 'w', encoding='utf-8') as f:
        f.write(key)
    return key


app.secret_key = get_secret()
SETUP_MODE = not os.path.exists(ADMIN_PATH)


def get_admin_pass():
    try:
        with open(ADMIN_PATH, encoding='utf-8') as f:
            ap = f.read().strip()
        if ap:
            return ap
    except Exception:
        pass
    return None


def is_authed():
    return bool(session.get('authed'))


# Endpoints reachable BEFORE any authentication. This is an exact-match
# allow-list checked against request.path, so a route template such as
# '/api/customers/<int:customer_id>' would never match a real request and is
# not a usable entry here - only literal paths belong in this set.
#
# Everything else under /api/ and /files/ requires a customer session or the
# admin password. Keep this list as small as possible.
PUBLIC_ENDPOINTS = {'/api/login', '/api/status_setup', '/api/auth_state'}


def _is_local_request() -> bool:
    """True when the request came from this machine (first-run setup only)."""
    addr = (get_remote_address() or '')
    if addr in ('127.0.0.1', '::1', 'localhost'):
        return True
    return addr.startswith('127.')


def is_admin() -> bool:
    """True when the caller holds a valid admin (dashboard gate) session."""
    return bool(session.get('authed'))


def require_admin(f):
    """Reject the request unless it carries a valid admin session."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not is_admin():
            logger.warning("Admin-only endpoint %s refused to %s",
                           request.path, get_remote_address())
            return jsonify({'ok': False, 'error': 'admin authentication required'}), 401
        return f(*args, **kwargs)
    return wrapper


# Fields that must never leave the server in an API response.
_SECRET_CUSTOMER_FIELDS = ('password_hash', 'paystack_auth_code')


def public_customer(row) -> dict:
    """Customer row as JSON, with credential material stripped out."""
    if row is None:
        return {}
    d = dict(row)
    for field in _SECRET_CUSTOMER_FIELDS:
        d.pop(field, None)
    return d


def customer_col(row, name: str, default=None):
    """Read an optional column that older databases may not have yet."""
    if row is None:
        return default
    try:
        if name not in row.keys():
            return default
    except AttributeError:
        return default
    value = row[name]
    return default if value is None else value


@app.route('/api/auth_state')
def api_auth_state():
    return jsonify({'setup': SETUP_MODE or (get_admin_pass() is None),
                    'authed': is_authed()})


@app.before_request
def gate():
    if request.path in PUBLIC_ENDPOINTS:
        return None
    if request.path.startswith(('/api/', '/files/')):
        # No admin password has been chosen yet. Fail CLOSED for anything that
        # is not coming from this machine: previously this returned None
        # (allow) for every /api/* path, which left the whole API - including
        # /api/customers and the job runners - open to anyone on the network.
        if SETUP_MODE and get_admin_pass() is None:
            if not _is_local_request():
                logger.warning("Blocked unauthenticated %s %s from %s during first-run setup",
                               request.method, request.path, get_remote_address())
                return jsonify({'ok': False, 'error': 'server not initialised',
                                'setup': True}), 403
            return None  # first-run setup from the laptop itself

        # Check for customer authentication first (cookie-based)
        customer_id = auth.get_current_customer_id()
        if customer_id is not None:
            g.customer_id = customer_id
            return None

        # Check for admin switched customer context
        if is_authed():
            active_cust_id = session.get('active_customer_id')
            if active_cust_id is not None:
                g.customer_id = active_cust_id
                return None

        # Fall back to admin authentication
        if not is_authed():
            return jsonify({'ok': False, 'auth': False, 'error': 'login required'}), 401
    return None


@app.route('/api/login', methods=['POST'])
@limiter.limit("5 per minute")
def api_login():
    data = request.json or {}
    if get_admin_pass() and data.get('password') == get_admin_pass():
        logger.info("Authentication successful from %s", get_remote_address())
        session['authed'] = True
        return jsonify({'ok': True})
    logger.warning("Authentication failed from %s", get_remote_address())
    return jsonify({'ok': False, 'error': 'wrong password'}), 401


@app.route('/api/status_setup', methods=['POST'])
def api_status_setup():
    """First run: set the admin password (before the gate is enforced)."""
    global SETUP_MODE
    # Only this machine may perform first-run setup. Without this check any host
    # that can reach the port could claim the admin password before the owner.
    if not _is_local_request():
        logger.warning("Blocked remote first-run setup attempt from %s", get_remote_address())
        return jsonify({'ok': False, 'error': 'setup is only allowed from the local machine'}), 403
    if not SETUP_MODE and get_admin_pass():
        return jsonify({'ok': False, 'error': 'already set up'}), 400
    pwd = (request.json or {}).get('password', '')
    if len(pwd) < 6:
        return jsonify({'ok': False, 'error': 'password too short (min 6)'}), 400
    with open(ADMIN_PATH, 'w', encoding='utf-8') as f:
        f.write(pwd)
    SETUP_MODE = False
    session['authed'] = True
    return jsonify({'ok': True, 'out': 'admin password set. You are logged in.'})


@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify({'ok': True})


# ---------------------------------------------------------------- Customer Authentication
@app.route('/auth/register', methods=['POST'])
@limiter.limit("5 per hour")
def api_customer_register():
    """Register a new customer account."""
    data = request.json or {}
    name = str(data.get('name', '')).strip()
    email = str(data.get('email', '')).strip().lower()
    password = str(data.get('password', ''))
    location = str(data.get('location', '')).strip() or None
    country = str(data.get('country', 'nigeria')).strip()
    
    if not name:
        return jsonify({'ok': False, 'error': 'name required'}), 400
    if len(name) > 100:
        return jsonify({'ok': False, 'error': 'name too long (max 100)'}), 400
    if not email:
        return jsonify({'ok': False, 'error': 'email required'}), 400
    if len(email) > 254:
        return jsonify({'ok': False, 'error': 'email too long'}), 400
    if not password:
        return jsonify({'ok': False, 'error': 'password required'}), 400
    if len(password) < 8:
        return jsonify({'ok': False, 'error': 'password must be at least 8 characters'}), 400
    if len(password) > 128:
        return jsonify({'ok': False, 'error': 'password too long'}), 400
    
    success, result, token = auth.register_customer(name, email, password, location, country)
    if not success:
        return jsonify({'ok': False, 'error': result}), 400
    
    customer_id = result
    response = jsonify({'ok': True, 'customer_id': customer_id})
    auth.set_session_cookie(response, token)
    logger.info("Customer registered: %s (%s)", name, email)
    return response


@app.route('/auth/public_signup', methods=['POST'])
@limiter.limit("5 per hour")
def api_public_signup():
    """
    Public landing page signup: creates customer + initial profile with keywords,
    sets session cookie, and redirects to dashboard.
    Accepts form data or JSON.
    """
    if request.is_json:
        data = request.json or {}
    else:
        data = request.form or {}
    
    name = str(data.get('name', '')).strip()
    email = str(data.get('email', '')).strip().lower()
    password = str(data.get('password', ''))
    keywords = str(data.get('keywords', '')).strip()
    location = str(data.get('location', 'remote')).strip() or 'remote'
    country = str(data.get('country', 'nigeria')).strip()
    
    # Validation
    if not name:
        return jsonify({'ok': False, 'error': 'name required'}), 400
    if len(name) > 100:
        return jsonify({'ok': False, 'error': 'name too long (max 100)'}), 400
    if not email:
        return jsonify({'ok': False, 'error': 'email required'}), 400
    if len(email) > 254:
        return jsonify({'ok': False, 'error': 'email too long'}), 400
    if not password:
        return jsonify({'ok': False, 'error': 'password required'}), 400
    if len(password) < 8:
        return jsonify({'ok': False, 'error': 'password must be at least 8 characters'}), 400
    if len(password) > 128:
        return jsonify({'ok': False, 'error': 'password too long'}), 400
    if not keywords:
        return jsonify({'ok': False, 'error': 'target job keywords required'}), 400
    if len(keywords) > 500:
        return jsonify({'ok': False, 'error': 'keywords too long (max 500)'}), 400
    
    # Register customer
    success, result, token = auth.register_customer(name, email, password, location, country)
    if not success:
        return jsonify({'ok': False, 'error': result}), 400
    
    customer_id = result
    
    # Create initial profile with keywords
    database.create_or_update_profile(
        customer_id=customer_id,
        keywords=keywords,
        preferred_locations=location,
        job_types='',
        target_roles='',
        home_country=country,
    )
    
    # Set session cookie and redirect to dashboard
    response = redirect('/')
    auth.set_session_cookie(response, token)
    logger.info("Public signup: %s (%s) - keywords: %s", name, email, keywords[:80])
    return response


@app.route('/auth/login', methods=['POST'])
@limiter.limit("10 per minute")
def api_customer_login():
    """Log in a customer."""
    data = request.json or {}
    email = str(data.get('email', '')).strip().lower()
    password = str(data.get('password', ''))
    
    if not email or not password:
        return jsonify({'ok': False, 'error': 'email and password required'}), 400
    
    success, result, token = auth.login_customer(email, password)
    if not success:
        logger.warning("Customer login failed for %s from %s", email, get_remote_address())
        return jsonify({'ok': False, 'error': result}), 401
    
    customer_id = result
    response = jsonify({'ok': True, 'customer_id': customer_id})
    auth.set_session_cookie(response, token)
    logger.info("Customer login: %s", email)
    return response


@app.route('/auth/logout', methods=['POST'])
def api_customer_logout():
    """Log out the current customer."""
    auth.logout_customer()
    response = jsonify({'ok': True})
    auth.clear_session_cookie(response)
    return response


# ---------------------------------------------------------------- Paystack Billing
PAYSTACK_SECRET_KEY = os.environ.get('PAYSTACK_SECRET_KEY', '')
PAYSTACK_PUBLIC_KEY = os.environ.get('PAYSTACK_PUBLIC_KEY', '')
PAYSTACK_PLAN_CODE = os.environ.get('PAYSTACK_PLAN_CODE', 'PLN_jobmatch_monthly')
PLAN_PRICE_NGN = 150000  # ₦1,500 in kobo


# Billable task names. These strings are the join key between a quota
# reservation and the quota check, so the two sides must match exactly.
TASK_SCAN = 'Scan for jobs'
TASK_TAILOR = 'Tailor CVs'


def check_usage_limit(customer_id: int, resource: str) -> tuple[bool, str]:
    """Check if customer has quota for resource."""
    cust = database.get_customer(customer_id)
    if not cust:
        return False, 'customer not found'

    # Optional columns: older databases predate billing, so read defensively.
    sub_status = customer_col(cust, 'subscription_status', 'trial')
    if sub_status not in ('active', 'trial'):
        return False, 'subscription required'

    expires_at = customer_col(cust, 'subscription_expires_at')
    if expires_at and datetime.now().isoformat() > expires_at:
        return False, 'subscription expired'

    month_start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

    if resource == 'scan':
        # Units-based so a scan that crashed and released its reservation is not
        # billed; scan reservations are always 1 unit.
        used = database.count_task_units_since(customer_id, TASK_SCAN, month_start)
        limit = customer_col(cust, 'monthly_scan_limit', 30)
        if used >= limit:
            return False, f'scan limit reached ({used}/{limit}/month)'
    elif resource == 'tailor':
        # Charge the quota for what was RESERVED, not only for what finished.
        # A tailor request runs in a background process that writes its
        # tailored_cvs rows minutes later, so counting completions alone let a
        # client fire several requests inside the rate-limit window and blow
        # well past monthly_tailor_limit before a single row landed.
        reserved = database.count_task_units_since(customer_id, TASK_TAILOR, month_start)
        completed = database.count_tailored_this_month(customer_id, month_start)
        used = max(reserved, completed)
        limit = customer_col(cust, 'monthly_tailor_limit', 50)
        if used >= limit:
            return False, f'tailor limit reached ({used}/{limit}/month)'
    elif resource == 'email':
        used = database.count_emails_this_month(customer_id, month_start)
        limit = customer_col(cust, 'monthly_email_limit', 100)
        if used >= limit:
            return False, f'email limit reached ({limit}/month)'
    elif resource == 'tokens':
        used = database.get_tokens_used_today(customer_id)
        limit = customer_col(cust, 'daily_token_budget', 50000)
        if used >= limit:
            return False, f'daily token budget exhausted ({limit}/day)'

    return True, ''


def record_usage_event(customer_id: int, name: str) -> None:
    """Record that a billable action started, so count_scans_this_month works.

    count_scans_this_month() reads the `tasks` table. That table used to be
    absent, and the resulting OperationalError was swallowed into a constant 0,
    which meant the monthly scan quota could never be reached.
    """
    try:
        database.record_task_event(customer_id, name)
    except Exception:
        logger.exception("Could not record usage event %r for customer %s",
                         name, customer_id)


def verify_paystack_signature(payload: bytes, signature: str) -> bool:
    """Verify Paystack webhook signature."""
    import hmac, hashlib
    expected = hmac.new(
        PAYSTACK_SECRET_KEY.encode('utf-8'),
        payload,
        hashlib.sha512
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def enforce_usage(resource: str):
    """Decorator to enforce usage limits on endpoints."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            customer_id = _get_request_customer_id()
            if customer_id is None:
                return jsonify({'ok': False, 'error': 'authentication required'}), 401
            ok, msg = check_usage_limit(customer_id, resource)
            if not ok:
                return jsonify({'ok': False, 'error': msg, 'upgrade': True}), 403
            return f(*args, **kwargs)
        return wrapper
    return decorator


@app.route('/api/checkout', methods=['POST'])
@limiter.limit("5 per hour")
def api_checkout():
    """Create Paystack checkout session for subscription."""
    customer_id = _get_request_customer_id()
    if customer_id is None:
        return jsonify({'ok': False, 'error': 'authentication required'}), 401
    
    customer = database.get_customer(customer_id)
    if not customer:
        return jsonify({'ok': False, 'error': 'customer not found'}), 404
    
    if not PAYSTACK_SECRET_KEY:
        return jsonify({'ok': False, 'error': 'billing not configured'}), 503
    
    try:
        import paystackapi
        paystackapi.api_key = PAYSTACK_SECRET_KEY
        
        # Create Paystack customer if needed
        if not customer['paystack_customer_id']:
            pc = paystackapi.Customer.create(
                email=customer['email'],
                first_name=customer['name'].split()[0] if customer['name'] else 'User',
                last_name=' '.join(customer['name'].split()[1:]) if customer['name'] and len(customer['name'].split()) > 1 else 'User'
            )
            database.update_customer(customer_id, paystack_customer_id=pc['data']['customer_code'])
            customer['paystack_customer_id'] = pc['data']['customer_code']
        
        # Initialize transaction
        txn = paystackapi.Transaction.initialize(
            amount=PLAN_PRICE_NGN,
            email=customer['email'],
            reference=f"jobmatch_{customer_id}_{int(time.time())}",
            callback_url=request.url_root.rstrip('/') + '/billing/success',
            metadata={'customer_id': customer_id, 'plan': 'monthly'},
            channels=['card', 'bank', 'ussd', 'qr', 'mobile_money', 'bank_transfer']
        )
        
        if txn['status']:
            return jsonify({'ok': True, 'authorization_url': txn['data']['authorization_url'], 'reference': txn['data']['reference']})
        else:
            return jsonify({'ok': False, 'error': txn.get('message', 'checkout failed')}), 500
            
    except Exception as e:
        logger.exception("Checkout failed")
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/billing/success')
def billing_success():
    """Paystack callback after successful payment."""
    reference = request.args.get('reference', '')
    if reference:
        try:
            import paystackapi
            paystackapi.api_key = PAYSTACK_SECRET_KEY
            verify = paystackapi.Transaction.verify(reference)
            if verify['status'] and verify['data']['status'] == 'success':
                # Extract customer_id from metadata
                metadata = verify['data'].get('metadata', {})
                customer_id = metadata.get('customer_id')
                if customer_id:
                    customer_id = int(customer_id)
                    auth_code = verify['data']['authorization']['authorization_code']
                    database.update_customer(
                        customer_id,
                        paystack_auth_code=auth_code,
                        subscription_status='active',
                        subscription_expires_at=(datetime.now() + __import__('datetime').timedelta(days=30)).isoformat()
                    )
        except Exception as e:
            logger.exception("Payment verification failed")
    
    return render_template_string('''
<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Payment Successful</title>
<style>
body{font-family:system-ui;background:#0b1020;color:#eaf0ff;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
.card{background:#161f3d;border:1px solid #2a3660;border-radius:16px;padding:40px;text-align:center;max-width:400px}
h1{color:#2fd48f;margin-bottom:16px} p{color:#9fb0d9}
a{color:#5b8cff;text-decoration:none;font-weight:600}
</style></head>
<body><div class="card">
<h1>✓ Payment Successful</h1>
<p>Your JobMatch subscription is now active.</p>
<p><a href="/">Go to Dashboard</a></p>
</div></body></html>
''')


@app.route('/api/paystack/webhook', methods=['POST'])
def paystack_webhook():
    """Handle Paystack webhook events."""
    if not PAYSTACK_SECRET_KEY:
        return jsonify({'ok': False}), 503
    
    payload = request.get_data()
    signature = request.headers.get('x-paystack-signature', '')
    
    if not verify_paystack_signature(payload, signature):
        logger.warning("Invalid Paystack signature")
        return jsonify({'ok': False}), 400
    
    try:
        event = json.loads(payload)
        data = event.get('data', {})
        event_type = event.get('event', '')
        
        if event_type == 'charge.success':
            metadata = data.get('metadata', {})
            customer_id = metadata.get('customer_id')
            if customer_id:
                customer_id = int(customer_id)
                auth_code = data.get('authorization', {}).get('authorization_code')
                database.update_customer(
                    customer_id,
                    paystack_auth_code=auth_code,
                    subscription_status='active',
                    subscription_expires_at=(datetime.now() + __import__('datetime').timedelta(days=30)).isoformat()
                )
                logger.info("Subscription activated for customer %s", customer_id)
        
        elif event_type == 'subscription.disable':
            paystack_cust = data.get('customer', {}).get('customer_code')
            if paystack_cust:
                cust = database.get_customer_by_paystack_customer(paystack_cust)
                if cust:
                    database.update_customer(cust['id'], subscription_status='cancelled')
                    logger.info("Subscription cancelled for customer %s", cust['id'])
        
        elif event_type == 'invoice.payment_failed':
            paystack_cust = data.get('customer', {}).get('customer_code')
            if paystack_cust:
                cust = database.get_customer_by_paystack_customer(paystack_cust)
                if cust:
                    database.update_customer(cust['id'], subscription_status='past_due')
                    logger.warning("Payment failed for customer %s", cust['id'])
                    
    except Exception as e:
        logger.exception("Webhook processing failed")
        return jsonify({'ok': False}), 500
    
    return jsonify({'ok': True})


@app.route('/api/billing/status')
def api_billing_status():
    """Get current billing status for customer."""
    customer_id = _get_request_customer_id()
    if customer_id is None:
        return jsonify({'ok': False, 'error': 'authentication required'}), 401
    
    customer = database.get_customer(customer_id)
    if not customer:
        return jsonify({'ok': False, 'error': 'customer not found'}), 404
    
    return jsonify({
        'ok': True,
        'subscription_status': customer_col(customer, 'subscription_status', 'trial'),
        'subscription_expires_at': customer_col(customer, 'subscription_expires_at'),
        'monthly_scan_limit': customer_col(customer, 'monthly_scan_limit', 30),
        'monthly_tailor_limit': customer_col(customer, 'monthly_tailor_limit', 50),
        'monthly_email_limit': customer_col(customer, 'monthly_email_limit', 100),
        'daily_token_budget': customer_col(customer, 'daily_token_budget', 50000),
    })


@app.route('/api/me')
def api_me():
    """Get current customer info (respects admin customer switch)."""
    # Check for admin switched customer context first
    if is_authed():
        active_cust_id = session.get('active_customer_id')
        if active_cust_id is not None:
            customer = database.get_customer(active_cust_id)
            if customer:
                return jsonify({
                    'ok': True,
                    'customer': {
                        'id': customer['id'],
                        'name': customer['name'],
                        'email': customer['email'],
                        'location': customer['location'],
                        'country': customer['country'],
                        'status': customer['status'],
                        'created_at': customer['created_at']
                    }
                })
    # Fall back to regular customer auth
    customer = auth.get_current_customer()
    if not customer:
        return jsonify({'ok': False, 'error': 'not authenticated'}), 401
    
    return jsonify({
        'ok': True,
        'customer': {
            'id': customer['id'],
            'name': customer['name'],
            'email': customer['email'],
            'location': customer['location'],
            'country': customer['country'],
            'status': customer['status'],
            'created_at': customer['created_at']
        }
    })


# ---------------------------------------------------------------- Customer-scoped API (authenticated)
def _get_request_customer_id():
    """Resolve the customer this request acts on.

    Order of trust:
      1. g.customer_id, set by the gate from a real customer session.
      2. an admin session's explicitly switched customer.
      3. an ADMIN session naming a customer_id explicitly (query or body).

    A customer session may NEVER name a different customer_id: previously this
    fallback ran for every caller, so any registered customer could read or
    overwrite any other customer by adding ?customer_id=<other>.
    """
    cid = getattr(g, 'customer_id', None)
    if cid is not None:
        return cid

    if is_admin():
        active_cust_id = session.get('active_customer_id')
        if active_cust_id is not None:
            return active_cust_id
        # Admin acting on behalf of a specific customer.
        data = request.get_json(silent=True) or {}
        raw = data.get('customer_id') or request.args.get('customer_id', type=int)
        if raw is not None:
            try:
                return int(raw)
            except (ValueError, TypeError):
                logger.warning("Ignoring non-integer customer_id %r from %s",
                               raw, get_remote_address())
                return None
        return None

    return auth.get_current_customer_id()


@app.route('/api/profile')
def api_get_profile():
    """Get current customer's profile."""
    customer_id = _get_request_customer_id()
    if customer_id is None:
        return jsonify({'ok': False, 'error': 'not authenticated'}), 401
    profile = database.get_customer_profile(customer_id)
    if not profile:
        return jsonify({'ok': False, 'error': 'profile not found'}), 404
    return jsonify(dict(profile))


@app.route('/api/profile', methods=['POST'])
@limiter.limit("10 per minute")
def api_update_profile():
    """Update current customer's profile."""
    customer_id = _get_request_customer_id()
    if customer_id is None:
        return jsonify({'ok': False, 'error': 'not authenticated'}), 401
    data = request.json or {}
    keywords = str(data.get('keywords', ''))
    preferred_locations = str(data.get('preferred_locations', ''))
    job_types = str(data.get('job_types', ''))
    target_roles = str(data.get('target_roles', ''))
    home_country = str(data.get('home_country', 'nigeria'))
    if len(keywords) > 500:
        return jsonify({'ok': False, 'error': 'keywords too long (max 500)'}), 400
    if len(preferred_locations) > 100:
        return jsonify({'ok': False, 'error': 'preferred_locations too long (max 100)'}), 400
    if not keywords.strip():
        return jsonify({'ok': False, 'error': 'keywords required'}), 400
    database.create_or_update_profile(
        customer_id=customer_id,
        keywords=keywords,
        preferred_locations=preferred_locations,
        job_types=job_types,
        target_roles=target_roles,
        home_country=home_country,
    )
    return jsonify({'ok': True})


@app.route('/api/cv')
def api_get_cv():
    """Get current customer's active CV."""
    customer_id = _get_request_customer_id()
    if customer_id is None:
        return jsonify({'ok': False, 'error': 'not authenticated'}), 401
    cv = database.get_customer_active_cv(customer_id)
    if not cv:
        return jsonify({'ok': False, 'error': 'no active CV'}), 404
    return jsonify(dict(cv))


@app.route('/api/cv', methods=['POST'])
@enforce_usage('tokens')
def api_upload_cv():
    """Upload CV for current customer."""
    customer_id = _get_request_customer_id()
    if customer_id is None:
        return jsonify({'ok': False, 'error': 'not authenticated'}), 401
    import customer_engine
    if 'file' not in request.files:
        return jsonify({'ok': False, 'out': 'no file field'}), 400
    f = request.files['file']
    data = f.read()
    path = customer_engine.save_cv_bytes(customer_id, data, f.filename)
    if not path:
        return jsonify({'ok': False, 'out': 'could not read text from that file '
                                        '- try .txt or .pdf'}), 400
    return jsonify({'ok': True, 'out': f'CV saved: {path}'})


@app.route('/api/matches')
def api_get_matches():
    """Get current customer's job matches."""
    customer_id = _get_request_customer_id()
    if customer_id is None:
        return jsonify({'ok': False, 'error': 'not authenticated'}), 401
    status = request.args.get('status')
    limit = int(request.args.get('limit', 100))
    matches = database.get_customer_matches(customer_id, status=status, limit=limit)
    return jsonify({'matches': [dict(m) for m in matches]})


@app.route('/api/applications')
def api_get_applications():
    """Get current customer's applications."""
    customer_id = _get_request_customer_id()
    if customer_id is None:
        return jsonify({'ok': False, 'error': 'not authenticated'}), 401
    status = request.args.get('status')
    applications = database.get_customer_applications(customer_id, status=status)
    return jsonify({'applications': [dict(a) for a in applications]})


@app.route('/api/applications', methods=['POST'])
def api_create_application():
    """Create an application for current customer."""
    customer_id = _get_request_customer_id()
    if customer_id is None:
        return jsonify({'ok': False, 'error': 'not authenticated'}), 401
    data = request.json or {}
    job_id = data.get('job_id')
    if not job_id:
        return jsonify({'ok': False, 'error': 'job_id required'}), 400
    try:
        job_id = int(job_id)
    except (ValueError, TypeError):
        return jsonify({'ok': False, 'error': 'invalid job_id'}), 400
    status = str(data.get('status', 'TO_APPLY'))
    valid_statuses = {'TO_APPLY', 'EMAILED', 'APPLIED', 'WATCHLIST', 'REJECTED', 'INTERVIEW', 'OFFER'}
    if status not in valid_statuses:
        return jsonify({'ok': False, 'error': f'invalid status: {status}'}), 400
    date_applied = str(data.get('date_applied', '')).strip() or None
    next_followup = str(data.get('next_followup', '')).strip() or None
    notes = str(data.get('notes', ''))
    apply_method = str(data.get('apply_method', ''))
    apply_link = str(data.get('apply_link', ''))
    app_id = database.create_application(
        customer_id=customer_id,
        job_id=job_id,
        status=status,
        date_applied=date_applied,
        next_followup=next_followup,
        notes=notes,
        apply_method=apply_method,
        apply_link=apply_link,
    )
    return jsonify({'ok': True, 'application_id': app_id})


@app.route('/api/tailored_cvs')
def api_get_tailored_cvs():
    """Get current customer's tailored CVs."""
    customer_id = _get_request_customer_id()
    if customer_id is None:
        return jsonify({'ok': False, 'error': 'not authenticated'}), 401
    tailored = database.get_customer_tailored_cvs(customer_id)
    return jsonify({'tailored_cvs': [dict(t) for t in tailored]})


@app.route('/api/customer/scan', methods=['POST'])
@limiter.limit("3 per hour")
def api_customer_scan():
    """Run job scan for current customer (customer-scoped, cookie auth only)."""
    customer_id = auth.get_current_customer_id()
    if customer_id is None:
        return jsonify({'ok': False, 'error': 'not authenticated'}), 401
    ok, msg = check_usage_limit(customer_id, 'scan')
    if not ok:
        return jsonify({'ok': False, 'error': msg, 'upgrade': True}), 403
    record_usage_event(customer_id, TASK_SCAN)
    import customer_engine
    customer_engine.run_scan(customer_id)
    return jsonify({'ok': True})


@app.route('/api/tailor', methods=['POST'])
@limiter.limit("5 per hour")
@enforce_usage('tailor')
@enforce_usage('tokens')
def api_customer_tailor_endpoint():
    """Tailor CV for current customer's top matches."""
    customer_id = auth.get_current_customer_id()
    if customer_id is None:
        return jsonify({'ok': False, 'error': 'not authenticated'}), 401
    if not pin_ok():
        logger.warning("Wrong PIN for customer tailor from %s", get_remote_address())
        return jsonify({'ok': False, 'out': 'WRONG PIN - tailor not started'}), 401
    data = request.json or {}
    top = data.get('top')
    if top is not None:
        try:
            top = int(top)
            if top < 1 or top > 50:
                return jsonify({'ok': False, 'error': 'top must be 1-50'}), 400
        except (ValueError, TypeError):
            return jsonify({'ok': False, 'error': 'invalid top'}), 400
    else:
        top = 8
    force = 1 if data.get('force') else 0
    cover = 1 if data.get('cover') else 0
    args = ['tailor', '--customer-id', str(customer_id), '--top', str(top)]
    if cover:
        args.append('--cover')
    if force:
        args.append('--force')
    logger.info("Customer tailor started by %s (customer_id=%s, top=%s, force=%s, cover=%s)", get_remote_address(), customer_id, top, force, cover)
    return jsonify(start_or_report(f'Tailor CVs (top {top})',
                                   'customer_engine.py', args, timeout=1800,
                                   reserve=[(customer_id, TASK_TAILOR, top)]))


# ---------------------------------------------------------------- PIN
def get_pin():
    try:
        with open(PIN_PATH, encoding='utf-8') as f:
            pin = f.read().strip()
        if len(pin) >= 4:
            return pin
    except Exception:
        pass
    pin = str(random.randint(100000, 999999))
    with open(PIN_PATH, 'w', encoding='utf-8') as f:
        f.write(pin)
    print('  [WEB APP] New send-PIN generated ->', pin, '(also saved in web_pin.env)')
    return pin


def pin_ok():
    # request.json can be None for a literal "null" JSON body, and a wrong PIN
    # must never raise - it has to return a clean 401.
    if request.is_json:
        data = request.get_json(silent=True) or {}
        sent = data.get('pin', '')
    else:
        sent = request.args.get('pin', '')
    expected = get_pin()
    if not sent or not expected:
        return False
    return secrets.compare_digest(str(sent), str(expected))


# ---------------------------------------------------------------- helpers
def read_json(path, default=None):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def plain_text(text, limit=600):
    """Readable text for the dashboard, whatever the source put in the field.

    Older scan files still hold raw markup ("<img src=...>"), and the scrapers
    only clean on the way in now, so clean on the way out too.
    """
    if not text:
        return ''
    try:
        from job_scraper import clean_html
        return clean_html(text, limit)
    except Exception:
        import html as html_mod
        text = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', str(text),
                      flags=re.I | re.S)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = html_mod.unescape(text)
        return re.sub(r'\s+', ' ', text).strip()[:limit]


def tidy_location(raw):
    """Sources repeat the country for every office: 'South Africa; Gauteng,
    South Africa; Cape Town, Western Cape, South Africa'. Show it once."""
    text = plain_text(raw, 200).replace('\n', ' ').strip()
    if ';' not in text:
        return text
    parts = [p.strip() for p in text.split(';') if p.strip()]
    if not parts:
        return ''
    head = parts[0].lower()
    if len(parts) > 1 and all(head in p.lower() for p in parts[1:]):
        return parts[0]
    seen, out = set(), []
    for p in parts:
        key = p.lower()
        if key not in seen:
            seen.add(key)
            out.append(p)
    return '; '.join(out[:3])


def tidy_title(raw, company):
    """Sources often append ' at <company>' to the title we already show."""
    text = plain_text(raw, 200).replace('\n', ' ').strip()
    text = text.replace('\ufffd', '-')          # damaged dashes from some feeds
    text = re.sub(r'\s+', ' ', text).strip(' -|\u2013')
    company = (company or '').strip()
    if company and len(company) > 3:
        suffix = f' at {company}'
        if text.lower().endswith(suffix.lower()):
            text = text[:-len(suffix)].strip()
    return text


def safe_url(url):
    """Only ever hand the page a real, absolute http(s) link.

    Anything else (empty, 'javascript:', a relative path, a stray quote or tag
    that survived scraping) becomes '' and the UI renders a disabled button
    rather than a link that goes nowhere.
    """
    if not url:
        return ''
    url = str(url).strip().strip('\'"<> \t\r\n')
    if url.startswith('//'):
        url = 'https:' + url
    if not re.match(r'^https?://', url, re.I):
        return ''
    if re.search(r'[\s"\'<>]', url):
        return ''
    if len(url) > 2000:
        return ''
    return url


def read_csv_rows():
    rows = []
    try:
        with open(CSV_PATH, encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                rows.append(r)
    except Exception:
        pass
    return rows


def write_csv_rows(rows):
    cols = ['Application ID', 'Date Applied', 'Job Title', 'Company', 'Location',
            'Source', 'Apply Link', 'Apply Method', 'Status', 'Next Follow-up', 'Notes']
    with open(CSV_PATH, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, '') for c in cols})


def run_script(script, args=None, timeout=420):
    """Run one of the toolkit's python scripts; return dict(out, err, ok)."""
    cmd = [sys.executable, os.path.join(BASE, script)]
    if args:
        cmd.extend(args)
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    logger.debug("Running script: %s %s", script, args or '')
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env,
                              timeout=timeout, cwd=BASE)
        out = (proc.stdout + '\n' + proc.stderr).strip()
        if proc.returncode != 0:
            logger.warning("Script %s failed with code %d: %s", script, proc.returncode, out[-500:])
        return {'ok': proc.returncode == 0, 'out': out[-6000:]}
    except subprocess.TimeoutExpired:
        logger.warning("Script %s timed out after %ds", script, timeout)
        return {'ok': False, 'out': f'Timed out after {timeout}s'}
    except Exception as e:
        logger.exception("Script %s raised exception", script)
        return {'ok': False, 'out': repr(e)}


# ---------------------------------------------------------------- background tasks
# The long jobs (scan, crawl, tailor) take minutes. Holding the HTTP request open
# for that long is what made the buttons look dead: nothing rendered, no timer,
# and a proxy/browser timeout could kill a run that was actually working. So they
# run in a thread, stream their output, and the phone polls for progress.
TASKS = {}
TASK_LOCK = threading.Lock()
TASK_LOG_LIMIT = 8000


def _public_task(task):
    return {k: v for k, v in task.items() if k != 'lock'}


def start_task(name, script, args=None, timeout=1800):
    """Kick off a long script in the background. One at a time, on purpose."""
    with TASK_LOCK:
        running = [t for t in TASKS.values() if t['status'] == 'running']
        if running:
            return None, running[0]
        task_id = f'{int(time.time())}-{len(TASKS) + 1}'
        task = {'id': task_id, 'name': name, 'status': 'running', 'log': '',
                'started': time.time(), 'finished': None, 'ok': None,
                'script': script, 'args': args or [], 'timeout': timeout}
        TASKS[task_id] = task

    logger.info("Background task started: %s (id=%s)", name, task_id)

    def close_reservation(ok):
        """Release or confirm the quota reservations made by start_or_report.

        A failed task produced nothing, so its units go back to the customer;
        leaving ok NULL would charge them for work that never happened.
        """
        for event_id in task.get('quota_event_ids') or []:
            try:
                database.finish_task_event(event_id, ok)
            except Exception:
                logger.exception('Could not close the quota reservation for %s', name)

    def worker():
        # -u / PYTHONUNBUFFERED: without this the child's stdout is block-buffered
        # into a pipe, so the phone would show no progress until the run ended.
        cmd = [sys.executable, '-u', os.path.join(BASE, script)] + list(task['args'])
        env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1')
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True,
                                    env=env, cwd=BASE, bufsize=1)
        except Exception as e:
            task['status'] = 'failed'
            task['log'] += f'could not start: {e!r}\n'
            task['finished'] = time.time()
            close_reservation(False)
            return

        # The timeout has to be enforced by a timer, not by the read loop: a
        # script that hangs silently produces no lines, so a check inside the
        # loop would never fire.
        timed_out = threading.Event()

        def on_timeout():
            timed_out.set()
            proc.kill()

        killer = threading.Timer(task['timeout'], on_timeout)
        killer.daemon = True
        killer.start()
        try:
            for line in proc.stdout:
                task['log'] = (task['log'] + line)[-TASK_LOG_LIMIT:]
            proc.wait()
            # Decide the verdict from the process itself. Checking
            # killer.is_alive() here was inverted: the timer is still pending
            # whenever the child finishes EARLY, so every successful run was
            # reported as failed with a bogus "[stopped: over Ns]" line.
            if timed_out.is_set():
                task['log'] += f'\n[stopped: over {task["timeout"]}s]\n'
                task['ok'] = False
            else:
                task['ok'] = proc.returncode == 0
            task['status'] = 'done' if task['ok'] else 'failed'
        except Exception as e:
            task['ok'] = False
            task['status'] = 'failed'
            task['log'] += f'\n[error: {e!r}]\n'
        finally:
            killer.cancel()
            task['finished'] = time.time()
            close_reservation(bool(task['ok']))
            logger.info("Background task completed: %s (id=%s, ok=%s, duration=%.1fs)",
                        name, task_id, task['ok'], task['finished'] - task['started'])

    threading.Thread(target=worker, daemon=True).start()
    return task_id, None


@app.route('/api/task')
def api_tasks():
    with TASK_LOCK:
        tasks = [_public_task(t) for t in TASKS.values()]
    tasks.sort(key=lambda t: t['started'], reverse=True)
    return jsonify({'tasks': tasks[:8]})


@app.route('/api/task/<task_id>')
def api_task(task_id):
    with TASK_LOCK:
        task = TASKS.get(task_id)
    if not task:
        return jsonify({'ok': False, 'error': 'unknown task'}), 404
    return jsonify(_public_task(task))


def tracker_status_lookup():
    status = {}
    for r in read_csv_rows():
        link = (r.get('Apply Link') or '').strip()
        if link:
            status[link] = r.get('Status', '')
    return status


def lan_ips():
    try:
        return sorted({i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None)
                       if i[4][0].startswith(('192.', '10.', '172.'))})
    except Exception:
        return []


# ---------------------------------------------------------------- state
@app.route('/api/state')
def api_state():
    scanned = read_json(SCANNED_PATH) or {}
    newjobs = read_json(NEWJOBS_PATH) or {}
    career = read_json(CAREER_PATH) or {}
    targets = read_json(TARGETS_PATH, []) or []

    status = tracker_status_lookup()

    def enrich(job, category=''):
        j = dict(job)
        raw_link = j.get('link', '') or ''
        link = safe_url(raw_link)
        company = plain_text(j.get('company', ''), 120).replace('\n', ' ').strip()
        j['link'] = link
        j['title'] = tidy_title(j.get('title', ''), company)
        j['company'] = company.replace('\ufffd', '-').strip()
        j['location'] = tidy_location(j.get('location', ''))
        j['description'] = plain_text(j.get('description', ''), 600).replace('\ufffd', '-')
        j['source'] = plain_text(j.get('source', ''), 40).strip()
        # Most crawled roles carry no description text, so tell the UI to
        # prompt opening the job page instead of rendering a blank card.
        j['has_description'] = len(j['description']) > 40
        # tracker rows are keyed by whatever is in the CSV, so try both forms
        j['status'] = status.get(link, '') or status.get(raw_link, '')
        j['id'] = link or raw_link or j.get('title', '')
        j['category'] = category
        return j

    cats = scanned.get('categories', {})
    jobs = []
    # Cap per category, not overall: a single big category (170 Nigerian roles)
    # would otherwise push every remote job off the end of the list.
    for cat in ('nigerian_onsite', 'remote_global', 'other_matches'):
        rows = [enrich(job, cat)
                for job in (scanned.get('jobs', {}).get(cat, []) or [])]
        jobs.extend(rows[:60])

    return jsonify({
        'last_scan': scanned.get('scan_date', 'never'),
        'total': scanned.get('total_results', 0),
        'categories': cats,
        'jobs': jobs,
        'counts': {c: len(scanned.get('jobs', {}).get(c, []) or [])
                   for c in ('nigerian_onsite', 'remote_global', 'other_matches')},
        'new_jobs': [enrich(j, 'new') for j in (newjobs.get('jobs', []) or [])][:40],
        'new_count': newjobs.get('count', 0),
        'career_total': career.get('total_results', 0),
        'career_date': career.get('scan_date', ''),
        'staged_emails': len(targets) if isinstance(targets, list) else 0,
        'gmail_ready': os.path.exists(os.path.join(BASE, 'sender_config.env')),
        'tracker': read_csv_rows(),
        'lan_ips': lan_ips(),
        'port': 5000,
        'pin_required': True,
    })


# ---------------------------------------------------------------- actions
def start_or_report(name, script, args=None, timeout=1800, reserve=None):
    """Start a background job, or explain what is already running.

    `timeout` is forwarded to start_task; /api/tailor has always passed it here,
    which raised TypeError because this wrapper did not accept it.

    `reserve` is an optional list of (customer_id, task_name, units) triples
    charging the caller's quota. The rows are written only once the task has
    actually been accepted, so a request refused because something else is
    already running never burns quota. The reservations are closed by the
    worker, which releases the units if the task fails.
    """
    task_id, busy = start_task(name, script, args, timeout=timeout)
    if busy:
        return {'ok': False, 'error': f'{busy["name"]} is already running',
                'task': busy['id']}
    for customer_id, task_name, units in (reserve or []):
        try:
            TASKS[task_id].setdefault('quota_event_ids', []).append(
                database.record_task_event(customer_id, task_name, units=units))
        except Exception:
            logger.exception('Could not record the %s reservation for %s',
                             task_name, name)
    return {'ok': True, 'task': task_id, 'name': name}


@app.route('/api/scan', methods=['POST'])
@limiter.limit("5 per hour")
def api_scan():
    logger.info("Job scan started by %s", get_remote_address())
    return jsonify(start_or_report('Scan for jobs', 'job_scraper.py'))


@app.route('/api/crawl', methods=['POST'])
@limiter.limit("5 per hour")
def api_crawl():
    max_n = 12
    if request.is_json:
        try:
            max_n = int(request.json.get('max', 12))
            if max_n < 1 or max_n > 100:
                return jsonify({'ok': False, 'error': 'max must be 1-100'}), 400
        except (ValueError, TypeError):
            return jsonify({'ok': False, 'error': 'invalid max'}), 400
    logger.info("Career crawl started by %s (max=%s)", get_remote_address(), max_n)
    return jsonify(start_or_report('Crawl company career pages',
                                   'career_crawler.py', ['--max', str(max_n)]))


@app.route('/api/import', methods=['POST'])
@limiter.limit("10 per hour")
def api_import():
    logger.info("Import jobs started by %s", get_remote_address())
    return jsonify(start_or_report('Import jobs to tracker', 'import_scanned_jobs.py'))


@app.route('/api/extract', methods=['POST'])
@limiter.limit("10 per hour")
def api_extract():
    logger.info("Email extraction started by %s", get_remote_address())
    task_id, busy = start_task('Find emails to write to', 'extract_email_targets.py')
    if busy:
        return jsonify({'ok': False, 'error': f'{busy["name"]} is already running'})
    return jsonify({'ok': True, 'task': task_id})


@app.route('/api/email_preview')
@limiter.limit("30 per minute")
def api_email_preview():
    logger.info("Email preview requested by %s", get_remote_address())
    return jsonify(run_script('send_applications.py'))


@app.route('/api/send_emails', methods=['POST'])
@limiter.limit("10 per hour")
@enforce_usage('email')
def api_send_emails():
    if not pin_ok():
        logger.warning("Wrong PIN for send_emails from %s", get_remote_address())
        return jsonify({'ok': False, 'out': 'WRONG PIN - email not sent'}), 401
    limit = request.json.get('limit') if request.is_json else None
    if limit is not None:
        try:
            limit = int(limit)
            if limit < 1 or limit > 100:
                return jsonify({'ok': False, 'error': 'limit must be 1-100'}), 400
        except (ValueError, TypeError):
            return jsonify({'ok': False, 'error': 'invalid limit'}), 400
    args = ['--send']
    if limit:
        args += ['--limit', str(limit)]
    logger.info("Email send started by %s (limit=%s)", get_remote_address(), limit)
    return jsonify(start_or_report('Send application emails',
                                   'send_applications.py', args, timeout=1800))


@app.route('/api/status', methods=['POST'])
@limiter.limit("30 per minute")
def api_status():
    data = request.json or {}
    row_id = str(data.get('id', ''))
    new_status = str(data.get('status', '')).strip()
    date_applied = str(data.get('date_applied', '')).strip()
    valid_statuses = {'TO_APPLY', 'EMAILED', 'APPLIED', 'WATCHLIST'}
    if new_status and new_status not in valid_statuses:
        return jsonify({'ok': False, 'error': f'invalid status: {new_status}'}), 400
    if not row_id:
        return jsonify({'ok': False, 'error': 'id required'}), 400
    if date_applied:
        try:
            datetime.strptime(date_applied, '%Y-%m-%d')
        except ValueError:
            return jsonify({'ok': False, 'error': 'date_applied must be YYYY-MM-DD'}), 400
    rows = read_csv_rows()
    found = False
    for r in rows:
        if r.get('Apply Link', '') == row_id or r.get('Application ID', '') == row_id:
            r['Status'] = new_status
            if date_applied:
                r['Date Applied'] = date_applied
                follow = ''
                try:
                    d = datetime.strptime(date_applied, '%Y-%m-%d')
                    from datetime import timedelta
                    follow = (d + timedelta(days=5)).strftime('%Y-%m-%d')
                except Exception:
                    pass
                if follow:
                    r['Next Follow-up'] = follow
            found = True
            break
    if found:
        write_csv_rows(rows)
        logger.info("Status updated by %s: %s -> %s", get_remote_address(), row_id, new_status)
        return jsonify({'ok': True})
    return jsonify({'ok': False, 'out': 'row not found'}), 404


# ---------------------------------------------------------------- customer (product) - legacy endpoints with customer_id support
def _get_customer_id_legacy():
    """Resolve customer_id for the legacy /api/customer* endpoints.

    Same trust rules as _get_request_customer_id(): a customer session is always
    pinned to itself, and only an admin session may name another customer_id.
    """
    customer_id = auth.get_current_customer_id()
    if customer_id is not None:
        return customer_id
    if is_admin():
        active_cust = session.get('active_customer_id')
        if active_cust is not None:
            return active_cust
        data = request.get_json(silent=True) or {}
        raw = data.get('customer_id') or request.args.get('customer_id', type=int)
        if raw is not None:
            try:
                return int(raw)
            except (ValueError, TypeError):
                logger.warning("Ignoring non-integer customer_id %r from %s",
                               raw, get_remote_address())
                return None
    return None


@app.route('/api/customer')
def api_customer_state():
    import customer_engine
    customer_id = _get_customer_id_legacy()
    if customer_id is None:
        # Check if this is an unauthenticated request (no session, no customer_id param)
        # Return 401 for unauthenticated, 400 for invalid customer_id
        auth_customer_id = auth.get_current_customer_id()
        if auth_customer_id is None:
            # No customer session and no customer_id param - unauthenticated
            return jsonify({'ok': False, 'error': 'authentication required'}), 401
        else:
            # Has session but no customer_id param - this shouldn't happen with _get_customer_id_legacy
            return jsonify({'ok': False, 'error': 'customer_id required'}), 400
    # Ensure customer_id is int for internal use
    try:
        customer_id_int = int(customer_id)
    except (ValueError, TypeError):
        return jsonify({'ok': False, 'error': 'invalid customer_id'}), 400
    profile = customer_engine.load_profile(customer_id_int)
    results = []
    # Check customer-specific results only
    customer_dir = os.path.join(BASE, 'data', 'customers', str(customer_id_int), 'results')
    results_path = os.path.join(customer_dir, 'customer_results.json')
    if os.path.exists(results_path):
        try:
            with open(results_path, encoding='utf-8') as f:
                results = json.load(f).get('results', [])
        except Exception:
            pass
    # Get tailored CVs from customer-specific directory
    tailored_dir = os.path.join(BASE, 'data', 'customers', str(customer_id_int), 'tailored_cvs')
    tailored = sorted(os.listdir(tailored_dir)) if os.path.exists(tailored_dir) else []
    return jsonify({
        'profile': profile,
        'cv_present': os.path.exists(customer_engine.get_active_cv_path(customer_id_int)),
        'results': results[:120],
        'tailored_count': len(tailored),
    })


@app.route('/api/customer/profile', methods=['POST'])
@limiter.limit("10 per minute")
def api_customer_profile():
    import customer_engine
    data = request.json or {}
    customer_id = _get_customer_id_legacy()
    if customer_id is None:
        # Check if this is an unauthenticated request
        auth_customer_id = auth.get_current_customer_id()
        if auth_customer_id is None:
            return jsonify({'ok': False, 'error': 'authentication required'}), 401
        else:
            return jsonify({'ok': False, 'error': 'customer_id required'}), 400
    name = str(data.get('name', ''))
    keywords = str(data.get('keywords', ''))
    location = str(data.get('location', ''))
    if len(name) > 100:
        return jsonify({'ok': False, 'error': 'name too long (max 100)'}), 400
    if len(keywords) > 500:
        return jsonify({'ok': False, 'error': 'keywords too long (max 500)'}), 400
    if len(location) > 100:
        return jsonify({'ok': False, 'error': 'location too long (max 100)'}), 400
    if not keywords.strip():
        return jsonify({'ok': False, 'error': 'keywords required'}), 400
    customer_engine.save_profile(customer_id, name=name[:100], keywords=keywords[:500], location=location[:100])
    logger.info("Customer profile updated by %s", get_remote_address())
    return jsonify({'ok': True})


@app.route('/api/customer/cv', methods=['POST'])
@enforce_usage('tokens')
def api_customer_cv():
    import customer_engine
    customer_id = _get_customer_id_legacy()
    if customer_id is None:
        return jsonify({'ok': False, 'error': 'customer_id required'}), 400
    if 'file' not in request.files:
        return jsonify({'ok': False, 'out': 'no file field'}), 400
    f = request.files['file']
    data = f.read()
    path = customer_engine.save_cv_bytes(customer_id, data, f.filename)
    if not path:
        return jsonify({'ok': False, 'out': 'could not read text from that file '
                                            '- try .txt or .pdf'}), 400
    return jsonify({'ok': True, 'out': f'CV saved: {path}'})


@app.route('/api/customer/run', methods=['POST'])
@limiter.limit("3 per hour")
@enforce_usage('scan')
@enforce_usage('tailor')
@enforce_usage('tokens')
def api_customer_run():
    if not pin_ok():
        logger.warning("Wrong PIN for customer run from %s", get_remote_address())
        return jsonify({'ok': False, 'out': 'WRONG PIN - run not started'}), 401
    data = request.json or {}
    customer_id = _get_customer_id_legacy()
    if customer_id is None:
        return jsonify({'ok': False, 'error': 'customer_id required'}), 400
    top = data.get('top')
    if top is not None:
        try:
            top = int(top)
            if top < 1 or top > 50:
                return jsonify({'ok': False, 'error': 'top must be 1-50'}), 400
        except (ValueError, TypeError):
            return jsonify({'ok': False, 'error': 'invalid top'}), 400
    else:
        top = int(os.environ.get('JOBMATCH_TOP', 8))
    cover = 1 if data.get('cover') else 0
    args = ['run', '--customer-id', str(customer_id), '--top', str(top)]
    if cover:
        args.append('--cover')
    logger.info("Customer run started by %s (customer_id=%s, top=%s, cover=%s)", get_remote_address(), customer_id, top, cover)
    # One task, two quotas: the run scans AND tailors `top` CVs. Previously the
    # scan event was written before `top` was even parsed, so a request rejected
    # for a bad `top` still cost the customer a scan.
    return jsonify(start_or_report(
        f'Find jobs + tailor CVs (top {top})', 'customer_engine.py', args, timeout=1800,
        reserve=[(customer_id, TASK_SCAN, 1), (customer_id, TASK_TAILOR, top)]))


@app.route('/api/customer/tailor', methods=['POST'])
@limiter.limit("5 per hour")
@enforce_usage('tailor')
@enforce_usage('tokens')
def api_customer_tailor():
    if not pin_ok():
        logger.warning("Wrong PIN for customer tailor from %s", get_remote_address())
        return jsonify({'ok': False, 'out': 'WRONG PIN - tailor not started'}), 401
    data = request.json or {}
    customer_id = _get_customer_id_legacy()
    if customer_id is None:
        return jsonify({'ok': False, 'error': 'customer_id required'}), 400
    top = data.get('top')
    if top is not None:
        try:
            top = int(top)
            if top < 1 or top > 50:
                return jsonify({'ok': False, 'error': 'top must be 1-50'}), 400
        except (ValueError, TypeError):
            return jsonify({'ok': False, 'error': 'invalid top'}), 400
    else:
        top = 8
    force = 1 if data.get('force') else 0
    cover = 1 if data.get('cover') else 0
    args = ['tailor', '--customer-id', str(customer_id), '--top', str(top)]
    if cover:
        args.append('--cover')
    if force:
        args.append('--force')
    logger.info("Customer tailor started by %s (customer_id=%s, top=%s, force=%s, cover=%s)", get_remote_address(), customer_id, top, force, cover)
    return jsonify(start_or_report(f'Tailor CVs (top {top})',
                                   'customer_engine.py', args, timeout=1800,
                                   reserve=[(customer_id, TASK_TAILOR, top)]))


@app.route('/api/customer/cv_text')
def api_customer_cv_text():
    import customer_engine
    customer_id = _get_customer_id_legacy()
    if customer_id is None:
        return jsonify({'ok': False, 'error': 'customer_id required'}), 400
    cv_path = customer_engine.get_active_cv_path(customer_id)
    if cv_path and os.path.exists(cv_path):
        with open(cv_path, encoding='utf-8') as f:
            text = f.read()
    else:
        text = ''
    return jsonify({'cv': text})


# ---------------------------------------------------------------- multi-customer API (admin only)
# Every route in this block used to be reachable by any authenticated customer,
# which let a customer read another customer's row (including password_hash)
# and PATCH arbitrary columns such as password_hash - a full account takeover.
# They are admin-only now, and never return credential material.
@app.route('/api/customers')
@require_admin
def api_list_customers():
    """List all customers (admin only)."""
    customers = database.list_customers()
    return jsonify({'customers': [public_customer(c) for c in customers]})


@app.route('/api/customers', methods=['POST'])
@require_admin
def api_create_customer():
    """Create a new customer (admin only)."""
    data = request.json or {}
    name = str(data.get('name', '')).strip()
    email = str(data.get('email', '')).strip() or None
    location = str(data.get('location', '')).strip() or None
    country = str(data.get('country', 'nigeria')).strip()
    if not name:
        return jsonify({'ok': False, 'error': 'name required'}), 400
    if email:
        existing = database.get_customer_by_email(email)
        if existing:
            return jsonify({'ok': False, 'error': 'email already exists'}), 400
    customer_id = database.create_customer(name=name, email=email, location=location, country=country)
    return jsonify({'ok': True, 'customer_id': customer_id})


@app.route('/api/customers/<int:customer_id>')
@require_admin
def api_get_customer(customer_id):
    """Get customer by ID (admin only)."""
    customer = database.get_customer(customer_id)
    if not customer:
        return jsonify({'ok': False, 'error': 'customer not found'}), 404
    return jsonify(public_customer(customer))


# Columns an admin may change through PATCH. password_hash and status are
# deliberately absent: credential state must go through the auth layer.
_CUSTOMER_PATCH_FIELDS = {'name', 'email', 'location', 'country'}


@app.route('/api/customers/<int:customer_id>', methods=['PATCH'])
@require_admin
def api_update_customer(customer_id):
    """Update customer (admin only)."""
    data = request.json or {}
    customer = database.get_customer(customer_id)
    if not customer:
        return jsonify({'ok': False, 'error': 'customer not found'}), 404
    updates = {k: v for k, v in data.items() if k in _CUSTOMER_PATCH_FIELDS}
    rejected = sorted(set(data) - _CUSTOMER_PATCH_FIELDS)
    if rejected:
        logger.warning("Rejected non-whitelisted PATCH fields %s for customer %s",
                       rejected, customer_id)
    if not updates:
        return jsonify({'ok': False,
                        'error': f'no updatable fields (allowed: {sorted(_CUSTOMER_PATCH_FIELDS)})',
                        'rejected': rejected}), 400
    database.update_customer(customer_id, **updates)
    return jsonify({'ok': True})


@app.route('/api/customers/<int:customer_id>/profile')
@require_admin
def api_get_customer_profile(customer_id):
    """Get customer profile (admin only)."""
    profile = database.get_customer_profile(customer_id)
    if not profile:
        return jsonify({'ok': False, 'error': 'profile not found'}), 404
    return jsonify(dict(profile))


@app.route('/api/customers/<int:customer_id>/profile', methods=['POST'])
@require_admin
def api_update_customer_profile(customer_id):
    """Update customer profile (admin only)."""
    if not database.get_customer(customer_id):
        return jsonify({'ok': False, 'error': 'customer not found'}), 404
    data = request.json or {}
    database.create_or_update_profile(
        customer_id=customer_id,
        keywords=data.get('keywords', ''),
        preferred_locations=data.get('preferred_locations', ''),
        job_types=data.get('job_types', ''),
        target_roles=data.get('target_roles', ''),
        home_country=data.get('home_country', 'nigeria'),
    )
    return jsonify({'ok': True})


@app.route('/api/customers/<int:customer_id>/cvs')
@require_admin
def api_get_customer_cvs(customer_id):
    """Get customer CVs (admin only)."""
    cvs = database.get_customer_cvs(customer_id)
    return jsonify({'cvs': [dict(c) for c in cvs]})


@app.route('/api/customers/<int:customer_id>/cvs/active')
@require_admin
def api_get_customer_active_cv(customer_id):
    """Get customer's active CV (admin only)."""
    cv = database.get_customer_active_cv(customer_id)
    if not cv:
        return jsonify({'ok': False, 'error': 'no active CV'}), 404
    return jsonify(dict(cv))


@app.route('/api/customers/<int:customer_id>/matches')
@require_admin
def api_get_customer_matches(customer_id):
    """Get customer job matches (admin only)."""
    status = request.args.get('status')
    try:
        limit = int(request.args.get('limit', 100))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'limit must be an integer'}), 400
    limit = max(1, min(limit, 500))
    matches = database.get_customer_matches(customer_id, status=status, limit=limit)
    return jsonify({'matches': [dict(m) for m in matches]})


@app.route('/api/customers/<int:customer_id>/applications')
@require_admin
def api_get_customer_applications(customer_id):
    """Get customer applications (admin only)."""
    status = request.args.get('status')
    applications = database.get_customer_applications(customer_id, status=status)
    return jsonify({'applications': [dict(a) for a in applications]})


@app.route('/api/customers/<int:customer_id>/tailored_cvs')
@require_admin
def api_get_customer_tailored_cvs(customer_id):
    """Get customer tailored CVs (admin only)."""
    tailored = database.get_customer_tailored_cvs(customer_id)
    return jsonify({'tailored_cvs': [dict(t) for t in tailored]})


# ---------------------------------------------------------------- file serving (safe)
# Customer-specific file serving - requires customer_id and serves from customer's tailored_cvs dir
@app.route('/files/<int:customer_id>/<path:filename>')
@limiter.limit("100 per minute")
def api_serve_file(customer_id, filename):
    # Verify customer exists
    customer = database.get_customer(customer_id)
    if not customer:
        return jsonify({'ok': False, 'error': 'customer not found'}), 404
    
    # Authorization: admin can access any customer's files, customer can only access their own
    is_admin = is_authed()
    current_customer_id = getattr(g, 'customer_id', None)
    if not is_admin and current_customer_id != customer_id:
        logger.warning("File access denied: customer %s tried to access customer %s files", current_customer_id, customer_id)
        return jsonify({'ok': False, 'error': 'access denied'}), 403
    
    # Reject obvious traversal attempts early
    if any(seq in filename for seq in ('..', '~', ':', '|', '<', '>', '"')):
        logger.warning("File traversal attempt blocked: %s from %s (customer_id=%s)", filename, get_remote_address(), customer_id)
        return jsonify({'ok': False, 'error': 'invalid path'}), 400

    # Reject absolute paths (Unix-style /path, Windows-style \path or C:\path)
    # Also check for URL-encoded slashes
    if filename.startswith(('/', '\\')) or re.match(r'^[A-Za-z]:[\\/]', filename):
        logger.warning("Absolute path blocked: %s from %s (customer_id=%s)", filename, get_remote_address(), customer_id)
        return jsonify({'ok': False, 'error': 'invalid path'}), 400

    # Additional check: reject paths that start with slash after URL decoding
    if '/etc/' in filename or '\\windows\\' in filename.lower():
        logger.warning("Sensitive path blocked: %s from %s (customer_id=%s)", filename, get_remote_address(), customer_id)
        return jsonify({'ok': False, 'error': 'invalid path'}), 400

    # Serve only from customer's tailored_cvs directory
    customer_tailored_dir = os.path.abspath(os.path.join(BASE, 'data', 'customers', str(customer_id), 'tailored_cvs'))
    full = os.path.normpath(os.path.join(customer_tailored_dir, filename))
    
    # Ensure the resolved path is within the customer's tailored_cvs directory
    if not os.path.commonpath([full, customer_tailored_dir]) == customer_tailored_dir:
        logger.warning("Path traversal attempt blocked: %s from %s (customer_id=%s)", filename, get_remote_address(), customer_id)
        return jsonify({'ok': False, 'error': 'invalid path'}), 400
    
    if os.path.isfile(full):
        logger.debug("File served: %s to %s (customer_id=%s)", filename, get_remote_address(), customer_id)
        return send_file(full, as_attachment=True)
    
    logger.warning("File not found or access denied: %s from %s (customer_id=%s)", filename, get_remote_address(), customer_id)
    return jsonify({'ok': False, 'error': 'not found'}), 404


# ---------------------------------------------------------------- landing page
LANDING_PATH = os.path.join(BASE, 'templates', 'landing.html')


@app.route('/landing')
def landing():
    """Public landing page for lead capture."""
    try:
        with open(LANDING_PATH, encoding='utf-8') as f:
            html = f.read()
    except Exception:
        logger.exception("Failed to load landing page")
        html = '<h1>Landing page not found</h1>'
    return render_template_string(html)


# ---------------------------------------------------------------- usage stats
@app.route('/api/usage')
def api_usage():
    """Get usage stats for current customer."""
    customer_id = _get_request_customer_id()
    if customer_id is None:
        return jsonify({'ok': False, 'error': 'authentication required'}), 401

    resource = request.args.get('resource')
    if resource not in ('scan', 'tailor', 'email'):
        return jsonify({'ok': False, 'error': 'invalid resource'}), 400

    customer = database.get_customer(customer_id)
    if not customer:
        return jsonify({'ok': False, 'error': 'customer not found'}), 404

    month_start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

    # The limit column may be absent on a database created before billing was
    # added, so read it defensively instead of letting a KeyError become a 500.
    if resource == 'scan':
        used = database.count_scans_this_month(customer_id, month_start)
        limit = customer_col(customer, 'monthly_scan_limit', 30)
    elif resource == 'tailor':
        used = database.count_tailored_this_month(customer_id, month_start)
        limit = customer_col(customer, 'monthly_tailor_limit', 50)
    else:
        used = database.count_emails_this_month(customer_id, month_start)
        limit = customer_col(customer, 'monthly_email_limit', 100)

    return jsonify({'ok': True, 'used': used, 'limit': limit,
                    'remaining': max(0, limit - used)})


# ---------------------------------------------------------------- auth switch
@app.route('/api/auth/switch', methods=['POST'])
@limiter.limit("10 per minute")
def api_auth_switch():
    """Switch active customer context (admin only)."""
    if not is_authed():
        return jsonify({'ok': False, 'error': 'admin authentication required'}), 401
    data = request.json or {}
    cust_id = data.get('customer_id')
    if cust_id is None:
        return jsonify({'ok': False, 'error': 'customer_id required'}), 400
    try:
        cust_id = int(cust_id)
    except (ValueError, TypeError):
        return jsonify({'ok': False, 'error': 'invalid customer_id'}), 400
    customer = database.get_customer(cust_id)
    if not customer:
        return jsonify({'ok': False, 'error': 'customer not found'}), 404
    # Store the active customer_id in admin session
    session['active_customer_id'] = cust_id
    logger.info("Admin switched to customer %s (%s)", cust_id, customer['name'])
    return jsonify({'ok': True, 'customer_id': cust_id, 'name': customer['name']})


# ---------------------------------------------------------------- pages
@app.route('/')
def index():
    # Show landing page for unauthenticated users, dashboard for authenticated
    if is_authed() or auth.get_current_customer_id() is not None:
        try:
            with open(DASHBOARD_PATH, encoding='utf-8') as f:
                html = f.read()
        except Exception:
            logger.exception("Failed to load dashboard")
            html = '<h1>Missing web_dashboard.html</h1>'
        return render_template_string(html)
    # Unauthenticated - show landing page
    try:
        with open(LANDING_PATH, encoding='utf-8') as f:
            html = f.read()
    except Exception:
        logger.exception("Failed to load landing page")
        html = '<h1>Landing page not found</h1>'
    return render_template_string(html)


@app.errorhandler(404)
def handle_404(e):
    logger.warning("404: %s from %s", request.path, get_remote_address())
    return jsonify({'ok': False, 'error': 'not found'}), 404


@app.errorhandler(500)
def handle_500(e):
    logger.exception("Internal server error from %s", get_remote_address())
    return jsonify({'ok': False, 'error': 'internal server error'}), 500


@app.errorhandler(429)
def handle_429(e):
    logger.warning("Rate limit exceeded from %s", get_remote_address())
    return jsonify({'ok': False, 'error': 'rate limit exceeded'}), 429


def ensure_schema_ready() -> None:
    """Bring the configured database up to the current schema.

    Nothing ran init_db() on startup, so a database created before the current
    schema booted fine and only failed later, per request: /api/usage?resource=
    scan returned 500 "no such table: tasks" and the Paystack billing routes
    could not read customers.paystack_auth_code. Raises on failure so the
    caller can refuse to serve rather than 500 on every request.
    """
    database.init_db()


if __name__ == '__main__':
    # See ensure_schema_ready(): migrate before serving, never after.
    try:
        ensure_schema_ready()
    except Exception as e:
        print(f'FATAL: could not initialize the database at {database.DB_PATH}: {e}')
        raise SystemExit(1) from e
    print(f'Database ready: {database.DB_PATH}')

    print('=' * 60)
    print('  HOPE JOHN SUNDAY - PHONE CONTROL PANEL')
    print('=' * 60)
    print('  On this laptop:   http://127.0.0.1:5000')
    for ip in lan_ips():
        print(f'  On your phone:    http://{ip}:5000')
    print('  (Same Wi-Fi needed. Allow Python through Firewall on first run.)')
    print('  Press Ctrl+C to stop.')
    get_pin()
    print('=' * 60)
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
