"""Archive current competition entries to historical_entries.json in S3 configBucket.

Run this once at the end of each competition cycle, before resetting the DB for the next year.
Existing historical entries are preserved; new entries overwrite any record with the same
(full_name, email) pair so the most recent data wins.

Usage:
    uv run python scripts/archive_entries.py
"""

import json

try:
    from scripts._bootstrap import add_repo_root_to_path, confirm_db_url
except ModuleNotFoundError:
    from _bootstrap import add_repo_root_to_path, confirm_db_url

add_repo_root_to_path()

import boto3

from app import app
from models import Coach, Competitor

_HISTORICAL_KEY = "historical_entries.json"

_AUTOFILL_FIELDS = {
    "full_name",
    "email",
    "phone",
    "school",
    "birthdate",
    "age",
    "gender",
    "parent",
    "allergies",
    "medications",
    "medical_conditions",
    "medical_contacts",
    "reg_type",
    "coach",
    "belt_rank",
}


def _slim(entry: dict) -> dict:
    return {k: v for k, v in entry.items() if k in _AUTOFILL_FIELDS}


def _s3_client():
    import os

    return boto3.client("s3", region_name=os.getenv("AWS_REGION", "us-east-1"))


with app.app_context():
    confirm_db_url(app.config["SQLALCHEMY_DATABASE_URI"])
    bucket = app.config["configBucket"]
    s3 = _s3_client()

    # Load existing historical entries
    existing: dict[str, dict] = {}
    try:
        obj = s3.get_object(Bucket=bucket, Key=_HISTORICAL_KEY)
        for e in json.loads(obj["Body"].read()):
            key = (e.get("full_name", "").lower(), e.get("email", "").lower())
            existing[key] = e
        print(f"Loaded {len(existing)} existing historical entries from S3.")
    except s3.exceptions.NoSuchKey:
        print("No existing historical_entries.json found — creating new file.")
    except Exception as exc:
        raise SystemExit(f"Error: could not load existing historical archive ({exc}). Aborting to prevent data loss.") from exc

    # Collect current competition entries
    competitors = Competitor.query.all()
    coaches = Coach.query.all()
    current = [_slim(e.to_dict()) for e in competitors + coaches]
    print(f"Archiving {len(current)} entries from current competition.")

    # Merge: current entries overwrite existing on (full_name, email) collision
    for entry in current:
        key = (entry.get("full_name", "").lower(), entry.get("email", "").lower())
        existing[key] = entry

    merged = list(existing.values())
    merged.sort(key=lambda e: (e.get("full_name") or "").lower())

    s3.put_object(
        Bucket=bucket,
        Key=_HISTORICAL_KEY,
        Body=json.dumps(merged, default=str),
        ContentType="application/json",
    )
    print(f"Wrote {len(merged)} total entries to s3://{bucket}/{_HISTORICAL_KEY}")
