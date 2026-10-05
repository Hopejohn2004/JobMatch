"""Regression tests for the 2026-10-04 security / data-integrity fix pass.

Each test names the bug it locks down. Source of truth: BUG_REGISTER.md.
These use only the database layer plus the Flask test client - no network, no
subprocesses, no outbound LLM calls.

The shared fixtures (temp_db_path, db, two_customers, web_app_module,
app_client, booted_client) now live in tests/conftest.py.
"""

import pytest


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def as_remote(client, addr='203.0.113.9'):
    client.environ_base['REMOTE_ADDR'] = addr
    return client


def customer_login(client, email, password):
    return client.post('/auth/login', json={'email': email, 'password': password})


# --------------------------------------------------------------------------
# B-26 / R-01 : the connection cache must honour DB_PATH
# --------------------------------------------------------------------------
def test_reassigning_db_path_switches_database(db, tmp_path):
    """Regression: DB_PATH was ignored, so tests wrote into the real DB."""
    before = db.get_customer(1)
    other = tmp_path / 'other.db'
    db.close_db()
    db.DB_PATH = other
    db.init_db()
    try:
        # Fresh database: nothing from the first one may be visible.
        assert db.list_customers() == []
        assert before is None or before['id'] is not None
    finally:
        db.close_db()
        db.DB_PATH = tmp_path / 'test_jobmatch.db'


def test_init_db_creates_billing_and_task_schema(db):
    """B-11 / B-16: columns and the tasks table must exist after init_db()."""
    conn = db.get_connection()
    cols = {r[1] for r in conn.execute('PRAGMA table_info(customers)')}
    assert 'paystack_auth_code' in cols
    assert 'subscription_status' in cols
    prof = {r[1] for r in conn.execute('PRAGMA table_info(customer_profiles)')}
    assert {'cv_source', 'cv_quality', 'cv_repair'} <= prof
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert 'tasks' in tables


def test_migrations_are_idempotent(db):
    assert db.apply_migrations() == []


# --------------------------------------------------------------------------
# B-30 : the app never migrated the database it was pointed at
# --------------------------------------------------------------------------
def _downgrade_to_pre_tasks_schema(db):
    """Recreate the shape of database.py's parent commit's live file."""
    conn = db.get_connection()
    conn.execute('DROP TABLE IF EXISTS tasks')
    conn.execute('ALTER TABLE customers DROP COLUMN paystack_auth_code')
    conn.commit()
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    cols = {r[1] for r in conn.execute('PRAGMA table_info(customers)')}
    assert 'tasks' not in tables and 'paystack_auth_code' not in cols


def test_pre_tasks_database_breaks_usage_counting(db, two_customers):
    """The failure the startup guard exists to prevent."""
    _downgrade_to_pre_tasks_schema(db)
    with pytest.raises(RuntimeError):
        db.count_scans_this_month(two_customers[0], '2026-10-01')


def test_ensure_schema_ready_migrates_before_serving(db, two_customers):
    a, b = two_customers
    counts_before = {
        t: db.get_connection().execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
        for t in ('customers', 'customer_profiles', 'sessions')
    }
    _downgrade_to_pre_tasks_schema(db)

    import web_app
    web_app.ensure_schema_ready()

    conn = db.get_connection()
    assert 'tasks' in {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert 'paystack_auth_code' in {r[1] for r in conn.execute('PRAGMA table_info(customers)')}
    assert db.count_scans_this_month(a, '2026-10-01') == 0
    assert db.count_scans_this_month(b, '2026-10-01') == 0
    for t, n in counts_before.items():
        assert conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] == n, t
    assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert conn.execute('PRAGMA foreign_key_check').fetchall() == []


def test_ensure_schema_ready_is_idempotent(db):
    import web_app
    web_app.ensure_schema_ready()
    web_app.ensure_schema_ready()
    assert db.apply_migrations() == []


def test_startup_block_migrates_before_app_run():
    """__main__ must not reach app.run() with an unmigrated database."""
    from pathlib import Path
    src = (Path(__file__).parent.parent / 'web_app.py').read_text(encoding='utf-8')
    block = src[src.index("if __name__ == '__main__':"):]
    assert 'ensure_schema_ready()' in block
    assert block.index('ensure_schema_ready()') < block.index('app.run(')
    assert 'SystemExit(1)' in block


