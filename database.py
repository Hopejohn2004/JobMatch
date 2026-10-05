"""
database.py - SQLite database layer for JobMatch multi-customer architecture.

Designed for eventual PostgreSQL migration:
- Uses standard SQL with minimal SQLite-specific features
- WAL mode enabled for concurrency
- Connection pooling via context managers
- Explicit transactions
"""

import hashlib
import json
import os
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB_DIR = BASE / 'data'
# JOBMATCH_DB_PATH lets tests (and any deployment) point at a different
# database file. It was referenced by tests/conftest.py and every fixture but
# never read here, so the switch silently did nothing.
DB_PATH = Path(os.environ.get('JOBMATCH_DB_PATH') or (DB_DIR / 'jobmatch.db'))

# Thread-local storage for connections
_local = threading.local()

SCHEMA = """
-- Customers table
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE,
    password_hash TEXT,
    location TEXT,
    country TEXT DEFAULT 'nigeria',
    status TEXT DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'archived')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    -- Billing (Paystack). paystack_auth_code is a REUSABLE card authorisation
    -- code: it must never be returned by an API response.
    subscription_status TEXT DEFAULT 'trial',
    paystack_customer_id TEXT,
    paystack_subscription_id TEXT,
    paystack_auth_code TEXT,
    subscription_expires_at TEXT,
    monthly_scan_limit INTEGER DEFAULT 30,
    monthly_tailor_limit INTEGER DEFAULT 50,
    monthly_email_limit INTEGER DEFAULT 100,
    daily_token_budget INTEGER DEFAULT 50000
);

-- Billable task events. count_scans_this_month() reads this table; it used to
-- be missing from the schema entirely, so the scan quota always read 0.
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER REFERENCES customers(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    started TEXT NOT NULL,
    finished TEXT,
    ok INTEGER
);
CREATE INDEX IF NOT EXISTS idx_tasks_customer ON tasks(customer_id, name, started);

-- Customer profiles (search preferences)
CREATE TABLE IF NOT EXISTS customer_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    keywords TEXT,
    preferred_locations TEXT,
    job_types TEXT,
    target_roles TEXT,
    home_country TEXT DEFAULT 'nigeria',
    -- CV ingestion provenance (see customer_engine.save_cv_bytes)
    cv_source TEXT DEFAULT '',
    cv_quality REAL DEFAULT 0,
    cv_repair TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(customer_id)
);

-- Customer CVs (master CVs uploaded by customer)
CREATE TABLE IF NOT EXISTS customer_cvs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    original_filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    file_hash TEXT,
    text_content TEXT,
    quality_score REAL,
    is_active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Jobs (discovered from scraping - shared across customers)
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    external_id TEXT,
    title TEXT NOT NULL,
    company TEXT,
    location TEXT,
    url TEXT,
    description TEXT,
    discovered_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source, external_id)
);

-- Job matches (customer-specific scoring of jobs)
CREATE TABLE IF NOT EXISTS job_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    score REAL NOT NULL,
    fit_score REAL,
    reason TEXT,
    status TEXT DEFAULT 'new' CHECK (status IN ('new', 'reviewed', 'applied', 'dismissed')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(customer_id, job_id)
);

-- Applications (customer-specific application tracking)
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'TO_APPLY' CHECK (status IN ('TO_APPLY', 'EMAILED', 'APPLIED', 'WATCHLIST', 'REJECTED', 'INTERVIEW', 'OFFER')),
    date_applied TEXT,
    next_followup TEXT,
    notes TEXT,
    apply_method TEXT,
    apply_link TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(customer_id, job_id)
);

-- Tailored CVs (customer-specific tailored CVs per job)
CREATE TABLE IF NOT EXISTS tailored_cvs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    source_cv_id INTEGER NOT NULL REFERENCES customer_cvs(id) ON DELETE CASCADE,
    stored_path TEXT NOT NULL,
    cover_letter_path TEXT,
    qc_notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(customer_id, job_id, source_cv_id)
);

-- Sessions (customer authentication)
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL,
    revoked INTEGER DEFAULT 0,
    last_seen_at TEXT
);

-- LLM token ledger. Spend used to be inferred from tailored_cvs.qc_notes, but that
-- column holds free text written by customer_engine ('; '.join(qc)), so
-- json_extract() returned NULL and the daily budget always read 0. Tokens are
-- also spent where no tailored_cvs row is ever written (CV repair, failed
-- tailors), so the ledger has to be its own table.
CREATE TABLE IF NOT EXISTS token_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    tokens INTEGER NOT NULL DEFAULT 0,
    kind TEXT NOT NULL DEFAULT 'tailor',
    note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_job_matches_customer ON job_matches(customer_id);
CREATE INDEX IF NOT EXISTS idx_job_matches_status ON job_matches(status);
CREATE INDEX IF NOT EXISTS idx_applications_customer ON applications(customer_id);
CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status);
CREATE INDEX IF NOT EXISTS idx_tailored_cvs_customer ON tailored_cvs(customer_id);
CREATE INDEX IF NOT EXISTS idx_customer_cvs_customer ON customer_cvs(customer_id);
CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source);
CREATE INDEX IF NOT EXISTS idx_sessions_customer ON sessions(customer_id);
CREATE INDEX IF NOT EXISTS idx_sessions_token_hash ON sessions(token_hash);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_token_usage_customer ON token_usage(customer_id, created_at);
"""

