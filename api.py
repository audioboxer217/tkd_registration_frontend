import json
import os
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr
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


class DuplicateRegistrationError(Exception):
    """Raised when a registration already exists for the same name/school/type."""


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
    checkout_session_id = String(allow_none=True)
    status = String(allow_none=True)


class RegistrationCreatedData(Schema):
    id = Integer()


class RegistrationCreateOut(Schema):
    data = Nested(lambda: RegistrationCreatedData())


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
    tshirt = String()
    medical_contacts = String()
    medical_conditions = List(String())
    allergies = List(String())
    medications = List(String())
    img_filename = String()


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


def _err(description: str) -> dict:
    """Build an OpenAPI response object linking ErrorOut as the response schema."""
    return {"description": description, "content": {"application/json": {"schema": ErrorOut}}}


def _s3():
    return boto3.client("s3", region_name=os.getenv("AWS_REGION", "us-east-1"))


def _sqs():
    return boto3.client("sqs", region_name=os.getenv("AWS_REGION", "us-east-1"))


def _err_response(message: str, status: int):
    """Return a Flask Response with an error JSON body, bypassing the @output schema."""
    resp = jsonify({"error": message})
    resp.status_code = status
    return resp


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
    description = getattr(e, "description", "Validation error")
    if isinstance(description, (dict, list)):
        error = json.dumps(description, sort_keys=True)
    else:
        error = str(description or "Validation error")
    return jsonify({"error": error}), 422


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
        return None, None
    school = School.query.filter_by(name=school_name).first()
    new_school_name = None
    if school is None:
        school = School(name=school_name)
        db.session.add(school)
        db.session.flush()
        new_school_name = school_name
    return school, new_school_name


def _find_reg_by_checkout_session(session_id):
    return Competitor.query.filter_by(checkout_session_id=session_id).first()


def _get_coach_by_name_and_school(coach_name: str, school_id: int):
    """Look up a coach by exact name and school_id. Returns None if not found."""
    if not coach_name or not school_id:
        return None
    return Coach.query.filter_by(full_name=coach_name, school_id=school_id).first()


def _check_duplicate(full_name: str, school_id: int, reg_type: str) -> None:
    model = Competitor if reg_type == "competitor" else Coach
    existing = model.query.filter_by(full_name=full_name, school_id=school_id).first()
    if existing:
        raise DuplicateRegistrationError(f"Duplicate registration for {full_name}")


def _send_admin_school_alert(school_name: str) -> None:
    """Send an unknown-school alert email directly to the admin via SMTP."""
    comp_name = os.environ.get("COMPETITION_NAME", "")
    email_server = os.environ.get("EMAIL_SERVER")
    email_port = os.environ.get("EMAIL_PORT")
    email_sender = os.environ.get("FROM_EMAIL")
    email_password = os.environ.get("EMAIL_PASSWD")
    admin_email = os.environ.get("ADMIN_EMAIL")

    if not all([email_server, email_port, email_sender, email_password, admin_email]):
        current_app.logger.warning("Skipping unknown school alert; email server env vars are not fully configured")
        return

    em = EmailMessage()
    em["From"] = formataddr((comp_name, email_sender))
    em["To"] = formataddr(("Competition Admin", admin_email))
    em["Subject"] = f"Entry added with unknown school - {school_name}"
    em.set_content(f"New School Added: {school_name}")

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(email_server, int(email_port), context=context) as smtp:
            smtp.login(email_sender, email_password)
            smtp.sendmail(email_sender, admin_email, em.as_string())
        current_app.logger.info("Unknown school alert sent to admin for new school: %s", school_name)
    except (smtplib.SMTPException, ssl.SSLError, OSError):
        current_app.logger.exception("Failed to send unknown school alert for school: %s", school_name)
    return


def send_admin_school_alert(school_name: str) -> None:
    """Public wrapper used by callers outside this module for school-alert sending."""
    _send_admin_school_alert(school_name)


