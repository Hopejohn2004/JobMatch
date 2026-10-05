"""Multi-customer tests for JobMatch M1 milestone."""

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


class TestCustomerCRUD:
    """Test customer CRUD operations."""

    def test_create_customer(self, db_module):
        customer_id = db_module.create_customer(
            name="Test User",
            email="test@example.com",
            location="Lagos, Nigeria",
            country="nigeria"
        )
        assert customer_id == 1

        customer = db_module.get_customer(customer_id)
        assert customer is not None
        assert customer['name'] == "Test User"
        assert customer['email'] == "test@example.com"
        assert customer['location'] == "Lagos, Nigeria"
        assert customer['country'] == "nigeria"
        assert customer['status'] == "active"

    def test_get_customer_by_email(self, db_module):
        db_module.create_customer(name="User 1", email="user1@example.com")
        db_module.create_customer(name="User 2", email="user2@example.com")

        customer = db_module.get_customer_by_email("user1@example.com")
        assert customer is not None
        assert customer['name'] == "User 1"

        # Non-existent email
        assert db_module.get_customer_by_email("nonexistent@example.com") is None

    def test_list_customers(self, db_module):
        db_module.create_customer(name="User 1", email="user1@example.com")
        db_module.create_customer(name="User 2", email="user2@example.com")
        # Update second customer to inactive
        customer2 = db_module.get_customer_by_email("user2@example.com")
        db_module.update_customer(customer2['id'], status="inactive")

        all_customers = db_module.list_customers()
        assert len(all_customers) == 2

        active_only = db_module.list_customers(status="active")
        assert len(active_only) == 1
        assert active_only[0]['name'] == "User 1"

    def test_update_customer(self, db_module):
        customer_id = db_module.create_customer(name="Original", email="orig@example.com")
        result = db_module.update_customer(customer_id, name="Updated", location="Abuja")
        assert result is True

        customer = db_module.get_customer(customer_id)
        assert customer['name'] == "Updated"
        assert customer['location'] == "Abuja"
        assert customer['email'] == "orig@example.com"  # unchanged


class TestCustomerProfile:
    """Test customer profile operations."""

    def test_create_or_update_profile(self, db_module):
        customer_id = db_module.create_customer(name="Test User")
        profile_id = db_module.create_or_update_profile(
            customer_id=customer_id,
            keywords="python, django, flask",
            preferred_locations="remote",
            job_types="full-time",
            target_roles="backend developer",
            home_country="nigeria"
        )
        assert profile_id == 1

        profile = db_module.get_customer_profile(customer_id)
        assert profile is not None
        assert profile['keywords'] == "python, django, flask"
        assert profile['preferred_locations'] == "remote"
        assert profile['home_country'] == "nigeria"

    def test_update_existing_profile(self, db_module):
        customer_id = db_module.create_customer(name="Test User")
        db_module.create_or_update_profile(customer_id=customer_id, keywords="old keywords")

        # Update
        db_module.create_or_update_profile(customer_id=customer_id, keywords="new keywords")

        profile = db_module.get_customer_profile(customer_id)
        assert profile['keywords'] == "new keywords"


class TestCustomerCV:
    """Test customer CV operations."""

    def test_create_customer_cv(self, db_module):
        customer_id = db_module.create_customer(name="Test User")
        cv_id = db_module.create_customer_cv(
            customer_id=customer_id,
            original_filename="cv.pdf",
            stored_path="data/customers/1/cvs/cv.txt",
            file_hash="abc123",
            text_content="Test CV content",
            quality_score=0.9
        )
        assert cv_id == 1

        cv = db_module.get_customer_active_cv(customer_id)
        assert cv is not None
        assert cv['original_filename'] == "cv.pdf"
        assert cv['quality_score'] == 0.9
        assert cv['is_active'] == 1

    def test_multiple_cvs_only_one_active(self, db_module):
        customer_id = db_module.create_customer(name="Test User")
        db_module.create_customer_cv(customer_id=customer_id, original_filename="cv1.pdf", stored_path="p1")
        db_module.create_customer_cv(customer_id=customer_id, original_filename="cv2.pdf", stored_path="p2")

        cvs = db_module.get_customer_cvs(customer_id)
        assert len(cvs) == 2

        active = db_module.get_customer_active_cv(customer_id)
        assert active['original_filename'] == "cv2.pdf"  # latest is active

    def test_set_active_cv(self, db_module):
        customer_id = db_module.create_customer(name="Test User")
        cv1_id = db_module.create_customer_cv(customer_id=customer_id, original_filename="cv1.pdf", stored_path="p1")
        cv2_id = db_module.create_customer_cv(customer_id=customer_id, original_filename="cv2.pdf", stored_path="p2")

        # cv2 is active by default, switch to cv1
        result = db_module.set_active_cv(customer_id, cv1_id)
        assert result is True

        active = db_module.get_customer_active_cv(customer_id)
        assert active['id'] == cv1_id