# Trigger to auto-update updated_at timestamps
TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS update_customers_updated_at
AFTER UPDATE ON customers
BEGIN
    UPDATE customers SET updated_at = datetime('now') WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_customer_profiles_updated_at
AFTER UPDATE ON customer_profiles
BEGIN
    UPDATE customer_profiles SET updated_at = datetime('now') WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_customer_cvs_updated_at
AFTER UPDATE ON customer_cvs
BEGIN
    UPDATE customer_cvs SET updated_at = datetime('now') WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_applications_updated_at
AFTER UPDATE ON applications
BEGIN
    UPDATE applications SET updated_at = datetime('now') WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_sessions_last_seen
AFTER UPDATE ON sessions
BEGIN
    UPDATE sessions SET last_seen_at = datetime('now') WHERE id = NEW.id;
END;
"""


def get_connection() -> sqlite3.Connection:
    """Get a thread-local database connection with WAL mode enabled.

    The cached connection is keyed on the current DB_PATH. Callers (notably the
    test suite) reassign database.DB_PATH to point at a temporary file; when the
    path changed the old code kept handing back the connection that was already
    open, so those writes landed in the REAL database instead of the temp one.
    """
    if getattr(_local, 'db_path', None) != str(DB_PATH):
        # DB_PATH was repointed: drop the stale connection for this thread.
        old = getattr(_local, 'conn', None)
        if old is not None:
            try:
                old.close()
            except sqlite3.Error:
                pass
        _local.conn = None
        _local.db_path = str(DB_PATH)
    if not hasattr(_local, 'conn') or _local.conn is None:
        DB_DIR.mkdir(parents=True, exist_ok=True)
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA busy_timeout=5000')
        _local.conn = conn
    return _local.conn


@contextmanager
def transaction():
    """Context manager for explicit transactions."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _table_columns(conn, table: str) -> set:
    try:
        return {r[1] for r in conn.execute(f'PRAGMA table_info({table})')}
    except sqlite3.OperationalError:
        return set()


# Columns added after the first released schema. CREATE TABLE IF NOT EXISTS will
# NOT add these to a database that already exists, so they must be migrated
# explicitly or code that reads them raises OperationalError at runtime.
MIGRATIONS = {
    'customers': [
        ('password_hash', 'TEXT'),
        ('subscription_status', "TEXT DEFAULT 'trial'"),
        ('paystack_customer_id', 'TEXT'),
        ('paystack_subscription_id', 'TEXT'),
        ('paystack_auth_code', 'TEXT'),
        ('subscription_expires_at', 'TEXT'),
        ('monthly_scan_limit', 'INTEGER DEFAULT 30'),
        ('monthly_tailor_limit', 'INTEGER DEFAULT 50'),
        ('monthly_email_limit', 'INTEGER DEFAULT 100'),
        ('daily_token_budget', 'INTEGER DEFAULT 50000'),
    ],
    'customer_profiles': [
        ('cv_source', "TEXT DEFAULT ''"),
        ('cv_quality', 'REAL DEFAULT 0'),
        ('cv_repair', "TEXT DEFAULT ''"),
    ],
    # A tailor request spends `top` CVs worth of LLM calls but used to log a
    # single row, so the monthly quota could not be charged for what was
    # actually reserved.
    'tasks': [
        ('units', 'INTEGER DEFAULT 1'),
    ],
}


def apply_migrations() -> list:
    """Add any missing columns to existing tables. Returns the changes made."""
    applied = []
    with transaction() as conn:
        for table, columns in MIGRATIONS.items():
            existing = _table_columns(conn, table)
            if not existing:
                continue  # table itself is missing; CREATE TABLE handles it
            for name, decl in columns:
                if name in existing:
                    continue
                try:
                    conn.execute(f'ALTER TABLE {table} ADD COLUMN {name} {decl}')
                    applied.append(f'{table}.{name}')
                except sqlite3.OperationalError:
                    # Racing migration from another process - harmless.
                    pass
    return applied


def init_db() -> None:
    """Initialize the database schema and bring an existing one up to date."""
    with transaction() as conn:
        conn.executescript(SCHEMA)
        conn.executescript(TRIGGERS)
    applied = apply_migrations()
    if applied:
        print('Database migrations applied:', ', '.join(applied))
    # Expired/revoked sessions were never pruned: cleanup_expired_sessions() was
    # defined but nothing called it, so the table grew without bound.
    try:
        removed = cleanup_expired_sessions()
        if removed:
            print(f'Pruned {removed} expired/revoked session(s)')
    except sqlite3.Error:
        pass


def close_db() -> None:
    """Close the thread-local connection."""
    if hasattr(_local, 'conn') and _local.conn is not None:
        _local.conn.close()
        _local.conn = None
    _local.db_path = None


# --- Customer CRUD ---

def create_customer(name: str, email: str | None = None, location: str | None = None,
                    country: str = 'nigeria', password_hash: str | None = None) -> int:
    """Create a new customer. Returns customer_id."""
    now = datetime.now().isoformat(timespec='seconds')
    with transaction() as conn:
        cursor = conn.execute(
            'INSERT INTO customers (name, email, password_hash, location, country, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
            (name, email, password_hash, location, country, now, now)
        )
        return cursor.lastrowid


