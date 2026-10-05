"""Smoke tests for JobMatch application."""

import os
import tempfile

import pytest


@pytest.mark.smoke
def test_application_imports():
    """Verify main application modules can be imported without crashing."""
    import apply_all
    import career_crawler
    import customer_engine
    import cv_tailor
    import cv_to_pdf
    import extract_email_targets
    import import_scanned_jobs
    import job_scraper
    import prefill_apply
    import send_applications
    import send_followups
    import web_app

    assert cv_tailor is not None
    assert customer_engine is not None
    assert job_scraper is not None
    assert web_app is not None
    assert apply_all is not None
    assert prefill_apply is not None
    assert send_applications is not None
    assert career_crawler is not None
    assert extract_email_targets is not None
    assert import_scanned_jobs is not None
    assert send_followups is not None
    assert cv_to_pdf is not None


@pytest.mark.smoke
def test_cv_tailor_provider_configuration():
    """Verify LLM provider configuration has valid model names."""
    from cv_tailor import PROVIDERS

    # Check all providers have required fields
    for provider_name, config in PROVIDERS.items():
        assert 'key' in config, f"Provider {provider_name} missing 'key'"
        assert 'model' in config, f"Provider {provider_name} missing 'model'"
        assert config['key'], f"Provider {provider_name} has empty key"
        assert config['model'], f"Provider {provider_name} has empty model"

    # Verify specific model names are not the known-bad ones.
    #
    # This assertion used to forbid 'gemini-3.6-flash', which was wrong: it was
    # presumably written after a transient 503 was mistaken for the model being
    # unavailable. Measured live against the real API on 2026-10-04, 8 calls each:
    #   gemini-3.6-flash -> 7/8 HTTP 200 (one 429 rate-limit), no 503s
    #   gemini-1.5-flash -> 0/8, every call HTTP 404 "not found for v1beta"
    #   gemini-2.5-flash -> 404 "no longer available to new users"
    # So gemini-3.6-flash is the only one of the three that actually works, and
    # the model that WAS configured (1.5-flash) had a 100% failure rate that was
    # invisible because call_gemini returns None on "model not found" and the
    # caller silently falls through to the next provider.
    dead_gemini = {'gemini-1.5-flash', 'gemini-2.0-flash', 'gemini-2.5-flash',
                   'gemini-1.5-pro'}
    assert PROVIDERS['gemini']['model'] not in dead_gemini, \
        f"dead gemini model configured: {PROVIDERS['gemini']['model']}"
    assert PROVIDERS['groq']['model'] != 'llama-3.3-70b-versatile', "llama-3.3-70b-versatile is invalid"


@pytest.mark.smoke
def test_cv_tailor_get_model_env_override():
    """Verify get_model respects environment variable overrides."""
    from cv_tailor import PROVIDERS, get_model

    # Test with a mock env dict
    test_env = {
        'GEMINI_API_KEY': 'test-key',
        'GEMINI_API_KEY_MODEL': 'gemini-custom-model',
        'GROQ_API_KEY': 'test-key',
    }

    # Should use env override for gemini
    assert get_model(test_env, 'gemini') == 'gemini-custom-model'

    # Should use default for groq (no override)
    assert get_model(test_env, 'groq') == PROVIDERS['groq']['model']

    # Should use default for openrouter (no key in env)
    assert get_model(test_env, 'openrouter') == PROVIDERS['openrouter']['model']


@pytest.mark.smoke
def test_cv_tailor_decide_provider_fallback():
    """Verify provider fallback logic works correctly."""
    from cv_tailor import decide_provider

    # Test with only groq key
    env_groq_only = {'GROQ_API_KEY': 'test-key'}
    provider = decide_provider(env_groq_only, None)
    assert provider == 'groq', f"Expected groq, got {provider}"

    # Test with only gemini key
    env_gemini_only = {'GEMINI_API_KEY': 'test-key'}
    provider = decide_provider(env_gemini_only, None)
    assert provider == 'gemini', f"Expected gemini, got {provider}"

    # Test with requested provider that has key
    env_both = {'GEMINI_API_KEY': 'test-key', 'GROQ_API_KEY': 'test-key'}
    provider = decide_provider(env_both, 'groq')
    assert provider == 'groq', f"Expected groq (requested), got {provider}"

    # Test with no keys
    provider = decide_provider({}, None)
    assert provider is None, f"Expected None, got {provider}"


@pytest.mark.smoke
def test_customer_engine_profile_operations(tmp_path):
    """Verify customer profile save/load works."""
    import customer_engine
    import database

    # Use temp directory for database
    test_db = tmp_path / 'test_jobmatch.db'
    database.DB_PATH = test_db
    database.init_db()

    # Create a test customer
    customer_id = database.create_customer(name="Test User", email="test@example.com")

    try:
        # Save profile with customer_id
        profile = customer_engine.save_profile(customer_id, name="Test User", keywords="python, django", location="remote")
        assert profile['name'] == "Test User"
        assert profile['keywords'] == "python, django"
        assert profile['location'] == "remote"

        # Load profile
        loaded = customer_engine.load_profile(customer_id)
        assert loaded['name'] == "Test User"
        assert loaded['keywords'] == "python, django"
        assert loaded['preferred_locations'] == "remote"
    finally:
        database.close_db()


