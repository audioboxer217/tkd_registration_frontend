# Copilot Instructions for tkd_registration_frontend

## Project Overview

This is the **Frontend** of the TKD Registration Project — a Flask-based web application that allows users to register for Taekwondo competitions. It integrates with Supabase (PostgreSQL + Auth), Stripe for payments, and AWS services (S3, SQS) for media storage and background job queues.

## Tech Stack

- **Language**: Python 3.11+
- **Web Framework**: Flask 3.1.0
- **ORM**: SQLAlchemy 3.1+ with Flask-SQLAlchemy
- **Database**: Supabase (PostgreSQL) with Alembic migrations
- **Auth**: Supabase Auth (JWT-based)
- **Package Manager**: [uv](https://github.com/astral-sh/uv)
- **Linter**: [ruff](https://github.com/astral-sh/ruff) (130 char line limit, rules E/F)
- **Test Framework**: pytest with mocks for external services
- **Deployment**: [Zappa](https://github.com/Zappa/Zappa) to AWS Lambda
- **AWS Services**: S3 (media storage), SQS (job queue)
- **External APIs**: Stripe, Google Maps, Supabase

## Development Environment Setup

1. Install `uv`:
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   uv python install
   uv sync --all-extras --dev
   ```
   This installs the correct Python version and all dependencies including dev.

2. Environment variables are stored in `.env` at the project root. Load them before running the app or tests:
   ```bash
   set -a && source .env && set +a
   ```

3. Start the Flask dev server:
   ```bash
   flask --app app --debug run
   ```
   Or use the VSCode debugger via the existing `launch.json`.

## Linting

```bash
uv run ruff check .
uv run ruff format --check .
```

- Line length limit: **130 characters** (configured in `ruff.toml`)
- Rules enabled: `E`, `F`; rule `E402` is ignored

## Running Tests

```bash
set -a && source .env && set +a
uv run pytest
```

Tests live in `tests/test_website.py`. They use pytest with class-based organization and extensive mocking. Key patterns:

- **Setup**: Test app uses in-memory SQLite (`SQLALCHEMY_DATABASE_URI=sqlite:///:memory:`) and disables CSRF.
- **Mocking**: Mock external services (Stripe, Supabase, S3). Example helpers: `make_stripe_coupon_mock()`, `make_admin_session()`.
- **Assertions**: Check status codes, HTML content, form validation, redirect behavior, admin access control.
- **Required Env Vars**: `COMPETITION_NAME`, `CONTACT_EMAIL`, `EARLY_REG_DATE`, `REG_CLOSE_DATE`, `CONFIG_BUCKET`, `PUBLIC_MEDIA_BUCKET`, `STRIPE_API_KEY` (see `.github/workflows/main.yml` for CI values).

## Common Development Tasks

### Adding a New Registration Field
1. Add column to `Competitor` or `Coach` model in `models.py` (e.g., `new_field = db.Column(String(100))`).
2. Generate a migration: `uv run flask --app app db migrate -m "add new_field"`.
3. Review generated migration file in `migrations/versions/`.
4. Apply: `uv run flask --app app db upgrade`.
5. Update form template in `templates/form/` if user-facing.
6. Update `.to_dict()` method to include the field.
7. Add test case in `tests/test_website.py` to validate form submission.

### Querying Registrations
- **Competitors only**: `Competitor.query.all()` or `.filter_by(school_id=x)`.
- **Coaches only**: `Coach.query.all()`.
- **Both types**: Query both tables separately and combine results (see `admin_page()` route for pattern).
- **Legacy data**: Query `Registration` table only for historical lookups/CSV export. Do not insert new rows.

### Updating Templates
- Templates receive model instances; call `.to_dict()` on them if needed for complex logic.
- Use Jinja2 filters and conditionals; avoid complex Python logic in templates.
- HTMX attributes (`hx-get`, `hx-target`, `hx-swap`) trigger partial page updates. Routes must return HTML, not JSON, for HTMX endpoints.
- Test template updates in browser after running `flask --app app --debug run`.

### Adding an API Endpoint
1. Add function to `api.py` decorated with `@api_bp.route(...)` and `@api_auth_required`.
2. Query models and call `.to_dict()` on results.
3. Return JSON via `jsonify({"data": result})` or error via `{"error": msg}`, HTTP status code.
4. Add test case in `tests/test_website.py` using mocked JWT and mocked external services.
5. Document expected request/response format in PR.

## Project Structure

```
app.py              # UI Blueprint — all page and HTMX partial routes (Flask)
api.py              # API Blueprint — JSON REST endpoints at /api/v1 (protected by JWT auth)
models.py           # SQLAlchemy models (School, Coach, Competitor, Registration)
templates/          # Jinja2 HTML templates
static/             # Static assets (CSS, images, etc.)
tests/              # pytest test suite
scripts/            # Utility scripts (DB init/reset, fuzzy matching, etc.)
envs/               # Zappa deployment config YAML files (one per environment)
pyproject.toml      # Project metadata and dependencies
ruff.toml           # Ruff linter configuration (130 char line limit)
```

## Architecture Notes

### Core Structure
- **app.py** (UI Routes): Jinja2 templates, HTMX interactions, admin workflows. Protected routes use `@login_required` (Supabase JWT check).
- **api.py** (API Routes): `/api/v1/*` endpoints return JSON. Protected by `@api_auth_required` (validates Supabase JWT in Authorization header, checks role == "admin").
- **models.py** (SQLAlchemy ORM): Three active tables `schools`, `coaches`, `competitors` + legacy `registrations` archive.
- **Templates**: Bootstrap 5.3.3 + HTMX 2.0.4 for dynamic forms. Master layout in `base.html`, form sections in `templates/form/`.

### Database Schema (Recent Refactoring)
**Schools** (reference table):
- `id` (PK, autoincrement), `name` (unique), `created_at`
- Used by both coaches and competitors to enforce school relationships

**Coaches** (registration type):
- `id`, `full_name`, `email`, `phone`, `school_id` (FK), `img_filename`, `created_at`, `updated_at`
- `.to_dict()` includes `reg_type: "coach"` + competitor-specific fields as empty/null defaults

**Competitors** (registration type):
- `id`, `full_name`, `email`, `phone`, `school_id` (FK), `coach_id` (FK, nullable), parent info, age, gender, weight, height, belt rank
- Events, poomsae forms (individual/WC/pair/team/family), medical info, t-shirt size, payment status
- `.to_dict()` includes `reg_type: "competitor"`

**Registration** (legacy archive):
- **Do not insert new rows**. Used by CSV export and historical lookups. All new code queries `competitors` or `coaches` tables instead.
- Kept for backward compatibility during migration phase.

### Key Patterns

1. **Model Queries**: Always query `Competitor.query` or `Coach.query` for new data. Use `.to_dict()` to serialize for templates/API.
2. **School Resolution**: Use `_get_or_create_school(name)` helper to ensure FK constraint compliance.
3. **Response Format**: API endpoints return `{"data": [...]}` or `{"error": "msg"}` via `jsonify()`.
4. **Template Context**: Routes pass model instances directly; templates use `.` notation and Jinja2 filters. No DynamoDB format wrappers.
5. **Admin Protection**: Routes check `current_user` (Flask-Login) or JWT `role` claim; missing auth redirects to `/login`.

### Security
- **CSRF**: Enabled by default via Flask-WTF; disable in tests with `WTF_CSRF_ENABLED=False`.
- **Auth**: Supabase JWT checked on every `/api/*` call. Admin routes in `app.py` use session-based auth with role verification.
- **Secrets**: All config (DB URL, API keys, JWT secret) loaded from environment variables; never hard-coded.

## Coding Conventions

- **Style**: PEP 8 via ruff. Max line length: **130 characters** (configured in `ruff.toml`).
- **Imports**: Sorted and grouped (stdlib → third-party → local). Use `from models import Competitor, Coach` style.
- **Variables**: Prefer domain-specific names (`competitor`, `coach`, `school_name`) over generic (`reg`, `item`).
- **Configuration**: All config from environment variables via `os.getenv()`. No hard-coded secrets or resource names.
- **Flash Messages**: Use Bootstrap alert levels: `"success"`, `"danger"`, `"warning"`, `"info"`.
- **Model Serialization**: Always call `.to_dict()` on models before passing to templates or returning from API.
- **Error Handling**: Validate input at system boundaries (user submissions, external APIs). Trust internal functions and FK constraints.
- **Testing**: Mock external services (Stripe, Supabase, S3). Use in-memory SQLite for test DB. See `tests/test_website.py` for patterns.


## Known Gotchas & Migration Status

### Recent Refactoring (Apr 2026)
- **Completed**: Separated `registrations` table into `schools`, `competitors`, `coaches`.
- **Helper Functions**: Use `_get_or_create_school()` before creating competitors/coaches to ensure FK constraints are met.
- **Fuzzy Matching**: Run `scripts/fuzzy_match_coaches.py` to link competitor coach names to coach records (>85% confidence threshold). Unmatched coaches logged for manual review.
- **Legacy Data**: Old `registrations` table is an archive. CSV export queries only `competitors` table. Do not insert new rows into `registrations`.
- **Template Updates**: All templates updated to use native Python dict format (no DynamoDB `.S`/`.N` suffix wrappers).

### Common Issues
- **FK Violations**: Always create schools before competitors/coaches. Use helper functions.
- **Coach Linking**: Competitor `coach_id` is nullable. Empty means no coach assigned.
- **Events Field**: Stored as comma-separated string; split on read via `.to_dict()`.
- **Medical Info**: Stored as JSON or Text; handle None defaults when reading.

## Deployment

Deployments use Zappa with per-environment config files in `envs/`:

```bash
uv run zappa deploy <env> -s envs/<account>.yml   # First-time deploy
uv run zappa update <env> -s envs/<account>.yml   # Update existing deployment
uv run zappa certify <env> -s envs/<account>.yml  # Set up custom domain TLS cert
uv run zappa status <env> -s envs/<account>.yml   # Check deployment status
uv run zappa tail <env> -s envs/<account>.yml     # Tail live logs
uv run zappa undeploy <env> -s envs/<account>.yml # Tear down deployment
```

**Environment Config**: Store all env vars in a JSON file on S3 (configured via `remote_env` in YAML). Update this file with Supabase credentials, Stripe keys, and JWT secret when deploying to a new environment.