def create_customer_with_password(name: str, email: str, password: str,
                                   location: str | None = None,
                                   country: str = 'nigeria') -> int:
    """Create a new customer with a hashed password. Returns customer_id."""
    password_hash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'),
                                         email.encode('utf-8'), 100000).hex()
    return create_customer(name=name, email=email, location=location, country=country,
                           password_hash=password_hash)


def verify_customer_password(customer_id: int, password: str) -> bool:
    """Verify a customer's password. Returns True if valid."""
    customer = get_customer(customer_id)
    if not customer or not customer['password_hash']:
        return False
    email = customer['email'] or ''
    computed_hash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'),
                                        email.encode('utf-8'), 100000).hex()
    # Constant-time compare, matching auth.verify_password.
    return secrets.compare_digest(computed_hash, customer['password_hash'])


def get_customer(customer_id: int) -> sqlite3.Row | None:
    """Get customer by ID."""
    conn = get_connection()
    return conn.execute('SELECT * FROM customers WHERE id = ?', (customer_id,)).fetchone()


def get_customer_by_email(email: str) -> sqlite3.Row | None:
    """Get customer by email."""
    conn = get_connection()
    return conn.execute('SELECT * FROM customers WHERE email = ?', (email,)).fetchone()


def list_customers(status: str | None = None) -> list[sqlite3.Row]:
    """List all customers, optionally filtered by status."""
    conn = get_connection()
    if status:
        return conn.execute('SELECT * FROM customers WHERE status = ? ORDER BY created_at DESC', (status,)).fetchall()
    return conn.execute('SELECT * FROM customers ORDER BY created_at DESC').fetchall()


def update_customer(customer_id: int, **fields) -> bool:
    """Update customer fields. Returns True if updated.

    Only the whitelisted columns below can ever be written, so a caller cannot
    reach a column that is not listed here by passing **fields straight from
    request JSON.

    password_hash is deliberately absent: nothing needs to rewrite a credential
    through this helper (create_customer_with_password inserts the hash), and
    leaving it writable is exactly what turned a PATCH into account takeover.
    """
    if not fields:
        return False
    allowed = {'name', 'email', 'location', 'country', 'status',
               'paystack_customer_id', 'paystack_subscription_id', 'paystack_auth_code',
               'subscription_status', 'subscription_expires_at',
               'monthly_scan_limit', 'monthly_tailor_limit', 'monthly_email_limit',
               'daily_token_budget'}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return False
    updates['updated_at'] = datetime.now().isoformat(timespec='seconds')
    set_clause = ', '.join(f'{k} = ?' for k in updates)
    with transaction() as conn:
        cursor = conn.execute(
            f'UPDATE customers SET {set_clause} WHERE id = ?',
            (*updates.values(), customer_id)
        )
        return cursor.rowcount > 0


# --- Session CRUD ---

def create_session(customer_id: int, expires_at: str) -> str:
    """Create a new session for a customer. Returns the plain session token."""
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    now = datetime.now().isoformat(timespec='seconds')
    with transaction() as conn:
        conn.execute(
            '''INSERT INTO sessions (customer_id, token_hash, created_at, expires_at, revoked, last_seen_at)
               VALUES (?, ?, ?, ?, 0, ?)''',
            (customer_id, token_hash, now, expires_at, now)
        )
    return token


def get_session_by_token_hash(token_hash: str) -> sqlite3.Row | None:
    """Get session by token hash."""
    conn = get_connection()
    return conn.execute('SELECT * FROM sessions WHERE token_hash = ?', (token_hash,)).fetchone()


def validate_session(token: str) -> sqlite3.Row | None:
    """Validate a session token. Returns session row if valid, None otherwise."""
    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    session = get_session_by_token_hash(token_hash)
    if not session:
        return None
    if session['revoked']:
        return None
    if session['expires_at'] < datetime.now().isoformat(timespec='seconds'):
        return None
    # Verify customer still exists and is active
    customer = get_customer(session['customer_id'])
    if not customer or customer['status'] != 'active':
        return None
    return session


def revoke_session(token: str) -> bool:
    """Revoke a session by token. Returns True if revoked."""
    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    with transaction() as conn:
        cursor = conn.execute(
            'UPDATE sessions SET revoked = 1 WHERE token_hash = ?',
            (token_hash,)
        )
        return cursor.rowcount > 0


def revoke_all_customer_sessions(customer_id: int) -> int:
    """Revoke all sessions for a customer. Returns count of revoked sessions."""
    with transaction() as conn:
        cursor = conn.execute(
            'UPDATE sessions SET revoked = 1 WHERE customer_id = ? AND revoked = 0',
            (customer_id,)
        )
        return cursor.rowcount


def update_session_last_seen(token: str) -> bool:
    """Update the last_seen_at timestamp for a session. Returns True if updated."""
    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    now = datetime.now().isoformat(timespec='seconds')
    with transaction() as conn:
        cursor = conn.execute(
            'UPDATE sessions SET last_seen_at = ? WHERE token_hash = ?',
            (now, token_hash)
        )
        return cursor.rowcount > 0


