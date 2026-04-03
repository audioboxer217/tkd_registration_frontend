import json
import os
from datetime import date, datetime, timedelta
from functools import wraps

import boto3
import pytz
import stripe
from api import api_bp
from email_validator import EmailNotValidError, validate_email
from flask import (
    Blueprint,
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    render_template_string,
    request,
    session,
    url_for,
)
from models import Registration, db, init_db
from supabase import Client, create_client
from zoneinfo import ZoneInfo

ui_bp = Blueprint("ui", __name__)


# ---------------------------------------------------------------------------
# Supabase client (lazy, created once per request context via g)
# ---------------------------------------------------------------------------


def get_supabase() -> Client:
    if "supabase" not in g:
        g.supabase = create_client(
            os.getenv("SUPABASE_URL", ""),
            os.getenv("SUPABASE_ANON_KEY", ""),
        )
    return g.supabase


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def login_required(f):
    @wraps(f)
    def auth_wrapper(*args, **kwargs):
        user = session.get("user")
        if not user:
            return redirect(url_for("ui.login"))
        role = (user.get("app_metadata") or {}).get("role")
        if role != "admin":
            flash("You are not authorized to view this page. Please contact the administrator.", "danger")
            return redirect(url_for("ui.logout"))
        return f(*args, **kwargs)

    return auth_wrapper


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _s3():
    return boto3.client("s3", region_name=os.getenv("AWS_REGION", "us-east-1"))


def _sqs():
    return boto3.client("sqs", region_name=os.getenv("AWS_REGION", "us-east-1"))


def get_price_details():
    price_dict = {}
    products = stripe.Product.list()
    for p in products:
        price_detail = stripe.Price.retrieve(p.default_price)
        price_dict[p.name] = {
            "price_id": price_detail.id,
            "price": f"{int(price_detail.unit_amount/100)}",
        }
    return price_dict


def convert_to_local(utc_dt):
    local_tz = pytz.timezone(os.getenv("LOCAL_TIMEZONE", "US/Central"))
    return utc_dt.astimezone(local_tz)


def get_s3_file(bucket, file_name):
    """Download a file from S3 into static/public_media if not already cached."""
    if not os.path.exists("static/public_media"):
        os.makedirs("static/public_media")

    output = f"public_media/{os.path.basename(file_name)}"

    if not os.path.exists(f"static/{output}"):
        try:
            _s3().download_file(bucket, file_name, f"static/{output}")
        except Exception as e:
            print(f"Error downloading {file_name} from S3: {e}")
            return None

    return output


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


def set_weight_class(entries):
    config_bucket = os.getenv("CONFIG_BUCKET")
    weight_classes = json.load(_s3().get_object(Bucket=config_bucket, Key="weight_classes.json")["Body"])
    updated_entries = []
    for entry in entries:
        age_group = get_age_group(entry["age"]["N"])
        entry["age_group"] = age_group
        gender = "female" if entry["gender"]["S"] == "F" else "male" if entry["gender"]["S"] == "M" else entry["gender"]["S"]
        weight_class_ranges = weight_classes[age_group][gender]
        entry["weight_class"] = next(
            (
                weight_class
                for weight_class, weights in weight_class_ranges.items()
                if float(entry["weight"]["N"]) >= float(weights[0]) and float(entry["weight"]["N"]) < float(weights[1])
            ),
            "UNKNOWN",
        )
        updated_entries.append(entry)
    return updated_entries


def render_base(content_file, **page_params):
    user = session.get("user")
    if user and (user.get("app_metadata") or {}).get("role") == "admin":
        page_params["admin"] = True
    config = _current_app_config()
    s3_favicon = get_s3_file(config["mediaBucket"], "favicon.png")
    return render_template(
        "base.html",
        competition_name=os.getenv("COMPETITION_NAME"),
        favicon_url=url_for("static", filename=s3_favicon) if s3_favicon else None,
        event_city=os.getenv("EVENT_CITY", None),
        button_style=os.getenv("BUTTON_STYLE", "btn-primary"),
        form_js=url_for("static", filename="js/form.js"),
        address_enabled=os.getenv("ENABLE_ADDRESS", False),
        maps_api_key=os.getenv("MAPS_API_KEY") if os.getenv("ENABLE_ADDRESS") else None,
        content_file=content_file,
        **page_params,
    )


def _current_app_config():
    """Return current Flask app config as a dict for use outside app context."""
    from flask import current_app

    return current_app.config


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------


@ui_bp.route("/login", methods=["GET"])
def login():
    return render_base("login.html")


@ui_bp.route("/login", methods=["POST"])
def login_post():
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")
    try:
        supabase = get_supabase()
        response = supabase.auth.sign_in_with_password({"email": email, "password": password})
        user_data = response.user
        session["user"] = {
            "id": user_data.id,
            "email": user_data.email,
            "app_metadata": user_data.app_metadata or {},
            "access_token": response.session.access_token,
            "refresh_token": response.session.refresh_token,
        }
        return redirect(url_for("ui.admin_page"))
    except Exception as e:
        flash(f"Login failed: {e}", "danger")
        return render_base("login.html")


