"""Regression tests for LLM token accounting and async quota reservations.

Source of truth: BUG_REGISTER.md (B-31 token accounting, B-32 tailor
reservation race, B-33 /api/tailor TypeError).

No network, no subprocesses, no real LLM calls: providers are monkeypatched.
"""

import time
from datetime import datetime, timedelta

import pytest


@pytest.fixture
def month_start():
    return (datetime.now().replace(day=1, hour=0, minute=0, second=0,
                                   microsecond=0) - timedelta(days=1)).isoformat()


# --------------------------------------------------------------------------
# The ledger must count rows written TODAY
# --------------------------------------------------------------------------
def test_token_ledger_counts_same_day_rows(db, two_customers):
    """The ledger must count rows written TODAY.

    Two format traps, both of which silently zeroed the daily budget:
      * token_usage.created_at defaulted to SQLite's datetime('now'), which is
        UTC and writes 'YYYY-MM-DD HH:MM:SS', while callers pass Python
        isoformat() -> 'YYYY-MM-DDTHH:MM:SS'. Compared as TEXT, space (0x20)
        sorts before 'T' (0x54), so every row from the current day fell BEFORE
        the midnight boundary.
      * That default is also UTC while `since` is local midnight, so on a UTC+1
        machine anything written between 00:00 and 01:00 local was dated to the
        previous day. record_token_usage now writes local time explicitly.
    """
    a, _ = two_customers
    db.record_token_usage(a, 1234, kind='tailor')

    created = db.get_connection().execute(
        'SELECT created_at FROM token_usage').fetchone()['created_at']
    # Local ISO with a 'T', and matching the local date - not UTC.
    assert created.startswith(datetime.now().strftime('%Y-%m-%d')), created
    assert db.get_tokens_used_today(a) == 1234


def test_token_ledger_reads_legacy_space_separated_rows(db, two_customers):
    """Rows written with the old UTC/space default must still be counted.

    get_tokens_used_since goes through datetime() on both sides precisely so
    both stored formats work, not just the one we write today.
    """
    a, _ = two_customers
    conn = db.get_connection()
    conn.execute("INSERT INTO token_usage (customer_id, tokens, kind, note, created_at)"
                 " VALUES (?, ?, 'tailor', 'legacy', datetime('now'))", (a, 777))
    assert db.get_tokens_used_today(a) == 777


def test_token_ledger_respects_the_since_boundary(db, two_customers):
    a, _ = two_customers
    db.record_token_usage(a, 500)
    future = (datetime.now() + timedelta(days=1)).isoformat()
    assert db.get_tokens_used_since(a, future) == 0


def test_record_token_usage_ignores_non_positive(db, two_customers):
    """A failed LLM call can report 0 tokens; that must not write a row."""
    a, _ = two_customers
    assert db.record_token_usage(a, 0) is None
    assert db.record_token_usage(a, -5) is None
    assert db.get_tokens_used_today(a) == 0


def test_token_ledger_is_per_customer(db, two_customers):
    a, b = two_customers
    db.record_token_usage(a, 900)
    db.record_token_usage(b, 100)
    assert db.get_tokens_used_today(a) == 900
    assert db.get_tokens_used_today(b) == 100


def test_missing_token_ledger_raises_instead_of_reporting_zero(db, two_customers):
    """An un-migrated database must not read as '0 tokens used'.

    That would disable the daily cap entirely - the exact failure mode of B-30
    for scans, and of B-31 for tokens.
    """
    a, _ = two_customers
    conn = db.get_connection()
    conn.execute('DROP TABLE token_usage')
    conn.commit()
    with pytest.raises(RuntimeError):
        db.get_tokens_used_today(a)


def test_missing_tasks_table_raises_from_unit_counting(db, two_customers,
                                                       month_start):
    """check_usage_limit now counts reservations, so this path needs the guard too."""
    a, _ = two_customers
    conn = db.get_connection()
    conn.execute('DROP TABLE tasks')
    conn.commit()
    with pytest.raises(RuntimeError):
        db.count_task_units_since(a, 'Tailor CVs', month_start)


