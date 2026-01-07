import json
import os
import urllib
from datetime import date, datetime, timedelta

import boto3
import stripe
from authlib.integrations.flask_client import OAuth
from email_validator import EmailNotValidError, validate_email
from flask import Flask, abort, flash, redirect, render_template, render_template_string, request, session, url_for

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", os.urandom(24))
app.config["profilePicBucket"] = os.getenv("PROFILE_PIC_BUCKET")
app.config["configBucket"] = os.getenv("CONFIG_BUCKET")
app.config["mediaBucket"] = os.getenv("PUBLIC_MEDIA_BUCKET")
if os.getenv("FLASK_DEBUG"):
    app.config["URL"] = "http://localhost:5001"
else:
    app.config["URL"] = os.getenv("REG_URL")
app.config["SQS_QUEUE_URL"] = os.getenv("SQS_QUEUE_URL")
app.config["reg_table_name"] = os.getenv("REG_DB_TABLE")
app.config["auth_table_name"] = os.getenv("AUTH_DB_TABLE", "admin_auth_table")
app.config["lookup_table_name"] = os.getenv("LOOKUP_DB_TABLE", "reg_lookup_table")
stripe.api_key = os.getenv("STRIPE_API_KEY")
maps_api_key = os.getenv("MAPS_API_KEY")
aws_region = os.getenv("AWS_REGION", "us-east-1")
s3 = boto3.client("s3")
sqs = boto3.client("sqs")
dynamodb = boto3.client("dynamodb")
dynamodb_res = boto3.resource("dynamodb")
badges_enabled = os.getenv("ENABLE_BADGES", False)
address_enabled = os.getenv("ENABLE_ADDRESS", False)

# Oauth Login
oauth = OAuth(app)
oauth.register(
    name="oidc",
    authority=os.getenv("COGNITO_AUTHORITY_URL"),
    client_id=os.getenv("COGNITO_CLIENT_ID"),
    client_secret=os.getenv("COGNITO_CLIENT_SECRET"),
    server_metadata_url=f"{os.getenv('COGNITO_AUTHORITY_URL')}/.well-known/openid-configuration",
    client_kwargs={"scope": "phone openid email"},
)


def login_required(func):
    def auth_wrapper():
        user = session.get("user")
        if not user:
            return redirect(url_for("login"))
        elif "Admins" not in user.get("cognito:groups", []):
            flash("You are not authorized to view this page. Please contact the adminstrator.", "danger")
            return redirect(url_for("logout"))
        else:
            return func()

    auth_wrapper.__name__ = func.__name__
    return auth_wrapper


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


def get_s3_file(bucket, file_name):
    """
    Function to download a given file from an S3 bucket
    """
    if not os.path.exists("static/public_media"):
        os.makedirs("static/public_media")

    output = f"public_media/{os.path.basename(file_name)}"

    if not os.path.exists(output):
        try:
            s3.download_file(bucket, file_name, f"static/{output}")
        except Exception as e:
            print(f"Error downloading {file_name} from S3: {e}")
            return None

    return output


def format_medical_form(contacts, medicalConditions_list, allergy_list, medications_list):
    return dict(
        contacts=dict(S=contacts),
        medicalConditions=dict(L=[{"S": mc} for mc in medicalConditions_list if mc != ""]),
        allergies=dict(L=[{"S": a} for a in allergy_list if a != ""]),
        medications=dict(L=[{"S": m} for m in medications_list if m != ""]),
    )


@app.route("/login")
def login():
    return oauth.oidc.authorize_redirect(f"{app.config['URL']}/authorize")


@app.route("/authorize")
def authorize():
    token = oauth.oidc.authorize_access_token()
    user = token["userinfo"]
    session["user"] = user
    return redirect(f"{app.config['URL']}/admin")


@app.route("/logout")
def logout():
    index_page_uri = urllib.parse.quote_plus(url_for("index", _external=True))
    logout_uri = f"{os.getenv('COGNITO_AUTH_URL')}/logout?client_id={os.getenv('COGNITO_CLIENT_ID')}&logout_uri={index_page_uri}"
    session.pop("user", None)
    return redirect(logout_uri)


