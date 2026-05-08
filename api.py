import json
import os
from datetime import datetime
from functools import wraps
from typing import Union

import boto3
import jwt
import stripe
from apiflask import APIBlueprint, Schema
from apiflask.fields import Float, Integer, List, Nested, String
from apiflask.validators import OneOf
from flask import current_app, g, jsonify, request

from models import Coach, Competitor, School, db

RegistrationRecord = Union[Competitor, Coach]

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
    payment_intent = String()
    status = String()
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
    status = String()


class RegistrationCheckoutData(Schema):
    id = Integer()
    checkout_url = String()


class RegistrationCreateOut(Schema):
    data = Nested(lambda: RegistrationCheckoutData())


class RegistrationIn(Schema):
    reg_type = String(validate=OneOf(["competitor", "coach"]), required=True)
    full_name = String(required=True)
    email = String(required=True)
    phone = String()
    school = String(required=True)
    parent = String()
    birthdate = String()
    age = Integer()
    gender = String(validate=OneOf(["M", "F"]))
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
    line_items = List(Nested(lambda: LineItemIn()))


class LineItemIn(Schema):
    price = String(required=True)
    quantity = Integer(required=True)


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
    events = List(String())
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
    """Annotate a list of registration dicts with age_group and weight_class.

    Entries missing age or weight will have age_group/weight_class set to "UNKNOWN".
    If config_bucket is not configured, returns entries unchanged (no weight class annotation).
    """
    if not config_bucket:
        return entries

    try:
        weight_classes = json.load(_s3().get_object(Bucket=config_bucket, Key="weight_classes.json")["Body"])
    except Exception:
        return entries

    updated = []
    for entry in entries:
        age = entry.get("age")
        weight = entry.get("weight")
        gender = entry.get("gender")
        if age is None or weight is None or gender is None:
            entry["age_group"] = "UNKNOWN"
            entry["weight_class"] = "UNKNOWN"
            updated.append(entry)
            continue
        age_group = get_age_group(age)
        entry["age_group"] = age_group
        gender_key = "female" if gender == "F" else "male" if gender == "M" else gender
        weight_class_ranges = weight_classes.get(age_group, {}).get(gender_key, {})
        entry["weight_class"] = next(
            (
                wc
                for wc, weights in weight_class_ranges.items()
                if float(weight) >= float(weights[0]) and float(weight) < float(weights[1])
            ),
            "UNKNOWN",
        )
        updated.append(entry)
    return updated


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------


def _get_or_create_school(school_name: str):
    if not school_name:
        return None
    school = School.query.filter_by(name=school_name).first()
    if school is None:
        school = School(name=school_name)
        db.session.add(school)
        db.session.flush()
    return school


def _find_reg_by_checkout_session(session_id):
    return Competitor.query.filter_by(checkout_session_id=session_id).first()


def _send_confirmation_email(reg: RegistrationRecord) -> RegistrationRecord:
    """Placeholder for registration confirmation email dispatch.

    TODO: Integrate with backend email service in a follow-up phase.
    """
    return reg


def _check_school(reg: RegistrationRecord) -> RegistrationRecord:
    """Placeholder for school-level post-registration checks.

    TODO: Add school-level validation/workflow hooks in a follow-up phase.
    """
    return reg


