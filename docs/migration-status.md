# Database Migration Status

## Overview

This document tracks the migration from AWS DynamoDB to Supabase PostgreSQL with proper normalization into `schools`, `coaches`, and `competitors` tables.

---

## Migration Timeline

### Phase 1: ✅ Completed (Mar 2026)
**Goal**: Replace DynamoDB with Supabase PostgreSQL

- Migrated DynamoDB registrations table to Supabase Postgres
- Set up SQLAlchemy ORM with Flask-SQLAlchemy
- Created `Registration` model as direct mapping of old DynamoDB format
- Updated Flask routes to use new database
- All tests passing

### Phase 2: ✅ Completed (Apr 2026)
**Goal**: Normalize schema and separate concerns

**Completed Steps**:
1. ✅ Created `schools` table (reference table)
2. ✅ Created `coaches` table (registration type)
3. ✅ Created `competitors` table (registration type)
4. ✅ Migrated data from `registrations` → `schools`, `coaches`, `competitors`
5. ✅ Updated all routes to query new tables
6. ✅ Removed DynamoDB wrapper functions (`_reg_to_legacy()`)
7. ✅ Updated all templates to use native Python dict format
8. ✅ Removed unnecessary `.S` and `.N` suffixes from templates
9. ✅ Fuzzy-matched competitor coaches to coach records (>85% confidence)
10. ✅ All tests passing with new schema

### Phase 3: 🟡 In Progress (Apr 2026)
**Goal**: Final verification and cleanup

- [ ] Run fuzzy_match_coaches.py on production data to finalize coach linking
- [ ] Manually review unmatched coaches (logged in script output)
- [ ] Verify admin workflows (add/edit/view entries work correctly)
- [ ] Test registration flow end-to-end with new schema
- [ ] Performance testing (query times, indexes)
- [ ] Drop `registrations` table after verification

---

## Current Database Schema

### Active Tables

#### Schools
```sql
CREATE TABLE schools (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(200) NOT NULL UNIQUE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

#### Coaches
```sql
CREATE TABLE coaches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name VARCHAR(200) NOT NULL,
    email VARCHAR(200) NOT NULL,
    phone VARCHAR(20),
    school_id INTEGER NOT NULL,
    img_filename VARCHAR(200),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (school_id) REFERENCES schools(id),
    INDEX (email)
);
```

#### Competitors
```sql
CREATE TABLE competitors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name VARCHAR(200) NOT NULL,
    email VARCHAR(200) NOT NULL,
    phone VARCHAR(20),
    school_id INTEGER NOT NULL,
    coach_id INTEGER,
    parent VARCHAR(200),
    birthdate VARCHAR(10),
    age INTEGER,
    gender VARCHAR(1),
    weight NUMERIC(6,1),
    height INTEGER,
    belt_rank VARCHAR(50),
    events TEXT,
    poomsae_form VARCHAR(100),
    wc_poomsae_form VARCHAR(100),
    pair_poomsae_form VARCHAR(100),
    team_poomsae_form VARCHAR(100),
    family_poomsae_form VARCHAR(100),
    medical_contacts TEXT,
    medical_conditions JSON,
    allergies JSON,
    medications JSON,
    img_filename VARCHAR(200),
    tshirt VARCHAR(20),
    checkout_session_id VARCHAR(100),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (school_id) REFERENCES schools(id),
    FOREIGN KEY (coach_id) REFERENCES coaches(id),
    INDEX (email),
    INDEX (checkout_session_id)
);
```

#### Registration (Legacy Archive)
```sql
-- Deprecated: Do not insert new rows
-- Kept for historical lookups and data export
CREATE TABLE registrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name VARCHAR(200) NOT NULL,
    email VARCHAR(200) NOT NULL,
    phone VARCHAR(20),
    school VARCHAR(200),
    school_id INTEGER,
    reg_type VARCHAR(20) NOT NULL,
    parent VARCHAR(200),
    birthdate VARCHAR(10),
    age INTEGER,
    gender VARCHAR(1),
    weight NUMERIC(6,1),
    height INTEGER,
    coach VARCHAR(200),
    belt_rank VARCHAR(50),
    events TEXT,
    poomsae_form VARCHAR(100),
    wc_poomsae_form VARCHAR(100),
    pair_poomsae_form VARCHAR(100),
    team_poomsae_form VARCHAR(100),
    family_poomsae_form VARCHAR(100),
    medical_contacts TEXT,
    medical_conditions JSON,
    allergies JSON,
    medications JSON,
    img_filename VARCHAR(200),
    tshirt VARCHAR(20),
    checkout_session_id VARCHAR(100),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX (email),
    INDEX (checkout_session_id)
);
```

---

## Data Migration Approach

### Step 1: Create New Tables
Migrations created in Supabase:
- `schools` table with unique school names
- `coaches` table with FK to schools
- `competitors` table with FKs to schools and coaches

### Step 2: Migrate Data
```python
# Pseudocode of migration process