def render_base(content_file, **page_params):
    user = session.get("user")
    if user and "Admins" in user.get("cognito:groups", []):
        page_params["admin"] = True
    return render_template(
        "base.html",
        title=os.getenv("COMPETITION_NAME"),
        favicon_url=url_for("static", filename=get_s3_file(app.config["mediaBucket"], "favicon.png")),
        event_city=os.getenv("EVENT_CITY"),
        button_style=os.getenv("BUTTON_STYLE", "btn-primary"),
        form_js=url_for("static", filename="js/form.js"),
        address_enabled=address_enabled,
        maps_api_key=maps_api_key if address_enabled else None,
        content_file=content_file,
        **page_params,
    )


@app.route("/", methods=["GET"])
def index():
    page_params = {
        "email": os.getenv("CONTACT_EMAIL"),
        "early_reg_date": datetime.fromtimestamp(stripe.Coupon.list(limit=1).data[0]["redeem_by"]).strftime("%B %d, %Y"),
        "reg_close_date": os.getenv("REG_CLOSE_DATE"),
        "poster_url": url_for("static", filename=get_s3_file(app.config["mediaBucket"], "registration_poster.jpg")),
    }
    if request.headers.get("HX-Request"):
        return render_template("landing.html", **page_params)
    else:
        return render_base("landing.html", **page_params)


@app.route("/lookup_entry", methods=["POST"])
def lookup_entry():
    email = request.form.get("email")
    name = f"{request.form.get('fname','').lower()} {request.form.get('lname','').lower()}"
    entries = dynamodb.scan(
        TableName=app.config["lookup_table_name"],
        IndexName="email-index",
        FilterExpression="email = :email",
        ExpressionAttributeValues={
            ":email": {
                "S": email,
            },
        },
    )["Items"]

    if len(entries) > 1:
        if name != " ":
            entries = [e for e in entries if name.strip() in e["name"]["S"].lower()]

    return render_template("form/lookup_modal.html", entries=entries)


@app.route("/api/autofill", methods=["GET"])
def autofill():
    entry = json.loads(request.args.get("entry"))
    entry["fname"] = entry["name"]["S"].split()[0]
    entry["lname"] = entry["name"]["S"].split()[1]
    birthdate = datetime.strptime(entry["birthdate"]["S"], "%m/%d/%Y")
    entry["birthdate"] = birthdate.strftime("%Y-%m-%d")
    entry["age"] = str(date.today().year - birthdate.year)
    entry["age_group"] = get_age_group(int(entry["age"]))
    schools = json.load(s3.get_object(Bucket=app.config["configBucket"], Key="schools.json")["Body"])
    entry["allergy_list"] = [a["S"] for a in entry["medical_form"]["M"]["allergies"]["L"]]
    entry["meds_list"] = [m["S"] for m in entry["medical_form"]["M"]["medications"]["L"]]
    entry["medicalConditionsList"] = [mc["S"] for mc in entry["medical_form"]["M"]["medicalConditions"]["L"]]

    return render_template(
        "form/autofill.html",
        entry=entry,
        schools=schools,
    )


@app.route("/api/validate/name/<string:form_item_name>", methods=["POST"])
def api_validate_name(form_item_name):
    form_item = request.form.get(form_item_name)
    form_item_id = request.args.get(id, form_item_name)
    if form_item != "" and form_item.replace(" ", "").isalpha():
        form_item_valid = True
    else:
        form_item_valid = False

    return render_template(
        "validation/name.html",
        form_item=form_item,
        form_item_id=form_item_id,
        form_item_name=form_item_name,
        form_item_valid=form_item_valid,
    )


@app.route("/api/validate/number/<string:form_item_name>", methods=["POST"])
def api_validate_number(form_item_name):
    form_item = request.form.get(form_item_name)
    form_item_id = request.args.get("id", form_item_name)
    form_item_step = request.args.get("step", "1")
    form_item_min = request.args.get("min", "")
    form_item_max = request.args.get("max", "")

    if form_item != "" and form_item.isdigit():
        form_item_valid = True
    else:
        form_item_valid = False

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


@app.route("/api/validate/email", methods=["POST"])
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


@app.route("/api/validate/phone", methods=["POST"])
def api_validate_phone():
    phone_num = request.form.get("phone").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if phone_num != "" and phone_num.isdigit() and len(phone_num) == 10:
        phone_num = phone_num[0:3] + "-" + phone_num[3:6] + "-" + phone_num[6:]
        phone_valid = True
    else:
        phone_valid = False

    return render_template(
        "validation/phone.html",
        phone_num=phone_num,
        phone_valid=phone_valid,
    )


