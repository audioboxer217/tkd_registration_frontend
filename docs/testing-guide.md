# Testing Guide

## Overview

This project uses **pytest** for testing with a class-based organization and extensive mocking of external services. Tests are located in `tests/test_website.py`.

---

## Running Tests

```bash
uv run pytest                    # Run all tests
uv run pytest -v                # Verbose output
uv run pytest -k test_register  # Run tests matching pattern
uv run pytest tests/test_website.py::TestRegister  # Run specific test class
```

---

## Test Setup & Configuration

### In-Memory Database
Tests use SQLite in-memory database to avoid polluting production data and for speed:

```python
@pytest.fixture
def app():
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['WTF_CSRF_ENABLED'] = False
    
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
```

**Why in-memory?**
- Fast: No I/O to real database
- Isolated: Each test gets a fresh DB
- Safe: No risk of polluting production data
- Deterministic: Reproducible results

### Disabled CSRF
CSRF protection is disabled in tests (`WTF_CSRF_ENABLED = False`) to simplify form submissions.

### Required Environment Variables
Tests need these env vars set (see `.github/workflows/main.yml` for CI values):

```bash
export COMPETITION_NAME="Test Competition"
export CONTACT_EMAIL="contact@example.com"
export EARLY_REG_DATE="June 01, 2026"
export REG_CLOSE_DATE="July 01, 2026"
export CONFIG_BUCKET="test-config"
export PUBLIC_MEDIA_BUCKET="test-media"
export STRIPE_API_KEY="sk_test_..."
```

Or run with `set -a && source frontend.env && set +a` before pytest.

---

## Mocking External Services

### Why Mock?
- Tests should be fast and isolated
- Avoid calling real APIs during test runs
- Prevent unexpected charges (Stripe) or quota limits
- Make tests deterministic and reproducible

### Key Services to Mock

#### 1. Stripe (Payments)
```python
from unittest.mock import MagicMock, patch

@patch('stripe.Checkout.Session.create')
def test_payment_flow(self, mock_stripe_create):
    # Setup mock
    mock_stripe_create.return_value = MagicMock(
        id='cs_test_123',
        payment_status='unpaid',
        url='https://checkout.stripe.com/...'
    )
    
    # Test code that calls Stripe
    response = self.client.post('/pay', data={...})
    
    # Assert mock was called
    mock_stripe_create.assert_called_once()
    assert response.status_code == 302
```

#### 2. Supabase (Database & Auth)
```python
@patch('supabase.Client.auth.get_user')
def test_admin_access(self, mock_supabase_auth):
    # Setup mock user
    mock_user = MagicMock()
    mock_user.user.app_metadata = {"role": "admin"}
    mock_supabase_auth.return_value = mock_user
    
    response = self.client.get('/admin')
    assert response.status_code == 200
```

#### 3. S3 (File Upload)
```python
@patch('boto3.client')
def test_upload_photo(self, mock_boto3):
    mock_s3 = MagicMock()
    mock_boto3.return_value = mock_s3
    mock_s3.put_object.return_value = {'ETag': '123'}
    
    response = self.client.post('/upload-photo', data={...})
    assert mock_s3.put_object.called
```

### Mock Helpers
Common mock setup functions in test file:

```python
def make_stripe_coupon_mock():
    """Returns a mock Stripe coupon with expected structure."""
    return MagicMock(
        id="test_coupon",
        percent_off=10.0,
        valid=True
    )

def make_admin_session():
    """Returns a mock Supabase session with admin role."""
    session = MagicMock()
    session.user.app_metadata = {"role": "admin"}
    return session
```

Use these in your tests:

```python
@patch('stripe.Coupon.retrieve')
def test_apply_coupon(self, mock_coupon):
    mock_coupon.return_value = make_stripe_coupon_mock()
    # ... test code ...
```

---

## Test Organization & Patterns

### Class-Based Organization
Tests are organized into classes by feature/route:

```python
class TestHomepage:
    """Tests for homepage routes."""
    
    def test_homepage_loads(self):
        response = self.client.get('/')
        assert response.status_code == 200
        assert b'Register' in response.data

class TestRegistration:
    """Tests for registration form and submission."""
    
    def test_register_competitor(self):
        response = self.client.post('/register', data={
            'full_name': 'Jane Doe',
            'email': 'jane@example.com',
            ...
        })
        assert response.status_code == 302  # Redirect on success

class TestAdminRoutes:
    """Tests for admin-only routes."""
    
    @patch('flask_login.current_user')
    def test_admin_access_denied_without_auth(self, mock_user):
        mock_user.is_authenticated = False
        response = self.client.get('/admin')
        assert response.status_code == 302  # Redirect to /login
```

### Setup & Teardown
Use pytest fixtures for setup:

```python
@pytest.fixture
def app():
    """Create app with test config."""
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['WTF_CSRF_ENABLED'] = False
    
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()

@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()

class TestMyFeature:
    def test_something(self, client):
        response = client.get('/')
        assert response.status_code == 200
```

---

## Common Test Patterns

### Testing Form Submission
```python
def test_register_competitor(self):
    response = self.client.post('/register', data={
        'full_name': 'Jane Doe',
        'email': 'jane@example.com',
        'phone': '555-1234',
        'school': 'Dragon Dojo',
        'parent': 'John Doe',
        'birthdate': '01/15/2015',
        'age': 11,
        'gender': 'F',
        'weight': '85.5',
        'height': '54',
        'belt_rank': 'Yellow',
    })
    
    # Verify redirect (successful submission)
    assert response.status_code == 302
    
    # Verify data was saved to DB
    competitor = Competitor.query.filter_by(email='jane@example.com').first()
    assert competitor is not None
    assert competitor.full_name == 'Jane Doe'
    assert competitor.age == 11
```

### Testing Form Validation
```python
def test_register_missing_email(self):
    response = self.client.post('/register', data={
        'full_name': 'Jane Doe',
        # Missing email
        'school': 'Dragon Dojo',
    })
    
    # Verify form validation error (no redirect)
    assert response.status_code == 200
    assert b'Email is required' in response.data
    
    # Verify no record created
    assert Competitor.query.count() == 0
```

### Testing Admin Access Control
```python
@patch('flask_login.current_user')
def test_admin_page_requires_auth(self, mock_user):
    mock_user.is_authenticated = False
    
    response = self.client.get('/admin')
    assert response.status_code == 302  # Redirect
    assert '/login' in response.location
```

### Testing HTML Content
```python
def test_homepage_shows_competition_name(self):
    response = self.client.get('/')
    assert response.status_code == 200
    assert b'Spring TKD Tournament' in response.data  # Check for expected text
    assert b'Register Now' in response.data
```

### Testing Query String Parameters
```python
def test_lookup_by_email(self):
    # Create test competitor
    school = _get_or_create_school('Dragon Dojo')
    competitor = Competitor(
        full_name='Jane Doe',
        email='jane@example.com',
        school_id=school.id
    )
    db.session.add(competitor)
    db.session.commit()
    
    # Query by email
    response = self.client.get('/lookup?email=jane@example.com')
    assert response.status_code == 200
    assert b'Jane Doe' in response.data
```

### Testing Redirects
```python
def test_successful_registration_redirects(self):
    response = self.client.post('/register', data={...})
    assert response.status_code == 302
    assert '/thank-you' in response.location
```

---

## Working with Database in Tests

### Creating Test Data
```python
def test_admin_view(self):
    # Create test school
    school = _get_or_create_school('Dragon Dojo')
    
    # Create test competitors
    for i in range(5):
        competitor = Competitor(
            full_name=f'Competitor {i}',
            email=f'comp{i}@example.com',
            school_id=school.id,
            age=10 + i,
        )
        db.session.add(competitor)
    db.session.commit()
    
    # Test that admin page shows all
    response = self.client.get('/admin')
    assert response.status_code == 200
    assert b'Competitor 0' in response.data
    assert b'Competitor 4' in response.data
```

