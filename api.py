import json
import os
from datetime import datetime
from functools import wraps

import boto3
import jwt
import stripe
from flask import Blueprint, g, jsonify, request

from models import Registration, Competitor, Coach, School, db

api_bp = Blueprint("api", __name__, url_prefix="/api/v1")

stripe.api_key = os.getenv("STRIPE_API_KEY")


def _s3():
    return boto3.client("s3", region_name=os.getenv("AWS_REGION", "us-east-1"))


def _sqs():
    return boto3.client("sqs", region_name=os.getenv("AWS_REGION", "us-east-1"))


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def api_auth_required(f):
    """Decorator that validates a Supabase JWT from the Authorization header.

    Sets g.current_user on success. Checks app_metadata.role == 'admin'.
    """

    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Unauthorized"}), 401

        token = auth_header.removeprefix("Bearer ").strip()
        jwt_secret = os.getenv("SUPABASE_JWT_SECRET")
        if not jwt_secret:
            return jsonify({"error": "Server misconfiguration"}), 500

        try:
            payload = jwt.decode(
                token,
                jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
            )
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token"}), 401

        role = (payload.get("app_metadata") or {}).get("role")
        if role != "admin":
            return jsonify({"error": "Forbidden"}), 403

        g.current_user = payload
        return f(*args, **kwargs)

    return decorated


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------


@api_bp.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found"}), 404


@api_bp.errorhandler(422)
def unprocessable(e):
    return jsonify({"error": str(e)}), 422


# ---------------------------------------------------------------------------
# Helper: age group and weight class (shared business logic)
# ---------------------------------------------------------------------------


def get_age_group(age):
    age_groups = {
        "too_young": list(range(0, 4)),
        "dragon": [4, 5, 6, 7],
        "tiger": [8, 9],
        "youth": [10, 11],
        "cadet": [12, 13, 14],
        "junior": [15, 16],
        "senior": list(range(17, 33)),
        "ultra": list(range(33, 100)),
    }
    return next((group for group, ages in age_groups.items() if int(age) in ages), "too_old")


def set_weight_class(entries, config_bucket):
    """Annotate a list of registration dicts with age_group and weight_class."""
    weight_classes = json.load(_s3().get_object(Bucket=config_bucket, Key="weight_classes.json")["Body"])
    updated = []
    for entry in entries:
        age_group = get_age_group(entry["age"])
        entry["age_group"] = age_group
        gender = "female" if entry["gender"] == "F" else "male" if entry["gender"] == "M" else entry["gender"]
        weight_class_ranges = weight_classes.get(age_group, {}).get(gender, {})
        entry["weight_class"] = next(
            (
                wc
                for wc, weights in weight_class_ranges.items()
                if float(entry["weight"]) >= float(weights[0]) and float(entry["weight"]) < float(weights[1])
            ),
            "UNKNOWN",
        )
        updated.append(entry)
    return updated


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------


@api_bp.route("/entries", methods=["GET"])
def entries_api():
    """Return all competitor and coach registrations as JSON."""
    config_bucket = os.getenv("CONFIG_BUCKET")

    competitors = Competitor.query.all()
    coaches = Coach.query.all()

    competitor_dicts = [c.to_dict() for c in competitors]
    competitor_dicts = set_weight_class(competitor_dicts, config_bucket)

    coach_dicts = [c.to_dict() for c in coaches]

    return jsonify({"data": competitor_dicts + coach_dicts})


@api_bp.route("/registrations/<string:registration_id>/status", methods=["GET"])
def registration_status(registration_id):
    """Check registration and payment status by ID."""
    reg = db.session.get(Registration, registration_id)
    if reg is None:
        return jsonify({"error": "Not found"}), 404
    return jsonify(
        {
            "data": {
                "id": str(reg.id),
                "full_name": reg.full_name,
                "reg_type": reg.reg_type,
                "checkout_session_id": reg.checkout_session_id,
            }
        }
    )


# ---------------------------------------------------------------------------
# Admin endpoints (auth required)
# ---------------------------------------------------------------------------