@app.route("/api/validate/birthdate", methods=["POST"])
def api_validate_birthdate():
    birthdate = datetime.strptime(request.form.get("birthdate"), "%Y-%m-%d")
    try:
        birthyear = birthdate.year
        curr_year = datetime.now().year
        age = curr_year - birthyear
        age_group = get_age_group(age)
        date_valid = True
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


@app.route("/api/validate/school", methods=["POST"])
def api_validate_school():
    school_selection = request.form.get("school")
    if school_selection != "":
        school_valid = True
    else:
        school_valid = False

    return render_template(
        "validation/school.html",
        school_selection=school_selection,
        school_valid=school_valid,
        schools=json.load(s3.get_object(Bucket=app.config["configBucket"], Key="schools.json")["Body"]),
    )


@app.route("/register", methods=["GET"])
def display_form():
    if date.today() > datetime.strptime(os.getenv("REG_CLOSE_DATE"), "%B %d, %Y").date():
        page_params = {
            "email": os.getenv("CONTACT_EMAIL"),
            "competition_name": os.getenv("COMPETITION_NAME"),
        }
        if request.headers.get("HX-Request"):
            return render_template("disabled.html", **page_params)
        else:
            return render_base("disabled.html", **page_params)
    else:
        early_reg_coupon = stripe.Coupon.list(limit=1).data[0]
        reg_type = request.args.get("reg_type")
        school_list = json.load(s3.get_object(Bucket=app.config["configBucket"], Key="schools.json")["Body"])

        # Display the form
        page_params = {
            "early_reg_date": datetime.fromtimestamp(early_reg_coupon["redeem_by"]),
            "early_reg_coupon_amount": f'{int(early_reg_coupon["amount_off"]/100)}',
            "price_dict": get_price_details(),
            "reg_type": reg_type,
            "schools": school_list,
            "enable_badges": badges_enabled,
            "enable_address": address_enabled,
        }
        if request.headers.get("HX-Request"):
            return render_template("form.html", button_style=os.getenv("BUTTON_STYLE", "btn-primary"), **page_params)
        else:
            return render_base("form.html", **page_params)