### Querying Test Data
```python
def test_lookup_functionality(self):
    # Create test competitor
    school = _get_or_create_school('Dragon Dojo')
    competitor = Competitor(
        full_name='Jane Doe',
        email='jane@example.com',
        school_id=school.id
    )
    db.session.add(competitor)
    db.session.commit()
    
    # Verify created
    found = Competitor.query.filter_by(email='jane@example.com').first()
    assert found is not None
    assert found.full_name == 'Jane Doe'
```

### Clearing Test Data Between Tests
Pytest fixtures handle this automatically, but you can explicitly clear if needed:

```python
def test_first(self):
    competitor = Competitor(...)
    db.session.add(competitor)
    db.session.commit()
    assert Competitor.query.count() == 1

def test_second(self):
    # Automatically starts with clean DB
    assert Competitor.query.count() == 0
```

---

## Debugging Tests

### Print Debug Output
```python
def test_debug(self):
    competitor = Competitor.query.first()
    print(f"Competitor: {competitor.to_dict()}")  # Will show in pytest -s output
    assert competitor is not None
```

Run with verbose output:
```bash
uv run pytest -s -v tests/test_website.py::TestMyFeature::test_debug
```

### Inspect Response Content
```python
def test_response(self):
    response = self.client.get('/admin')
    print(response.data.decode())  # Print HTML response
    assert b'Expected Text' in response.data
```

### Use debugger
```python
def test_with_debugger(self):
    import pdb; pdb.set_trace()  # Breakpoint
    response = self.client.get('/')
```

Run with:
```bash
uv run pytest --pdb tests/test_website.py::TestMyFeature::test_with_debugger
```

---

## Common Pitfalls

### ❌ Forgetting to Commit to DB
```python
# Wrong: Changes not saved
competitor = Competitor(full_name='Jane', email='jane@example.com')
db.session.add(competitor)
# Missing: db.session.commit()

query = Competitor.query.filter_by(email='jane@example.com').first()
assert query is not None  # ❌ Fails! Data not committed
```

**Solution**: Always commit:
```python
db.session.add(competitor)
db.session.commit()  # ✅ Now data is saved
```

### ❌ Not Mocking External Services
```python
# Wrong: Real Stripe call during test
@patch('stripe.Coupon.retrieve')
def test_coupon(self, mock_stripe):
    # Forgot to set return value!
    response = self.client.post('/apply-coupon', data={...})
    # Test hangs or fails because mock is not configured
```

**Solution**: Configure the mock:
```python
@patch('stripe.Coupon.retrieve')
def test_coupon(self, mock_stripe):
    mock_stripe.return_value = MagicMock(percent_off=10.0)  # ✅ Configured
    response = self.client.post('/apply-coupon', data={...})
```

### ❌ Not Initializing Test Database
```python
# Wrong: Fixtures not used
def test_something():
    # Missing: @pytest.fixture or fixture parameter
    response = self.client.get('/')  # ❌ client not available
```

**Solution**: Use fixtures as parameters:
```python
def test_something(self, client):  # ✅ Pass fixture as parameter
    response = client.get('/')
```

### ❌ Asserting Without Checking Type
```python
# Wrong: response.data is bytes, not string
assert 'Expected Text' in response.data  # ❌ TypeError
```

**Solution**: Use bytes:
```python
assert b'Expected Text' in response.data  # ✅ Correct
```

---

## Test Coverage

To see test coverage:

```bash
uv run pytest --cov=. --cov-report=html
open htmlcov/index.html
```

This generates an HTML report showing which lines are covered by tests.

---

## Continuous Integration

GitHub Actions runs tests on every push (see `.github/workflows/main.yml`). Tests must pass before merging to `main`.

To mimic CI locally:

```bash
# Run linting + tests (same as CI)
uv run ruff check .
uv run pytest
```
