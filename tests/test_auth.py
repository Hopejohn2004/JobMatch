"""Authentication and authorization tests for JobMatch M2.1."""

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / 'test_jobmatch.db'
        # Set environment variable for database path
        original_db = os.environ.get('JOBMATCH_DB_PATH')
        os.environ['JOBMATCH_DB_PATH'] = str(db_path)
        yield str(db_path)
        if original_db:
            os.environ['JOBMATCH_DB_PATH'] = original_db
        else:
            os.environ.pop('JOBMATCH_DB_PATH', None)


@pytest.fixture
def db_module(temp_db):
    """Import database module with test database."""
    import database
    database.DB_PATH = Path(temp_db)
    database.DATA = Path(temp_db).parent
    database.init_db()
    yield database
    database.close_db()


@pytest.fixture
def client(db_module, tmp_path, monkeypatch):
    """Create a test client with the web app.

    ADMIN_PATH is redirected as well as the database. It used to point at the
    real project-root web_admin.env, and TestAdminAuthenticationCompatibility
    wrote to it and then os.remove()'d it in a finally block - so running the
    suite silently deleted the owner's admin password, flipped the app into
    first-run setup mode, and made every remote /api/* request return 403.
    """
    import web_app
    from web_app import app
    monkeypatch.setattr(web_app, 'ADMIN_PATH', str(tmp_path / 'web_admin.env'),
                        raising=False)
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client


def assert_unauthenticated(response):
    """Assert a request was refused as unauthenticated.

    Deliberately does NOT assert one exact error string. Which of the two
    correct 401s comes back depends on whether an admin password is configured:
    with one, gate() short-circuits before the route runs and says
    'login required' (web_app.py:218); without one, a local request falls
    through to the route's own check and says 'not authenticated'
    (web_app.py:692 and neighbours).

    These tests used to assert 'not authenticated' only, so they passed solely
    because the destructive admin-env tests deleted web_admin.env before this
    class ran. Configure an admin password - i.e. deploy for real - and all
    four fail on wording despite the behaviour being right.
    """
    assert response.status_code == 401
    data = response.get_json()
    assert data['ok'] is False
    assert data['error'].lower() in ('not authenticated', 'login required'), data


class TestCustomerRegistration:
    """Test customer registration."""

    def test_successful_registration(self, client):
        """Test successful customer registration."""
        response = client.post('/auth/register', json={
            'name': 'Test User',
            'email': 'test@example.com',
            'password': 'securepassword123',
            'location': 'remote',
            'country': 'nigeria'
        })
        assert response.status_code == 200
        data = response.get_json()
        assert data['ok'] is True
        assert 'customer_id' in data
        assert data['customer_id'] == 1
        
        # Check session cookie is set
        assert 'customer_session' in response.headers.get('Set-Cookie', '')

    def test_duplicate_email_registration(self, client):
        """Test registration with duplicate email fails."""
        client.post('/auth/register', json={
            'name': 'Test User',
            'email': 'test@example.com',
            'password': 'securepassword123'
        })
        response = client.post('/auth/register', json={
            'name': 'Another User',
            'email': 'test@example.com',
            'password': 'anotherpassword123'
        })
        assert response.status_code == 400
        data = response.get_json()
        assert data['ok'] is False
        assert 'email already registered' in data['error'].lower()

    def test_missing_name(self, client):
        """Test registration without name fails."""
        response = client.post('/auth/register', json={
            'email': 'test@example.com',
            'password': 'securepassword123'
        })
        assert response.status_code == 400
        data = response.get_json()
        assert data['ok'] is False
        assert 'name required' in data['error'].lower()

    def test_missing_email(self, client):
        """Test registration without email fails."""
        response = client.post('/auth/register', json={
            'name': 'Test User',
            'password': 'securepassword123'
        })
        assert response.status_code == 400
        data = response.get_json()
        assert data['ok'] is False
        assert 'email required' in data['error'].lower()

    def test_missing_password(self, client):
        """Test registration without password fails."""
        response = client.post('/auth/register', json={
            'name': 'Test User',
            'email': 'test@example.com'
        })
        assert response.status_code == 400
        data = response.get_json()
        assert data['ok'] is False
        assert 'password required' in data['error'].lower()

    def test_invalid_email_format(self, client):
        """Test registration with invalid email format fails."""
        response = client.post('/auth/register', json={
            'name': 'Test User',
            'email': 'invalid-email',
            'password': 'securepassword123'
        })
        assert response.status_code == 400
        data = response.get_json()
        assert data['ok'] is False
        assert 'invalid email' in data['error'].lower()

    def test_weak_password(self, client):
        """Test registration with weak password fails."""
        response = client.post('/auth/register', json={
            'name': 'Test User',
            'email': 'test@example.com',
            'password': 'short'
        })
        assert response.status_code == 400
        data = response.get_json()
        assert data['ok'] is False
        assert 'at least 8 characters' in data['error'].lower()

    def test_name_too_long(self, client):
        """Test registration with name too long fails."""
        response = client.post('/auth/register', json={
            'name': 'x' * 101,
            'email': 'test@example.com',
            'password': 'securepassword123'
        })
        assert response.status_code == 400
        data = response.get_json()
        assert data['ok'] is False
        assert 'name too long' in data['error'].lower()