@ui_bp.route("/logout")
def logout():
    try:
        supabase = get_supabase()
        supabase.auth.sign_out()
    except Exception:
        pass
    session.pop("user", None)
    return redirect(url_for("ui.index"))


# ---------------------------------------------------------------------------
# Public page routes
# ---------------------------------------------------------------------------


@ui_bp.route("/", methods=["GET"])
def index():
    config = _current_app_config()
    try:
        coupons = stripe.Coupon.list(limit=1)
        early_reg_date = (
            datetime.fromtimestamp(coupons.data[0]["redeem_by"]).replace(tzinfo=config["TZ_LOCAL"]) if coupons.data else None
        )
    except stripe.StripeError:
        early_reg_date_str = os.getenv("EARLY_REG_DATE")
        try:
            early_reg_date = (
                datetime.strptime(early_reg_date_str, "%B %d, %Y").replace(tzinfo=config["TZ_LOCAL"])
                if early_reg_date_str
                else None
            )
        except ValueError:
            early_reg_date = None

    s3_poster = get_s3_file(config["mediaBucket"], "registration_poster.jpg")
    page_params = {
        "today": convert_to_local(datetime.today()),
        "email": os.getenv("CONTACT_EMAIL"),
        "early_reg_date": early_reg_date,
        "reg_close_date": os.getenv("REG_CLOSE_DATE"),
        "poster_url": url_for("static", filename=s3_poster) if s3_poster else None,
    }
    if request.headers.get("HX-Request"):
        return render_template("landing.html", **page_params)
    return render_base("landing.html", **page_params)


@ui_bp.route("/visit", methods=["GET"])
def visit_page():
    if request.headers.get("HX-Request"):
        return render_template("tulsa.html")
    return render_base("tulsa.html")


@ui_bp.route("/hotel", methods=["GET"])
def hotel_page():
    if request.headers.get("HX-Request"):
        return render_template("hotel.html", button_style=os.getenv("BUTTON_STYLE", "btn-primary"))
    return render_base("hotel.html")


@ui_bp.route("/schedule", methods=["GET"])
def schedule_page():
    if request.headers.get("HX-Request"):
        return render_template("schedule.html")
    return render_base("schedule.html")


@ui_bp.route("/get_schedule_details", methods=["GET"])
def schedule_details():
    config = _current_app_config()
    if schedule_img_file := get_s3_file(config["configBucket"], "schedule.png"):
        schedule_img = url_for("static", filename=schedule_img_file)
        return render_template_string(
            """
            <div class="row g-1 mb-1 justify-content-md-center">
                <div class="col-md-12 center-block" align="center">
                    <img src="{{ schedule_img }}"" class=" img-fluid"><img><br />
                </div>
            </div>
            """,
            schedule_img=schedule_img,
        )
    elif schedule_json := get_s3_file(config["configBucket"], "schedule.json"):
        schedule_dict = json.load(open(os.path.join("static", schedule_json), "r"))
        return render_template_string(
            """
            <div class="table-responsive" align="center">
                <table class="table table-striped table-bordered">
                    {% for day in schedule_dict %}
                    <thead>
                        <tr>
                            <th class="{{ day.class }}" scope="col" colspan="{{ day.colspan }}">
                                <h4>{{day.date}}</h4>
                            </th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for item in day['items'] %}
                        <tr>
                            {% if item.time is defined %}
                            <th scope="row" class="table-primary" {% if item.time_rowspan is defined
                                %}rowspan="{{item.time_rowspan}}" {%endif%}>
                                {{item.time }}
                            </th>
                            {%endif%}
                            <td {% if item.title_class is defined -%}class="{{item.title_class}}" {%endif%}>
                                {{ item.title | safe }}
                            </td>
                            {% if item.location is defined %}
                            <td {% if item.location.class is defined -%}class="{{item.location.class}}" {%endif%}{% if
                                item.location.rowspan is defined %}rowspan="{{item.location.rowspan}}" {%endif%}><a
                                    href="{{item.location.link}}" target="_blank">{{
                                    item.location.name }}</a></td>
                            {%endif%}
                        </tr>
                        {%endfor%}
                    </tbody>
                    {%endfor%}
                </table>
            </div>
            """,
            schedule_dict=schedule_dict,
        )
    return render_template_string('<div align="center">Schedule not found</div>')


@ui_bp.route("/information", methods=["GET"])
def info_page():
    config = _current_app_config()
    s3_addl_images = _s3().list_objects(Bucket=config["mediaBucket"], Prefix="additional_information_images/")["Contents"]
    page_params = {
        "information_booklet_url": url_for("static", filename=get_s3_file(config["mediaBucket"], "information_booklet.pdf")),
        "poomsae_booklet_url": url_for("static", filename=get_s3_file(config["mediaBucket"], "poomsae_booklet.pdf")),
        "breaking_booklet_url": url_for("static", filename=get_s3_file(config["mediaBucket"], "breaking_booklet.pdf")),
        "additional_imgs": [
            url_for("static", filename=get_s3_file(config["mediaBucket"], i["Key"])) for i in s3_addl_images if i["Size"] > 0
        ],
    }
    if request.headers.get("HX-Request"):
        return render_template("information.html", button_style=os.getenv("BUTTON_STYLE", "btn-primary"), **page_params)
    return render_base("information.html", **page_params)