def test_usage_endpoint_survives_a_pre_tasks_database(booted_client, db, two_customers):
    """End to end: the endpoint that 500'd in production returns 200."""
    customer_login(booted_client, 'alice@example.com', 'pw-alice')
    assert booted_client.get('/api/usage?resource=scan').status_code == 200
    _downgrade_to_pre_tasks_schema(db)
    db.close_db()

    import web_app
    web_app.ensure_schema_ready()

    r = booted_client.get('/api/usage?resource=scan')
    assert r.status_code == 200
    assert {'used', 'limit', 'remaining'} <= set(r.get_json())


# --------------------------------------------------------------------------
# B-04 : create_or_update_profile accepts the cv_* arguments
# --------------------------------------------------------------------------
def test_create_or_update_profile_accepts_cv_fields(db, two_customers):
    a, _ = two_customers
    db.create_or_update_profile(customer_id=a, keywords='python',
                                cv_source='cv.pdf', cv_quality=0.8, cv_repair='fixed dashes')
    prof = db.get_customer_profile(a)
    assert prof['cv_source'] == 'cv.pdf'
    assert prof['cv_quality'] == 0.8
    assert prof['cv_repair'] == 'fixed dashes'


def test_partial_profile_update_preserves_cv_provenance(db, two_customers):
    a, _ = two_customers
    db.create_or_update_profile(customer_id=a, keywords='python',
                                cv_source='cv.pdf', cv_quality=0.8)
    db.create_or_update_profile(customer_id=a, keywords='rust')
    prof = db.get_customer_profile(a)
    assert prof['keywords'] == 'rust'
    assert prof['cv_source'] == 'cv.pdf'
    assert prof['cv_quality'] == 0.8


# --------------------------------------------------------------------------
# B-16 : the scan quota must be able to count
# --------------------------------------------------------------------------
def test_scan_events_are_counted_per_customer(db, two_customers):
    a, b = two_customers
    since = '2000-01-01T00:00:00'
    assert db.count_scans_this_month(a, since) == 0
    db.record_task_event(a, 'Scan for jobs')
    db.record_task_event(a, 'Tailor CVs (top 8)')
    assert db.count_scans_this_month(a, since) == 1
    assert db.count_scans_this_month(b, since) == 0


def test_scan_count_ignores_events_before_since(db, two_customers):
    a, _ = two_customers
    db.record_task_event(a, 'Scan for jobs')
    assert db.count_scans_this_month(a, '2999-01-01T00:00:00') == 0


def test_missing_tasks_table_raises_instead_of_reporting_zero(db, two_customers):
    """Silently returning 0 made the quota unenforceable."""
    a, _ = two_customers
    conn = db.get_connection()
    conn.execute('DROP TABLE tasks')
    conn.commit()
    with pytest.raises(RuntimeError):
        db.count_scans_this_month(a, '2000-01-01T00:00:00')


# --------------------------------------------------------------------------
# B-06 : update_customer whitelist
# --------------------------------------------------------------------------
def test_update_customer_rejects_fields_outside_the_whitelist(db, two_customers):
    """password_hash and id must not be writable through the shared helper.

    subscription_status IS writable here on purpose: the Paystack success and
    webhook paths need it. The control that stops a caller reaching it over HTTP
    is the narrower whitelist in api_update_customer, covered by
    test_admin_patch_cannot_reach_protected_columns.
    """
    a, _ = two_customers
    before = db.get_customer(a)
    db.update_customer(a, password_hash='x' * 40, id=999, name='Alice Renamed')
    after = db.get_customer(a)
    assert after['name'] == 'Alice Renamed'
    assert after['password_hash'] == before['password_hash']
    assert after['id'] == a


def test_update_customer_ignores_unknown_columns(db, two_customers):
    a, _ = two_customers
    assert db.update_customer(a, not_a_column='x') is False


