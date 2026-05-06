# API Patterns

## Overview

The REST API is implemented in `api.py` using Flask Blueprints. All endpoints are under `/api/v1/` and are protected by JWT authentication via Supabase.

---

## Core Structure

### Blueprint Setup
```python
# api.py
api_bp = Blueprint("api", __name__, url_prefix="/api/v1")

@api_bp.route('/entries', methods=['GET'])
@api_auth_required
def get_entries():
    """Get all entries (coaches + competitors)."""
    ...
```

### Authentication Decorator
Every API endpoint requires the `@api_auth_required` decorator:

```python
def api_auth_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check Authorization header
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Missing or invalid Authorization header'}), 401
        
        # Validate JWT token with Supabase
        token = auth_header.split(' ')[1]
        user = verify_jwt_token(token)
        if not user:
            return jsonify({'error': 'Invalid token'}), 401
        
        # Check admin role
        if user.get('role') != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
        
        return f(*args, **kwargs)
    return decorated_function
```

**Usage**: Add `@api_auth_required` to any endpoint that requires authentication.

---

## Response Format

### Success Responses
All successful API responses follow this format:

```python
@api_bp.route('/entries', methods=['GET'])
@api_auth_required
def get_entries():
    entries = []
    
    # Fetch competitors
    for competitor in Competitor.query.all():
        entries.append(competitor.to_dict())
    
    # Fetch coaches
    for coach in Coach.query.all():
        entries.append(coach.to_dict())
    
    return jsonify({"data": entries})  # ✅ Wrap in "data" key
```

Response body:
```json
{
  "data": [
    {
      "id": 1,
      "full_name": "Jane Doe",
      "email": "jane@example.com",
      "reg_type": "competitor",
      ...
    },
    {
      "id": 1,
      "full_name": "Sensei John",
      "email": "john@example.com",
      "reg_type": "coach",
      ...
    }
  ]
}
```

### Error Responses
All errors follow this format:

```python
@api_bp.route('/entries/<int:entry_id>', methods=['GET'])
@api_auth_required
def get_entry(entry_id):
    # Try competitor first
    competitor = Competitor.query.get(entry_id)
    if competitor:
        return jsonify({"data": competitor.to_dict()})
    
    # Try coach
    coach = Coach.query.get(entry_id)
    if coach:
        return jsonify({"data": coach.to_dict()})
    
    # Not found
    return jsonify({"error": "Entry not found"}), 404  # ✅ Error format
```

Response body (error):
```json
{
  "error": "Entry not found"
}
```

### HTTP Status Codes
- **200 OK**: Successful GET, POST, PUT, DELETE
- **201 Created**: New resource created (optional, usually use 200)
- **400 Bad Request**: Invalid input/validation error
- **401 Unauthorized**: Missing/invalid authentication
- **403 Forbidden**: Authenticated but not authorized (e.g., not admin)
- **404 Not Found**: Resource doesn't exist
- **422 Unprocessable Entity**: Request well-formed but semantically incorrect
- **500 Internal Server Error**: Server error (avoid, handle exceptions)

---

## Endpoint Examples

### GET List of Resources
```python
@api_bp.route('/entries', methods=['GET'])
@api_auth_required
def get_entries():
    """Get all entries (competitors + coaches)."""
    entries = []
    
    # Combine competitors and coaches
    for competitor in Competitor.query.all():
        entries.append(competitor.to_dict())
    
    for coach in Coach.query.all():
        entries.append(coach.to_dict())
    
    return jsonify({"data": entries})
```

**Request**:
```
GET /api/v1/entries
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

**Response (200)**:
```json
{
  "data": [
    {"id": 1, "full_name": "Jane Doe", "reg_type": "competitor", ...},
    {"id": 1, "full_name": "Sensei John", "reg_type": "coach", ...}
  ]
}
```

### GET Single Resource
```python
@api_bp.route('/entries/<int:entry_id>', methods=['GET'])
@api_auth_required
def get_entry(entry_id):
    """Get a specific entry by ID."""
    # Try competitor first
    competitor = Competitor.query.get(entry_id)
    if competitor:
        return jsonify({"data": competitor.to_dict()})
    
    # Try coach
    coach = Coach.query.get(entry_id)
    if coach:
        return jsonify({"data": coach.to_dict()})
    
    return jsonify({"error": "Entry not found"}), 404