@ui_bp.route("/entries", methods=["GET"])
def entries_page():
    if request.headers.get("HX-Request"):
        return render_template("entries.html")
    return render_base("entries.html")


@ui_bp.route("/registration_error", methods=["GET"])
def error_page():
    page_params = {
        "reg_type": request.args.get("reg_type"),
        "email": os.getenv("CONTACT_EMAIL"),
    }
    if request.headers.get("HX-Request"):
        return render_template(
            "registration_error.html",
            button_style=os.getenv("BUTTON_STYLE", "btn-primary"),
            competition_name=os.getenv("COMPETITION_NAME"),
            **page_params,
        )
    return render_base("registration_error.html", **page_params)


@ui_bp.route("/success", methods=["GET"])
def success_page():
    price_dict = get_price_details()
    full_session = stripe.checkout.Session.retrieve(request.args.get("session_id"), expand=["payment_intent"])
    payment_intent = full_session.payment_intent
    if payment_intent:
        print(f"Payment Intent ID: {payment_intent.id}")
        transfer_group = payment_intent.transfer_group
        if transfer_group:
            print(f"Transfer already completed: {transfer_group}")
        else:
            transfer_obj = stripe.Transfer.create(
                amount=int(price_dict["Convenience Fee"]["price"]) * 100,
                currency="usd",
                source_transaction=payment_intent.latest_charge,
                destination=os.getenv("CONNECT_ACCT"),
            )
            print(f"Transfer created: {transfer_obj.transfer_group}")
    page_params = {
        "reg_type": request.args.get("reg_type"),
        "session_id": request.args.get("session_id"),
        "email": os.getenv("CONTACT_EMAIL"),
    }
    if request.headers.get("HX-Request"):
        return render_template(
            "success.html",
            button_style=os.getenv("BUTTON_STYLE", "btn-primary"),
            competition_name=os.getenv("COMPETITION_NAME"),
            **page_params,
        )
    return render_base("success.html", **page_params)


# ---------------------------------------------------------------------------
# Registration form routes
# ---------------------------------------------------------------------------


@ui_bp.route("/register", methods=["GET"])
def display_form():
    config = _current_app_config()
    today = datetime.now(config["TZ_LOCAL"])
    reg_close_date = datetime.strptime(f"{os.getenv('REG_CLOSE_DATE')} 23:59", "%B %d, %Y %H:%M").replace(
        tzinfo=config["TZ_LOCAL"]
    )
    if today > reg_close_date:
        page_params = {"email": os.getenv("CONTACT_EMAIL")}
        if request.headers.get("HX-Request"):
            return render_template("disabled.html", competition_name=os.getenv("COMPETITION_NAME"), **page_params)
        return render_base("disabled.html", **page_params)

    early_reg_coupon = stripe.Coupon.list(limit=1).data[0]
    reg_type = request.args.get("reg_type")
    school_list = json.load(_s3().get_object(Bucket=config["configBucket"], Key="schools.json")["Body"])

    page_params = {
        "early_reg_date": datetime.fromtimestamp(early_reg_coupon["redeem_by"]).replace(tzinfo=config["TZ_LOCAL"]),
        "early_reg_coupon_amount": f'{int(early_reg_coupon["amount_off"]/100)}',
        "price_dict": get_price_details(),
        "reg_type": reg_type,
        "schools": school_list,
        "enable_badges": config["ENABLE_BADGES"],
        "enable_address": config["ENABLE_ADDRESS"],
    }
    if request.headers.get("HX-Request"):
        return render_template("form.html", button_style=os.getenv("BUTTON_STYLE", "btn-primary"), **page_params)
    return render_base("form.html", **page_params)