def _send_confirmation_email(reg: RegistrationRecord) -> RegistrationRecord:
    """Send a confirmation email directly via SMTP using SQLAlchemy model fields."""
    comp_year = os.environ.get("COMPETITION_YEAR", "")
    comp_name = os.environ.get("COMPETITION_NAME", "")
    email_server = os.environ.get("EMAIL_SERVER")
    email_port = os.environ.get("EMAIL_PORT")
    email_sender = os.environ.get("FROM_EMAIL")
    email_password = os.environ.get("EMAIL_PASSWD")
    contact_email = os.environ.get("CONTACT_EMAIL")

    if not all([email_server, email_port, email_sender, email_password]):
        current_app.logger.warning("Skipping confirmation email; email server env vars are not fully configured")
        return reg

    reg_data = reg.to_dict()
    reg_type = reg_data["reg_type"]
    school_name = reg_data.get("school") or ""

    reg_details = f"""
        Name: {reg_data['full_name']}
        Type: {reg_type}
        Email: {reg_data['email']}
        Phone: {reg_data.get('phone') or ''}
        School: {school_name}
    """

    if reg_type == "competitor":
        reg_details += f"""    Coach: {reg_data.get('coach') or ''}
        Parent: {reg_data.get('parent') or ''}
        Birthdate: {reg_data.get('birthdate') or ''}
        Gender: {reg_data.get('gender') or ''}
        Weight: {reg_data.get('weight') or ''}
        Belt: {reg_data.get('belt_rank') or ''}
        {f"T-Shirt size: {reg_data['tshirt']}" if reg_data.get('tshirt') else ''}
        Events:"""

        poomsae_form_lookup = {
            "poomsae": "poomsae_form",
            "wc poomsae": "wc_poomsae_form",
            "pair poomsae": "pair_poomsae_form",
            "team poomsae": "team_poomsae_form",
            "family poomsae": "family_poomsae_form",
        }

        for e in reg_data.get("events", []):
            display = e.strip()
            if display == "little_dragon":
                display = "Little Dragon Obstacle Course"
            if display.startswith("sparring"):
                spar_dict = {"wc": "world class ", "gr": "grass roots "}
                spar_parts = display.split("-")
                spar_type = spar_dict.get(spar_parts[1], "") if len(spar_parts) > 1 else ""
                display = f"{spar_type}sparring"
            form_key = poomsae_form_lookup.get(display.replace("_", " "))
            if form_key:
                form_name = reg_data.get(form_key) or ""
                if form_name.isnumeric():
                    form_name = f"Taegeuk {form_name} Jang"
                display += f" (Form: {form_name})"
            reg_details += f"\n          • {display.title()}"

    body = f"""
    Dear {reg_data['full_name']},

    Thank you for being a part of the {comp_year} {comp_name}!

    Your registration has been accepted with the following details.
    {reg_details}

    If you have any questions please contact us at {contact_email}

    Warm Regards,
    {comp_name}
    """

    em = EmailMessage()
    em["From"] = formataddr((comp_name, email_sender))
    em["To"] = formataddr((reg_data["full_name"], reg_data["email"]))
    em["Subject"] = f"{comp_year} {comp_name} Registration"
    em.set_content(body)

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(email_server, int(email_port), context=context) as smtp:
        smtp.login(email_sender, email_password)
        smtp.sendmail(email_sender, reg_data["email"], em.as_string())

    current_app.logger.info("Confirmation email sent to %s", reg_data["email"])
    return reg


def create_registration_record(body: dict) -> tuple:
    """Validate and persist a registration record to the database.

    Performs school resolution, duplicate detection, and creates the appropriate
    Competitor or Coach record.  The session is flushed (not committed) on success
    so the caller can attach additional fields (e.g. checkout_session_id) before
    committing.

    Returns:
        (reg, None, None, new_school_name_or_none) on success – reg is flushed but not yet committed.
        (None, error_msg, code, None)          on failure – session is rolled back.
    """
    school, new_school_name = _get_or_create_school(body.get("school"))
    if school is None:
        db.session.rollback()
        return None, "School is required", 422, None

    try:
        _check_duplicate(body["full_name"], school.id, body["reg_type"])
    except DuplicateRegistrationError:
        db.session.rollback()
        return None, f"Duplicate registration for {body['full_name']}", 409, None

    if body["reg_type"] == "competitor":
        coach_name = (body.get("coach") or "").strip() or None
        coach_id = None
        if coach_name:
            linked_coach = _get_coach_by_name_and_school(coach_name, school.id)
            coach_id = linked_coach.id if linked_coach else None
        reg = Competitor(
            full_name=body["full_name"],
            email=body["email"],
            phone=body.get("phone"),
            school_id=school.id,
            coach_id=coach_id,
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
            medical_contacts=body.get("medical_contacts"),
            medical_conditions=body.get("medical_conditions", []),
            allergies=body.get("allergies", []),
            medications=body.get("medications", []),
            img_filename=body.get("img_filename"),
            tshirt=body.get("tshirt"),
            status="pending",
        )
    else:
        reg = Coach(
            full_name=body["full_name"],
            email=body["email"],
            phone=body.get("phone"),
            school_id=school.id,
            img_filename=body.get("img_filename"),
        )

    db.session.add(reg)
    db.session.flush()
    return reg, None, None, new_school_name