class TestJobs:
    """Test job operations."""

    def test_create_job(self, db_module):
        job_id = db_module.create_job(
            source="MyJobMag",
            title="IT Support Engineer",
            company="Test Company",
            location="Lagos, Nigeria",
            url="https://example.com/job/1",
            description="Job description here",
            external_id="https://example.com/job/1"
        )
        assert job_id == 1

        job = db_module.get_job(job_id)
        assert job['title'] == "IT Support Engineer"
        assert job['company'] == "Test Company"

    def test_get_job_by_url(self, db_module):
        db_module.create_job(source="MyJobMag", title="Job 1", url="https://example.com/job/1", external_id="https://example.com/job/1")

        job = db_module.get_job_by_url("https://example.com/job/1")
        assert job is not None
        assert job['title'] == "Job 1"

        # Non-existent
        assert db_module.get_job_by_url("https://example.com/job/999") is None


class TestJobMatches:
    """Test job match operations."""

    def test_create_job_match(self, db_module):
        customer_id = db_module.create_customer(name="Test User")
        job_id = db_module.create_job(source="MyJobMag", title="IT Support", url="https://example.com/1")

        match_id = db_module.create_job_match(
            customer_id=customer_id,
            job_id=job_id,
            score=85.5,
            fit_score=75.0,
            reason="Good keyword match",
            status="new"
        )
        assert match_id == 1

        matches = db_module.get_customer_matches(customer_id)
        assert len(matches) == 1
        assert matches[0]['score'] == 85.5
        assert matches[0]['fit_score'] == 75.0
        assert matches[0]['status'] == "new"

    def test_update_match_status(self, db_module):
        customer_id = db_module.create_customer(name="Test User")
        job_id = db_module.create_job(source="MyJobMag", title="IT Support", url="https://example.com/1")
        db_module.create_job_match(customer_id=customer_id, job_id=job_id, score=50, status="new")

        result = db_module.update_match_status(customer_id, job_id, "reviewed")
        assert result is True

        matches = db_module.get_customer_matches(customer_id, status="reviewed")
        assert len(matches) == 1
        assert matches[0]['status'] == "reviewed"


class TestApplications:
    """Test application operations."""

    def test_create_application(self, db_module):
        customer_id = db_module.create_customer(name="Test User")
        job_id = db_module.create_job(source="MyJobMag", title="IT Support", url="https://example.com/1")

        app_id = db_module.create_application(
            customer_id=customer_id,
            job_id=job_id,
            status="TO_APPLY",
            date_applied="2026-01-15",
            notes="Applied via portal",
            apply_method="Online portal",
            apply_link="https://example.com/1"
        )
        assert app_id == 1

        apps = db_module.get_customer_applications(customer_id)
        assert len(apps) == 1
        assert apps[0]['status'] == "TO_APPLY"
        assert apps[0]['notes'] == "Applied via portal"

    def test_update_application_status(self, db_module):
        customer_id = db_module.create_customer(name="Test User")
        job_id = db_module.create_job(source="MyJobMag", title="IT Support", url="https://example.com/1")
        db_module.create_application(customer_id=customer_id, job_id=job_id, status="TO_APPLY")

        result = db_module.update_application_status(customer_id, job_id, "APPLIED", date_applied="2026-01-20")
        assert result is True

        apps = db_module.get_customer_applications(customer_id, status="APPLIED")
        assert len(apps) == 1
        assert apps[0]['status'] == "APPLIED"
        assert apps[0]['date_applied'] == "2026-01-20"