# --------------------------------------------------------------------------
# B-18 : set_active_cv must not damage the owner on rejection
# --------------------------------------------------------------------------
def test_set_active_cv_rejects_foreign_cv_without_clearing_active(db, two_customers):
    a, b = two_customers
    mine = db.create_customer_cv(customer_id=a, original_filename='a.pdf',
                                  stored_path='x/a.txt', file_hash='h1',
                                  text_content='A CV')
    theirs = db.create_customer_cv(customer_id=b, original_filename='b.pdf',
                                   stored_path='x/b.txt', file_hash='h2',
                                   text_content='B CV')
    assert db.get_customer_active_cv(a)['id'] == mine

    assert db.set_active_cv(a, theirs) is False

    # The rejected call must leave the owner's active CV exactly as it was.
    active = db.get_customer_active_cv(a)
    assert active is not None and active['id'] == mine
    n_active = db.get_connection().execute(
        'SELECT COUNT(*) FROM customer_cvs WHERE customer_id = ? AND is_active = 1', (a,)
    ).fetchone()[0]
    assert n_active == 1


def test_set_active_cv_switches_within_own_records(db, two_customers):
    a, _ = two_customers
    first = db.create_customer_cv(customer_id=a, original_filename='1.txt',
                                  stored_path='x/1.txt', file_hash='h1', text_content='one')
    second = db.create_customer_cv(customer_id=a, original_filename='2.txt',
                                   stored_path='x/2.txt', file_hash='h2', text_content='two')
    assert db.set_active_cv(a, first) is True
    assert db.set_active_cv(a, second) is True
    assert db.get_customer_active_cv(a)['id'] == second


# --------------------------------------------------------------------------
# B-17 : token accounting must commit, into a real ledger
# --------------------------------------------------------------------------
def test_increment_tokens_used_commits(db, two_customers):
    """Token spend accumulates in token_usage, not in tailored_cvs.qc_notes.

    The old implementation UPDATEd the newest tailored_cvs.qc_notes. That
    column holds free text written by customer_engine ('; '.join(qc)), so
    json_extract() found nothing and get_tokens_used_today() always read 0 -
    the daily_token_budget cap could never fire. It also ran outside
    transaction(), so the write never committed, and it destroyed the QC notes.
    """
    a, _ = two_customers
    cv_id = db.create_customer_cv(customer_id=a, original_filename='a.txt',
                                  stored_path='x/a.txt', file_hash='h', text_content='cv')
    job_id = db.create_job(source='t', title='Dev', company='Acme')
    t = db.create_tailored_cv(customer_id=a, job_id=job_id, source_cv_id=cv_id,
                              stored_path='t/a.docx', qc_notes='checked: no dates')

    db.increment_tokens_used(a, 120)
    db.increment_tokens_used(a, 30)

    assert db.get_tokens_used_today(a) == 150

    # The QC notes are prose and must survive untouched.
    notes = db.get_connection().execute(
        'SELECT qc_notes FROM tailored_cvs WHERE id = ?', (t,)
    ).fetchone()['qc_notes']
    assert notes == 'checked: no dates'

    # Append-only: two calls, two rows, no lost update.
    rows = db.get_connection().execute(
        'SELECT tokens FROM token_usage WHERE customer_id = ? ORDER BY id', (a,)
    ).fetchall()
    assert [r['tokens'] for r in rows] == [120, 30]


# --------------------------------------------------------------------------
# B-01 / B-02 / B-03 : setup mode and the public allow-list
# --------------------------------------------------------------------------
def test_setup_mode_blocks_anonymous_api_remotely(app_client):
    c = as_remote(app_client)
    for path in ('/api/customers', '/api/state', '/api/matches', '/api/usage?resource=scan'):
        assert c.get(path).status_code == 403, path


def test_setup_mode_blocks_anonymous_api_from_localhost_too(app_client):
    """Only the bootstrap endpoint stays reachable before setup."""
    c = as_remote(app_client, '127.0.0.1')
    assert c.get('/api/customers').status_code in (401, 403)
    assert c.post('/api/status_setup', json={'password': 'ownerpassword123'}).status_code == 200


def test_remote_cannot_claim_first_run_setup(app_client, tmp_path):
    c = as_remote(app_client)
    assert c.post('/api/status_setup', json={'password': 'attacker-chosen'}).status_code == 403
    assert not (tmp_path / 'admin.env').exists()


