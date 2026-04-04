"""Shared path bootstrap for repository management scripts."""

import sys
from pathlib import Path


def add_repo_root_to_path() -> None:
    """Ensure repository root is importable when running scripts from scripts/."""
    repo_root = Path(__file__).resolve().parent.parent
    root_str = str(repo_root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