def test_configured_gemini_model_is_not_a_dead_one():
    """B-34: the configured model was 'gemini-1.5-flash', which the API 404s.

    Nothing caught this because call_gemini returns None on "model not found"
    so the caller silently falls through to the next provider. Measured live
    2026-10-04, 8 calls each:
      gemini-3.6-flash -> 7/8 HTTP 200 (one 429), no 503s
      gemini-1.5-flash -> 0/8, all 404
      gemini-2.5-flash -> 404 "no longer available to new users"
    """
    import cv_tailor
    dead = ('gemini-1.5-flash', 'gemini-2.5-flash', 'gemini-1.5-pro',
            'gemini-2.0-flash')
    assert cv_tailor.PROVIDERS['gemini']['model'] not in dead


def test_rejected_call_is_not_charged(clean_tally, monkeypatch):
    """A 404 'model not found' generated nothing, so estimate nothing.

    tailor() charges an estimate when no usage block comes back, which is right
    for a call that was transmitted and lost. Charging it for a request the
    provider refused outright would bill the customer for our config error.
    """
    import cv_tailor
    monkeypatch.setattr(cv_tailor, 'get_model', lambda env, p: 'gemini-1.5-flash')
    monkeypatch.setattr(cv_tailor, 'get_key', lambda env, p: 'k')
    monkeypatch.setattr(cv_tailor, 'call_gemini', lambda env, prompt, model: None)

    assert cv_tailor.tailor({}, 'p' * 400, 'gemini') is None
    assert cv_tailor.take_token_usage() == {'tokens': 0, 'calls': 0}


# --------------------------------------------------------------------------
# Provider usage metadata must actually be captured
# --------------------------------------------------------------------------
class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload


@pytest.fixture
def clean_tally():
    import cv_tailor
    cv_tailor.take_token_usage()
    yield cv_tailor
    cv_tailor.take_token_usage()


def test_gemini_usage_metadata_is_tallied(clean_tally, monkeypatch):
    import cv_tailor
    payload = {
        'candidates': [{'content': {'parts': [{'text': 'tailored cv'}]}}],
        'usageMetadata': {'totalTokenCount': 4321},
    }
    monkeypatch.setattr(cv_tailor, 'get_key', lambda env, p: 'k')
    monkeypatch.setattr(cv_tailor.requests, 'post',
                        lambda *a, **kw: _FakeResponse(payload))

    assert cv_tailor.call_gemini({}, 'prompt', 'gemini-x') == 'tailored cv'
    assert cv_tailor.take_token_usage() == {'tokens': 4321, 'calls': 1}


def test_openai_compat_usage_is_tallied(clean_tally, monkeypatch):
    import cv_tailor
    payload = {
        'choices': [{'message': {'content': 'tailored cv'}}],
        'usage': {'prompt_tokens': 1000, 'completion_tokens': 250},
    }
    monkeypatch.setattr(cv_tailor, 'get_key', lambda env, p: 'k')
    monkeypatch.setattr(cv_tailor, 'get_model', lambda env, p: 'm')
    monkeypatch.setattr(cv_tailor.requests, 'post',
                        lambda *a, **kw: _FakeResponse(payload))

    assert cv_tailor.call_openai_compat({}, 'groq', 'prompt') == 'tailored cv'
    assert cv_tailor.take_token_usage() == {'tokens': 1250, 'calls': 1}


def test_missing_usage_block_falls_back_to_an_estimate(clean_tally, monkeypatch):
    """No usage block must still move the budget, not silently cost nothing.

    Some OpenAI-compatible gateways omit the usage block entirely. Without a
    fallback the call would be free, and a customer looping tailor requests
    would spend real money with the daily budget stuck at 0.
    """
    import cv_tailor
    payload = {'choices': [{'message': {'content': 'x' * 400}}]}
    monkeypatch.setattr(cv_tailor, 'get_key', lambda env, p: 'k')
    monkeypatch.setattr(cv_tailor, 'get_model', lambda env, p: 'm')
    monkeypatch.setattr(cv_tailor.requests, 'post',
                        lambda *a, **kw: _FakeResponse(payload))

    assert cv_tailor.tailor({}, 'p' * 400, 'groq') == 'x' * 400
    usage = cv_tailor.take_token_usage()
    assert usage['calls'] == 1
    assert usage['tokens'] >= 200