def test_anonymous_cannot_reach_the_customer_admin_surface(booted_client, two_customers):
    a, _ = two_customers
    c = booted_client
    assert c.get('/api/customers').status_code == 401
    assert c.post('/api/customers', json={'name': 'X', 'email': 'x@y.com'}).status_code == 401
    assert c.patch(f'/api/customers/{a}', json={'name': 'pwned'}).status_code == 401
    assert c.get(f'/api/customers/{a}/cvs').status_code == 401


def test_admin_patch_cannot_reach_protected_columns(booted_client, db, two_customers):
    """B-06: the HTTP PATCH whitelist is narrower than the DB helper's."""
    a, _ = two_customers
    before = db.get_customer(a)
    c = booted_client
    assert c.post('/api/login', json={'password': 'ownerpassword123'}).status_code == 200
    r = c.patch(f'/api/customers/{a}', json={
        'name': 'Alice Renamed',
        'password_hash': 'x' * 40,
        'subscription_status': 'lifetime',
        'status': 'archived',
        'monthly_scan_limit': 99999,
        'id': 999,
    })
    assert r.status_code == 200
    after = db.get_customer(a)
    assert after['name'] == 'Alice Renamed'
    assert after['password_hash'] == before['password_hash']
    assert after['subscription_status'] == before['subscription_status']
    assert after['status'] == before['status']
    assert after['monthly_scan_limit'] == before['monthly_scan_limit']
    assert after['id'] == a


# --------------------------------------------------------------------------
# B-04 / B-05 / B-07 : cross-tenant access
# --------------------------------------------------------------------------
def test_customer_cannot_reach_another_customers_records(booted_client, two_customers):
    a, b = two_customers
    c = booted_client
    assert customer_login(c, 'alice@example.com', 'pw-alice').status_code == 200
    for method, path in (('get', f'/api/customers/{b}/profile'),
                         ('get', f'/api/customers/{b}/cvs'),
                         ('get', f'/api/customers/{b}/cvs/active'),
                         ('get', f'/api/customers/{b}/matches'),
                         ('get', '/api/customers')):
        assert getattr(c, method)(path).status_code in (401, 403), path
    assert c.patch(f'/api/customers/{b}', json={'name': 'pwned'}).status_code in (401, 403)


def test_customer_reads_and_writes_only_their_own_profile(booted_client, db, two_customers):
    a, b = two_customers
    c = booted_client
    customer_login(c, 'alice@example.com', 'pw-alice')

    assert c.get('/api/profile').status_code == 200
    assert c.post('/api/profile', json={'keywords': 'alice-new'}).status_code == 200
    assert db.get_customer_profile(a)['keywords'] == 'alice-new'
    assert db.get_customer_profile(b)['keywords'] == 'bob-secret'


def test_customer_id_in_the_body_cannot_switch_tenant(booted_client, db, two_customers):
    a, b = two_customers
    c = booted_client
    customer_login(c, 'alice@example.com', 'pw-alice')
    c.post('/api/profile', json={'keywords': 'mine', 'customer_id': b})
    assert db.get_customer_profile(b)['keywords'] == 'bob-secret'


def test_customer_responses_never_include_secrets(booted_client, two_customers):
    a, _ = two_customers
    c = booted_client
    # admin session for these admin-only reads
    assert c.post('/api/login', json={'password': 'ownerpassword123'}).status_code == 200
    rows = c.get('/api/customers').get_json()['customers']
    assert rows
    for row in rows:
        assert 'password_hash' not in row
        assert 'paystack_auth_code' not in row
    one = c.get(f'/api/customers/{a}').get_json()
    assert 'password_hash' not in one
    assert 'paystack_auth_code' not in one


# --------------------------------------------------------------------------
# B-09 / B-10 : shared legacy files must not cross tenants
# --------------------------------------------------------------------------
def test_load_profile_does_not_fall_back_to_shared_file(db, two_customers, tmp_path, monkeypatch):
    import customer_engine
    _, b = two_customers
    # plant a poisoned shared legacy file
    legacy = tmp_path / 'customer_profile.json'
    legacy.write_text('{"name": "Mallory", "keywords": "leaked"}', encoding='utf-8')
    monkeypatch.setattr(customer_engine, 'PROFILE_PATH', legacy, raising=False)

    fresh = db.create_customer(name='Carol', email='carol@example.com')
    profile = customer_engine.load_profile(fresh)
    assert profile.get('keywords') != 'leaked'
    assert 'Mallory' not in str(profile)
    # the other customer's real profile is unaffected and still correct
    assert db.get_customer_profile(b)['keywords'] == 'bob-secret'


