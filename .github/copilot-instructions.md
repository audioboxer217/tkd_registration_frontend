# Copilot Instructions for tkd_registration_frontend

## Project Overview

This is the **Frontend** of the TKD Registration Project — a Flask-based web application that allows users to register for Taekwondo competitions. It integrates with AWS services (DynamoDB, S3, SQS), Stripe for payments, and AWS Cognito for admin authentication via OAuth.

## Tech Stack

- **Language**: Python 3.11+
- **Web Framework**: Flask ~3.1.0
- **Package Manager**: [uv](https://github.com/astral-sh/uv)
- **Task Runner**: [just](https://github.com/casey/just) (see `justfile`)
- **Linter**: [ruff](https://github.com/astral-sh/ruff) (config in `ruff.toml`)
- **Test Framework**: pytest
- **Deployment**: [Zappa](https://github.com/Zappa/Zappa) to AWS Lambda
- **AWS Services**: DynamoDB, S3, SQS
- **External APIs**: Stripe, Google Maps

## Development Environment Setup

1. Install `uv` (bootstrapped via `just bootstrap`):
   ```bash
   just bootstrap
   ```
   This installs `uv`, the correct Python version, and all dependencies including dev.

2. Create a `frontend.env` file with required environment variables (see `README.md` for the full list).

3. Load env vars and start the Flask dev server:
   ```bash
   set -a && source frontend.env && set +a
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
uv run pytest
```

Tests live in `tests/test_website.py`. They use Flask's built-in test client and require the following environment variables to be set:
- `COMPETITION_NAME`
- `CONTACT_EMAIL`
- `EARLY_REG_DATE`
- `REG_CLOSE_DATE`
- `CONFIG_BUCKET`
- `PUBLIC_MEDIA_BUCKET`
- `STRIPE_API_KEY`

In CI, these are provided via GitHub Actions environment variables (see `.github/workflows/main.yml`).

## Project Structure

```
app.py              # Main Flask application (all routes and business logic)
templates/          # Jinja2 HTML templates
static/             # Static assets (CSS, images, etc.)
tests/              # pytest test suite
envs/               # Zappa deployment config YAML files (one per environment)
justfile            # Common developer tasks
pyproject.toml      # Project metadata and dependencies
ruff.toml           # Ruff linter configuration
```

## Architecture Notes

- All application logic lives in `app.py` (single-file Flask app pattern).
- Templates use Jinja2 and are stored in `templates/`.
- Static files (including downloaded S3 media cached locally) are in `static/`.
- AWS clients (`boto3`) are initialised at module level; AWS credentials come from environment variables or IAM roles.
- Admin routes are protected by a `@login_required` decorator that checks AWS Cognito group membership (`Admins`).
- Feature flags: `ENABLE_BADGES` and `ENABLE_ADDRESS` env vars toggle optional features.

## Coding Conventions

- Follow PEP 8 style; use `ruff` to enforce it automatically.
- Keep imports sorted and grouped (stdlib → third-party → local).
- Use environment variables (via `os.getenv`) for all configuration; never hard-code secrets.
- AWS resource names (tables, buckets, queues) are loaded from environment variables at startup.
- Flash messages use Bootstrap alert levels: `"success"`, `"danger"`, `"warning"`, `"info"`.
- Prefer descriptive variable names that match the domain (e.g., `competitor`, `division`, `reg_table`).

## Deployment

Deployments use Zappa with per-environment config files in `envs/`. Use `just` targets:

```bash
just deploy <account> <env>   # First-time deploy
just update <account> <env>   # Update existing deployment
just certify <account> <env>  # Set up custom domain TLS cert
just status <account> <env>   # Check deployment status
just logs <account> <env>     # Tail live logs
just undeploy <account> <env> # Tear down deployment
```
