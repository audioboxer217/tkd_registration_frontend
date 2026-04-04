try:
    from scripts._bootstrap import add_repo_root_to_path, confirm_db_url
except ModuleNotFoundError:  # Allows `python scripts/reset_db.py`
    from _bootstrap import add_repo_root_to_path, confirm_db_url

add_repo_root_to_path()

import os
import sys

from app import app
from models import db

with app.app_context():
    confirm_db_url(app.config["SQLALCHEMY_DATABASE_URI"])
    db.drop_all()
    print("Database tables dropped.")
    db.create_all()
    print("Database tables created.")