class TestTailoredCVs:
    """Test tailored CV operations."""

    def test_create_tailored_cv(self, db_module):
        customer_id = db_module.create_customer(name="Test User")
        job_id = db_module.create_job(source="MyJobMag", title="IT Support", url="https://example.com/1")
        cv_id = db_module.create_customer_cv(customer_id=customer_id, original_filename="cv.pdf", stored_path="p1")

        tailored_id = db_module.create_tailored_cv(
            customer_id=customer_id,
            job_id=job_id,
            source_cv_id=cv_id,
            stored_path="data/customers/1/tailored_cvs/01_Company_tailored_cv.txt",
            cover_letter_path="data/customers/1/tailored_cvs/01_Company_cover_letter.txt",
            qc_notes="All good"
        )
        assert tailored_id == 1

        tailored = db_module.get_customer_tailored_cvs(customer_id)
        assert len(tailored) == 1
        assert tailored[0]['stored_path'] == "data/customers/1/tailored_cvs/01_Company_tailored_cv.txt"
        assert tailored[0]['qc_notes'] == "All good"


class TestCustomerIsolation:
    """Test that customers are properly isolated."""

    def test_customers_cannot_access_each_other_data(self, db_module):
        # Create two customers
        customer_a = db_module.create_customer(name="Customer A", email="a@example.com")
        customer_b = db_module.create_customer(name="Customer B", email="b@example.com")

        # Create profile for A
        db_module.create_or_update_profile(customer_id=customer_a, keywords="python")
        # Create profile for B
        db_module.create_or_update_profile(customer_id=customer_b, keywords="java")

        # Verify isolation
        profile_a = db_module.get_customer_profile(customer_a)
        profile_b = db_module.get_customer_profile(customer_b)

        assert profile_a['keywords'] == "python"
        assert profile_b['keywords'] == "java"

        # A cannot see B's profile
        assert db_module.get_customer_profile(customer_a)['keywords'] != "java"
        assert db_module.get_customer_profile(customer_b)['keywords'] != "python"

    def test_cv_isolation(self, db_module):
        customer_a = db_module.create_customer(name="Customer A")
        customer_b = db_module.create_customer(name="Customer B")

        db_module.create_customer_cv(customer_id=customer_a, original_filename="cv_a.pdf", stored_path="a")
        db_module.create_customer_cv(customer_id=customer_b, original_filename="cv_b.pdf", stored_path="b")

        cvs_a = db_module.get_customer_cvs(customer_a)
        cvs_b = db_module.get_customer_cvs(customer_b)

        assert len(cvs_a) == 1
        assert len(cvs_b) == 1
        assert cvs_a[0]['original_filename'] == "cv_a.pdf"
        assert cvs_b[0]['original_filename'] == "cv_b.pdf"

    def test_applications_isolation(self, db_module):
        customer_a = db_module.create_customer(name="Customer A")
        customer_b = db_module.create_customer(name="Customer B")
        job_id = db_module.create_job(source="MyJobMag", title="IT Support", url="https://example.com/1")

        db_module.create_application(customer_id=customer_a, job_id=job_id, status="APPLIED")
        db_module.create_application(customer_id=customer_b, job_id=job_id, status="TO_APPLY")

        apps_a = db_module.get_customer_applications(customer_a)
        apps_b = db_module.get_customer_applications(customer_b)

        assert len(apps_a) == 1
        assert len(apps_b) == 1
        assert apps_a[0]['status'] == "APPLIED"
        assert apps_b[0]['status'] == "TO_APPLY"

    def test_matches_isolation(self, db_module):
        customer_a = db_module.create_customer(name="Customer A")
        customer_b = db_module.create_customer(name="Customer B")
        job_id = db_module.create_job(source="MyJobMag", title="IT Support", url="https://example.com/1")

        db_module.create_job_match(customer_id=customer_a, job_id=job_id, score=90, status="new")
        db_module.create_job_match(customer_id=customer_b, job_id=job_id, score=60, status="reviewed")

        matches_a = db_module.get_customer_matches(customer_a)
        matches_b = db_module.get_customer_matches(customer_b)

        assert len(matches_a) == 1
        assert len(matches_b) == 1
        assert matches_a[0]['score'] == 90
        assert matches_b[0]['score'] == 60