@api_bp.route("/registrations", methods=["POST"])
@api_bp.input(RegistrationIn, arg_name="body")
def create_registration(body):
    school = _get_or_create_school(body.get("school"))
    if school is None:
        return {"error": "School is required"}, 422

    try:
        default_unit_amount = int(os.getenv("STRIPE_DEFAULT_UNIT_AMOUNT", "5000"))
    except ValueError:
        return {"error": "Invalid STRIPE_DEFAULT_UNIT_AMOUNT configuration"}, 500
    if default_unit_amount <= 0:
        return {"error": "Invalid STRIPE_DEFAULT_UNIT_AMOUNT configuration"}, 500
    reg_type_title = body["reg_type"].capitalize()
    line_items = body.get("line_items") or [
        {
            "price_data": {
                "currency": "usd",
                "product_data": {"name": f"{reg_type_title} Registration"},
                "unit_amount": default_unit_amount,
            },
            "quantity": 1,
        }
    ]

    if body["reg_type"] == "competitor":
        reg = Competitor(
            full_name=body["full_name"],
            email=body["email"],
            phone=body.get("phone"),
            school_id=school.id,
            parent=body.get("parent"),
            birthdate=body.get("birthdate"),
            age=body.get("age"),
            gender=body.get("gender"),
            weight=body.get("weight"),
            height=body.get("height"),
            belt_rank=body.get("belt_rank"),
            events=",".join(body.get("events", [])),
            poomsae_form=body.get("poomsae_form"),
            wc_poomsae_form=body.get("wc_poomsae_form"),
            pair_poomsae_form=body.get("pair_poomsae_form"),
            team_poomsae_form=body.get("team_poomsae_form"),
            family_poomsae_form=body.get("family_poomsae_form"),
            status="pending",
        )
    else:
        reg = Coach(
            full_name=body["full_name"],
            email=body["email"],
            phone=body.get("phone"),
            school_id=school.id,
        )

    db.session.add(reg)
    db.session.flush()

    try:
        base_url = request.url_root.rstrip("/")
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=line_items,
            mode="payment",
            success_url=f"{base_url}/success?reg_id={reg.id}",
            cancel_url=f"{base_url}/cancel",
            metadata={"registration_id": str(reg.id)},
        )
        reg.checkout_session_id = session.id
        db.session.commit()
    except stripe.error.StripeError:
        current_app.logger.exception("Stripe API error while creating checkout session")
        db.session.rollback()
        return {"error": "Unable to create checkout session. Please verify payment configuration or try again later."}, 502
    except Exception:
        current_app.logger.exception("Unexpected error while creating checkout session")
        db.session.rollback()
        return {"error": "Unable to create checkout session. Please verify payment configuration or try again later."}, 502

    return {"data": {"checkout_url": session.url, "id": reg.id}}, 201


@api_bp.route("/webhooks/stripe", methods=["POST"])
def stripe_webhook():
    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature")
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    if not webhook_secret:
        return jsonify({"error": "Server misconfiguration"}), 500

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except ValueError:
        current_app.logger.exception("Malformed Stripe webhook payload")
        return jsonify({"error": "Invalid payload or signature"}), 400
    except stripe.error.SignatureVerificationError:
        current_app.logger.exception("Invalid Stripe webhook signature")
        return jsonify({"error": "Invalid payload or signature"}), 400

    session = event["data"]["object"]
    session_id = session.get("id")
    reg = _find_reg_by_checkout_session(session_id)
    if reg is None:
        return jsonify({"status": "ok"}), 200

    if event["type"] == "checkout.session.completed":
        reg.status = "complete"
        reg.payment_intent = session.get("payment_intent")
        db.session.commit()
        try:
            _send_confirmation_email(reg)
            _check_school(reg)
        except Exception:
            current_app.logger.exception("Post-checkout completion actions failed for registration %s", reg.id)
    elif event["type"] == "checkout.session.expired":
        reg.status = "failed"
        db.session.commit()

    return jsonify({"status": "ok"}), 200


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
    try:
        reg_id = int(registration_id)
    except (ValueError, TypeError):
        return jsonify({"error": "Not found"}), 404

    reg = db.session.get(Competitor, reg_id)
    reg_type = "competitor"
    if reg is None:
        reg = db.session.get(Coach, reg_id)
        reg_type = "coach"
    if reg is None:
        return jsonify({"error": "Not found"}), 404

    return jsonify(
        {
            "data": {
                "id": str(reg.id),
                "full_name": reg.full_name,
                "reg_type": reg_type,
                "checkout_session_id": reg.checkout_session_id,
                "status": getattr(reg, "status", None),
            }
        }
    )


# ---------------------------------------------------------------------------
# Admin endpoints (auth required)
# ---------------------------------------------------------------------------


def _get_registration_by_id(registration_id):
    """Look up a registration by integer ID from Competitor or Coach tables.

    Returns (record, reg_type) tuple, or (None, None) if not found.
    """
    try:
        reg_id = int(registration_id)
    except (ValueError, TypeError):
        return None, None

    reg = db.session.get(Competitor, reg_id)
    if reg is not None:
        return reg, "competitor"
    reg = db.session.get(Coach, reg_id)
    if reg is not None:
        return reg, "coach"
    return None, None


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
    reg, _ = _get_registration_by_id(registration_id)
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
    reg, _ = _get_registration_by_id(registration_id)
    if reg is None:
        return jsonify({"error": "Not found"}), 404

    for field, value in body.items():
        # Normalize events: accept list or string, persist as comma-separated string
        if field == "events" and isinstance(value, list):
            value = ",".join(value)
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
    reg, _ = _get_registration_by_id(registration_id)
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