@ui_bp.route("/register", methods=["POST"])
def handle_form():
    config = _current_app_config()
    price_dict = get_price_details()
    reg_type = request.form.get("regType")

    fname = request.form.get("fname").strip()
    lname = request.form.get("lname").strip()
    full_name = f"{fname} {lname}"
    school = request.form.get("school")
    if school == "unlisted":
        school = request.form.get("unlistedSchool").strip()
    coach = request.form.get("coach", "").strip()

    # Check for duplicate registration
    duplicate = Registration.query.filter_by(
        full_name=full_name,
        school=school,
        reg_type=reg_type,
    ).first()
    if duplicate:
        print("registration exists")
        return redirect(f'{config["URL"]}/registration_error?reg_type={reg_type}')

    reg = Registration(
        full_name=full_name,
        email=request.form.get("email"),
        phone=request.form.get("phone"),
        school=school,
        reg_type=reg_type,
    )

    registration_items = []

    if reg_type == "competitor":
        if request.form.get("liability") != "on":
            abort(400, "Please go back and accept the Liability Waiver Conditions")

        height = (int(request.form.get("heightFt")) * 12) + int(request.form.get("heightIn"))
        belt = request.form.get("beltRank")
        if belt == "black":
            dan = request.form.get("blackBeltDan")
            belt = "Master" if dan == "4" else f"{dan} degree {belt}"

        event_list = request.form.get("eventList")
        if not event_list:
            abort(400, "You must choose at least one event")

        reg.parent = request.form.get("parentName")
        reg.birthdate = request.form.get("birthdate")
        reg.age = int(request.form.get("age"))
        reg.gender = request.form.get("gender")
        reg.weight = float(request.form.get("weight"))
        reg.height = height
        reg.coach = coach
        reg.belt_rank = belt
        reg.events = event_list
        reg.poomsae_form = request.form.get("poomsae form", "")
        reg.pair_poomsae_form = request.form.get("pair poomsae form", "")
        reg.team_poomsae_form = request.form.get("team poomsae form", "")
        reg.family_poomsae_form = request.form.get("family poomsae form", "")
        reg.medical_contacts = request.form.get("contacts")
        reg.medical_conditions = [mc for mc in request.form.get("medicalConditionsList", "").split(",") if mc]
        reg.allergies = [a for a in request.form.get("allergy_list", "").split("\r\n") if a]
        reg.medications = [m for m in request.form.get("meds_list", "").split("\r\n") if m]

        if config["ENABLE_BADGES"]:
            profile_img = request.files["profilePic"]
            image_ext = os.path.splitext(profile_img.filename)[1]
            if not profile_img.content_type or not image_ext:
                abort(400, "There was an error uploading your profile pic. Please go back and try again.")
            img_filename = f"{school}_{reg_type}_{fname}_{lname}{image_ext}"
            reg.img_filename = img_filename
            _s3().upload_fileobj(profile_img, config["profilePicBucket"], img_filename)

        events_list = event_list.split(",")
        if request.form.get("beltRank") == "black":
            registration_items = [{"price": price_dict["Black Belt Registration"]["price_id"], "quantity": 1}]
        else:
            registration_items = [{"price": price_dict["Color Belt Registration"]["price_id"], "quantity": 1}]

        num_add_event = len(events_list) - 1
        if "little_dragon" in events_list:
            reg.tshirt = request.form.get("t-shirt")
            if num_add_event == 0:
                registration_items = [{"price": price_dict["Little Dragon Obstacle Course"]["price_id"], "quantity": 1}]
            else:
                num_add_event -= 1
                registration_items.append({"price": price_dict["Little Dragon Obstacle Course"]["price_id"], "quantity": 1})
        if num_add_event > 0:
            registration_items.append({"price": price_dict["Additional Event"]["price_id"], "quantity": num_add_event})
        registration_items.append({"price": price_dict["Convenience Fee"]["price_id"], "quantity": 1})
    else:
        registration_items = [{"price": price_dict["Coach Registration"]["price_id"], "quantity": 1}]

    if os.getenv("FLASK_DEBUG"):
        db.session.add(reg)
        db.session.commit()
        return render_template(
            "success.html",
            competition_name=os.getenv("COMPETITION_NAME"),
            email=os.getenv("CONTACT_EMAIL"),
            reg_detail={"id": str(reg.id), "full_name": reg.full_name},
            cost_detail=registration_items,
        )

    early_reg_coupon = stripe.Coupon.list(limit=1).data[0]
    try:
        early_reg_date = datetime.fromtimestamp(early_reg_coupon["redeem_by"]).replace(tzinfo=config["TZ_LOCAL"])
        current_time = convert_to_local(datetime.now())
        checkout_timeout = current_time + timedelta(minutes=30)
        checkout_details = {
            "line_items": registration_items,
            "mode": "payment",
            "discounts": [],
            "success_url": f'{config["URL"]}/success?reg_type={reg_type}&session_id={{CHECKOUT_SESSION_ID}}',
            "cancel_url": f'{config["URL"]}/register?reg_type={reg_type}',
            "expires_at": int(checkout_timeout.timestamp()),
        }
        if reg_type == "competitor" and current_time < early_reg_date:
            checkout_details["discounts"].append({"coupon": early_reg_coupon["id"]})
        checkout_session = stripe.checkout.Session.create(
            line_items=checkout_details["line_items"],
            mode=checkout_details["mode"],
            discounts=checkout_details["discounts"],
            success_url=checkout_details["success_url"],
            cancel_url=checkout_details["cancel_url"],
            expires_at=checkout_details["expires_at"],
        )
    except Exception as e:
        return str(e)

    reg.checkout_session_id = checkout_session.id
    db.session.add(reg)
    db.session.commit()

    _sqs().send_message(
        QueueUrl=config["SQS_QUEUE_URL"],
        DelaySeconds=120,
        MessageAttributes={
            "Name": {"DataType": "String", "StringValue": f"{fname}_{lname}"},
            "Transaction": {"DataType": "String", "StringValue": checkout_session.id},
        },
        MessageBody=json.dumps({"id": str(reg.id), "full_name": reg.full_name, "email": reg.email}),
    )

    return render_template_string(
        '<meta http-equiv="refresh" content="0; url={{ checkout_url }}" />', checkout_url=checkout_session.url
    )


