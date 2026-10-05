"""Pytest configuration for JobMatch tests.

The shared fixtures below (temp database, throwaway customers, Flask test
clients) used to live inside test_security_regressions.py, which made them
unreachable from any other test module. They are here now so every test file
gets the same isolated database.
"""

import os
import sys
from pathlib import Path

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Disable rate limiting for tests
os.environ['PYTEST_DISABLE_RATELIMIT'] = '1'

pytest_plugins = []


def pytest_configure(config):
    """Configure pytest."""
    config.addinivalue_line("markers", "smoke: quick smoke tests")
    config.addinivalue_line("markers", "slow: slow tests")
    config.addinivalue_line("markers", "integration: integration tests")


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------
@pytest.fixture
def temp_db_path():
    """Point the database at a throwaway file for the duration of the test."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        original = os.environ.get('JOBMATCH_DB_PATH')
        target = Path(tmpdir) / 'test_jobmatch.db'
        os.environ['JOBMATCH_DB_PATH'] = str(target)
        import database
        # B-26: reassigning DB_PATH must actually switch databases.
        database.DB_PATH = target
        database.close_db()
        database.init_db()
        yield target
        database.close_db()
        if original:
            os.environ['JOBMATCH_DB_PATH'] = original
        else:
            os.environ.pop('JOBMATCH_DB_PATH', None)


@pytest.fixture
def db(temp_db_path):
    import database
    return database


@pytest.fixture
def two_customers(db):
    a = db.create_customer_with_password('Alice', 'alice@example.com', 'pw-alice', 'Lagos')
    b = db.create_customer_with_password('Bob', 'bob@example.com', 'pw-bob', 'Abuja')
    db.create_or_update_profile(customer_id=a, keywords='alice-secret')
    db.create_or_update_profile(customer_id=b, keywords='bob-secret')
    return a, b


@pytest.fixture
def web_app_module(temp_db_path, tmp_path, monkeypatch):
    """Import web_app with the admin password redirected into tmp_path."""
    import database
    import web_app

    monkeypatch.setattr(web_app, 'ADMIN_PATH', str(tmp_path / 'admin.env'), raising=False)
    monkeypatch.setattr(web_app, 'SETUP_MODE', True, raising=False)
    web_app.app.config['TESTING'] = True
    web_app.app.config['RATELIMIT_ENABLED'] = False
    database.close_db()
    yield web_app
    database.close_db()


@pytest.fixture
def app_client(web_app_module):
    with web_app_module.app.test_client() as c:
        yield c


@pytest.fixture
def booted_client(app_client, web_app_module, tmp_path):
    """A fresh remote client for a server whose first-run setup is already done.

    The gate fails closed while no admin password exists, so tests about normal
    operation have to finish the local bootstrap first. The setup is done with a
    throwaway client so the returned client carries no admin session - otherwise
    it would be admin *and* customer and every authorization check would pass.
    """
    setup_client = web_app_module.app.test_client()
    setup_client.environ_base['REMOTE_ADDR'] = '127.0.0.1'
    assert setup_client.post('/api/status_setup',
                             json={'password': 'ownerpassword123'}).status_code == 200
    fresh = web_app_module.app.test_client()
    fresh.environ_base['REMOTE_ADDR'] = '203.0.113.9'
    return fresh