# Extract unique schools from old registrations
for reg in registrations:
    school_name = reg.school
    if not School.query.filter_by(name=school_name).first():
        school = School(name=school_name)
        db.session.add(school)
db.session.commit()

# Migrate coaches
for reg in registrations:
    if reg.reg_type == 'coach':
        school = School.query.filter_by(name=reg.school).first()
        coach = Coach(
            full_name=reg.full_name,
            email=reg.email,
            phone=reg.phone,
            school_id=school.id,
            img_filename=reg.img_filename
        )
        db.session.add(coach)
db.session.commit()

# Migrate competitors
for reg in registrations:
    if reg.reg_type == 'competitor':
        school = School.query.filter_by(name=reg.school).first()
        
        # Fuzzy match coach by name
        coach = fuzzy_match_coach(reg.coach, school.id)
        
        competitor = Competitor(
            full_name=reg.full_name,
            email=reg.email,
            phone=reg.phone,
            school_id=school.id,
            coach_id=coach.id if coach else None,
            parent=reg.parent,
            # ... all other fields ...
        )
        db.session.add(competitor)
db.session.commit()
```

### Step 3: Fuzzy Matching Coaches
Script: `scripts/fuzzy_match_coaches.py`

**Purpose**: Link competitor coach names to coach records

**Approach**:
- For each competitor with a coach_name but no coach_id
- Find the coach in the same school with the closest name match
- Use fuzzy string matching with >85% confidence threshold
- Log unmatched coaches for manual review

**Running the script**:
```bash
set -a && source frontend.env && set +a
uv run python scripts/fuzzy_match_coaches.py
```

**Output**:
```
Processing school: Dragon Dojo
  - Competitor: Jane Doe, coach_name: Sensei John
    → Found match: Coach #5 (Sensei John) [confidence: 0.95]
    → Updated competitor #123

Unmatched coaches (manual review required):
  - Competitor #456: coach_name: "Master X" (school: Dragon Dojo) - no match found