@app.route("/register", methods=["POST"])
def handle_form():
    price_dict = get_price_details()
    reg_type = request.form.get("regType")

    # Name
    fname = request.form.get("fname").strip()
    lname = request.form.get("lname").strip()
    fullName = f"{fname}_{lname}"

    school = request.form.get("school")
    if school == "unlisted":
        school = request.form.get("unlistedSchool").strip()
    coach = request.form.get("coach").strip()

    # Check if registration already exists
    # if not os.getenv("FLASK_DEBUG"):
    pk_school_name = school.replace(" ", "_")
    pk_exists = dynamodb.get_item(
        TableName=app.config["reg_table_name"],
        Key={"pk": {"S": f"{pk_school_name}-{reg_type}-{fullName}"}},
    )

    if "Item" in pk_exists:
        print("registration exists")
        return redirect(f'{app.config["URL"]}/registration_error?reg_type={reg_type}')

    # Base Form Data
    form_data = dict(
        full_name={"S": f"{fname} {lname}"},
        email={"S": request.form.get("email")},
        phone={"S": request.form.get("phone")},
        school={"S": school},
        reg_type={"S": request.form.get("regType")},
    )

    # Add Competitor Form Data
    if reg_type == "competitor":
        if request.form.get("liability") != "on":
            msg = "Please go back and accept the Liability Waiver Conditions"
            abort(400, msg)

        height = (int(request.form.get("heightFt")) * 12) + int(request.form.get("heightIn"))
        belt = request.form.get("beltRank")
        if belt == "black":
            dan = request.form.get("blackBeltDan")
            if dan == "4":
                belt = "Master"
            else:
                belt = f"{dan} degree {belt}"
        eventList = request.form.get("eventList")
        if eventList == "":
            msg = "You must choose at least one event"
            abort(400, msg)

        medical_form = format_medical_form(
            request.form.get("contacts"),
            request.form.get("medicalConditionsList").split(","),
            request.form.get("allergy_list").split("\r\n"),
            request.form.get("meds_list").split("\r\n"),
        )

        form_data.update(
            dict(
                parent={"S": request.form.get("parentName")},
                birthdate={"S": request.form.get("birthdate")},
                age={"N": request.form.get("age")},
                gender={"S": request.form.get("gender")},
                weight={"N": request.form.get("weight")},
                height={"N": str(height)},
                coach={"S": coach},
                beltRank={"S": belt},
                events={"S": eventList},
                poomsae_form={"S": request.form.get("poomsae form")},
                pair_poomsae_form={"S": request.form.get("pair poomsae form")},
                team_poomsae_form={"S": request.form.get("team poomsae form")},
                family_poomsae_form={"S": request.form.get("family poomsae form")},
                medical_form={"M": medical_form},
            )
        )
        if badges_enabled:
            profileImg = request.files["profilePic"]
            imageExt = os.path.splitext(profileImg.filename)[1]
            if profileImg.content_type == "" or imageExt == "":
                msg = "There was an error uploading your profile pic. Please go back and try again."
                abort(400, msg)

            form_data.update(dict(imgFilename={"S": f"{school}_{reg_type}_{fullName}{imageExt}"}))

            s3.upload_fileobj(
                profileImg,
                app.config["profilePicBucket"],
                form_data["imgFilename"]["S"],
            )

        events_list = eventList.split(",")
        if request.form.get("beltRank") == "black":
            registration_items = [
                {
                    "price": price_dict["Black Belt Registration"]["price_id"],
                    "quantity": 1,
                },
            ]
        else:
            registration_items = [
                {
                    "price": price_dict["Color Belt Registration"]["price_id"],
                    "quantity": 1,
                },
            ]
        num_add_event = len(events_list) - 1
        if "little_dragon" in eventList.split(","):
            form_data.update(dict(tshirt={"S": request.form.get("t-shirt")}))
            if num_add_event == 0:
                registration_items = [
                    {
                        "price": price_dict["Little Dragon Obstacle Course"]["price_id"],
                        "quantity": 1,
                    },
                ]
            else:
                registration_items.append = (
                    {
                        "price": price_dict["Little Dragon Obstacle Course"]["price_id"],
                        "quantity": 1,
                    },
                )
        if num_add_event > 0:
            registration_items.append(
                {
                    "price": price_dict["Additional Event"]["price_id"],
                    "quantity": num_add_event,
                },
            )
        # Code to have 'convenience fee' transfered to separate acct ###
        registration_items.append({"price": price_dict["Convenience Fee"]["price_id"], "quantity": 1})
    else:
        registration_items = [
            {
                "price": price_dict["Coach Registration"]["price_id"],
                "quantity": 1,
            }
        ]

    if os.getenv("FLASK_DEBUG"):
        # For Testing Form Data
        return render_template(
            "success.html",
            competition_name=os.getenv("COMPETITION_NAME"),
            email=os.getenv("CONTACT_EMAIL"),
            reg_detail=form_data,
            cost_detail=registration_items,
        )
    else:
        early_reg_coupon = stripe.Coupon.list(limit=1).data[0]
        try:
            early_reg_date = datetime.fromtimestamp(early_reg_coupon["redeem_by"])
            current_time = datetime.now()
            checkout_timeout = current_time + timedelta(minutes=30)
            checkout_details = {
                "line_items": registration_items,
                "mode": "payment",
                "discounts": [],
                # "success_url": f'{app.config["URL"]}/success',
                # Code to have 'convenience fee' transfered to separate acct ###
                "success_url": f'{app.config["URL"]}/success?reg_type={reg_type}&session_id={{CHECKOUT_SESSION_ID}}',
                "cancel_url": f'{app.config["URL"]}/register?reg_type={reg_type}',
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

        form_data.update(dict(checkout={"S": checkout_session.id}))
        sqs.send_message(
            QueueUrl=app.config["SQS_QUEUE_URL"],
            DelaySeconds=120,
            MessageAttributes={
                "Name": {"DataType": "String", "StringValue": fullName},
                "Transaction": {
                    "DataType": "String",
                    "StringValue": checkout_session.id,
                },
            },
            MessageBody=json.dumps(form_data),
        )

        return redirect(checkout_session.url, code=303)


@app.route("/registration_error", methods=["GET"])
def error_page():
    page_params = {
        "reg_type": request.args.get("reg_type"),
        "email": os.getenv("CONTACT_EMAIL"),
        "competition_name": os.getenv("COMPETITION_NAME"),
    }
    if request.headers.get("HX-Request"):
        return render_template("registration_error.html", button_style=os.getenv("BUTTON_STYLE", "btn-primary"), **page_params)
    else:
        return render_base("registration_error.html", **page_params)


@app.route("/visit", methods=["GET"])
def visit_page():
    if request.headers.get("HX-Request"):
        return render_template("tulsa.html")
    else:
        return render_base("tulsa.html")


@app.route("/schedule", methods=["GET"])
def schedule_page():
    if request.headers.get("HX-Request"):
        return render_template("schedule.html")
    else:
        return render_base("schedule.html")


@app.route("/get_schedule_details", methods=["GET"])
def schedule_details():
    if schedule_img_file := get_s3_file(app.config["configBucket"], "schedule.png"):
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
    elif schedule_json := get_s3_file(app.config["configBucket"], "schedule.json"):
        schedule_dict = json.load(open(os.path.join(app.static_folder, schedule_json), "r"))
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
                            <td {% if item.title_class is defined -%}class="{{item.title_class}}" {%endif%}>{{ item.title | safe }}
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
    else:
        return render_template_string('<div align="center">Schedule not found</div>')


@app.route("/api/upload/<string:resource>", methods=["GET"])
def upload_form(resource):
    return render_template(
        "upload.html",
        title=f"Upload {resource.capitalize()}",
        competition_name=os.getenv("COMPETITION_NAME"),
        favicon_url=url_for("static", filename=get_s3_file(app.config["mediaBucket"], "favicon.png")),
        event_city=os.getenv("EVENT_CITY"),
        button_style=os.getenv("BUTTON_STYLE", "btn-primary"),
        resource=resource,
    )


@app.route("/api/upload/<string:resource>", methods=["POST"])
def upload_item(resource):
    upload_item = request.files["uploadFile"]
    if resource == "schedule":
        bucket = app.config["configBucket"]
        filename = "schedule.png"
    elif resource == "booklet":
        bucket = app.config["mediaBucket"]
        filename = "information_booklet.pdf"

    s3.upload_fileobj(
        upload_item,
        bucket,
        filename,
    )

    flash(f"{resource} updated successfully!", "success")
    return redirect(f'{app.config["URL"]}/admin', code=303)


@app.route("/information", methods=["GET"])
def info_page():
    s3_addl_images = s3.list_objects(Bucket=app.config["mediaBucket"], Prefix="additional_information_images/")["Contents"]
    page_params = {
        "information_booklet_url": url_for("static", filename=get_s3_file(app.config["mediaBucket"], "information_booklet.pdf")),
        "additional_imgs": [
            url_for("static", filename=get_s3_file(app.config["mediaBucket"], i["Key"])) for i in s3_addl_images if i["Size"] > 0
        ],
    }
    if request.headers.get("HX-Request"):
        return render_template("information.html", button_style=os.getenv("BUTTON_STYLE", "btn-primary"), **page_params)
    else:
        return render_base("information.html", **page_params)


def get_age_group(age):
    age_groups = {
        "dragon": [4, 5, 6, 7],
        "tiger": [8, 9],
        "youth": [10, 11],
        "cadet": [12, 13, 14],
        "junior": [15, 16],
        "senior": list(range(17, 33)),
        "ultra": list(range(33, 100)),
    }

    age_group = next((group for group, ages in age_groups.items() if int(age) in ages))

    return age_group


def set_weight_class(entries):
    s3 = boto3.client("s3")
    weight_classes = json.load(s3.get_object(Bucket=app.config["configBucket"], Key="weight_classes.json")["Body"])
    updated_entries = []
    for entry in entries:
        if entry["reg_type"] == "competitor":
            age_group = get_age_group(entry["age"]["N"])
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


@app.route("/api/entries", methods=["GET"])
def entries_api():
    entries = dynamodb.scan(TableName=app.config["reg_table_name"])["Items"]
    entries = set_weight_class(entries)
    for i, e in enumerate(entries):
        if "events" in e:
            e["events"]["S"] = e["events"]["S"].split(",")
            entries[i] = e

    return {"data": entries}


@app.route("/entries", methods=["GET"])
def entries_page():
    if request.headers.get("HX-Request"):
        return render_template("entries.html")
    else:
        return render_base("entries.html")


@app.route("/admin")
@login_required
def admin_page():
    entries = dynamodb.scan(
        TableName=app.config["reg_table_name"],
    )["Items"]
    page_params = {"entries": entries}
    if request.headers.get("HX-Request"):
        return render_template("admin.html", button_style=os.getenv("BUTTON_STYLE", "btn-primary"), **page_params)
    else:
        return render_base("admin.html", **page_params)


@app.route("/add_entry")
@login_required
def add_entry_form():
    early_reg_coupon = stripe.Coupon.list(limit=1).data[0]
    reg_type = request.args.get("reg_type")
    school_list = json.load(s3.get_object(Bucket=app.config["configBucket"], Key="schools.json")["Body"])
    page_params = {
        "price_dict": get_price_details(),
        "early_reg_date": datetime.fromtimestamp(early_reg_coupon["redeem_by"]),
        "early_reg_coupon_amount": f'{int(early_reg_coupon["amount_off"]/100)}',
        "badge_enabled": badges_enabled,
        "address_enabled": address_enabled,
        "maps_api_key": maps_api_key,
        "reg_type": reg_type,
        "schools": school_list,
        "enable_badges": badges_enabled,
        "enable_address": address_enabled,
    }
    if request.headers.get("HX-Request"):
        return render_template("add_entry.html", button_style=os.getenv("BUTTON_STYLE", "btn-primary"), **page_params)
    else:
        return render_base("add_entry.html", **page_params)


@app.route("/add_entry", methods=["POST"])
@login_required
def add_entry():
    reg_type = request.form.get("regType")

    # Name
    fname = request.form.get("fname").strip()
    lname = request.form.get("lname").strip()
    fullName = f"{fname}_{lname}"

    school = request.form.get("school")
    coach = request.form.get("coach").strip()

    # Check if registration already exists
    if not os.getenv("FLASK_DEBUG"):
        pk_school_name = school.replace(" ", "_")
        pk_exists = dynamodb.get_item(
            TableName=app.config["reg_table_name"],
            Key={"pk": {"S": f"{pk_school_name}-{reg_type}-{fullName}"}},
        )

        if "Item" in pk_exists:
            print("registration exists")
            return redirect(f'{app.config["URL"]}/registration_error?reg_type={reg_type}')

    # Base Form Data
    form_data = dict(
        full_name={"S": f"{fname} {lname}"},
        email={"S": request.form.get("email")},
        phone={"S": request.form.get("phone")},
        school={"S": school},
        reg_type={"S": request.form.get("regType")},
    )

    # Add Competitor Form Data
    if reg_type == "competitor":
        height = (int(request.form.get("heightFt")) * 12) + int(request.form.get("heightIn"))
        belt = request.form.get("beltRank")
        if belt == "black":
            dan = request.form.get("blackBeltDan")
            if dan == "4":
                belt = "Master"
            else:
                belt = f"{dan} degree {belt}"

        eventList = request.form.get("eventList")
        if eventList == "":
            msg = "You must choose at least one event"
            abort(400, msg)

        medical_form = format_medical_form(
            request.form.get("contacts"),
            request.form.get("medicalConditionsList").split(","),
            request.form.get("allergy_list").split("\r\n"),
            request.form.get("meds_list").split("\r\n"),
        )

        form_data.update(
            dict(
                parent={"S": request.form.get("parentName")},
                birthdate={"S": request.form.get("birthdate")},
                age={"N": request.form.get("age")},
                gender={"S": request.form.get("gender")},
                weight={"N": request.form.get("weight")},
                height={"N": str(height)},
                coach={"S": coach},
                beltRank={"S": belt},
                events={"S": eventList},
                poomsae_form={"S": request.form.get("poomsae form")},
                pair_poomsae_form={"S": request.form.get("pair poomsae form")},
                team_poomsae_form={"S": request.form.get("team poomsae form")},
                family_poomsae_form={"S": request.form.get("family poomsae form")},
                medical_form={"M": medical_form},
            )
        )
        if badges_enabled:
            profileImg = request.files["profilePic"]
            imageExt = os.path.splitext(profileImg.filename)[1]
            if profileImg.content_type == "" or imageExt == "":
                msg = "There was an error uploading your profile pic. Please go back and try again."
                abort(400, msg)

            form_data.update(dict(imgFilename={"S": f"{school}_{reg_type}_{fullName}{imageExt}"}))

            s3.upload_fileobj(
                profileImg,
                app.config["profilePicBucket"],
                form_data["imgFilename"]["S"],
            )

    if os.getenv("FLASK_DEBUG"):
        # For Testing Form Data
        return render_template(
            "success.html",
            competition_name=os.getenv("COMPETITION_NAME"),
            email=os.getenv("CONTACT_EMAIL"),
            reg_detail=form_data,
        )
    else:
        form_data.update(dict(checkout={"S": "manual_entry"}))
        sqs.send_message(
            QueueUrl=app.config["SQS_QUEUE_URL"],
            DelaySeconds=120,
            MessageAttributes={
                "Name": {"DataType": "String", "StringValue": fullName},
                "Transaction": {
                    "DataType": "String",
                    "StringValue": "manual_entry",
                },
            },
            MessageBody=json.dumps(form_data),
        )

        flash(f"{form_data['full_name']['S']} added successfully!", "success")
        return redirect(f'{app.config["URL"]}/admin', code=303)


@app.route("/edit_entry")
@login_required
def edit_entry_form():
    pk = request.args.get("pk")
    entry = dynamodb.get_item(
        TableName=app.config["reg_table_name"],
        Key={"pk": {"S": pk}},
    )["Item"]
    school_list = json.load(s3.get_object(Bucket=app.config["configBucket"], Key="schools.json")["Body"])
    page_params = {
        "schools": school_list,
        "entry": entry,
    }
    if request.headers.get("HX-Request"):
        return render_template("edit.html", button_style=os.getenv("BUTTON_STYLE", "btn-primary"), **page_params)
    else:
        return render_base("edit.html", **page_params)


@app.route("/edit", methods=["POST"])
@login_required
def edit_entry():
    form_data = dict(
        full_name={"S": request.form.get("full_name")},
        email={"S": request.form.get("email")},
        phone={"S": request.form.get("phone")},
        school={"S": request.form.get("school")},
        reg_type={"S": request.form.get("regType")},
    )
    if form_data["reg_type"]["S"] == "competitor":
        belt = request.form.get("beltRank")
        if belt == "black":
            dan = request.form.get("blackBeltDan")
            if dan == "4":
                belt = "Master"
            else:
                belt = f"{dan} degree {belt}"
        form_data.update(
            dict(
                parent={"S": request.form.get("parentName")},
                birthdate={"S": request.form.get("birthdate")},
                age={"N": request.form.get("age")},
                gender={"S": request.form.get("gender")},
                weight={"N": request.form.get("weight")},
                height={"N": request.form.get("height")},
                coach={"S": request.form.get("coach").strip()},
                beltRank={"S": belt},
                poomsae_form={"S": request.form.get("poomsae form")},
                pair_poomsae_form={"S": request.form.get("pair poomsae form")},
                team_poomsae_form={"S": request.form.get("team poomsae form")},
                family_poomsae_form={"S": request.form.get("family poomsae form")},
            )
        )
        update_expression = "SET {}".format(",".join(f"#{k}=:{k}" for k in form_data))
        expression_attribute_values = {f":{k}": v for k, v in form_data.items()}
        expression_attribute_names = {f"#{k}": k for k in form_data}

        dynamodb.update_item(
            TableName=app.config["reg_table_name"],
            Key={
                "pk": {"S": request.args.get("pk")},
            },
            UpdateExpression=update_expression,
            ExpressionAttributeValues=expression_attribute_values,
            ExpressionAttributeNames=expression_attribute_names,
            ReturnValues="UPDATED_NEW",
        )

    flash(f'{form_data["full_name"]["S"]} updated successfully!', "success")
    return redirect(f'{app.config["URL"]}/admin', code=303)


@app.route("/export")
@login_required
def generate_csv():
    data = dynamodb.scan(
        TableName=app.config["reg_table_name"],
        FilterExpression="reg_type = :type",
        ExpressionAttributeValues={
            ":type": {
                "S": "competitor",
            },
        },
    )["Items"]
    entries = sorted(data, key=lambda item: item["full_name"]["S"].split()[-1])
    return render_template(
        "export.html",
        competition_year=os.getenv("COMPETITION_YEAR"),
        competition_name=os.getenv("COMPETITION_NAME"),
        favicon_url=url_for("static", filename=get_s3_file(app.config["mediaBucket"], "favicon.png")),
        button_style=os.getenv("BUTTON_STYLE", "btn-primary"),
        entries=entries,
    )


@app.errorhandler(404)
def page_not_found(e):
    return render_base("404.html"), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0")