# ---------------------------------------------------------------------------
# HTMX validation / autofill routes (return HTML partials)
# ---------------------------------------------------------------------------


@ui_bp.route("/lookup_entry", methods=["POST"])
def lookup_entry():
    email = request.form.get("email")
    name_query = f"{request.form.get('fname','').lower()} {request.form.get('lname','').lower()}".strip()
    query = Registration.query.filter(Registration.email == email)
    entries_raw = query.all()

    if len(entries_raw) > 1 and name_query:
        entries_raw = [e for e in entries_raw if name_query in e.full_name.lower()]

    # Convert to legacy DynamoDB-style dict format so templates continue to work unchanged
    entries = [_reg_to_legacy(e) for e in entries_raw]
    return render_template("form/lookup_modal.html", entries=entries)


def _reg_to_legacy(reg: Registration) -> dict:
    """Convert a Registration model to the legacy DynamoDB dict structure expected by templates."""
    d = {
        "name": {"S": reg.full_name or ""},
        "full_name": {"S": reg.full_name or ""},
        "email": {"S": reg.email or ""},
        "phone": {"S": reg.phone or ""},
        "school": {"S": reg.school or ""},
        "reg_type": {"S": reg.reg_type},
        "birthdate": {"S": reg.birthdate or ""},
        "age": {"N": str(reg.age or "")},
        "gender": {"S": reg.gender or ""},
        "weight": {"N": str(reg.weight or "")},
        "height": {"N": str(reg.height or "")},
        "coach": {"S": reg.coach or ""},
        "beltRank": {"S": reg.belt_rank or ""},
        "events": {"S": reg.events or ""},
        "poomsae_form": {"S": reg.poomsae_form or ""},
        "wc_poomsae_form": {"S": reg.wc_poomsae_form or ""},
        "pair_poomsae_form": {"S": reg.pair_poomsae_form or ""},
        "team_poomsae_form": {"S": reg.team_poomsae_form or ""},
        "family_poomsae_form": {"S": reg.family_poomsae_form or ""},
        "parent": {"S": reg.parent or ""},
        "pk": {"S": str(reg.id)},
        "medical_form": {
            "M": {
                "contacts": {"S": reg.medical_contacts or ""},
                "medicalConditions": {"L": [{"S": mc} for mc in (reg.medical_conditions or [])]},
                "allergies": {"L": [{"S": a} for a in (reg.allergies or [])]},
                "medications": {"L": [{"S": m} for m in (reg.medications or [])]},
            }
        },
    }
    return d


@ui_bp.route("/api/autofill", methods=["GET"])
def autofill():
    config = _current_app_config()
    import json as _json

    entry = _json.loads(request.args.get("entry"))
    entry["fname"] = entry["name"]["S"].split()[0]
    entry["lname"] = entry["name"]["S"].split()[1]
    birthdate = datetime.strptime(entry["birthdate"]["S"], "%m/%d/%Y")
    entry["birthdate"] = birthdate.strftime("%Y-%m-%d")
    entry["age"] = str(date.today().year - birthdate.year)
    entry["age_group"] = get_age_group(int(entry["age"]))
    schools = json.load(_s3().get_object(Bucket=config["configBucket"], Key="schools.json")["Body"])
    entry["allergy_list"] = [a["S"] for a in entry["medical_form"]["M"]["allergies"]["L"]]
    entry["meds_list"] = [m["S"] for m in entry["medical_form"]["M"]["medications"]["L"]]
    entry["medicalConditionsList"] = [mc["S"] for mc in entry["medical_form"]["M"]["medicalConditions"]["L"]]
    return render_template("form/autofill.html", entry=entry, schools=schools)


@ui_bp.route("/api/validate/name/<string:form_item_name>", methods=["POST"])
def api_validate_name(form_item_name):
    form_item = request.form.get(form_item_name)
    form_item_id = request.args.get("id", form_item_name)
    form_item_valid = bool(form_item) and form_item.replace(" ", "").isalpha()
    return render_template(
        "validation/name.html",
        form_item=form_item,
        form_item_id=form_item_id,
        form_item_name=form_item_name,
        form_item_valid=form_item_valid,
    )


@ui_bp.route("/api/validate/number/<string:form_item_name>", methods=["POST"])
def api_validate_number(form_item_name):
    form_item = request.form.get(form_item_name)
    form_item_id = request.args.get("id", form_item_name)
    form_item_step = request.args.get("step", "1")
    form_item_min = request.args.get("min", "")
    form_item_max = request.args.get("max", "")
    form_item_valid = bool(form_item) and form_item.isdigit()
    return render_template(
        "validation/number.html",
        form_item=form_item,
        form_item_id=form_item_id,
        form_item_step=form_item_step,
        form_item_min=form_item_min,
        form_item_max=form_item_max,
        form_item_name=form_item_name,
        form_item_valid=form_item_valid,
    )