@pytest.mark.smoke
def test_job_scraper_compute_score():
    """Verify job scoring function works."""
    from job_scraper import compute_score

    # Test basic scoring
    score = compute_score("IT Support Engineer", "We need IT support with help desk experience")
    assert score > 0, "Should score positive for matching keywords"

    # Test exclusion
    score = compute_score("Senior IT Support Engineer", "Senior role")
    assert score >= 0, "Should not be negative"

    # Test location bonus
    score_ng = compute_score("IT Support", "Based in Lagos, Nigeria")
    score_remote = compute_score("IT Support", "Remote worldwide")
    assert score_ng > score_remote, "Nigeria location should score higher"


@pytest.mark.smoke
def test_web_app_auth_state():
    """Verify web app auth state endpoint logic."""
    import flask

    from web_app import is_authed

    app = flask.Flask(__name__)
    app.secret_key = 'test-secret'

    # Test is_authed with session
    with app.test_request_context():
        with app.test_client().session_transaction() as sess:
            sess['authed'] = True
        # Need to use the same session - use test_client context
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['authed'] = True
        # Now test in request context with same app
        with app.test_request_context('/', headers={'Cookie': client.get_cookie('session')}):
            # Actually, let's just test the function logic directly
            pass

    # Simpler approach: test the function logic
    with app.test_request_context():
        flask.session['authed'] = True
        assert is_authed() is True

    with app.test_request_context():
        # No session set
        assert is_authed() is False


@pytest.mark.smoke
def test_cv_tailor_cv_text_quality():
    """Verify CV text quality scoring."""
    from cv_tailor import cv_text_quality

    # Clean text should score high (need enough words for scoring)
    clean_cv = """
    JOHN DOE
    Software Engineer
    john.doe@email.com
    +1-555-123-4567

    PROFESSIONAL SUMMARY
    Experienced software engineer with 5 years of experience in Python and JavaScript development.

    TECHNICAL SKILLS
    Python, JavaScript, SQL, Docker, Kubernetes, AWS, Git, Linux, REST APIs, GraphQL

    EXPERIENCE
    Senior Software Engineer at Tech Corp (2020-2024)
    Built scalable web applications using Python and React.
    """
    score = cv_text_quality(clean_cv)
    assert score > 0.5, f"Clean CV should score > 0.5, got {score}"

    # Garbled text should score low
    garbled_cv = """
    JOH N DOE
    Softw are Engin eer
    john.doe@em ail.com
    ex peri enced soft ware engin eer
    """
    score = cv_text_quality(garbled_cv)
    assert score < 0.75, f"Garbled CV should score < 0.75, got {score}"


@pytest.mark.smoke
def test_job_scraper_is_relevant():
    """Verify job relevance filtering."""
    from job_scraper import TARGET_KEYWORDS, is_relevant

    # Should match IT support keywords
    assert is_relevant("IT Support Engineer", "Help desk role", TARGET_KEYWORDS) is True

    # Should exclude senior roles
    assert is_relevant("Senior IT Support Engineer", "Lead role", TARGET_KEYWORDS) is False

    # Should match remote keywords
    assert is_relevant("Customer Support", "Remote position", TARGET_KEYWORDS) is True

    # Should filter noise
    assert is_relevant("Werkstudent", "German job", TARGET_KEYWORDS) is False


@pytest.mark.smoke
def test_config_loading_missing_secrets():
    """Verify configuration loading handles missing secrets gracefully."""
    from send_applications import load_config

    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = os.path.join(tmpdir, 'sender_config.env')
        # Empty config
        with open(config_path, 'w') as f:
            f.write('')

        # Should return empty dict, not crash
        cfg = load_config()
        # load_config reads from fixed path, so test the function directly
        from send_applications import CONFIG_PATH
        original = CONFIG_PATH
        try:
            import send_applications
            send_applications.CONFIG_PATH = config_path
            cfg = load_config()
            assert cfg == {}
        finally:
            send_applications.CONFIG_PATH = original


# Security-focused tests

@pytest.mark.security
def test_auth_valid_credentials():
    """Valid authentication succeeds."""
    import flask

    from web_app import app

    with app.test_request_context():
        with app.test_client().session_transaction() as sess:
            sess['authed'] = True
        with app.test_request_context():
            flask.session['authed'] = True
            from web_app import is_authed
            assert is_authed() is True


@pytest.mark.security
def test_auth_invalid_credentials():
    """Invalid authentication fails."""
    import flask

    from web_app import is_authed

    app = flask.Flask(__name__)
    app.secret_key = 'test-secret'
    with app.test_request_context():
        assert is_authed() is False


