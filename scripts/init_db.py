try:
    from scripts._bootstrap import add_repo_root_to_path
except ModuleNotFoundError:  # Allows `python scripts/init_db.py`
    from _bootstrap import add_repo_root_to_path

add_repo_root_to_path()

from app import app
from models import db

with app.app_context():
    db.create_all()
    print("Database tables created.")