class TestCustomerLogin:
    """Test customer login."""

    def test_successful_login(self, client):
        """Test successful customer login."""
        # First register
        client.post('/auth/register', json={
            'name': 'Test User',
            'email': 'test@example.com',
            'password': 'securepassword123'
        })
        # Then login
        response = client.post('/auth/login', json={
            'email': 'test@example.com',
            'password': 'securepassword123'
        })
        assert response.status_code == 200
        data = response.get_json()
        assert data['ok'] is True
        assert 'customer_id' in data
        assert 'customer_session' in response.headers.get('Set-Cookie', '')

    def test_wrong_password(self, client):
        """Test login with wrong password fails."""
        client.post('/auth/register', json={
            'name': 'Test User',
            'email': 'test@example.com',
            'password': 'securepassword123'
        })
        response = client.post('/auth/login', json={
            'email': 'test@example.com',
            'password': 'wrongpassword'
        })
        assert response.status_code == 401
        data = response.get_json()
        assert data['ok'] is False
        assert 'invalid credentials' in data['error'].lower()

    def test_nonexistent_email(self, client):
        """Test login with nonexistent email fails."""
        response = client.post('/auth/login', json={
            'email': 'nonexistent@example.com',
            'password': 'securepassword123'
        })
        assert response.status_code == 401
        data = response.get_json()
        assert data['ok'] is False
        assert 'invalid credentials' in data['error'].lower()

    def test_missing_credentials(self, client):
        """Test login without credentials fails."""
        response = client.post('/auth/login', json={
            'email': 'test@example.com'
        })
        assert response.status_code == 400
        data = response.get_json()
        assert data['ok'] is False
        assert 'email and password required' in data['error'].lower()


class TestCustomerLogout:
    """Test customer logout."""

    def test_successful_logout(self, client):
        """Test successful customer logout."""
        client.post('/auth/register', json={
            'name': 'Test User',
            'email': 'test@example.com',
            'password': 'securepassword123'
        })
        # Login to get session cookie
        response = client.post('/auth/login', json={
            'email': 'test@example.com',
            'password': 'securepassword123'
        })
        cookie = response.headers.get('Set-Cookie')
        session_value = cookie.split(';')[0].split('=')[1]
        
        # Logout with the session cookie
        client.set_cookie('customer_session', session_value)
        response = client.post('/auth/logout')
        assert response.status_code == 200
        data = response.get_json()
        assert data['ok'] is True
        
        # Cookie should be cleared
        assert 'customer_session=;' in response.headers.get('Set-Cookie', '')

    def test_logout_without_session(self, client):
        """Test logout without existing session succeeds."""
        response = client.post('/auth/logout')
        assert response.status_code == 200
        data = response.get_json()
        assert data['ok'] is True


