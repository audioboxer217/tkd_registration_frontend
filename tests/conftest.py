"""Shared pytest configuration for all tests in this package.

DATABASE_URL must be set before any test module imports the Flask app so that
the conditional ``app = create_app()`` at the bottom of app.py is executed.
This is required by the backend-scripts (generate_*.py / get_*.py) which all
do ``from app import app`` at module level.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
