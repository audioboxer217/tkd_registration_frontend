import json
import os
from datetime import datetime
from functools import wraps

import boto3
import jwt
import stripe
from apiflask import APIBlueprint, Schema
from apiflask.fields import Float, Integer, List, Nested, String
from apiflask.validators import OneOf
from flask import g, jsonify, request

from models import Coach, Competitor, Registration, School, db

api_bp = APIBlueprint("api", __name__, url_prefix="/api/v1", tag="Registrations")

stripe.api_key = os.getenv("STRIPE_API_KEY")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class RegistrationOut(Schema):
    id = Integer()
    full_name = String()
    email = String()
    phone = String()
    school = String()
    reg_type = String()
    parent = String()
    birthdate = String()
    age = Integer()
    gender = String()
    weight = Float()
    height = Integer()
    coach = String()
    belt_rank = String()
    events = List(String())
    poomsae_form = String()
    wc_poomsae_form = String()
    pair_poomsae_form = String()
    team_poomsae_form = String()
    family_poomsae_form = String()
    img_filename = String()
    tshirt = String()
    checkout_session_id = String()
    created_at = String()
    updated_at = String()


class RegistrationListOut(Schema):
    data = List(Nested(RegistrationOut))


class RegistrationDetailOut(Schema):
    data = Nested(RegistrationOut)


class RegistrationStatusOut(Schema):
    data = Nested(lambda: RegistrationStatusData())


class RegistrationStatusData(Schema):
    id = String()
    full_name = String()
    reg_type = String()
    checkout_session_id = String()


class RegistrationUpdateIn(Schema):
    full_name = String()
    email = String()
    phone = String()
    school = String()
    parent = String()
    birthdate = String()
    age = Integer()
    gender = String(validate=OneOf(["M", "F"]))
    weight = Float()
    height = Integer()
    coach = String()
    belt_rank = String()
    events = String()
    poomsae_form = String()
    wc_poomsae_form = String()
    pair_poomsae_form = String()
    team_poomsae_form = String()
    family_poomsae_form = String()


class DeletedOut(Schema):
    data = Nested(lambda: DeletedData())


class DeletedData(Schema):
    deleted = String()


class MessageOut(Schema):
    data = Nested(lambda: MessageData())


class MessageData(Schema):
    message = String()


class ErrorOut(Schema):
    error = String()


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
@api_bp.output(RegistrationListOut, description="All competitor and coach registrations")
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
@api_bp.output(RegistrationStatusOut, description="Registration and payment status")
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
@api_bp.doc(security=[{"BearerAuth": []}])
@api_auth_required
@api_bp.output(RegistrationListOut, description="All registrations")
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
@api_bp.doc(security=[{"BearerAuth": []}])
@api_auth_required
@api_bp.output(RegistrationDetailOut, description="Registration detail")
def admin_get_registration(registration_id):
    """Get a single registration by ID."""
    reg = db.session.get(Registration, registration_id)
    if reg is None:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"data": reg.to_dict()})


@api_bp.route("/admin/registrations/<string:registration_id>", methods=["PUT"])
@api_bp.doc(security=[{"BearerAuth": []}])
@api_auth_required
@api_bp.input(RegistrationUpdateIn, arg_name="body")
@api_bp.output(RegistrationDetailOut, description="Updated registration")
def admin_update_registration(registration_id, body):
    """Update editable fields on a registration."""
    reg = db.session.get(Registration, registration_id)
    if reg is None:
        return jsonify({"error": "Not found"}), 404

    for field, value in body.items():
        setattr(reg, field, value)
    reg.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"data": reg.to_dict()})


@api_bp.route("/admin/registrations/<string:registration_id>", methods=["DELETE"])
@api_bp.doc(security=[{"BearerAuth": []}])
@api_auth_required
@api_bp.output(DeletedOut, description="Deleted registration ID")
def admin_delete_registration(registration_id):
    """Delete a registration by ID."""
    reg = db.session.get(Registration, registration_id)
    if reg is None:
        return jsonify({"error": "Not found"}), 404
    db.session.delete(reg)
    db.session.commit()
    return jsonify({"data": {"deleted": str(registration_id)}}), 200


@api_bp.route("/admin/upload/<string:resource>", methods=["POST"])
@api_bp.doc(security=[{"BearerAuth": []}])
@api_auth_required
@api_bp.output(MessageOut, description="Upload result message")
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
        schools_list = list(set((request.form.get("schoolList") or "").split(",")))
        if "REMOVE" in schools_list:
            schools_list.remove("REMOVE")

        # Sync schools to database
        # First, get all school names that should exist
        schools = []
        for school_name in schools_list:
            school_name = school_name.strip()
            if school_name:
                existing = School.query.filter_by(name=school_name).first()
                if not existing:
                    existing = School(name=school_name)
                    db.session.add(existing)
                schools.append(existing)

        db.session.commit()

        # Keep S3 upload for backwards compatibility
        schools_list.sort()
        _s3().put_object(
            Bucket=config_bucket,
            Key="schools.json",
            Body=json.dumps(schools_list),
            ContentType="application/json",
        )
        return jsonify({"data": {"message": "Schools updated successfully"}}), 200

    return jsonify({"error": "Unknown resource"}), 404
