# Database Schema Documentation

## Overview

The TKD Registration database uses three active tables (`schools`, `coaches`, `competitors`) plus a legacy `registrations` archive. This refactoring (Apr 2026) separated a monolithic registrations table into properly normalized, type-specific tables.

---

## Table: Schools

Reference table for schools/clubs. Used as a foreign key by both coaches and competitors.

### Columns
| Name | Type | Constraints | Notes |
|------|------|-------------|-------|
| `id` | INTEGER | PRIMARY KEY, autoincrement | Unique school identifier |
| `name` | VARCHAR(200) | NOT NULL, UNIQUE | School/club name (enforced unique) |
| `created_at` | DATETIME | NOT NULL, default=utcnow | Timestamp of creation |

### Relationships
- One-to-Many with `coaches` (cascade delete)
- One-to-Many with `competitors` (cascade delete)

### Example Usage
```python
from models import School, Competitor

# Create or fetch school (recommended pattern)
school = _get_or_create_school("Dragon Dojo")

# Query schools
all_schools = School.query.all()
school = School.query.filter_by(name="Dragon Dojo").first()

# Serialize
school.to_dict()  # {"id": 1, "name": "Dragon Dojo", "created_at": "2026-04-01T..."}
```

---

## Table: Coaches

Registration type for coaches. Coaches belong to a school.

### Columns
| Name | Type | Constraints | Notes |
|------|------|-------------|-------|
| `id` | INTEGER | PRIMARY KEY, autoincrement | Unique coach identifier |
| `full_name` | VARCHAR(200) | NOT NULL | Coach's full name |
| `email` | VARCHAR(200) | NOT NULL, indexed | Coach's email (indexed for lookups) |
| `phone` | VARCHAR(20) | nullable | Phone number (optional) |
| `school_id` | INTEGER | FK(schools.id), NOT NULL | School this coach belongs to |
| `img_filename` | VARCHAR(200) | nullable | Badge photo filename (optional, ENABLE_BADGES) |
| `created_at` | DATETIME | NOT NULL, default=utcnow | Timestamp of creation |
| `updated_at` | DATETIME | NOT NULL, default=utcnow, onupdate | Timestamp of last update |

### Relationships
- Many-to-One with `schools` (back_populates="coaches")
- One-to-Many with `competitors` via `coach_rel` (back_populates="coach_rel")

### `.to_dict()` Output
```python
{
    "id": 1,
    "full_name": "Sensei John",
    "email": "john@dojo.com",
    "phone": "555-1234",
    "school_id": 1,
    "school": "Dragon Dojo",
    "reg_type": "coach",
    "img_filename": "john.png",
    # Competitor-specific fields (always null/empty for coaches)
    "parent": None,
    "birthdate": None,
    "age": None,
    "gender": None,
    "weight": None,
    "height": None,
    "belt_rank": None,
    "events": [],
    "poomsae_form": None,
    # ... etc
}
```

### Example Usage
```python
from models import Coach

# Query coaches
coaches = Coach.query.all()
coaches = Coach.query.filter_by(school_id=1).all()
coach = Coach.query.filter_by(email="john@dojo.com").first()

# Create coach (use helper to ensure school exists)
school = _get_or_create_school("Dragon Dojo")
coach = Coach(
    full_name="Sensei John",
    email="john@dojo.com",
    phone="555-1234",
    school_id=school.id
)
db.session.add(coach)
db.session.commit()

# Serialize
coach.to_dict()
```

---

## Table: Competitors

Registration type for competitors. Competitors belong to a school and optionally to a coach.