def cleanup_expired_sessions() -> int:
    """Remove expired and revoked sessions. Returns count of removed sessions."""
    now = datetime.now().isoformat(timespec='seconds')
    with transaction() as conn:
        cursor = conn.execute(
            'DELETE FROM sessions WHERE expires_at < ? OR revoked = 1',
            (now,)
        )
        return cursor.rowcount


# --- Customer Profile CRUD ---

def create_or_update_profile(customer_id: int, keywords: str = '', preferred_locations: str = '',
                              job_types: str = '', target_roles: str = '', home_country: str = 'nigeria',
                              cv_source: str | None = None, cv_quality: float | None = None,
                              cv_repair: str | None = None) -> int:
    """Create or update customer profile. Returns profile_id.

    cv_source / cv_quality / cv_repair are optional and only overwritten when
    supplied, so a partial update (e.g. changing just the keywords) does not
    wipe the CV provenance recorded at upload time.
    """
    now = datetime.now().isoformat(timespec='seconds')
    with transaction() as conn:
        existing = conn.execute('SELECT id FROM customer_profiles WHERE customer_id = ?', (customer_id,)).fetchone()
        if existing:
            sets = ['keywords = ?', 'preferred_locations = ?', 'job_types = ?',
                    'target_roles = ?', 'home_country = ?', 'updated_at = ?']
            params: list = [keywords, preferred_locations, job_types, target_roles,
                            home_country, now]
            if cv_source is not None:
                sets.append('cv_source = ?')
                params.append(cv_source)
            if cv_quality is not None:
                sets.append('cv_quality = ?')
                params.append(cv_quality)
            if cv_repair is not None:
                sets.append('cv_repair = ?')
                params.append(cv_repair)
            params.append(customer_id)
            conn.execute(
                f'UPDATE customer_profiles SET {", ".join(sets)} WHERE customer_id = ?',
                tuple(params)
            )
            return existing['id']
        else:
            cursor = conn.execute(
                '''INSERT INTO customer_profiles (customer_id, keywords, preferred_locations, job_types, target_roles,
                                                   home_country, cv_source, cv_quality, cv_repair, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (customer_id, keywords, preferred_locations, job_types, target_roles, home_country,
                 cv_source or '', cv_quality or 0, cv_repair or '', now, now)
            )
            return cursor.lastrowid


def get_customer_profile(customer_id: int) -> sqlite3.Row | None:
    """Get customer profile by customer_id."""
    conn = get_connection()
    return conn.execute('SELECT * FROM customer_profiles WHERE customer_id = ?', (customer_id,)).fetchone()


# --- Customer CV CRUD ---

def create_customer_cv(customer_id: int, original_filename: str, stored_path: str,
                        file_hash: str | None = None, text_content: str | None = None,
                        quality_score: float | None = None) -> int:
    """Register a customer CV. Returns cv_id."""
    now = datetime.now().isoformat(timespec='seconds')
    with transaction() as conn:
        # Deactivate other CVs for this customer
        conn.execute('UPDATE customer_cvs SET is_active = 0 WHERE customer_id = ?', (customer_id,))
        cursor = conn.execute(
            '''INSERT INTO customer_cvs (customer_id, original_filename, stored_path, file_hash, 
                                         text_content, quality_score, is_active, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)''',
            (customer_id, original_filename, stored_path, file_hash, text_content, quality_score, now, now)
        )
        return cursor.lastrowid


def get_customer_active_cv(customer_id: int) -> sqlite3.Row | None:
    """Get the active CV for a customer."""
    conn = get_connection()
    return conn.execute(
        'SELECT * FROM customer_cvs WHERE customer_id = ? AND is_active = 1 ORDER BY created_at DESC LIMIT 1',
        (customer_id,)
    ).fetchone()


def get_customer_cvs(customer_id: int) -> list[sqlite3.Row]:
    """Get all CVs for a customer."""
    conn = get_connection()
    return conn.execute(
        'SELECT * FROM customer_cvs WHERE customer_id = ? ORDER BY created_at DESC',
        (customer_id,)
    ).fetchall()


def set_active_cv(customer_id: int, cv_id: int) -> bool:
    """Set a specific CV as active for a customer.

    Ownership is verified BEFORE anything is deactivated. The previous version
    cleared is_active on every CV the customer owned first and only then
    discovered the id belonged to somebody else, so a rejected request still
    left the customer with no active CV at all.
    """
    with transaction() as conn:
        owned = conn.execute(
            'SELECT 1 FROM customer_cvs WHERE id = ? AND customer_id = ?', (cv_id, customer_id)
        ).fetchone()
        if not owned:
            return False
        conn.execute('UPDATE customer_cvs SET is_active = 0 WHERE customer_id = ?', (customer_id,))
        cursor = conn.execute(
            'UPDATE customer_cvs SET is_active = 1, updated_at = ? WHERE id = ? AND customer_id = ?',
            (datetime.now().isoformat(timespec='seconds'), cv_id, customer_id)
        )
        return cursor.rowcount > 0


# --- Jobs CRUD ---

def create_job(source: str, title: str, company: str = '', location: str = '', url: str = '',
               description: str = '', external_id: str | None = None) -> int:
    """Create or get existing job. Returns job_id."""
    now = datetime.now().isoformat(timespec='seconds')
    with transaction() as conn:
        # Try to find existing
        if external_id:
            existing = conn.execute('SELECT id FROM jobs WHERE source = ? AND external_id = ?',
                                    (source, external_id)).fetchone()
            if existing:
                return existing['id']
        # Also check by URL
        if url:
            existing = conn.execute('SELECT id FROM jobs WHERE url = ?', (url,)).fetchone()
            if existing:
                return existing['id']
        # Create new
        cursor = conn.execute(
            '''INSERT INTO jobs (source, external_id, title, company, location, url, description, discovered_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (source, external_id, title, company, location, url, description, now)
        )
        return cursor.lastrowid


def get_job(job_id: int) -> sqlite3.Row | None:
    """Get job by ID."""
    conn = get_connection()
    return conn.execute('SELECT * FROM jobs WHERE id = ?', (job_id,)).fetchone()


def get_job_by_url(url: str) -> sqlite3.Row | None:
    """Get job by URL."""
    conn = get_connection()
    return conn.execute('SELECT * FROM jobs WHERE url = ?', (url,)).fetchone()


# --- Job Matches CRUD ---

def create_job_match(customer_id: int, job_id: int, score: float, fit_score: float | None = None,
                      reason: str = '', status: str = 'new') -> int:
    """Create or update a job match for a customer. Returns match_id."""
    now = datetime.now().isoformat(timespec='seconds')
    with transaction() as conn:
        existing = conn.execute(
            'SELECT id FROM job_matches WHERE customer_id = ? AND job_id = ?', (customer_id, job_id)
        ).fetchone()
        if existing:
            conn.execute(
                '''UPDATE job_matches SET score = ?, fit_score = ?, reason = ?, status = ?
                   WHERE customer_id = ? AND job_id = ?''',
                (score, fit_score, reason, status, customer_id, job_id)
            )
            return existing['id']
        cursor = conn.execute(
            '''INSERT INTO job_matches (customer_id, job_id, score, fit_score, reason, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (customer_id, job_id, score, fit_score, reason, status, now)
        )
        return cursor.lastrowid


def get_customer_matches(customer_id: int, status: str | None = None, limit: int = 100) -> list[sqlite3.Row]:
    """Get job matches for a customer, optionally filtered by status."""
    conn = get_connection()
    if status:
        return conn.execute(
            '''SELECT jm.*, j.title, j.company, j.location, j.url, j.description, j.source
               FROM job_matches jm
               JOIN jobs j ON jm.job_id = j.id
               WHERE jm.customer_id = ? AND jm.status = ?
               ORDER BY jm.score DESC, jm.created_at DESC LIMIT ?''',
            (customer_id, status, limit)
        ).fetchall()
    return conn.execute(
        '''SELECT jm.*, j.title, j.company, j.location, j.url, j.description, j.source
           FROM job_matches jm
           JOIN jobs j ON jm.job_id = j.id
           WHERE jm.customer_id = ?
           ORDER BY jm.score DESC, jm.created_at DESC LIMIT ?''',
        (customer_id, limit)
    ).fetchall()


def update_match_status(customer_id: int, job_id: int, status: str) -> bool:
    """Update job match status."""
    with transaction() as conn:
        cursor = conn.execute(
            'UPDATE job_matches SET status = ? WHERE customer_id = ? AND job_id = ?',
            (status, customer_id, job_id)
        )
        return cursor.rowcount > 0


# --- Applications CRUD ---

def create_application(customer_id: int, job_id: int, status: str = 'TO_APPLY',
                        date_applied: str | None = None, next_followup: str | None = None,
                        notes: str = '', apply_method: str = '', apply_link: str = '') -> int:
    """Create or update an application. Returns application_id."""
    now = datetime.now().isoformat(timespec='seconds')
    with transaction() as conn:
        existing = conn.execute(
            'SELECT id FROM applications WHERE customer_id = ? AND job_id = ?', (customer_id, job_id)
        ).fetchone()
        if existing:
            conn.execute(
                '''UPDATE applications SET status = ?, date_applied = ?, next_followup = ?, 
                   notes = ?, apply_method = ?, apply_link = ?, updated_at = ?
                   WHERE customer_id = ? AND job_id = ?''',
                (status, date_applied, next_followup, notes, apply_method, apply_link, now, customer_id, job_id)
            )
            return existing['id']
        cursor = conn.execute(
            '''INSERT INTO applications (customer_id, job_id, status, date_applied, next_followup, 
                                         notes, apply_method, apply_link, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (customer_id, job_id, status, date_applied, next_followup, notes, apply_method, apply_link, now, now)
        )
        return cursor.lastrowid


def get_customer_applications(customer_id: int, status: str | None = None) -> list[sqlite3.Row]:
    """Get applications for a customer, optionally filtered by status."""
    conn = get_connection()
    if status:
        return conn.execute(
            '''SELECT a.*, j.title, j.company, j.location, j.url, j.source
               FROM applications a
               JOIN jobs j ON a.job_id = j.id
               WHERE a.customer_id = ? AND a.status = ?
               ORDER BY a.created_at DESC''',
            (customer_id, status)
        ).fetchall()
    return conn.execute(
        '''SELECT a.*, j.title, j.company, j.location, j.url, j.source
           FROM applications a
           JOIN jobs j ON a.job_id = j.id
           WHERE a.customer_id = ?
           ORDER BY a.created_at DESC''',
        (customer_id,)
    ).fetchall()


def update_application_status(customer_id: int, job_id: int, status: str,
                               date_applied: str | None = None,
                               next_followup: str | None = None) -> bool:
    """Update application status."""
    now = datetime.now().isoformat(timespec='seconds')
    with transaction() as conn:
        cursor = conn.execute(
            '''UPDATE applications SET status = ?, date_applied = COALESCE(?, date_applied),
               next_followup = COALESCE(?, next_followup), updated_at = ?
               WHERE customer_id = ? AND job_id = ?''',
            (status, date_applied, next_followup, now, customer_id, job_id)
        )
        return cursor.rowcount > 0


# --- Tailored CVs CRUD ---

def create_tailored_cv(customer_id: int, job_id: int, source_cv_id: int, stored_path: str,
                        cover_letter_path: str | None = None, qc_notes: str | None = None) -> int:
    """Create a tailored CV record. Returns tailored_cv_id."""
    now = datetime.now().isoformat(timespec='seconds')
    with transaction() as conn:
        cursor = conn.execute(
            '''INSERT INTO tailored_cvs (customer_id, job_id, source_cv_id, stored_path, 
                                         cover_letter_path, qc_notes, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (customer_id, job_id, source_cv_id, stored_path, cover_letter_path, qc_notes, now)
        )
        return cursor.lastrowid


def get_customer_tailored_cvs(customer_id: int) -> list[sqlite3.Row]:
    """Get all tailored CVs for a customer."""
    conn = get_connection()
    return conn.execute(
        '''SELECT tc.*, j.title, j.company
           FROM tailored_cvs tc
           JOIN jobs j ON tc.job_id = j.id
           WHERE tc.customer_id = ?
           ORDER BY tc.created_at DESC''',
        (customer_id,)
    ).fetchall()


def get_tailored_cv(customer_id: int, job_id: int) -> sqlite3.Row | None:
    """Get tailored CV for a specific customer and job."""
    conn = get_connection()
    return conn.execute(
        'SELECT * FROM tailored_cvs WHERE customer_id = ? AND job_id = ? ORDER BY created_at DESC LIMIT 1',
        (customer_id, job_id)
    ).fetchone()


# --- Migration helpers ---

def migrate_from_legacy(base_path: Path = None) -> dict:
    """
    Migrate existing single-customer data to the new multi-customer schema.
    Creates one initial customer and imports all existing data.
    Returns migration report.
    """
    import csv

    base = base_path or BASE

    report = {
        'customer_created': False,
        'customer_id': None,
        'profile_imported': False,
        'cv_imported': False,
        'cv_count': 0,
        'applications_imported': 0,
        'tailored_cvs_imported': 0,
        'jobs_imported': 0,
        'matches_imported': 0,
        'errors': []
    }

    # Check if migration already done
    existing = list_customers()
    if existing:
        report['errors'].append('Migration already performed - customers exist')
        return report

    # Read profile first to get name
    profile_name = 'Hope John Sunday'
    profile_email = 'hopejohn204@gmail.com'
    profile_location = 'Uyo, Akwa Ibom'
    profile_country = 'nigeria'

    profile_path = base / 'data' / 'customer_profile.json'
    if profile_path.exists():
        try:
            with open(profile_path, encoding='utf-8') as f:
                legacy_profile = json.load(f)
            profile_name = legacy_profile.get('name', profile_name)
            profile_email = legacy_profile.get('email', profile_email)
            profile_location = legacy_profile.get('location', profile_location)
            profile_country = legacy_profile.get('country', profile_country)
        except Exception:
            pass

    # 1. Create initial customer
    try:
        customer_id = create_customer(
            name=profile_name,
            email=profile_email,
            location=profile_location,
            country=profile_country
        )
        report['customer_created'] = True
        report['customer_id'] = customer_id
    except Exception as e:
        report['errors'].append(f'Failed to create customer: {e}')
        return report

    # 2. Import profile from customer_profile.json
    try:
        profile_path = base / 'data' / 'customer_profile.json'
        if profile_path.exists():
            with open(profile_path, encoding='utf-8') as f:
                profile = json.load(f)
            create_or_update_profile(
                customer_id=customer_id,
                keywords=profile.get('keywords', ''),
                preferred_locations=profile.get('location', ''),
                home_country=profile.get('country', 'nigeria')
            )
            report['profile_imported'] = True
    except Exception as e:
        report['errors'].append(f'Failed to import profile: {e}')

    # 3. Import CV from customer_cv.txt
    try:
        cv_path = base / 'data' / 'customer_cv.txt'
        if cv_path.exists():
            text = cv_path.read_text(encoding='utf-8')
            # Calculate hash
            file_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]
            cv_id = create_customer_cv(
                customer_id=customer_id,
                original_filename='customer_cv.txt',
                stored_path=str(cv_path.relative_to(base)),
                file_hash=file_hash,
                text_content=text,
                quality_score=0.84  # from existing profile
            )
            report['cv_imported'] = True
            report['cv_count'] = 1
    except Exception as e:
        report['errors'].append(f'Failed to import CV: {e}')

    # 4. Import applications from applications.csv
    try:
        csv_path = base / 'applications.csv'
        if csv_path.exists():
            with open(csv_path, encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                seen_urls = set()
                for row in reader:
                    url = row.get('Apply Link', '').strip()
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)

                    # Create job record (use INSERT OR IGNORE to handle duplicates)
                    now = datetime.now().isoformat(timespec='seconds')
                    with transaction() as conn:
                        cursor = conn.execute(
                            '''INSERT OR IGNORE INTO jobs (source, external_id, title, company, location, url, description, discovered_at)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                            (row.get('Source', ''), url, row.get('Job Title', ''), row.get('Company', ''),
                             row.get('Location', ''), url, '', now)
                        )
                        if cursor.rowcount > 0:
                            report['jobs_imported'] += 1
                            job_id = cursor.lastrowid
                        else:
                            # Job already exists, get its ID
                            existing = conn.execute('SELECT id FROM jobs WHERE url = ?', (url,)).fetchone()
                            job_id = existing['id'] if existing else None

                    if not job_id:
                        continue

                    # Create application (use INSERT OR IGNORE)
                    with transaction() as conn:
                        cursor = conn.execute(
                            '''INSERT OR IGNORE INTO applications (customer_id, job_id, status, date_applied, next_followup, 
                                                                 notes, apply_method, apply_link, created_at, updated_at)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                            (customer_id, job_id, row.get('Status', 'TO_APPLY'),
                             row.get('Date Applied', '') or None,
                             row.get('Next Follow-up', '') or None,
                             row.get('Notes', ''),
                             row.get('Apply Method', ''),
                             url, now, now)
                        )
                        if cursor.rowcount > 0:
                            report['applications_imported'] += 1

                    # Create match record with score from notes
                    score = 0
                    notes = row.get('Notes', '')
                    if 'Score' in notes:
                        try:
                            score = int(notes.split('Score')[1].split()[0])
                        except (IndexError, ValueError):
                            pass
                    create_job_match(
                        customer_id=customer_id,
                        job_id=job_id,
                        score=float(score),
                        status='reviewed' if row.get('Status') != 'TO_APPLY' else 'new'
                    )
                    report['matches_imported'] += 1
    except Exception as e:
        report['errors'].append(f'Failed to import applications: {e}')

    # 5. Import tailored CVs from tailored_cvs/ directory
    try:
        tailored_dir = base / 'tailored_cvs'
        if tailored_dir.exists():
            for cv_file in tailored_dir.glob('*_tailored_cv.txt'):
                # Try to match with existing job by company name in filename
                job_id = None
                for row in get_customer_matches(customer_id):
                    if row['company'] and row['company'].lower().replace(' ', '_') in cv_file.stem.lower():
                        job_id = row['job_id']
                        break

                if job_id:
                    # Get the active CV as source
                    active_cv = get_customer_active_cv(customer_id)
                    if active_cv:
                        cover_letter = None
                        letter_file = tailored_dir / cv_file.name.replace('_tailored_cv.txt', '_cover_letter.txt')
                        if letter_file.exists():
                            cover_letter = str(letter_file.relative_to(base))

                        create_tailored_cv(
                            customer_id=customer_id,
                            job_id=job_id,
                            source_cv_id=active_cv['id'],
                            stored_path=str(cv_file.relative_to(base)),
                            cover_letter_path=cover_letter
                        )
                        report['tailored_cvs_imported'] += 1
    except Exception as e:
        report['errors'].append(f'Failed to import tailored CVs: {e}')

    return report


# --- Usage Tracking ---
def count_scans_this_month(customer_id: int, since: str) -> int:
    """Count scans run this month."""
    conn = get_connection()
    try:
        row = conn.execute(
            'SELECT COUNT(*) as cnt FROM tasks WHERE customer_id = ? AND name = ? AND started >= ?',
            (customer_id, 'Scan for jobs', since)
        ).fetchone()
        return row['cnt'] if row else 0
    except sqlite3.OperationalError as e:
        # Do NOT silently report 0 here: that is what made the scan quota
        # unenforceable. Surface it so a missing table is a visible failure.
        raise RuntimeError(f'usage counting unavailable: {e}') from e


def record_task_event(customer_id: int, name: str, ok: int | None = None,
                      units: int = 1) -> int:
    """Record the start of a billable task. Returns the new task id.

    `units` is what the task reserves against its quota. A tailor request for
    `top` CVs reserves `top`, not 1, so a client cannot fire several requests
    inside the rate-limit window and blow past monthly_tailor_limit before the
    background process has written a single tailored_cvs row.
    """
    now = datetime.now().isoformat(timespec='seconds')
    with transaction() as conn:
        cursor = conn.execute(
            'INSERT INTO tasks (customer_id, name, started, ok, units) VALUES (?, ?, ?, ?, ?)',
            (customer_id, name, now, ok, max(1, int(units)))
        )
        return int(cursor.lastrowid)


def finish_task_event(task_id: int, ok: bool) -> None:
    """Close out a reservation: stamp `finished` and record the verdict.

    A failed task releases its units, because nothing was produced. Leaving ok
    NULL forever would charge the customer for work that never happened.
    """
    with transaction() as conn:
        conn.execute(
            'UPDATE tasks SET ok = ?, finished = ? WHERE id = ?',
            (1 if ok else 0, datetime.now().isoformat(timespec='seconds'), task_id)
        )


def count_task_units_since(customer_id: int, name: str, since: str,
                           include_failed: bool = False) -> int:
    """Sum the units reserved by a task name since `since`.

    Counts in-flight rows (ok IS NULL) as reserved, and by default excludes
    rows explicitly marked failed, since those released their units.
    """
    sql = ('SELECT COALESCE(SUM(units), 0) as total FROM tasks '
           'WHERE customer_id = ? AND name = ? AND started >= ?')
    params: list = [customer_id, name, since]
    if not include_failed:
        sql += ' AND ok IS NOT 0'
    try:
        row = get_connection().execute(sql, params).fetchone()
    except sqlite3.OperationalError as e:
        # Do NOT silently report 0: that is what made the scan and tailor quotas
        # unenforceable. A missing table is a visible failure, not a free pass.
        raise RuntimeError(f'usage counting unavailable: {e}') from e
    return int(row['total']) if row else 0


def count_tailored_this_month(customer_id: int, since: str) -> int:
    """Count tailored CVs created this month."""
    conn = get_connection()
    row = conn.execute(
        'SELECT COUNT(*) as cnt FROM tailored_cvs WHERE customer_id = ? AND created_at >= ?',
        (customer_id, since)
    ).fetchone()
    return row['cnt'] if row else 0


def count_emails_this_month(customer_id: int, since: str) -> int:
    """Count emails sent this month."""
    conn = get_connection()
    row = conn.execute(
        'SELECT COUNT(*) as cnt FROM applications WHERE customer_id = ? AND status = ? AND created_at >= ?',
        (customer_id, 'EMAILED', since)
    ).fetchone()
    return row['cnt'] if row else 0


def record_token_usage(customer_id: int, tokens: int, kind: str = 'tailor',
                       note: str | None = None) -> int | None:
    """Append LLM tokens to the customer's ledger. Returns the new row id.

    This is the only place token spend is recorded. It used to be inferred from
    tailored_cvs.qc_notes, but that column holds free text written by
    customer_engine ('; '.join(qc)), so json_extract() found nothing and the
    daily budget always read 0 - the cap could never fire.
    """
    tokens = int(tokens or 0)
    if tokens <= 0:
        return None
    # Write the timestamp explicitly, in LOCAL time, matching the format
    # record_task_event uses and the `since` values callers pass.
    # The column default, datetime('now'), is UTC with a space separator: on a
    # UTC+1 box anything written between local midnight and 01:00 was dated to
    # the previous day and therefore skipped by the daily budget.
    now = datetime.now().isoformat(timespec='seconds')
    with transaction() as conn:
        cursor = conn.execute(
            'INSERT INTO token_usage (customer_id, tokens, kind, note, created_at)'
            ' VALUES (?, ?, ?, ?, ?)',
            (customer_id, tokens, kind, note, now)
        )
        return int(cursor.lastrowid)


def get_tokens_used_since(customer_id: int, since: str) -> int:
    """Total ledgered tokens for a customer since `since`.

    The comparison goes through datetime() on both sides. token_usage.created_at
    defaults to SQLite's datetime('now'), which writes 'YYYY-MM-DD HH:MM:SS',
    while callers pass Python isoformat() timestamps that use a 'T' separator.
    Compared as plain text, space < 'T' meant every row from the current day
    sorted BEFORE the boundary and the daily budget silently read 0.
    """
    try:
        row = get_connection().execute(
            'SELECT COALESCE(SUM(tokens), 0) as total FROM token_usage '
            'WHERE customer_id = ? AND datetime(created_at) >= datetime(?)',
            (customer_id, since)
        ).fetchone()
    except sqlite3.OperationalError as e:
        # An un-migrated database must not read as "0 tokens used", which would
        # disable the cap entirely. Fail loudly instead (cf. B-30).
        raise RuntimeError(f'token accounting unavailable: {e}') from e
    return int(row['total']) if row else 0


def get_tokens_used_today(customer_id: int) -> int:
    """Get total LLM tokens used today."""
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    return get_tokens_used_since(customer_id, today)


def increment_tokens_used(customer_id: int, tokens: int) -> None:
    """Record token usage against a customer.

    Now appends to the token_usage ledger. The previous implementation updated
    the newest tailored_cvs.qc_notes, which was doubly wrong: that UPDATE ran on
    a raw connection with no transaction() so it never committed, and it
    overwrote the QC notes text with a JSON blob.
    """
    record_token_usage(customer_id, tokens)


def get_customer_by_paystack_customer(paystack_customer_code: str):
    """Get customer by Paystack customer code."""
    conn = get_connection()
    return conn.execute(
        'SELECT * FROM customers WHERE paystack_customer_id = ?',
        (paystack_customer_code,)
    ).fetchone()


if __name__ == '__main__':
    init_db()
    print('Database initialized at:', DB_PATH)

    # Run migration if no customers exist
    customers = list_customers()
    if not customers:
        print('No customers found, running migration...')
        report = migrate_from_legacy()
        print('Migration report:', json.dumps(report, indent=2, default=str))
    else:
        print(f'Found {len(customers)} existing customer(s)')