@api_bp.route("/registrations", methods=["POST"])
@api_bp.input(RegistrationIn, arg_name="body")
@api_bp.output(RegistrationCreateOut, status_code=201, description="Registration created")
@api_bp.doc(
    responses={
        409: _err("Duplicate registration"),
        422: _err("Validation error"),
    }
)
def create_registration(body):
    reg, err_msg, err_code, new_school_name = create_registration_record(body)
    if err_msg:
        return _err_response(err_msg, err_code)
    db.session.commit()
    if new_school_name:
        send_admin_school_alert(new_school_name)
    return {"data": {"id": reg.id}}, 201


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

    event_type = event["type"]
    if event_type not in {"checkout.session.completed", "checkout.session.expired"}:
        current_app.logger.debug("Ignoring unhandled Stripe webhook event type: %s", event_type)
        return jsonify({"status": "ok"}), 200

    session = event["data"]["object"]
    session_id = session.get("id")
    if not session_id:
        current_app.logger.warning("Stripe webhook received %s event with missing session id", event_type)
        return jsonify({"error": "Stripe checkout session ID is missing from webhook payload"}), 400

    reg = _find_reg_by_checkout_session(session_id)
    if reg is None:
        return jsonify({"status": "ok"}), 200

    current_status = reg.status

    if event_type == "checkout.session.completed":
        if current_status != "complete":
            reg.status = "complete"
            reg.payment_intent = session.get("payment_intent")
            db.session.commit()
            try:
                _send_confirmation_email(reg)
            except Exception:
                current_app.logger.exception("Post-checkout completion actions failed for registration %s", reg.id)
    elif event_type == "checkout.session.expired":
        if current_status not in {"complete", "failed"}:
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
@api_bp.doc(responses={404: _err("Not found")})
def registration_status(registration_id):
    """Check registration and payment status by ID.

    Pass ``?type=coach`` to look up a coach record; omit or pass ``?type=competitor``
    for the default competitor lookup.  This disambiguates when both tables share
    the same integer primary key.
    """
    try:
        reg_id = int(registration_id)
    except (ValueError, TypeError):
        return jsonify({"error": "Not found"}), 404

    reg_type_hint = request.args.get("type", "competitor").lower()

    # The type hint controls which table is searched first.  The fallback to the
    # opposite table is intentional: callers that omit the parameter (or supply
    # the wrong value) still get the correct record as long as the IDs are
    # unambiguous.  When both tables share the same integer ID the caller should
    # pass `?type=` explicitly to guarantee the correct result.
    if reg_type_hint == "coach":
        reg = db.session.get(Coach, reg_id)
        reg_type = "coach"
        if reg is None:
            reg = db.session.get(Competitor, reg_id)
            reg_type = "competitor"
    else:
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
                "checkout_session_id": getattr(reg, "checkout_session_id", None),
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
@api_bp.doc(security=[{"BearerAuth": []}], responses={401: _err("Unauthorized")})
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
@api_bp.doc(security=[{"BearerAuth": []}], responses={401: _err("Unauthorized"), 404: _err("Not found")})
@api_auth_required
@api_bp.output(RegistrationDetailOut, description="Registration detail")
def admin_get_registration(registration_id):
    """Get a single registration by ID."""
    reg, _ = _get_registration_by_id(registration_id)
    if reg is None:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"data": reg.to_dict()})


@api_bp.route("/admin/registrations/<string:registration_id>", methods=["PUT"])
@api_bp.doc(security=[{"BearerAuth": []}], responses={401: _err("Unauthorized"), 404: _err("Not found")})
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
@api_bp.doc(security=[{"BearerAuth": []}], responses={401: _err("Unauthorized"), 404: _err("Not found")})
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
@api_bp.doc(
    security=[{"BearerAuth": []}],
    responses={401: _err("Unauthorized"), 404: _err("Unknown resource"), 422: _err("No file provided")},
)
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