```

---

## Code Changes

### models.py
- Added `School`, `Coach`, `Competitor` models with proper relationships
- Kept `Registration` model for backward compatibility (archive)
- All models have `.to_dict()` method for serialization

### app.py
**Updated routes**:
- `handle_form()`: Create Competitor records (use helper to ensure school exists)
- `add_entry()`: Same, with coach linking
- `edit_entry_form()`: Query Competitor or Coach; serialize with `.to_dict()`
- `edit_entry()`: Update Competitor or Coach record
- `admin_page()`: Query both Competitor and Coach tables; combine results
- `generate_csv()`: Query Competitor table only (legacy data if needed)
- `lookup_entry()`: Search both tables; return `.to_dict()`

**Removed**:
- `_reg_to_legacy()` function (no longer needed)
- DynamoDB-specific logic

### api.py
- Added JWT auth via `@api_auth_required` decorator
- Updated endpoints to query new tables
- Return `.to_dict()` results

### templates/
All templates updated to use native Python dict format (no DynamoDB `.S`/`.N` wrappers):
- `edit.html`: Removed `.S` suffixes; use direct field access
- `export.html`: Changed from `e.beltRank.S` to `e.belt_rank`
- `form/autofill.html`: Changed from `entry.email.S` to `entry.email`
- `admin_entries.html`: Removed complex conditionals for type detection

---

## Verification Checklist

### Schema Verification
- [ ] `schools` table has correct structure (id, name unique, created_at)
- [ ] `coaches` table has FK to schools
- [ ] `competitors` table has FKs to schools and coaches
- [ ] Data correctly migrated from `registrations` table
- [ ] Foreign key constraints working (attempt to create competitor without school fails)

### Code Verification
- [ ] All routes use new `Competitor` or `Coach` models
- [ ] No code queries `registrations` table (except CSV export)
- [ ] All `.to_dict()` methods implemented and tested
- [ ] No DynamoDB-specific code remains

### Template Verification
- [ ] All templates use native dict format
- [ ] No `.S` or `.N` suffixes in template code
- [ ] Form autofill works correctly
- [ ] Admin page displays both coaches and competitors

### Functional Verification
- [ ] Registration form creates Competitor records
- [ ] Coach assignment works (nullable coach_id)
- [ ] Admin can add/edit/delete entries
- [ ] CSV export works correctly
- [ ] Lookups work for both registration types

### Performance
- [ ] Email lookup is fast (indexed column)
- [ ] Checkout session lookup is fast (indexed column)
- [ ] School lookup is fast (small reference table)

---

## Remaining Tasks (Phase 3)

### 1. Run Fuzzy Matching on Production
```bash
set -a && source frontend.env && set +a
uv run python scripts/fuzzy_match_coaches.py
```

Check output for:
- How many competitors were successfully matched to coaches
- Which competitors had unmatched coaches (need manual review)

### 2. Manual Coach Linking Review
For any unmatched coaches:
- Check `fuzzy_match_coaches.py` output for list
- Review competitor details to determine correct coach
- Either:
  - Update competitor directly in admin panel
  - Or update `scripts/fuzzy_match_coaches.py` confidence threshold and re-run

### 3. Test Admin Workflows
In browser (or via tests):
- Create a new competitor entry → verify it saves correctly
- Edit existing competitor → verify coach assignment works
- Delete competitor → verify it's removed
- View all entries → verify both competitors and coaches show

### 4. Test Registration Flow End-to-End
- User submits registration form
- Verify data saves to Competitor table
- Verify coach is correctly linked (if provided)
- Verify CSV export includes new entry

### 5. Performance Testing
- Run admin page with full dataset
- Check query times in logs
- Verify indexes are helping (email, checkout_session_id)

### 6. Drop Legacy Registration Table
Once verified:
```sql
DROP TABLE registrations;
```

---

## Rollback Plan

If issues arise, we can rollback to the old `registrations` table approach:

1. Keep `Registration` model in `models.py`
2. Create new routes that query `registrations` instead of `Competitor`/`Coach`
3. Revert template changes (re-add `.S` suffixes)
4. Restore `_reg_to_legacy()` function

This allows running both old and new code in parallel during testing.

---

## Current Branch

**Branch**: `migrate/update_db_models`

**Status**: Database models refactored; templates updated; ready for final verification

**Next PR**: Merge after Phase 3 verification + fuzzy matching completion

---

## Known Issues & Fixes

### Issue 1: Foreign Key Constraint Violations
**Problem**: Creating competitor without school fails with FK constraint error

**Solution**: Use `_get_or_create_school(name)` helper before creating:
```python
school = _get_or_create_school("Dragon Dojo")
competitor = Competitor(school_id=school.id, ...)
db.session.add(competitor)
```

### Issue 2: Competitors Without Coach Assignment
**Problem**: Some competitors don't have a coach (coach_id is NULL)

**Status**: Expected behavior. `coach_id` is nullable. Fuzzy matching attempts to link them, but some remain unmatched (need manual review).

### Issue 3: CSV Export Uses Old Schema
**Problem**: CSV export references `registrations` table

**Status**: Intentional (for now). CSV export queries `registrations` for backward compatibility. Can be updated to query `competitors` after verification.

---

## References

- **Database Schema**: See [`database-schema.md`](database-schema.md)
- **Fuzzy Matching Script**: `scripts/fuzzy_match_coaches.py`
- **Models**: `models.py`
- **Routes**: `app.py`
- **API**: `api.py`

---

## Questions?

If unsure about any aspect of the migration:
1. Check `CLAUDE.md` for project overview
2. Check [`database-schema.md`](database-schema.md) for detailed schema documentation
3. Check relevant route in `app.py` for how it queries the new schema
4. Check test in `tests/test_website.py` for how it should work
