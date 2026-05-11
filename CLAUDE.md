# CLAUDE.md — TKD Registration Frontend

Flask 3.1 + SQLAlchemy 3.1 + Supabase (PostgreSQL) + Pytest + Zappa (Lambda). Python 3.11+ via `uv`.

## Quick Start

```bash
uv sync --all-extras --dev
set -a && source .env && set +a
flask --app app --debug run        # Development server
uv run pytest                      # Run tests (requires .env to be sourced)
uv run ruff check .                # Lint (130 char line limit)
```

> **Environment variables are always in `.env`** at the project root. Always source it before running the app or tests: `set -a && source .env && set +a`

## Project Layout

```
app.py              UI routes (pages, HTMX, admin)
api.py              REST API endpoints (/api/v1/*)
models.py           SQLAlchemy ORM (School, Coach, Competitor, Registration)
templates/          Jinja2 + Bootstrap 5.3 + HTMX 2.0
tests/              pytest suite (class-based, extensive mocking)
scripts/            DB utilities, fuzzy matching, migrations
envs/               Zappa deployment configs
docs/               Reference documentation (see below)
```

## Architecture

**Core flow**: Form submission → `app.py` route validates → SQLAlchemy persists to Supabase → Jinja2 renders response

**Three blueprints**:
- **app.py**: UI routes with Supabase session auth (`@login_required`)
- **api.py**: JSON endpoints at `/api/v1/*` with JWT auth (`@api_auth_required`)
- **models.py**: `schools` (reference), `coaches`, `competitors`, `registrations` (legacy archive)

**Frontend**: Jinja2 templates, Bootstrap 5.3, HTMX 2.0 for dynamic forms

## Key Patterns

- Always call `.to_dict()` on models before passing to templates/API
- Use `_get_or_create_school(name)` helper before creating competitors/coaches (FK safety)
- Query `Competitor` or `Coach` tables; **do not insert** to `registrations` (archive only)
- Style: PEP 8 via ruff (130 char max), domain-specific names (`competitor` not `reg`), env vars only (no hardcoded secrets)
- HTMX routes return HTML not JSON

---

## Reference Documentation

Detailed guidance for specific tasks:

- **[Database Schema](docs/database-schema.md)** — Table structures, relationships, field types, adding fields, common queries
- **[Testing Guide](docs/testing-guide.md)** — pytest setup, mocking patterns, test examples, debugging
- **[API Patterns](docs/api-patterns.md)** — Request/response format, endpoint examples (GET/POST/PUT/DELETE), validation
- **[Migration Status](docs/migration-status.md)** — Current schema, phase status, verification checklist

## Deployment

Zappa to AWS Lambda with per-environment configs:

```bash
uv run zappa deploy <env> -s envs/<account>.yml    # First deploy
uv run zappa update <env> -s envs/<account>.yml    # Update
uv run zappa status <env> -s envs/<account>.yml    # Check status
uv run zappa tail <env> -s envs/<account>.yml      # View logs
```

Env vars stored in S3 JSON file (configured via `remote_env` in Zappa YAML).

## Git Conventions

- **main**: Production-ready
- **feature/**: New features
- **fix/**: Bug fixes
- **refactor/**: Code cleanup
- **migrate/**: Schema/migration work
- Commit messages: Explain the WHY, not just WHAT
- PRs: Require passing tests + linting before merge

## When You Get Stuck

1. **Adding a field?** → [`docs/database-schema.md`](docs/database-schema.md#adding-a-new-registration-field)
2. **Writing a test?** → [`docs/testing-guide.md`](docs/testing-guide.md#common-test-patterns)
3. **Adding an API endpoint?** → [`docs/api-patterns.md`](docs/api-patterns.md#endpoint-examples)
4. **Confused about migration?** → [`docs/migration-status.md`](docs/migration-status.md)
5. **Template issue?** → Check `templates/base.html` and `templates/form/`
6. **Field behavior?** → Search `models.py` + check `docs/database-schema.md`

## Key Context

**Current Branch**: `migrate/update_db_models` — Database refactored, templates updated, ready for verification

**Recent Changes** (Apr 2026): Separated monolithic `registrations` table into `schools`, `coaches`, `competitors` with proper normalization. All routes updated, templates cleaned up, fuzzy coach-matching in progress.

**Next Steps**: Run `fuzzy_match_coaches.py`, verify admin workflows, test end-to-end, drop legacy `registrations` table.

## External Resources

- Flask: https://flask.palletsprojects.com/
- SQLAlchemy: https://docs.sqlalchemy.org/
- Supabase: https://supabase.com/docs
- Pytest: https://docs.pytest.org/
- HTMX: https://htmx.org/docs/
- Bootstrap 5: https://getbootstrap.com/docs/5.3/

---

**Owner**: Scott Eppler | **Last Updated**: April 2026