@api_bp.route("/admin/registrations", methods=["GET"])
@api_auth_required
def admin_list_registrations():
    """List all registrations with optional reg_type filter."""
    reg_type = request.args.get("reg_type")

    results = []

    if not reg_type or reg_type == "competitor":
        competitors = Competitor.query.order_by(Competitor.created_at.desc()).all()
        results.extend([c.to_dict() for c in competitors])

    if not reg_type or reg_type == "coach":
        coaches = Coach.query.order_by(Coach.created_at.desc()).all()
        results.extend([c.to_dict() for c in coaches])

    # Sort all results by created_at descending
    results.sort(key=lambda x: x["created_at"], reverse=True)

    return jsonify({"data": results})


@api_bp.route("/admin/registrations/<string:registration_id>", methods=["GET"])
@api_auth_required
def admin_get_registration(registration_id):
    # Try competitor first
    competitor = db.session.get(Competitor, int(registration_id))
    if competitor:
        return jsonify({"data": competitor.to_dict()})

    # Try coach
    coach = db.session.get(Coach, int(registration_id))
    if coach:
        return jsonify({"data": coach.to_dict()})

    return jsonify({"error": "Not found"}), 404


@api_bp.route("/admin/registrations/<string:registration_id>", methods=["PUT"])
@api_auth_required
def admin_update_registration(registration_id):
    reg_id = int(registration_id)

    # Try competitor first
    competitor = db.session.get(Competitor, reg_id)
    if competitor:
        data = request.get_json(silent=True) or {}
        updatable_fields = [
            "full_name", "email", "phone", "school_id", "coach_id", "parent",
            "birthdate", "age", "gender", "weight", "height", "belt_rank", "events",
            "poomsae_form", "wc_poomsae_form", "pair_poomsae_form",
            "team_poomsae_form", "family_poomsae_form",
        ]
        for field in updatable_fields:
            if field in data:
                setattr(competitor, field, data[field])
        competitor.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify({"data": competitor.to_dict()})

    # Try coach
    coach = db.session.get(Coach, reg_id)
    if coach:
        data = request.get_json(silent=True) or {}
        updatable_fields = ["full_name", "email", "phone", "school_id"]
        for field in updatable_fields:
            if field in data:
                setattr(coach, field, data[field])
        coach.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify({"data": coach.to_dict()})

    return jsonify({"error": "Not found"}), 404


@api_bp.route("/admin/registrations/<string:registration_id>", methods=["DELETE"])
@api_auth_required
def admin_delete_registration(registration_id):
    reg_id = int(registration_id)

    # Try competitor first
    competitor = db.session.get(Competitor, reg_id)
    if competitor:
        db.session.delete(competitor)
        db.session.commit()
        return jsonify({"data": {"deleted": str(registration_id)}}), 200

    # Try coach
    coach = db.session.get(Coach, reg_id)
    if coach:
        db.session.delete(coach)
        db.session.commit()
        return jsonify({"data": {"deleted": str(registration_id)}}), 200

    return jsonify({"error": "Not found"}), 404


@api_bp.route("/admin/upload/<string:resource>", methods=["POST"])
@api_auth_required
def upload_item(resource):
    """Upload schedule, booklet, or update school list in S3."""
    config_bucket = os.getenv("CONFIG_BUCKET")
    media_bucket = os.getenv("PUBLIC_MEDIA_BUCKET")

    if resource in ("schedule", "booklet"):
        upload_conf = {
            "schedule": {"bucket": config_bucket, "filename": "schedule.png"},
            "booklet": {"bucket": media_bucket, "filename": "information_booklet.pdf"},
        }
        upload_file = request.files.get("uploadFile")
        if not upload_file:
            return jsonify({"error": "No file provided"}), 422
        conf = upload_conf[resource]
        _s3().upload_fileobj(upload_file, conf["bucket"], conf["filename"])
        return jsonify({"data": {"message": f"{resource.capitalize()} updated successfully"}}), 200

    elif resource == "schools":
        schools = list(set((request.form.get("schoolList") or "").split(",")))
        if "REMOVE" in schools:
            schools.remove("REMOVE")
        schools.sort()
        _s3().put_object(
            Bucket=config_bucket,
            Key="schools.json",
            Body=json.dumps(schools),
            ContentType="application/json",
        )
        return jsonify({"data": {"message": "Schools updated successfully"}}), 200

    return jsonify({"error": "Unknown resource"}), 404