@ui_bp.route("/api/validate/email", methods=["POST"])
def api_validate_email():
    email = request.form.get("email")
    reg_type = request.form.get("regType")
    try:
        validate_email(email)
        email_valid = True
    except EmailNotValidError:
        email_valid = False
    return render_template(
        "validation/email.html",
        email=email,
        email_valid=email_valid,
        reg_type=reg_type,
        button_style=os.getenv("BUTTON_STYLE", "btn-primary"),
    )


@ui_bp.route("/api/validate/phone", methods=["POST"])
def api_validate_phone():
    phone_num = request.form.get("phone").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if phone_num and phone_num.isdigit() and len(phone_num) == 10:
        phone_num = phone_num[0:3] + "-" + phone_num[3:6] + "-" + phone_num[6:]
        phone_valid = True
    else:
        phone_valid = False
    return render_template("validation/phone.html", phone_num=phone_num, phone_valid=phone_valid)


@ui_bp.route("/api/validate/birthdate", methods=["POST"])
def api_validate_birthdate():
    try:
        birthdate = datetime.strptime(request.form.get("birthdate"), "%Y-%m-%d")
        age = datetime.now().year - birthdate.year
        age_group = get_age_group(age)
        date_valid = age_group not in ("too_young", "too_old")
    except ValueError:
        age = ""
        age_group = ""
        date_valid = False
    return render_template(
        "validation/birthdate.html",
        birthdate=request.form.get("birthdate"),
        date_valid=date_valid,
        age=str(age),
        age_group=age_group,
    )


@ui_bp.route("/api/validate/school", methods=["POST"])
def api_validate_school():
    config = _current_app_config()
    school_selection = request.form.get("school")
    school_valid = bool(school_selection)
    return render_template(
        "validation/school.html",
        school_selection=school_selection,
        school_valid=school_valid,
        schools=json.load(_s3().get_object(Bucket=config["configBucket"], Key="schools.json")["Body"]),
    )


@ui_bp.route("/api/schools/add", methods=["POST"])
def add_item():
    school = request.form.get("school")
    school_list = request.form.get("schoolList").split(",")
    if school:
        school_list.append(school)
    return render_template("school_fragment.html", school=school, index=len(school_list) - 1, schools=school_list)


@ui_bp.route("/api/schools/remove/<int:index>", methods=["DELETE"])
def remove_school(index):
    school_list = request.args.get("schoolList").split(",")
    school_list[index] = "REMOVE"
    schools = ",".join(school_list)
    return render_template_string(
        f'<input type="text" hx-swap-oob="true" id="schoolList" name="schoolList" value="{schools}" hidden>',
    ), 200


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------


@ui_bp.route("/upload/<string:resource>", methods=["GET"])
@login_required
def upload_form(resource):
    page_params = {"resource": resource}
    if request.headers.get("HX-Request"):
        return render_template("upload.html", button_style=os.getenv("BUTTON_STYLE", "btn-primary"), **page_params)
    return render_base("upload.html", **page_params)


@ui_bp.route("/api/upload/<string:resource>", methods=["POST"])
@login_required
def upload_item(resource):
    config = _current_app_config()
    if resource in ("schedule", "booklet"):
        upload_conf = {
            "schedule": {"bucket": config["configBucket"], "filename": "schedule.png"},
            "booklet": {"bucket": config["mediaBucket"], "filename": "information_booklet.pdf"},
        }
        upload_file = request.files["uploadFile"]
        conf = upload_conf[resource]
        _s3().upload_fileobj(upload_file, conf["bucket"], conf["filename"])
    elif resource == "schools":
        schools = list(set(request.form.get("schoolList").split(",")))
        if "REMOVE" in schools:
            schools.remove("REMOVE")
        schools.sort()
        _s3().put_object(
            Bucket=config["configBucket"],
            Key="schools.json",
            Body=json.dumps(schools),
            ContentType="application/json",
        )
    flash(f"{resource.capitalize()} updated successfully!", "success")
    return redirect(f"{url_for('ui.admin_page')}?redirect=True", code=303)


@ui_bp.route("/schools", methods=["GET"])
@login_required
def schools_page():
    config = _current_app_config()
    schools_json = json.load(_s3().get_object(Bucket=config["configBucket"], Key="schools.json")["Body"])
    if request.headers.get("HX-Request"):
        return render_template("api/schools.html", schools=schools_json, button_style=os.getenv("BUTTON_STYLE", "btn-primary"))
    return render_base("api/schools.html", schools=schools_json)


