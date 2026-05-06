# Database Refactoring: Competitor & Coach Separation - Implementation Complete

## Changes Made

### 1. Database Migrations (Completed)
- ✅ Migration 1: Created `schools` table with id, name (unique, not null)
- ✅ Migration 2: Added `school_id` foreign key to `registrations` table
- ✅ Migration 3: Created `competitors` and `coaches` tables with appropriate columns
- ✅ Migration 4: Migrated data from `registrations` to new tables based on `reg_type`

### 2. SQLAlchemy Models (`models.py`)
- ✅ Added `School` model with relationships to Competitor and Coach
- ✅ Added `Coach` model with school_id FK and to_dict() method
- ✅ Added `Competitor` model with school_id FK, coach_id FK (nullable), and updated to_dict()
- ✅ Updated `Registration` model with school_id column (marked as legacy/archive)

### 3. API Endpoints (`api.py`)
- ✅ Updated `/api/v1/entries` to query both `Competitor` and `Coach` tables
- ✅ Updated `/api/v1/admin/registrations` to handle both new tables
- ✅ Updated `/api/v1/admin/registrations/<id>` GET/PUT/DELETE to try competitor first, then coach

### 4. Application Logic (`app.py`)
- ✅ Added helper functions:
  - `_get_or_create_school()`: Ensures school exists before creating registration
  - `_get_or_create_coach()`: Looks up coach by name and school_id
- ✅ Updated `_reg_to_legacy()`: Converts Competitor/Coach/Registration to legacy dict format
- ✅ Updated `handle_form()`: Uses new models, creates/looks up school and coach
- ✅ Updated `add_entry()`: Admin function updated for new models
- ✅ Updated `edit_entry_form()` and `edit_entry()`: Try competitor first, then coach
- ✅ Updated `admin_page()`: Query both tables and combine results
- ✅ Updated `generate_csv()`: Query only competitors
- ✅ Updated `lookup_entry()`: Query both Competitor and Coach tables

### 5. Data Migration Script
- ✅ Created `scripts/fuzzy_match_coaches.py` for fuzzy matching competitor coaches to coach records

## Key Design Decisions

1. **Backward Compatibility**: Used `_reg_to_legacy()` to convert new models to legacy DynamoDB dict format, so templates continue working unchanged
2. **Coach Lookup**: Coaches are looked up by name + school_id; if not found, coach_id remains NULL
3. **School Creation**: Schools are auto-created if they don't exist (from "unlisted" entries)
4. **Registration Archive**: Old `Registration` table kept as historical archive; new registrations use Competitor/Coach

## Next Steps

1. Run fuzzy_match_coaches.py to link competitors to coach records
2. Test registration flow (competitor + coach)
3. Test admin pages (add, edit, view entries)
4. Test export (CSV)
5. Verify all relationships are intact

## Files Modified

- `models.py` - Added School, Coach, Competitor models
- `api.py` - Updated all endpoints for new models
- `app.py` - Updated form handlers and admin logic
- `scripts/fuzzy_match_coaches.py` - New script for coach matching

## Database Tables

### schools
- id (PK), name (unique, not null), created_at

### coaches
- id (PK), full_name, email, phone, school_id (FK), img_filename, created_at, updated_at

### competitors
- id (PK), full_name, email, phone, school_id (FK), coach_id (FK, nullable), parent, birthdate, age, gender, weight, height, belt_rank, events, poomsae_form fields, medical fields, img_filename, tshirt, checkout_session_id, created_at, updated_at

### registrations (legacy archive)
- All original fields + school_id (FK)
