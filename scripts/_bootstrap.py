"""Shared path bootstrap for repository management scripts."""

import os
import sys
from pathlib import Path


def add_repo_root_to_path() -> None:
    """Ensure repository root is importable when running scripts from scripts/."""
    repo_root = Path(__file__).resolve().parent.parent
    root_str = str(repo_root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


def confirm_db_url() -> None:
    """Print the DATABASE_URL being affected and require confirmation if it is not SQLite."""
    default_db = Path(__file__).resolve().parent.parent / "instance" / "app.db"
    db_url = os.environ.get("DATABASE_URL", f"sqlite:///{default_db}")
    print(f"DATABASE_URL: {db_url}")
    if not db_url.startswith("sqlite"):
        try:
            confirm = input("Non-SQLite database detected. Type 'yes' to continue: ")
        except EOFError:
            print("Aborted.")
            sys.exit(1)
        if confirm.strip().lower() != "yes":
            print("Aborted.")
            sys.exit(0)