@ui_bp.route("/admin", methods=["GET"])
@login_required
def admin_page():
    entries_raw = Registration.query.order_by(Registration.created_at.desc()).all()
    entries = [_reg_to_legacy(e) for e in entries_raw]
    page_params = {"entries": entries}
    redirect_flag = bool(request.args.get("redirect"))
    page_template = "admin.html" if not redirect_flag else "admin_entries.html"
    if request.headers.get("HX-Request"):
        return render_template(page_template, button_style=os.getenv("BUTTON_STYLE", "btn-primary"), **page_params)
    return render_base(page_template, **page_params)


@ui_bp.route("/add_entry")
@login_required
def add_entry_form():
    config = _current_app_config()
    early_reg_coupon = stripe.Coupon.list(limit=1).data[0]
    reg_type = request.args.get("reg_type")
    school_list = json.load(_s3().get_object(Bucket=config["configBucket"], Key="schools.json")["Body"])
    page_params = {
        "price_dict": get_price_details(),
        "early_reg_date": datetime.fromtimestamp(early_reg_coupon["redeem_by"]).replace(tzinfo=config["TZ_LOCAL"]),
        "early_reg_coupon_amount": f'{int(early_reg_coupon["amount_off"]/100)}',
        "badge_enabled": config["ENABLE_BADGES"],
        "reg_type": reg_type,
        "schools": school_list,
        "enable_badges": config["ENABLE_BADGES"],
        "enable_address": config["ENABLE_ADDRESS"],
    }
    if request.headers.get("HX-Request"):
        return render_template("add_entry.html", button_style=os.getenv("BUTTON_STYLE", "btn-primary"), **page_params)
    return render_base("add_entry.html", **page_params)


@ui_bp.route("/add_entry", methods=["POST"])
@login_required
def add_entry():
    config = _current_app_config()
    reg_type = request.form.get("regType")

    fname = request.form.get("fname").strip()
    lname = request.form.get("lname").strip()
    full_name = f"{fname} {lname}"
    school = request.form.get("school")
    coach = request.form.get("coach", "").strip()

    if not os.getenv("FLASK_DEBUG"):
        duplicate = Registration.query.filter_by(full_name=full_name, school=school, reg_type=reg_type).first()
        if duplicate:
            return redirect(f'{config["URL"]}/registration_error?reg_type={reg_type}')

    reg = Registration(
        full_name=full_name,
        email=request.form.get("email"),
        phone=request.form.get("phone"),
        school=school,
        reg_type=reg_type,
    )

    if reg_type == "competitor":
        height = (int(request.form.get("heightFt")) * 12) + int(request.form.get("heightIn"))
        belt = request.form.get("beltRank")
        if belt == "black":
            dan = request.form.get("blackBeltDan")
            belt = "Master" if dan == "4" else f"{dan} degree {belt}"
        event_list = request.form.get("eventList")
        if not event_list:
            abort(400, "You must choose at least one event")

        reg.parent = request.form.get("parentName")
        reg.birthdate = request.form.get("birthdate")
        reg.age = int(request.form.get("age"))
        reg.gender = request.form.get("gender")
        reg.weight = float(request.form.get("weight"))
        reg.height = height
        reg.coach = coach
        reg.belt_rank = belt
        reg.events = event_list
        reg.poomsae_form = request.form.get("poomsae form", "")
        reg.wc_poomsae_form = request.form.get("world-class poomsae form", "")
        reg.pair_poomsae_form = request.form.get("pair poomsae form", "")
        reg.team_poomsae_form = request.form.get("team poomsae form", "")
        reg.family_poomsae_form = request.form.get("family poomsae form", "")
        reg.medical_contacts = request.form.get("contacts")
        reg.medical_conditions = [mc for mc in request.form.get("medicalConditionsList", "").split(",") if mc]
        reg.allergies = [a for a in request.form.get("allergy_list", "").split("\r\n") if a]
        reg.medications = [m for m in request.form.get("meds_list", "").split("\r\n") if m]

        if config["ENABLE_BADGES"]:
            profile_img = request.files["profilePic"]
            image_ext = os.path.splitext(profile_img.filename)[1]
            if not profile_img.content_type or not image_ext:
                abort(400, "There was an error uploading your profile pic. Please go back and try again.")
            img_filename = f"{school}_{reg_type}_{fname}_{lname}{image_ext}"
            reg.img_filename = img_filename
            _s3().upload_fileobj(profile_img, config["profilePicBucket"], img_filename)

    if os.getenv("FLASK_DEBUG"):
        db.session.add(reg)
        db.session.commit()
        return render_template(
            "success.html",
            competition_name=os.getenv("COMPETITION_NAME"),
            email=os.getenv("CONTACT_EMAIL"),
            reg_detail={"id": str(reg.id), "full_name": reg.full_name},
        )

    reg.checkout_session_id = "manual_entry"
    db.session.add(reg)
    db.session.commit()

    _sqs().send_message(
        QueueUrl=config["SQS_QUEUE_URL"],
        DelaySeconds=120,
        MessageAttributes={
            "Name": {"DataType": "String", "StringValue": f"{fname}_{lname}"},
            "Transaction": {"DataType": "String", "StringValue": "manual_entry"},
        },
        MessageBody=json.dumps({"id": str(reg.id), "full_name": reg.full_name, "email": reg.email}),
    )
    flash(f"{full_name} added successfully!", "success")
    return redirect(f'{config["URL"]}/admin', code=303)