```

**Request**:
```
GET /api/v1/entries/1
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

**Response (200)**:
```json
{
  "data": {
    "id": 1,
    "full_name": "Jane Doe",
    "email": "jane@example.com",
    "reg_type": "competitor",
    ...
  }
}
```

**Response (404)**:
```json
{
  "error": "Entry not found"
}
```

### POST Create Resource
```python
@api_bp.route('/entries', methods=['POST'])
@api_auth_required
def create_entry():
    """Create a new competitor entry."""
    data = request.get_json()
    
    # Validate required fields
    if not data.get('full_name'):
        return jsonify({"error": "full_name is required"}), 400
    if not data.get('email'):
        return jsonify({"error": "email is required"}), 400
    if not data.get('school'):
        return jsonify({"error": "school is required"}), 400
    
    # Get or create school
    school = _get_or_create_school(data.get('school'))
    
    # Get or create coach if provided
    coach_id = None
    if data.get('coach_name'):
        coach = _get_or_create_coach(
            data.get('coach_name'),
            data.get('coach_email', ''),
            school.id
        )
        coach_id = coach.id
    
    # Create competitor
    competitor = Competitor(
        full_name=data.get('full_name'),
        email=data.get('email'),
        phone=data.get('phone'),
        school_id=school.id,
        coach_id=coach_id,
        age=data.get('age'),
        gender=data.get('gender'),
        weight=data.get('weight'),
        height=data.get('height'),
        belt_rank=data.get('belt_rank'),
        events=','.join(data.get('events', [])) if data.get('events') else None,
    )
    
    db.session.add(competitor)
    db.session.commit()
    
    return jsonify({"data": competitor.to_dict()}), 200
```

**Request**:
```json
POST /api/v1/entries
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
Content-Type: application/json

{
  "full_name": "Jane Doe",
  "email": "jane@example.com",
  "school": "Dragon Dojo",
  "coach_name": "Sensei John",
  "coach_email": "john@dojo.com",
  "age": 11,
  "gender": "F",
  "weight": 85.5,
  "height": 54,
  "belt_rank": "Yellow",
  "events": ["sparring", "forms"]
}
```

**Response (200)**:
```json
{
  "data": {
    "id": 1,
    "full_name": "Jane Doe",
    "email": "jane@example.com",
    "reg_type": "competitor",
    "school_id": 1,
    "school": "Dragon Dojo",
    "events": ["sparring", "forms"],
    ...
  }
}
```

**Response (400)**:
```json
{
  "error": "email is required"
}
```

### PUT Update Resource
```python
@api_bp.route('/entries/<int:entry_id>', methods=['PUT'])
@api_auth_required
def update_entry(entry_id):
    """Update a competitor entry."""
    data = request.get_json()
    
    # Get competitor
    competitor = Competitor.query.get(entry_id)
    if not competitor:
        return jsonify({"error": "Entry not found"}), 404
    
    # Update fields (only if provided in request)
    if 'full_name' in data:
        competitor.full_name = data['full_name']
    if 'email' in data:
        competitor.email = data['email']
    if 'age' in data:
        competitor.age = data['age']
    if 'events' in data:
        competitor.events = ','.join(data['events'])
    
    db.session.commit()
    
    return jsonify({"data": competitor.to_dict()})
```

**Request**:
```json
PUT /api/v1/entries/1
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
Content-Type: application/json

{
  "age": 12,
  "events": ["sparring", "forms", "weapons"]
}
```

**Response (200)**:
```json
{
  "data": {
    "id": 1,
    "age": 12,
    "events": ["sparring", "forms", "weapons"],
    ...
  }
}
```

### DELETE Resource
```python
@api_bp.route('/entries/<int:entry_id>', methods=['DELETE'])
@api_auth_required
def delete_entry(entry_id):
    """Delete a competitor entry."""
    # Try competitor first
    competitor = Competitor.query.get(entry_id)
    if competitor:
        db.session.delete(competitor)
        db.session.commit()
        return jsonify({"data": {"message": "Entry deleted"}}), 200
    
    # Try coach
    coach = Coach.query.get(entry_id)
    if coach:
        db.session.delete(coach)
        db.session.commit()
        return jsonify({"data": {"message": "Entry deleted"}}), 200
    
    return jsonify({"error": "Entry not found"}), 404
```