class TestSessionValidation:
    """Test session validation."""

    def test_valid_session(self, client):
        """Test valid session allows access to protected endpoints."""
        client.post('/auth/register', json={
            'name': 'Test User',
            'email': 'test@example.com',
            'password': 'securepassword123'
        })
        client.post('/auth/login', json={
            'email': 'test@example.com',
            'password': 'securepassword123'
        })
        response = client.get('/api/me')
        assert response.status_code == 200
        data = response.get_json()
        assert data['ok'] is True
        assert data['customer']['email'] == 'test@example.com'

    def test_expired_session(self, client, db_module):
        """Test expired session is rejected."""
        import database
        from datetime import datetime, timedelta
        
        # Register and login
        client.post('/auth/register', json={
            'name': 'Test User',
            'email': 'test@example.com',
            'password': 'securepassword123'
        })
        client.post('/auth/login', json={
            'email': 'test@example.com',
            'password': 'securepassword123'
        })
        
        # Manually expire the session in the database
        with database.transaction() as conn:
            conn.execute(
                'UPDATE sessions SET expires_at = ? WHERE customer_id = 1',
                ((datetime.now() - timedelta(days=1)).isoformat(timespec='seconds'),)
            )
        
        response = client.get('/api/me')
        assert_unauthenticated(response)

    def test_revoked_session(self, client, db_module):
        """Test revoked session is rejected."""
        import database
        
        # Register and login
        client.post('/auth/register', json={
            'name': 'Test User',
            'email': 'test@example.com',
            'password': 'securepassword123'
        })
        client.post('/auth/login', json={
            'email': 'test@example.com',
            'password': 'securepassword123'
        })
        
        # Manually revoke the session in the database
        with database.transaction() as conn:
            conn.execute(
                'UPDATE sessions SET revoked = 1 WHERE customer_id = 1'
            )
        
        response = client.get('/api/me')
        assert_unauthenticated(response)

    def test_missing_session(self, client):
        """Test missing session is rejected."""
        response = client.get('/api/me')
        assert_unauthenticated(response)

    def test_invalid_session_token(self, client):
        """Test invalid session token is rejected."""
        client.set_cookie('customer_session', 'invalid-token')
        response = client.get('/api/me')
        assert_unauthenticated(response)


class TestCustomerIsolation:
    """Test that customers cannot access each other's data."""

    def test_customer_a_cannot_access_customer_b_profile(self, client, db_module):
        """Test customer A cannot access customer B's profile via legacy endpoint.
        
        The legacy endpoint now uses `_get_customer_id_legacy` which checks `g.customer_id` first, 
        so customer A can only update their own profile even if they pass customer_id=2.
        """
        import database
        
        # Register customer A
        client.post('/auth/register', json={
            'name': 'Customer A',
            'email': 'a@example.com',
            'password': 'password123'
        })
        # Login as customer A
        client.post('/auth/login', json={
            'email': 'a@example.com',
            'password': 'password123'
        })
        
        # Register customer B (directly in DB to avoid cookie conflict)
        with database.transaction() as conn:
            import hashlib
            password_hash = hashlib.pbkdf2_hmac('sha256', b'password123', b'b@example.com', 100000).hex()
            conn.execute(
                'INSERT INTO customers (name, email, password_hash, location, country, created_at, updated_at) VALUES (?, ?, ?, ?, ?, datetime("now"), datetime("now"))',
                ('Customer B', 'b@example.com', password_hash, 'remote', 'nigeria')
            )
        
        # Customer A tries to access customer B's profile via legacy endpoint with customer_id
        # The endpoint uses g.customer_id (customer A's ID) first, so customer A updates their own profile
        response = client.post('/api/customer/profile', json={
            'customer_id': 2,
            'keywords': 'hack attempt',
            'location': 'remote'
        })
        # Customer A can only access their own data - the request uses g.customer_id (1), not the param (2)
        assert response.status_code == 200
        data = response.get_json()
        assert data['ok'] is True
        
        # Verify customer A's profile was updated via the API
        response = client.get('/api/customer')
        assert response.status_code == 200
        data = response.get_json()
        # The legacy endpoint returns profile in 'profile' field
        # Check that the profile was updated
        # Since the legacy endpoint creates/updates profile, we can verify via the new endpoint
        response = client.get('/api/profile')
        assert response.status_code == 200
        profile_data = response.get_json()
        assert profile_data['keywords'] == 'hack attempt'
        
        # Verify customer B's profile is unchanged (should not exist or be empty)
        profile_b = database.get_customer_profile(2)
        assert profile_b is None or profile_b['keywords'] == ''

    def test_customer_a_cannot_access_customer_b_via_new_endpoints(self, client):
        """Test customer A can only access their own data via new endpoints."""
        # Register and login as customer A
        client.post('/auth/register', json={
            'name': 'Customer A',
            'email': 'a@example.com',
            'password': 'password123'
        })
        client.post('/auth/login', json={
            'email': 'a@example.com',
            'password': 'password123'
        })
        
        # Customer A tries to access /api/profile (should only see their own)
        # Profile doesn't exist yet, so 404
        response = client.get('/api/profile')
        assert response.status_code == 404
        
        # Customer A tries to access /api/cv
        response = client.get('/api/cv')
        assert response.status_code == 404  # No CV yet