def test_get_active_cv_path_returns_empty_instead_of_the_shared_cv(db, two_customers, monkeypatch):
    import customer_engine
    a, _ = two_customers
    shared = customer_engine.CV_PATH
    assert customer_engine.get_active_cv_path(a) == ''
    # the fallback must not resurrect a pre-existing shared file either
    if shared.exists():
        assert customer_engine.get_active_cv_path(a) != str(shared)


def test_save_profile_keeps_the_location_alias(db, two_customers):
    import customer_engine
    a, _ = two_customers
    saved = customer_engine.save_profile(a, name='Alice', keywords='python', location='remote')
    assert saved['name'] == 'Alice'
    assert saved['keywords'] == 'python'
    assert saved['location'] == 'remote'


# --------------------------------------------------------------------------
# B-13 : the duplicate /api/scan route
# --------------------------------------------------------------------------
def test_api_scan_has_exactly_one_handler():
    import web_app
    handlers = [(r.rule, r.endpoint) for r in web_app.app.url_map.iter_rules()
                if r.rule == '/api/scan']
    assert len(handlers) == 1, handlers
    assert handlers[0][1] == 'api_scan'
    cust = [r for r in web_app.app.url_map.iter_rules() if r.rule == '/api/customer/scan']
    assert len(cust) == 1 and cust[0].endpoint == 'api_customer_scan'


# --------------------------------------------------------------------------
# B-14 / B-15 : usage and billing endpoints
# --------------------------------------------------------------------------
def test_usage_endpoint_returns_used_limit_remaining(booted_client, two_customers):
    c = booted_client
    customer_login(c, 'alice@example.com', 'pw-alice')
    r = c.get('/api/usage?resource=scan')
    assert r.status_code == 200
    body = r.get_json()
    assert {'used', 'limit', 'remaining'} <= set(body)


def test_usage_endpoint_rejects_unknown_resource(booted_client, two_customers):
    c = booted_client
    customer_login(c, 'alice@example.com', 'pw-alice')
    assert c.get('/api/usage?resource=bogus').status_code == 400


def test_billing_status_hides_secrets(booted_client, two_customers):
    c = booted_client
    customer_login(c, 'alice@example.com', 'pw-alice')
    body = c.get('/api/billing/status').get_json()
    assert 'monthly_scan_limit' in body
    assert 'password_hash' not in body
    assert 'paystack_auth_code' not in body


# --------------------------------------------------------------------------
# B-21 : expired sessions are actually pruned
# --------------------------------------------------------------------------
def test_init_db_prunes_expired_sessions(db, two_customers):
    from datetime import datetime, timedelta
    a, _ = two_customers
    db.create_session(a, (datetime.now() - timedelta(days=90)).isoformat(timespec='seconds'))
    before = db.get_connection().execute('SELECT COUNT(*) FROM sessions').fetchone()[0]
    assert before >= 1
    db.init_db()
    remaining = db.get_connection().execute(
        'SELECT COUNT(*) FROM sessions WHERE expires_at < ?',
        (datetime.now().isoformat(timespec='seconds'),)
    ).fetchone()[0]
    assert remaining == 0


# --------------------------------------------------------------------------
# B-19 / B-20 : output encoding in the dashboard
# --------------------------------------------------------------------------
def test_dashboard_esc_really_escapes():
    from pathlib import Path
    html = (Path(__file__).parent.parent / 'web_dashboard.html').read_text(encoding='utf-8')
    idx = html.index('const esc')
    body = html[idx:idx + 400]
    for entity in ('&amp;', '&lt;', '&gt;', '&quot;', '&#39;'):
        assert entity in body, entity


def test_dashboard_does_not_double_escape_textcontent():
    from pathlib import Path
    html = (Path(__file__).parent.parent / 'web_dashboard.html').read_text(encoding='utf-8')
    assert 'textContent = esc(' not in html