### Columns
| Name | Type | Constraints | Notes |
|------|------|-------------|-------|
| `id` | INTEGER | PRIMARY KEY, autoincrement | Unique competitor identifier |
| `full_name` | VARCHAR(200) | NOT NULL | Competitor's full name |
| `email` | VARCHAR(200) | NOT NULL, indexed | Email (indexed for lookups) |
| `phone` | VARCHAR(20) | nullable | Phone number (optional) |
| `school_id` | INTEGER | FK(schools.id), NOT NULL | School this competitor belongs to |
| `coach_id` | INTEGER | FK(coaches.id), nullable | Coach assignment (optional, can be null) |
| `parent` | VARCHAR(200) | nullable | Parent/guardian name |
| `birthdate` | VARCHAR(10) | nullable | MM/DD/YYYY format (matches form input) |
| `age` | INTEGER | nullable | Calculated age |
| `gender` | VARCHAR(1) | nullable | M, F, or other |
| `weight` | NUMERIC(6,1) | nullable | Weight in pounds |
| `height` | INTEGER | nullable | Height in inches |
| `belt_rank` | VARCHAR(50) | nullable | Current belt rank |
| `events` | TEXT | nullable | Comma-separated list (e.g., "sparring,forms") |
| `poomsae_form` | VARCHAR(100) | nullable | Individual poomsae form selection |
| `wc_poomsae_form` | VARCHAR(100) | nullable | Weapon poomsae form |
| `pair_poomsae_form` | VARCHAR(100) | nullable | Pair poomsae form |
| `team_poomsae_form` | VARCHAR(100) | nullable | Team poomsae form |
| `family_poomsae_form` | VARCHAR(100) | nullable | Family poomsae form |
| `medical_contacts` | TEXT | nullable | Emergency contact info |
| `medical_conditions` | JSON | nullable | Array of medical conditions |
| `allergies` | JSON | nullable | Array of allergies |
| `medications` | JSON | nullable | Array of medications |
| `img_filename` | VARCHAR(200) | nullable | Badge photo filename (ENABLE_BADGES) |
| `tshirt` | VARCHAR(20) | nullable | T-shirt size for little dragons |
| `checkout_session_id` | VARCHAR(100) | indexed | Stripe checkout session ID |
| `created_at` | DATETIME | NOT NULL, default=utcnow | Timestamp of creation |
| `updated_at` | DATETIME | NOT NULL, default=utcnow, onupdate | Timestamp of last update |

### Relationships
- Many-to-One with `schools` (back_populates="competitors")
- Many-to-One with `coaches` via `coach_rel` (back_populates="competitors")

### `.to_dict()` Output
```python
{
    "id": 1,
    "full_name": "Jane Doe",
    "email": "jane@example.com",
    "phone": "555-5678",
    "school": "Dragon Dojo",
    "school_id": 1,
    "coach": "Sensei John",
    "coach_id": 1,
    "parent": "John Doe",
    "birthdate": "01/15/2015",
    "age": 11,
    "gender": "F",
    "weight": 85.5,
    "height": 54,
    "belt_rank": "Yellow",
    "events": ["sparring", "forms"],
    "poomsae_form": "Keumgang",
    "wc_poomsae_form": None,
    "pair_poomsae_form": None,
    "team_poomsae_form": None,
    "family_poomsae_form": None,
    "medical_contacts": "911",
    "medical_conditions": ["asthma"],
    "allergies": ["peanuts"],
    "medications": ["inhaler"],
    "img_filename": "jane.png",
    "tshirt": "XS",
    "checkout_session_id": "cs_test_...",
    "reg_type": "competitor",
    "created_at": "2026-04-01T...",
    "updated_at": "2026-04-01T...",
}
```

### Example Usage
```python
from models import Competitor

# Query competitors
competitors = Competitor.query.all()
competitors = Competitor.query.filter_by(school_id=1).all()
competitor = Competitor.query.filter_by(email="jane@example.com").first()

# Create competitor (use helper to ensure school exists)
school = _get_or_create_school("Dragon Dojo")
coach = _get_or_create_coach("Sensei John", "john@dojo.com", school.id)

competitor = Competitor(
    full_name="Jane Doe",
    email="jane@example.com",
    school_id=school.id,
    coach_id=coach.id,
    parent="John Doe",
    birthdate="01/15/2015",
    age=11,
    gender="F",
    weight=85.5,
    height=54,
    belt_rank="Yellow",
    events="sparring,forms",
)
db.session.add(competitor)
db.session.commit()

# Serialize
competitor.to_dict()
```

---

## Table: Registration (Legacy Archive)

**Do not insert new rows.** This table is kept for backward compatibility during the migration from DynamoDB.

All new code should query `Competitor` or `Coach` tables instead. Use `Registration` table only for:
- Historical lookups of old registrations
- CSV export of all registrations
- Data validation/debugging during migration

### Columns
Same as `Competitor` but with flattened structure (no FK relationships):
- `full_name`, `email`, `phone`, `school` (string, not FK)
- `reg_type` (string: "competitor" or "coach")
- All competitor-specific fields (nullable for coaches)

### Example Usage
```python
from models import Registration

# Historical lookup (read-only)
old_registrations = Registration.query.all()

# Do NOT do this:
# reg = Registration(full_name="...", ...)  # ❌ Wrong! Add to Competitor or Coach instead
```

---

## Adding a New Registration Field

### Step 1: Update Model
Edit `models.py` and add the column to `Competitor` or `Coach`:

```python
class Competitor(db.Model):
    # ... existing columns ...
    new_field = db.Column(String(100))  # Add new column
    
    def to_dict(self):
        return {
            # ... existing fields ...
            "new_field": self.new_field,  # Include in serialization
        }
```

### Step 2: Generate Migration
```bash
uv run flask --app app db migrate -m "add new_field to competitors"
```

This generates a migration file in `migrations/versions/`. Review it:
```python
def upgrade():
    op.add_column('competitors', sa.Column('new_field', sa.String(100), nullable=True))

def downgrade():
    op.drop_column('competitors', 'new_field')
```

### Step 3: Apply Migration
```bash
uv run flask --app app db upgrade
```

### Step 4: Update Form/Template (if user-facing)
Edit form templates in `templates/form/` to include the new field.

### Step 5: Add Test Case
In `tests/test_website.py`, add a test that submits the new field:

```python
def test_register_with_new_field(self):
    response = self.client.post('/register', data={
        'full_name': 'Test User',
        'new_field': 'test value',
        # ... other required fields ...
    })
    assert response.status_code == 302  # Redirect on success
    
    # Verify field was saved
    competitor = Competitor.query.filter_by(full_name='Test User').first()
    assert competitor.new_field == 'test value'
```

### Step 6: Commit & Deploy
- Commit migration + model + template + test changes together
- Deploy to dev environment first to verify
- Then production

---

## Migration Status

See [`migration-status.md`](migration-status.md) for detailed context on the ongoing DynamoDB → Postgres migration.

---

## Common Issues

### Foreign Key Constraint Violations
**Problem**: `IntegrityError: (psycopg.errors.ForeignKeyViolation) ... school_id ...`

**Solution**: Use `_get_or_create_school(name)` before creating competitors/coaches:
```python
school = _get_or_create_school("Dragon Dojo")
competitor = Competitor(school_id=school.id, ...)  # Now safe
```

### Competitor Without Coach
**Problem**: Need to handle competitors without an assigned coach

**Solution**: `coach_id` is nullable. Access it safely:
```python
competitor_dict = competitor.to_dict()
coach_name = competitor.coach_rel.full_name if competitor.coach_rel else None
```

### Events Field is a String, Not an Array
**Problem**: Querying competitors and getting `events="sparring,forms"` as a string

**Solution**: `.to_dict()` automatically splits it:
```python
competitor_dict = competitor.to_dict()
events = competitor_dict['events']  # ['sparring', 'forms'] (already a list)
```

### Medical Info is JSON
**Problem**: Reading `medical_conditions` and not sure of format

**Solution**: Check `.to_dict()` output or database directly. Always handle None:
```python
competitor_dict = competitor.to_dict()
conditions = competitor_dict['medical_conditions'] or []  # [] if None
```

---

## Queries by Use Case

### Find All Competitors from a School
```python
school = School.query.filter_by(name="Dragon Dojo").first()
competitors = Competitor.query.filter_by(school_id=school.id).all()
```

### Find All Competitors Under a Coach
```python
coach = Coach.query.filter_by(full_name="Sensei John").first()
competitors = Competitor.query.filter_by(coach_id=coach.id).all()
```

### Find Competitor by Email
```python
competitor = Competitor.query.filter_by(email="jane@example.com").first()
```

### Get All Registrations (Both Types)
```python
competitors = [c.to_dict() for c in Competitor.query.all()]
coaches = [c.to_dict() for c in Coach.query.all()]
all_registrations = competitors + coaches
```

### Export All Competitors to CSV
```python
competitors = Competitor.query.all()
csv_rows = [c.to_dict() for c in competitors]
# Then write to CSV file
```

---

## Performance Notes

- **Indexed columns**: `email` on both `Competitor` and `Coach` (fast lookups by email)
- **Indexed columns**: `checkout_session_id` on `Competitor` (fast Stripe payment lookups)
- **FK columns**: `school_id`, `coach_id` (use for filtering)
- **Avoid N+1 queries**: Use SQLAlchemy eager loading if fetching related objects in a loop

Example of N+1 problem:
```python
# ❌ Bad: N+1 query (1 + len(competitors) queries)
competitors = Competitor.query.all()
for c in competitors:
    print(c.school.name)  # Fetches school for each competitor

# ✅ Good: Use join or eager loading
from sqlalchemy.orm import joinedload
competitors = Competitor.query.options(joinedload(Competitor.school)).all()
for c in competitors:
    print(c.school.name)  # Already fetched
```