class TestAdminAuthenticationCompatibility:
    """Test that admin authentication still works."""

    @pytest.fixture
    def admin_pw(self, client, tmp_path, monkeypatch):
        """Write an admin password into the redirected ADMIN_PATH.

        monkeypatch + tmp_path own the lifetime, so no test can create or delete
        a file in the project root. These three tests used to hardcode
        'web_admin.env' and os.remove() it, which destroyed the real one.
        """
        import web_app
        path = Path(web_app.ADMIN_PATH)
        path.write_text('adminpassword123', encoding='utf-8')
        monkeypatch.setattr(web_app, 'SETUP_MODE', False, raising=False)
        return 'adminpassword123'

    def test_admin_login_still_works(self, client, admin_pw):
        """Test admin login still works."""
        response = client.post('/api/login', json={'password': admin_pw})
        assert response.status_code == 200
        data = response.get_json()
        assert data['ok'] is True

    def test_admin_can_access_customer_list(self, client, admin_pw):
        """Test admin can list customers."""
        client.post('/api/login', json={'password': admin_pw})
        response = client.get('/api/customers')
        assert response.status_code == 200
        data = response.get_json()
        assert 'customers' in data

    def test_admin_can_create_customer(self, client, admin_pw):
        """Test admin can create customers."""
        client.post('/api/login', json={'password': admin_pw})
        response = client.post('/api/customers', json={
            'name': 'Admin Created User',
            'email': 'admincreated@example.com',
            'location': 'lagos',
            'country': 'nigeria'
        })
        assert response.status_code == 200
        data = response.get_json()
        assert data['ok'] is True
        assert 'customer_id' in data


class TestRateLimiting:
    """Test rate limiting on auth endpoints."""

    @pytest.mark.skip(reason="Rate limiting disabled during tests")
    def test_registration_rate_limit(self, client):
        """Test registration rate limiting."""
        for i in range(6):
            response = client.post('/auth/register', json={
                'name': f'User {i}',
                'email': f'user{i}@example.com',
                'password': 'securepassword123'
            })
            if i < 5:
                assert response.status_code == 200
            else:
                assert response.status_code == 429

    @pytest.mark.skip(reason="Rate limiting disabled during tests")
    def test_login_rate_limit(self, client):
        """Test login rate limiting."""
        client.post('/auth/register', json={
            'name': 'Test User',
            'email': 'test@example.com',
            'password': 'securepassword123'
        })
        
        for i in range(11):
            response = client.post('/auth/login', json={
                'email': 'test@example.com',
                'password': 'wrongpassword'
            })
            if i < 10:
                assert response.status_code == 401
            else:
                assert response.status_code == 429