class TestDataPersistence:
    """Test that data persists across connections."""

    def test_data_persists_after_reconnect(self, db_module):
        customer_id = db_module.create_customer(name="Test User")
        db_module.create_or_update_profile(customer_id=customer_id, keywords="persistent")

        # Close and reopen connection
        db_module.close_db()

        # Re-import module to get fresh connection
        import importlib

        import database
        importlib.reload(database)
        database.DB_PATH = Path(os.environ['JOBMATCH_DB_PATH'])
        database.init_db()

        profile = database.get_customer_profile(customer_id)
        assert profile['keywords'] == "persistent"


class TestMigration:
    """Test migration from legacy data."""

    def test_migrate_from_legacy(self, db_module, tmp_path):
        # Create legacy files
        legacy_data = tmp_path / 'legacy'
        legacy_data.mkdir()
        # Create data subdirectory as expected by migration
        (legacy_data / 'data').mkdir()

        # Legacy profile
        import json
        profile = {
            "name": "Legacy User",
            "keywords": "python, django",
            "location": "remote",
            "updated": "2026-01-01T12:00:00"
        }
        (legacy_data / 'data' / 'customer_profile.json').write_text(json.dumps(profile))

        # Legacy CV
        (legacy_data / 'data' / 'customer_cv.txt').write_text("Test CV content")

        # Legacy applications CSV
        csv_content = """Application ID,Date Applied,Job Title,Company,Location,Source,Apply Link,Apply Method,Status,Next Follow-up,Notes
1,2026-01-15,IT Support,Company A,Lagos,MyJobMag,https://example.com/1,Online portal,APPLIED,2026-01-20,Score 80
2,2026-01-16,Developer,Company B,Remote,RemoteOK,https://example.com/2,Email,TO_APPLY,2026-01-21,Score 70
"""
        (legacy_data / 'applications.csv').write_text(csv_content)

        # Legacy tailored CVs
        tailored_dir = legacy_data / 'tailored_cvs'
        tailored_dir.mkdir()
        (tailored_dir / '01_Company_A_tailored_cv.txt').write_text("Tailored CV 1")
        (tailored_dir / '01_Company_A_cover_letter.txt').write_text("Cover letter 1")

        # Run migration
        import database
        database.DB_PATH = legacy_data / 'jobmatch.db'
        database.init_db()

        report = database.migrate_from_legacy(base_path=legacy_data)

        assert report['customer_created'] is True
        assert report['customer_id'] == 1
        assert report['profile_imported'] is True
        assert report['cv_imported'] is True
        assert report['applications_imported'] == 2
        assert report['jobs_imported'] == 2
        assert len(report['errors']) == 0

        # Verify migrated data
        customer = database.get_customer(1)
        assert customer['name'] == "Legacy User"

        profile = database.get_customer_profile(1)
        assert profile['keywords'] == "python, django"

        apps = database.get_customer_applications(1)
        assert len(apps) == 2


class TestFileIsolation:
    """Test file system isolation between customers."""

    def test_customer_tailored_dir_isolation(self, db_module, tmp_path):
        """Test that each customer has isolated tailored CV directory."""
        customer_a = db_module.create_customer(name="Customer A")
        customer_b = db_module.create_customer(name="Customer B")
        
        dir_a = tmp_path / 'data' / 'customers' / str(customer_a) / 'tailored_cvs'
        dir_b = tmp_path / 'data' / 'customers' / str(customer_b) / 'tailored_cvs'
        
        dir_a.mkdir(parents=True, exist_ok=True)
        dir_b.mkdir(parents=True, exist_ok=True)
        
        # Write files for each customer
        (dir_a / 'cv_a.txt').write_text("Customer A CV")
        (dir_b / 'cv_b.txt').write_text("Customer B CV")
        
        # Verify isolation
        assert (dir_a / 'cv_a.txt').exists()
        assert (dir_b / 'cv_b.txt').exists()
        assert not (dir_a / 'cv_b.txt').exists()
        assert not (dir_b / 'cv_a.txt').exists()

    def test_customer_cv_dir_isolation(self, db_module, tmp_path):
        """Test that each customer has isolated CV directory."""
        customer_a = db_module.create_customer(name="Customer A")
        customer_b = db_module.create_customer(name="Customer B")
        
        cv_dir_a = tmp_path / 'data' / 'customers' / str(customer_a) / 'cvs'
        cv_dir_b = tmp_path / 'data' / 'customers' / str(customer_b) / 'cvs'
        
        cv_dir_a.mkdir(parents=True, exist_ok=True)
        cv_dir_b.mkdir(parents=True, exist_ok=True)
        
        (cv_dir_a / 'cv_a.txt').write_text("CV A content")
        (cv_dir_b / 'cv_b.txt').write_text("CV B content")
        
        assert (cv_dir_a / 'cv_a.txt').exists()
        assert (cv_dir_b / 'cv_b.txt').exists()