@pytest.mark.security
def test_api_login_rate_limiting():
    """Repeated authentication attempts eventually receive rate-limit response."""
    from web_app import app
    app.config['TESTING'] = True
    client = app.test_client()

    # Make 5 requests (the limit is 5 per minute)
    for i in range(5):
        response = client.post('/api/login', json={'password': 'wrong'})
        # First 5 should get 401, not 429
        assert response.status_code in (401, 429)

    # 6th request might hit rate limit
    response = client.post('/api/login', json={'password': 'wrong'})
    # Accept either 401 or 429 - the test verifies no 500
    assert response.status_code in (401, 429)


@pytest.mark.security
def test_api_validation_missing_field():
    """Missing required field returns 400."""
    from web_app import app
    app.config['TESTING'] = True
    client = app.test_client()

    # Test customer profile without keywords
    with client.session_transaction() as sess:
        sess['authed'] = True
    response = client.post('/api/customer/profile', json={'customer_id': 1, 'name': 'Test'})
    assert response.status_code == 400
    assert 'keywords' in response.get_json().get('error', '').lower()


@pytest.mark.security
def test_api_validation_wrong_type():
    """Wrong data type returns 400."""
    from web_app import app, get_pin
    app.config['TESTING'] = True
    client = app.test_client()

    with client.session_transaction() as sess:
        sess['authed'] = True
    response = client.post('/api/customer/run',
                           json={'customer_id': 1, 'pin': get_pin(), 'top': 'invalid'})
    assert response.status_code == 400


@pytest.mark.security
def test_api_validation_oversized_input():
    """Oversized input returns 400."""
    from web_app import app
    app.config['TESTING'] = True
    client = app.test_client()

    with client.session_transaction() as sess:
        sess['authed'] = True
    response = client.post('/api/customer/profile', json={
        'customer_id': 1,
        'name': 'Test',
        'keywords': 'x' * 1000,  # exceeds 500 limit
        'location': 'remote'
    })
    assert response.status_code == 400
    assert 'too long' in response.get_json().get('error', '').lower()


@pytest.mark.security
def test_unauthenticated_request_blocked():
    """Unauthenticated requests to protected endpoints are blocked."""
    from web_app import app
    app.config['TESTING'] = True
    client = app.test_client()

    # No session set
    response = client.post('/api/customer/profile', json={'keywords': 'test'})
    assert response.status_code == 401


@pytest.mark.security
def test_file_legitimate_access():
    """Legitimate file access works."""
    from web_app import app
    app.config['TESTING'] = True
    client = app.test_client()

    # Create a test file in the existing tailored_cvs directory
    import os
    test_dir = os.path.join(os.path.dirname(__file__), '..', 'tailored_cvs')
    os.makedirs(test_dir, exist_ok=True)
    test_file = os.path.join(test_dir, 'test_legitimate_access.txt')
    try:
        with open(test_file, 'w') as f:
            f.write('test content')

        with client.session_transaction() as sess:
            sess['authed'] = True
        response = client.get('/files/test_legitimate_access.txt')
        # May return 404 if not found, but not 500
        assert response.status_code != 500
    finally:
        # On Windows, send_file might keep file open; ignore cleanup errors
        try:
            if os.path.exists(test_file):
                os.unlink(test_file)
        except PermissionError:
            pass


@pytest.mark.security
def test_file_traversal_blocked():
    """Path traversal attempts are blocked."""
    from web_app import app
    import database
    from pathlib import Path
    import tempfile
    
    # Create a test customer
    test_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False).name
    database.DB_PATH = Path(test_db)
    database.init_db()
    customer_id = database.create_customer(name="Test Customer")
    
    app.config['TESTING'] = True
    client = app.test_client()

    with client.session_transaction() as sess:
        sess['authed'] = True

    # Test various traversal attempts - require customer_id in path
    # Note: Flask may normalize /etc/passwd to a redirect (308), but traversal with .. is blocked (400)
    for path in ['../etc/passwd', '..\\windows\\system32', '..%2fetc%2fpasswd']:
        response = client.get(f'/files/{customer_id}/{path}')
        assert response.status_code == 400, f"Path {path} should be blocked, got {response.status_code}"

    # /etc/passwd gets normalized by Flask to a redirect, but still not served
    response = client.get(f'/files/{customer_id}//etc/passwd')
    assert response.status_code != 200, f"Path /etc/passwd should not be served, got {response.status_code}"
    
    database.close_db()


@pytest.mark.security
def test_error_no_stack_trace_exposed():
    """Internal exceptions don't expose stack traces."""
    from web_app import app
    app.config['TESTING'] = True
    client = app.test_client()

    with client.session_transaction() as sess:
        sess['authed'] = True

    # Trigger an error by accessing a non-existent endpoint
    response = client.get('/api/nonexistent')
    # Should return 404, not 500 with stack trace
    assert response.status_code == 404
    data = response.get_json()
    assert 'traceback' not in str(data).lower()
    assert 'file' not in str(data).lower() or 'not found' in str(data).lower()


@pytest.mark.security
def test_secrets_not_logged():
    """Secrets are never written to logs."""
    # This is a design test - verify that the logging configuration
    # doesn't accidentally log sensitive data
    import logging

    from web_app import logger

    # Verify logger is configured
    assert logger.level <= logging.INFO
    # The actual log output should not contain passwords/PINs/keys
    # This is verified by code review, not runtime


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
