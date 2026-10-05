"""
auth.py - Customer authentication and authorization for JobMatch.

Provides:
- Customer registration with password hashing
- Customer login with session creation
- Session validation and management
- @require_customer decorator for protecting routes
"""

import hashlib
import secrets
from datetime import datetime, timedelta
from functools import wraps

from flask import g, jsonify, request

import database

# Session configuration
SESSION_COOKIE_NAME = 'customer_session'
SESSION_EXPIRY_DAYS = 30


def hash_password(password: str, email: str) -> str:
    """Hash a password using PBKDF2 with email as salt."""
    return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), email.encode('utf-8'), 100000).hex()


def verify_password(password: str, email: str, password_hash: str) -> bool:
    """Verify a password against its hash."""
    computed = hash_password(password, email)
    return secrets.compare_digest(computed, password_hash)


def create_session_token() -> str:
    """Generate a cryptographically random session token."""
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    """Hash a session token for storage."""
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def _is_secure_request():
    """Detect if request is secure (HTTPS) including via Cloudflare reverse proxy."""
    from flask import request
    # Check X-Forwarded-Proto header (set by Cloudflare)
    forwarded_proto = request.headers.get('X-Forwarded-Proto', '')
    if 'https' in forwarded_proto.lower():
        return True
    # Check if request.scheme is https (when not behind proxy)
    if request.is_secure:
        return True
    return False


def set_session_cookie(response, token: str):
    """Set the secure session cookie on the response."""
    secure = _is_secure_request()
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        httponly=True,
        secure=secure,
        samesite='Lax',
        max_age=SESSION_EXPIRY_DAYS * 24 * 60 * 60,
        path='/'
    )


def clear_session_cookie(response):
    """Clear the session cookie."""
    secure = _is_secure_request()
    response.set_cookie(
        SESSION_COOKIE_NAME,
        '',
        httponly=True,
        secure=secure,
        samesite='Lax',
        max_age=0,
        path='/'
    )


def validate_session(token: str) -> database.sqlite3.Row | None:
    """Validate a session token. Returns session row if valid, None otherwise."""
    return database.validate_session(token)


def get_current_customer_id() -> int | None:
    """Get the current customer_id from the validated session."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    session = validate_session(token)
    if not session:
        return None
    return session['customer_id']


def require_customer(f):
    """
    Decorator to require customer authentication.
    Sets g.customer_id on successful authentication.
    Returns 401 if not authenticated.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        customer_id = get_current_customer_id()
        if customer_id is None:
            return jsonify({'ok': False, 'error': 'authentication required'}), 401
        g.customer_id = customer_id
        return f(*args, **kwargs)
    return wrapper


def register_customer(name: str, email: str, password: str,
                       location: str | None = None,
                       country: str = 'nigeria') -> tuple[bool, str | int, str | None]:
    """
    Register a new customer.
    Returns: (success, customer_id_or_error_message, session_token_or_None)
    """
    # Validate inputs
    if not name or not name.strip():
        return False, 'name required', None
    if not email or not email.strip():
        return False, 'email required', None
    if not password:
        return False, 'password required', None
    
    email = email.strip().lower()
    name = name.strip()
    
    # Basic email validation
    if '@' not in email or '.' not in email.split('@')[-1]:
        return False, 'invalid email format', None
    
    # Password requirements
    if len(password) < 8:
        return False, 'password must be at least 8 characters', None
    
    # Check for existing customer
    existing = database.get_customer_by_email(email)
    if existing:
        return False, 'email already registered', None
    
    # Create customer with hashed password
    try:
        customer_id = database.create_customer_with_password(
            name=name,
            email=email,
            password=password,
            location=location,
            country=country
        )
    except Exception as e:
        return False, f'registration failed: {e}', None
    
    # Create session - database function generates and returns the token
    expires_at = (datetime.now() + timedelta(days=SESSION_EXPIRY_DAYS)).isoformat(timespec='seconds')
    token = database.create_session(customer_id, expires_at)
    
    return True, customer_id, token


def login_customer(email: str, password: str) -> tuple[bool, str | int, str | None]:
    """
    Log in a customer.
    Returns: (success, customer_id_or_error_message, session_token_or_None)
    """
    if not email or not password:
        return False, 'email and password required', None
    
    email = email.strip().lower()
    customer = database.get_customer_by_email(email)
    if not customer:
        return False, 'invalid credentials', None
    
    if not verify_password(password, email, customer['password_hash'] or ''):
        return False, 'invalid credentials', None
    
    if customer['status'] != 'active':
        return False, 'account not active', None
    
    # Create session - database function generates and returns the token
    expires_at = (datetime.now() + timedelta(days=SESSION_EXPIRY_DAYS)).isoformat(timespec='seconds')
    token = database.create_session(customer['id'], expires_at)
    
    return True, customer['id'], token


def logout_customer() -> bool:
    """Log out the current customer by revoking their session."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return True  # Already logged out
    return database.revoke_session(token)


def get_current_customer() -> database.sqlite3.Row | None:
    """Get the current authenticated customer's full record."""
    customer_id = get_current_customer_id()
    if customer_id is None:
        return None
    return database.get_customer(customer_id)