def test_failed_call_after_send_is_still_estimated(clean_tally, monkeypatch):
    """A request that was transmitted but then failed still cost tokens."""
    import cv_tailor

    def boom(*a, **kw):
        raise RuntimeError('read timeout')

    monkeypatch.setattr(cv_tailor, 'get_model', lambda env, p: 'm')
    monkeypatch.setattr(cv_tailor.requests, 'post', boom)

    with pytest.raises(RuntimeError):
        cv_tailor.tailor({}, 'p' * 400, 'gemini')
    assert cv_tailor.take_token_usage()['tokens'] >= 100


def test_tally_resets_between_calls(clean_tally):
    """Each tailored CV must be billed for its own calls, not the batch total."""
    import cv_tailor
    cv_tailor._record_tokens(100)
    assert cv_tailor.take_token_usage() == {'tokens': 100, 'calls': 1}
    assert cv_tailor.take_token_usage() == {'tokens': 0, 'calls': 0}


def test_record_tokens_tolerates_junk(clean_tally):
    import cv_tailor
    for junk in (None, '', 'abc', {}, -1):
        cv_tailor._record_tokens(junk)
    assert cv_tailor.take_token_usage() == {'tokens': 0, 'calls': 0}


# --------------------------------------------------------------------------
# Reservations: units, release on failure, no double counting
# --------------------------------------------------------------------------
def test_reserved_units_are_charged_before_completion(db, two_customers, month_start):
    a, _ = two_customers
    db.record_task_event(a, 'Tailor CVs', units=12)
    assert db.count_task_units_since(a, 'Tailor CVs', month_start) == 12


def test_failed_task_releases_its_units(db, two_customers, month_start):
    a, _ = two_customers
    tid = db.record_task_event(a, 'Tailor CVs', units=12)
    db.finish_task_event(tid, False)
    assert db.count_task_units_since(a, 'Tailor CVs', month_start) == 0
    assert db.count_task_units_since(a, 'Tailor CVs', month_start,
                                     include_failed=True) == 12


def test_completed_task_keeps_its_units(db, two_customers, month_start):
    a, _ = two_customers
    tid = db.record_task_event(a, 'Tailor CVs', units=12)
    db.finish_task_event(tid, True)
    assert db.count_task_units_since(a, 'Tailor CVs', month_start) == 12


def test_tailor_quota_counts_reservations_not_just_completions(db, two_customers,
                                                               web_app_module,
                                                               month_start):
    """The overshoot bug: completions land minutes later, so a client could
    fire several tailor requests inside the rate-limit window and blow past
    monthly_tailor_limit before a single tailored_cvs row existed."""
    a, _ = two_customers
    ok, msg = web_app_module.check_usage_limit(a, 'tailor')
    assert ok, msg

    db.record_task_event(a, web_app_module.TASK_TAILOR, units=50)
    ok, msg = web_app_module.check_usage_limit(a, 'tailor')
    assert not ok
    assert '50/50' in msg

    # Even if the reservation later failed, the quota comes back.
    db.finish_task_event(db.get_connection().execute(
        'SELECT id FROM tasks WHERE customer_id = ? ORDER BY id DESC LIMIT 1',
        (a,)).fetchone()['id'], False)
    ok, msg = web_app_module.check_usage_limit(a, 'tailor')
    assert ok, msg


def test_scan_quota_ignores_failed_reservations(db, two_customers, web_app_module,
                                                month_start):
    a, _ = two_customers
    db.record_task_event(a, web_app_module.TASK_SCAN, units=1)
    ok, msg = web_app_module.check_usage_limit(a, 'scan')
    assert ok, msg