@ui_bp.route("/edit_entry")
@login_required
def edit_entry_form():
    config = _current_app_config()
    reg_id = request.args.get("pk")
    reg = db.session.get(Registration, reg_id)
    if reg is None:
        abort(404)
    school_list = json.load(_s3().get_object(Bucket=config["configBucket"], Key="schools.json")["Body"])
    page_params = {"schools": school_list, "entry": _reg_to_legacy(reg)}
    if request.headers.get("HX-Request"):
        return render_template("edit.html", button_style=os.getenv("BUTTON_STYLE", "btn-primary"), **page_params)
    return render_base("edit.html", **page_params)


@ui_bp.route("/edit", methods=["POST"])
@login_required
def edit_entry():
    config = _current_app_config()
    reg_id = request.args.get("pk")
    reg = db.session.get(Registration, reg_id)
    if reg is None:
        abort(404)

    reg.full_name = request.form.get("full_name")
    reg.email = request.form.get("email")
    reg.phone = request.form.get("phone")
    reg.school = request.form.get("school")
    reg.reg_type = request.form.get("regType")

    if reg.reg_type == "competitor":
        belt = request.form.get("beltRank")
        if belt == "black":
            dan = request.form.get("blackBeltDan")
            belt = "Master" if dan == "4" else f"{dan} degree {belt}"
        reg.parent = request.form.get("parentName")
        reg.birthdate = request.form.get("birthdate")
        reg.age = int(request.form.get("age"))
        reg.gender = request.form.get("gender")
        reg.weight = float(request.form.get("weight"))
        reg.height = int(request.form.get("height"))
        reg.coach = request.form.get("coach", "").strip()
        reg.belt_rank = belt
        reg.events = request.form.get("eventList")
        reg.poomsae_form = request.form.get("poomsae form", "")
        reg.pair_poomsae_form = request.form.get("pair poomsae form", "")
        reg.team_poomsae_form = request.form.get("team poomsae form", "")
        reg.family_poomsae_form = request.form.get("family poomsae form", "")

    db.session.commit()
    flash(f"{reg.full_name} updated successfully!", "success")
    return redirect(f'{config["URL"]}/admin', code=303)


@ui_bp.route("/export")
@login_required
def generate_csv():
    config = _current_app_config()
    entries_raw = Registration.query.filter_by(reg_type="competitor").order_by(Registration.full_name).all()
    entries = [_reg_to_legacy(e) for e in entries_raw]
    s3_favicon = get_s3_file(config["mediaBucket"], "favicon.png")
    return render_template(
        "export.html",
        competition_year=os.getenv("COMPETITION_YEAR"),
        competition_name=os.getenv("COMPETITION_NAME"),
        favicon_url=url_for("static", filename=s3_favicon) if s3_favicon else None,
        button_style=os.getenv("BUTTON_STYLE", "btn-primary"),
        entries=entries,
    )


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------


@ui_bp.app_errorhandler(404)
def page_not_found(e):
    return render_base("404.html"), 404


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app():
    flask_app = Flask(__name__)
    flask_app.secret_key = os.getenv("FLASK_SECRET_KEY", os.urandom(24))

    # Config
    flask_app.config["profilePicBucket"] = os.getenv("PROFILE_PIC_BUCKET")
    flask_app.config["configBucket"] = os.getenv("CONFIG_BUCKET")
    flask_app.config["mediaBucket"] = os.getenv("PUBLIC_MEDIA_BUCKET")
    flask_app.config["URL"] = "http://localhost:5001" if os.getenv("FLASK_DEBUG") else os.getenv("REG_URL")
    flask_app.config["SQS_QUEUE_URL"] = os.getenv("SQS_QUEUE_URL")
    flask_app.config["TZ_LOCAL"] = ZoneInfo(os.getenv("LOCAL_TIMEZONE", "US/Central"))
    flask_app.config["ENABLE_BADGES"] = os.getenv("ENABLE_BADGES", False)
    flask_app.config["ENABLE_ADDRESS"] = os.getenv("ENABLE_ADDRESS", False)

    # SQLAlchemy — serverless-safe pool settings for Supabase connection pooler
    db_url = os.getenv("DATABASE_URL", "sqlite:///:memory:")
    flask_app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    if not db_url.startswith("sqlite"):
        flask_app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
            "pool_pre_ping": True,
            "pool_recycle": 300,
            "pool_size": 1,
            "max_overflow": 2,
        }
    flask_app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    stripe.api_key = os.getenv("STRIPE_API_KEY")

    init_db(flask_app)

    flask_app.register_blueprint(ui_bp)
    flask_app.register_blueprint(api_bp)

    return flask_app


# Module-level app instance for Zappa and pytest compatibility
app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0")
