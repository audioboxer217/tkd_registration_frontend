try:
    from scripts._bootstrap import add_repo_root_to_path
except ModuleNotFoundError:  # Allows `python scripts/reset_db.py`
    from _bootstrap import add_repo_root_to_path

add_repo_root_to_path()

import os
import sys

app_env = (os.environ.get("APP_ENV") or os.environ.get("app_env") or "").lower()
if app_env == "prod":
    print("WARNING: APP_ENV is set to 'prod'. This will drop and recreate ALL production database tables.")
    try:
        confirm = input("Type 'yes' to confirm: ")
    except EOFError:
        print("Aborted.")
        sys.exit(1)
    if confirm.strip().lower() != "yes":
        print("Aborted.")
        sys.exit(0)

from app import app
from models import db

with app.app_context():
    db.drop_all()
    print("Database tables dropped.")
    db.create_all()
    print("Database tables created.")