class TestSecurity:
    """Test security properties."""

    def test_plaintext_passwords_never_stored(self, db_module):
        """Test that plaintext passwords are never stored."""
        import database
        
        # Use the database directly to register
        customer_id = database.create_customer_with_password(
            name='Test User',
            email='test@example.com',
            password='securepassword123',
            location='remote',
            country='nigeria'
        )
        
        customer = database.get_customer(customer_id)
        assert customer is not None
        assert customer['password_hash'] is not None
        assert customer['password_hash'] != 'securepassword123'
        assert len(customer['password_hash']) == 64  # SHA256 hex

    def test_session_tokens_not_stored_plaintext(self, db_module):
        """Test that session tokens are not stored in plaintext."""
        import database
        import hashlib
        
        # Create a customer first
        customer_id = database.create_customer_with_password(
            name='Test User',
            email='test@example.com',
            password='securepassword123',
            location='remote',
            country='nigeria'
        )
        
        token = 'test-session-token'
        token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
        
        with database.transaction() as conn:
            conn.execute(
                'INSERT INTO sessions (customer_id, token_hash, created_at, expires_at, revoked, last_seen_at) VALUES (?, ?, datetime("now"), datetime("now", "+30 days"), 0, datetime("now"))',
                (customer_id, token_hash)
            )
        
        session = database.get_session_by_token_hash(token_hash)
        assert session is not None
        assert session['token_hash'] == token_hash
        assert session['token_hash'] != token  # Not stored in plaintext

    def test_credentials_not_logged(self, client, caplog):
        """Test that credentials are not logged."""
        import logging
        
        with caplog.at_level(logging.INFO):
            client.post('/auth/register', json={
                'name': 'Test User',
                'email': 'test@example.com',
                'password': 'securepassword123'
            })
            
        # Check that password is not in logs
        for record in caplog.records:
            assert 'securepassword123' not in record.message
            assert 'test@example.com' not in record.getMessage().lower() or 'registered' in record.message.lower()

    def test_customer_id_from_request_cannot_override_authenticated_identity(self, client, db_module):
        """Test that client-supplied customer_id cannot override authenticated identity."""
        import database
        
        # Register customer A
        client.post('/auth/register', json={
            'name': 'Customer A',
            'email': 'a@example.com',
            'password': 'password123'
        })
        # Login as customer A
        client.post('/auth/login', json={
            'email': 'a@example.com',
            'password': 'password123'
        })
        
        # Create customer B directly in DB
        with database.transaction() as conn:
            import hashlib
            password_hash = hashlib.pbkdf2_hmac('sha256', b'password123', b'b@example.com', 100000).hex()
            conn.execute(
                'INSERT INTO customers (name, email, password_hash, location, country, created_at, updated_at) VALUES (?, ?, ?, ?, ?, datetime("now"), datetime("now"))',
                ('Customer B', 'b@example.com', password_hash, 'remote', 'nigeria')
            )
        
        # Customer A tries to use customer_id=2 in request to access customer B's data
        # The legacy endpoint should use g.customer_id (customer A's ID) not the request param
        response = client.post('/api/customer/profile', json={
            'customer_id': 2,  # Attempt to access customer B
            'keywords': 'hack attempt',
            'location': 'remote'
        })
        
        # The legacy endpoint uses _get_customer_id_legacy which checks g.customer_id FIRST
        # So this should use customer A's ID and update customer A's profile
        assert response.status_code == 200
        
        # Verify customer A's profile was updated, not customer B's
        profile_a = database.get_customer_profile(1)
        assert profile_a is not None
        assert profile_a['keywords'] == 'hack attempt'
        
        profile_b = database.get_customer_profile(2)
        assert profile_b is None or profile_b['keywords'] == ''  # Customer B's profile unchanged


if __name__ == '__main__':
    pytest.main([__file__, '-v'])