**Request**:
```
DELETE /api/v1/entries/1
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

**Response (200)**:
```json
{
  "data": {"message": "Entry deleted"}
}
```

---

## Request Validation

### Check for Required Fields
```python
data = request.get_json()

if not data.get('full_name'):
    return jsonify({"error": "full_name is required"}), 400

if not data.get('email'):
    return jsonify({"error": "email is required"}), 400
```

### Validate Email Format
```python
import re

email = data.get('email', '')
if not re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', email):
    return jsonify({"error": "Invalid email format"}), 400
```

### Validate Age
```python
age = data.get('age')
if age is not None and (age < 3 or age > 18):
    return jsonify({"error": "Age must be between 3 and 18"}), 400
```

---

## Error Handling

### Try-Catch for Database Errors
```python
@api_bp.route('/entries', methods=['POST'])
@api_auth_required
def create_entry():
    try:
        data = request.get_json()
        # ... validation ...
        
        competitor = Competitor(...)
        db.session.add(competitor)
        db.session.commit()
        
        return jsonify({"data": competitor.to_dict()})
    
    except IntegrityError as e:
        db.session.rollback()
        return jsonify({"error": f"Database integrity error: {str(e)}"}), 422
    
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Server error: {str(e)}"}), 500
```

### Validation Errors
```python
if not email or '@' not in email:
    return jsonify({"error": "Invalid email"}), 400
```

---

## Testing API Endpoints

### Mocking JWT Authentication
```python
@patch('api.verify_jwt_token')
def test_get_entries(self, mock_verify):
    # Mock successful authentication
    mock_verify.return_value = {'role': 'admin', 'user_id': '123'}
    
    # Make request with Authorization header
    response = self.client.get(
        '/api/v1/entries',
        headers={'Authorization': 'Bearer fake_token'}
    )
    
    assert response.status_code == 200
    data = response.get_json()
    assert 'data' in data
```

### Testing Validation
```python
def test_create_entry_missing_name(self):
    response = self.client.post(
        '/api/v1/entries',
        json={'email': 'jane@example.com', 'school': 'Dragon Dojo'},
        headers={'Authorization': 'Bearer fake_token'}
    )
    
    assert response.status_code == 400
    data = response.get_json()
    assert 'full_name is required' in data['error']
```

### Testing Error Responses
```python
def test_get_nonexistent_entry(self):
    response = self.client.get(
        '/api/v1/entries/999',
        headers={'Authorization': 'Bearer fake_token'}
    )
    
    assert response.status_code == 404
    data = response.get_json()
    assert 'Entry not found' in data['error']
```

---

## Common Patterns

### Querying Both Competitors and Coaches
```python
def get_all_registrations():
    """Get all competitors and coaches."""
    results = []
    
    # Add competitors
    for competitor in Competitor.query.all():
        results.append(competitor.to_dict())
    
    # Add coaches
    for coach in Coach.query.all():
        results.append(coach.to_dict())
    
    return results
```

### Filtering by School
```python
def get_entries_by_school(school_name):
    """Get all entries for a specific school."""
    school = School.query.filter_by(name=school_name).first()
    if not school:
        return None
    
    results = []
    
    # Get competitors from this school
    for competitor in Competitor.query.filter_by(school_id=school.id).all():
        results.append(competitor.to_dict())
    
    # Get coaches from this school
    for coach in Coach.query.filter_by(school_id=school.id).all():
        results.append(coach.to_dict())
    
    return results
```

### Pagination
```python
@api_bp.route('/entries', methods=['GET'])
@api_auth_required
def get_entries_paginated():
    """Get paginated list of entries."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    
    # Query competitors
    competitors = Competitor.query.paginate(page=page, per_page=per_page)
    
    return jsonify({
        "data": [c.to_dict() for c in competitors.items],
        "total": competitors.total,
        "page": page,
        "per_page": per_page,
        "pages": competitors.pages
    })
```

**Request**:
```
GET /api/v1/entries?page=1&per_page=25
```

---

## Best Practices

1. **Always call `.to_dict()`** on models before returning as JSON
2. **Validate input** at request boundaries (user input)
3. **Check authentication** with `@api_auth_required` decorator
4. **Use consistent error format** (`{"error": "message"}`)
5. **Use correct HTTP status codes** (400, 401, 403, 404, etc.)
6. **Handle database errors** with try-catch and rollback
7. **Mock external services** in tests
8. **Document request/response format** in PR or docstring