def test_daily_token_budget_blocks_when_ledger_is_full(db, two_customers,
                                                       web_app_module):
    a, _ = two_customers
    db.record_token_usage(a, 49999)
    ok, msg = web_app_module.check_usage_limit(a, 'tokens')
    assert ok, msg
    db.record_token_usage(a, 1)
    ok, msg = web_app_module.check_usage_limit(a, 'tokens')
    assert not ok
    assert 'token budget' in msg


# --------------------------------------------------------------------------
# start_or_report: the timeout bug and reservation bookkeeping
# --------------------------------------------------------------------------
def test_start_or_report_accepts_timeout(web_app_module):
    """B-33: /api/tailor passed timeout=1800 to a wrapper that had no such
    parameter, so the route raised TypeError and returned 500 every time."""
    import inspect
    params = inspect.signature(web_app_module.start_or_report).parameters
    assert 'timeout' in params


def _stub_task(web_app_module, tid='task-1'):
    web_app_module.TASKS[tid] = {'id': tid, 'name': 'x', 'args': [], 'log': '',
                                 'status': 'running', 'ok': False,
                                 'started': time.time(), 'finished': None}


def test_start_or_report_reserves_units_when_accepted(web_app_module, db,
                                                      two_customers, monkeypatch,
                                                      month_start):
    a, _ = two_customers
    monkeypatch.setattr(web_app_module, 'start_task',
                        lambda name, script, args=None, timeout=1800: ('task-1', None))
    _stub_task(web_app_module, 'task-1')

    res = web_app_module.start_or_report('Tailor CVs', 'customer_engine.py',
                                         ['tailor'], timeout=1800,
                                         reserve=[(a, web_app_module.TASK_TAILOR, 7)])
    assert res['ok'] is True
    assert web_app_module.TASKS['task-1']['quota_event_ids']
    assert db.count_task_units_since(a, web_app_module.TASK_TAILOR, month_start) == 7


def test_start_or_report_does_not_reserve_when_busy(web_app_module, db,
                                                    two_customers, monkeypatch,
                                                    month_start):
    """A request refused because another task is running must cost nothing."""
    a, _ = two_customers
    monkeypatch.setattr(web_app_module, 'start_task',
                        lambda name, script, args=None, timeout=1800:
                        ('other', {'id': 'other', 'name': 'Scan for jobs'}))
    res = web_app_module.start_or_report('Tailor CVs', 'customer_engine.py', [],
                                         reserve=[(a, web_app_module.TASK_TAILOR, 7)])
    assert res['ok'] is False
    assert db.count_task_units_since(a, web_app_module.TASK_TAILOR, month_start) == 0


def test_start_or_report_records_both_quotas_for_a_run(web_app_module, db,
                                                       two_customers, monkeypatch,
                                                       month_start):
    """A single run consumes one scan unit AND `top` tailor units."""
    a, _ = two_customers
    monkeypatch.setattr(web_app_module, 'start_task',
                        lambda name, script, args=None, timeout=1800: ('task-1', None))
    _stub_task(web_app_module, 'task-1')

    web_app_module.start_or_report(
        'Find jobs + tailor CVs (top 8)', 'customer_engine.py', [],
        reserve=[(a, web_app_module.TASK_SCAN, 1), (a, web_app_module.TASK_TAILOR, 8)])
    assert db.count_task_units_since(a, web_app_module.TASK_SCAN, month_start) == 1
    assert db.count_task_units_since(a, web_app_module.TASK_TAILOR, month_start) == 8


def test_start_task_is_unaffected_when_reservation_write_fails(web_app_module,
                                                               monkeypatch):
    """The job must still run even if the quota row cannot be written."""
    def boom(*a, **kw):
        raise RuntimeError('database is locked')

    monkeypatch.setattr(web_app_module, 'start_task',
                        lambda name, script, args=None, timeout=1800: ('task-1', None))
    monkeypatch.setattr(web_app_module.database, 'record_task_event', boom)
    _stub_task(web_app_module, 'task-1')
    res = web_app_module.start_or_report('Tailor CVs', 'customer_engine.py', [],
                                         reserve=[(1, 'Tailor CVs', 3)])
    assert res['ok'] is True