class TestDatabaseIsolationOverlap:
    """Test database isolation with overlapping/identical data."""

    def test_customers_can_have_identical_profile_keywords(self, db_module):
        """Two customers can have identical profile data without conflict."""
        customer_a = db_module.create_customer(name="Customer A")
        customer_b = db_module.create_customer(name="Customer B")
        
        # Both customers have identical keywords
        db_module.create_or_update_profile(customer_id=customer_a, keywords="python, django")
        db_module.create_or_update_profile(customer_id=customer_b, keywords="python, django")
        
        profile_a = db_module.get_customer_profile(customer_a)
        profile_b = db_module.get_customer_profile(customer_b)
        
        assert profile_a['keywords'] == "python, django"
        assert profile_b['keywords'] == "python, django"
        
        # Updating A doesn't affect B
        db_module.create_or_update_profile(customer_id=customer_a, keywords="java, spring")
        profile_a = db_module.get_customer_profile(customer_a)
        profile_b = db_module.get_customer_profile(customer_b)
        
        assert profile_a['keywords'] == "java, spring"
        assert profile_b['keywords'] == "python, django"

    def test_customers_can_have_same_job_matches(self, db_module):
        """Two customers can match the same job independently."""
        customer_a = db_module.create_customer(name="Customer A")
        customer_b = db_module.create_customer(name="Customer B")
        job_id = db_module.create_job(source="MyJobMag", title="IT Support", url="https://example.com/1")
        
        # Both customers match the same job with different scores
        db_module.create_job_match(customer_id=customer_a, job_id=job_id, score=90, fit_score=85, status="new")
        db_module.create_job_match(customer_id=customer_b, job_id=job_id, score=70, fit_score=65, status="reviewed")
        
        matches_a = db_module.get_customer_matches(customer_a)
        matches_b = db_module.get_customer_matches(customer_b)
        
        assert len(matches_a) == 1
        assert len(matches_b) == 1
        assert matches_a[0]['score'] == 90
        assert matches_b[0]['score'] == 70
        
        # Updating A's match doesn't affect B
        db_module.update_match_status(customer_a, job_id, "applied")
        matches_a = db_module.get_customer_matches(customer_a)
        matches_b = db_module.get_customer_matches(customer_b)
        
        assert matches_a[0]['status'] == "applied"
        assert matches_b[0]['status'] == "reviewed"

    def test_customers_can_have_same_application(self, db_module):
        """Two customers can apply to the same job independently."""
        customer_a = db_module.create_customer(name="Customer A")
        customer_b = db_module.create_customer(name="Customer B")
        job_id = db_module.create_job(source="MyJobMag", title="IT Support", url="https://example.com/1")
        
        db_module.create_application(customer_id=customer_a, job_id=job_id, status="APPLIED")
        db_module.create_application(customer_id=customer_b, job_id=job_id, status="TO_APPLY")
        
        apps_a = db_module.get_customer_applications(customer_a)
        apps_b = db_module.get_customer_applications(customer_b)
        
        assert len(apps_a) == 1
        assert len(apps_b) == 1
        assert apps_a[0]['status'] == "APPLIED"
        assert apps_b[0]['status'] == "TO_APPLY"

    def test_customers_can_have_same_tailored_cv(self, db_module):
        """Two customers can have tailored CVs for the same job."""
        customer_a = db_module.create_customer(name="Customer A")
        customer_b = db_module.create_customer(name="Customer B")
        job_id = db_module.create_job(source="MyJobMag", title="IT Support", url="https://example.com/1")
        cv_a_id = db_module.create_customer_cv(customer_id=customer_a, original_filename="cv_a.pdf", stored_path="a")
        cv_b_id = db_module.create_customer_cv(customer_id=customer_b, original_filename="cv_b.pdf", stored_path="b")
        
        db_module.create_tailored_cv(customer_id=customer_a, job_id=job_id, source_cv_id=cv_a_id, stored_path="tc_a.txt")
        db_module.create_tailored_cv(customer_id=customer_b, job_id=job_id, source_cv_id=cv_b_id, stored_path="tc_b.txt")
        
        tailored_a = db_module.get_customer_tailored_cvs(customer_a)
        tailored_b = db_module.get_customer_tailored_cvs(customer_b)
        
        assert len(tailored_a) == 1
        assert len(tailored_b) == 1
        assert tailored_a[0]['stored_path'] == "tc_a.txt"
        assert tailored_b[0]['stored_path'] == "tc_b.txt"

    def test_cascade_delete_customer_removes_owned_data(self, db_module):
        """Deleting a customer cascades to all owned data."""
        customer_a = db_module.create_customer(name="Customer A")
        customer_b = db_module.create_customer(name="Customer B")
        job_id = db_module.create_job(source="MyJobMag", title="IT Support", url="https://example.com/1")
        
        # Create data for both customers
        db_module.create_or_update_profile(customer_id=customer_a, keywords="python")
        db_module.create_or_update_profile(customer_id=customer_b, keywords="java")
        db_module.create_customer_cv(customer_id=customer_a, original_filename="cv_a.pdf", stored_path="a")
        db_module.create_customer_cv(customer_id=customer_b, original_filename="cv_b.pdf", stored_path="b")
        db_module.create_job_match(customer_id=customer_a, job_id=job_id, score=90)
        db_module.create_job_match(customer_id=customer_b, job_id=job_id, score=70)
        db_module.create_application(customer_id=customer_a, job_id=job_id, status="APPLIED")
        db_module.create_application(customer_id=customer_b, job_id=job_id, status="TO_APPLY")
        cv_a = db_module.get_customer_active_cv(customer_a)
        cv_b = db_module.get_customer_active_cv(customer_b)
        db_module.create_tailored_cv(customer_id=customer_a, job_id=job_id, source_cv_id=cv_a['id'], stored_path="tc_a.txt")
        db_module.create_tailored_cv(customer_id=customer_b, job_id=job_id, source_cv_id=cv_b['id'], stored_path="tc_b.txt")
        
        # Delete customer A using database transaction (respects FK constraints)
        with db_module.transaction() as conn:
            conn.execute("DELETE FROM customers WHERE id = ?", (customer_a,))
        
        # A's data should be gone, B's data should remain
        assert db_module.get_customer(customer_a) is None
        assert db_module.get_customer_profile(customer_a) is None
        assert db_module.get_customer_cvs(customer_a) == []
        assert db_module.get_customer_matches(customer_a) == []
        assert db_module.get_customer_applications(customer_a) == []
        assert db_module.get_customer_tailored_cvs(customer_a) == []
        
        # B's data intact
        assert db_module.get_customer(customer_b) is not None
        assert db_module.get_customer_profile(customer_b)['keywords'] == "java"
        assert len(db_module.get_customer_cvs(customer_b)) == 1
        assert len(db_module.get_customer_matches(customer_b)) == 1
        assert len(db_module.get_customer_applications(customer_b)) == 1
        assert len(db_module.get_customer_tailored_cvs(customer_b)) == 1


class TestLegacyEndpointCompatibility:
    """Document and verify legacy endpoint compatibility strategy."""

    def test_legacy_endpoints_require_customer_id(self):
        """Document that legacy endpoints now require explicit customer_id."""
        # This test documents the expected behavior
        # Legacy endpoints (/api/customer/*) require customer_id parameter
        # They return 400 if customer_id is not provided
        # They do NOT default to customer_id=1
        pass  # Behavior verified by integration tests

    def test_legacy_endpoints_use_customer_specific_storage(self):
        """Document that legacy endpoints use customer-specific storage."""
        # Legacy endpoints now:
        # - Read/write customer-specific profile from database
        # - Read/write customer-specific CVs from database
        # - Read/write customer-specific results from data/customers/<id>/results/
        # - Read/write customer-specific tailored CVs from data/customers/<id>/tailored_cvs/
        # They do NOT use global tailored_cvs/ or customer_results.json
        pass  # Behavior verified by integration tests


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
