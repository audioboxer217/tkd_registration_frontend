import json
import os
from datetime import date, datetime, timedelta

import boto3
import stripe
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from boto3.dynamodb.conditions import Key
from flask import Flask, abort, flash, redirect, render_template, request, url_for
from flask_login import LoginManager, UserMixin, login_required, login_user, logout_user

app = Flask(__name__)
app.secret_key = os.urandom(12)
app.config["configBucket"] = os.getenv("CONFIG_BUCKET")
app.config["mediaBucket"] = os.getenv("PUBLIC_MEDIA_BUCKET")
if os.getenv("FLASK_DEBUG"):
    app.config["URL"] = "http://127.0.0.1:5001"
else:
    app.config["URL"] = os.getenv("REG_URL")
app.config["SQS_QUEUE_URL"] = os.getenv("SQS_QUEUE_URL")
app.config["reg_table_name"] = os.getenv("REG_DB_TABLE")
app.config["auth_table_name"] = os.getenv("AUTH_DB_TABLE", "admin_auth_table")
app.config["lookup_table_name"] = os.getenv("LOOKUP_DB_TABLE", "reg_lookup_table")
app.config["sizes"] = os.getenv("SIZES", "XS,S,M,L,XL,XXL").split(",")
stripe.api_key = os.getenv("STRIPE_API_KEY")
aws_region = os.getenv("AWS_REGION", "us-east-1")
s3 = boto3.client("s3")
sqs = boto3.client("sqs")
dynamodb = boto3.client("dynamodb")
dynamodb_res = boto3.resource("dynamodb")
button_style = os.getenv("BUTTON_STYLE", "btn-primary")

# Login
login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.init_app(app)
ph = PasswordHasher()


class User(UserMixin):
    def __init__(self, id, email, name, password):
        self.id = id
        self.email = email
        self.name = name
        self.password = password

# early_reg_coupon = stripe.Coupon.list(limit=1).data[0]


def get_price_details():
    # Price Details
    price_dict = {}
    products = stripe.Product.list()
    for p in products:
        price_detail = stripe.Price.retrieve(p.default_price)
        price_dict[p.name] = {
            "price_id": price_detail.id,
            "price": f"{int(price_detail.unit_amount/100)}",
        }
    return price_dict


@login_manager.user_loader
def loader(user_id):
    auth_table = dynamodb_res.Table(app.config["auth_table_name"])
    response = auth_table.query(KeyConditionExpression=Key("id").eq(str(user_id)))

    if response["Count"] == 0:
        return
    user = User(
        id=response["Items"][0]["id"],
        email=response["Items"][0]["email"],
        name=response["Items"][0]["name"],
        password=response["Items"][0]["password"],
    )
    return user


def get_user(email):
    response = dynamodb.scan(
        TableName=app.config["auth_table_name"],
        FilterExpression="email = :email",
        ExpressionAttributeValues={
            ":email": {
                "S": email,
            },
        },
    )

    if response["Count"] == 0:
        return
    user = User(
        id=response["Items"][0]["id"]["S"],
        email=response["Items"][0]["email"]["S"],
        name=response["Items"][0]["name"]["S"],
        password=response["Items"][0]["password"]["S"],
    )
    return user


def get_s3_file(bucket, file_name):
    """
    Function to download a given file from an S3 bucket
    """
    if not os.path.exists("static/public_media"):
        os.makedirs("static/public_media")

    output = f"public_media/{os.path.basename(file_name)}"

    if not os.path.exists(output):
        s3.download_file(bucket, file_name, f"static/{output}")

    return output


@app.route("/login")
def login():
    return render_template(
        "login.html",
        title="Login",
        favicon_url=url_for("static", filename=get_s3_file(app.config["mediaBucket"], "favicon.png")),
        button_style=button_style,
        competition_name=os.getenv("COMPETITION_NAME"),
    )


@app.route("/login", methods=["POST"])
def login_post():
    # login code goes here
    email = request.form.get("email").lower()
    password = request.form.get("password")
    remember = True if request.form.get("remember") else False

    user = get_user(email)
    # check if the user actually exists
    if not user:
        flash("Please check your login details and try again.")
        return redirect(url_for("login"))
    try:
        ph.verify(user.password, password)
    except VerifyMismatchError:
        flash("Please check your login details and try again.")
        return redirect(url_for("login"))

    # if the above check passes, then we know the user has the right credentials
    login_user(user, remember=remember)
    return redirect(url_for("admin_page"))


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(app.config["URL"])


@app.route("/")
def index_page():
    return render_template(
        "index.html",
        title=os.getenv("COMPETITION_NAME"),
        email=os.getenv("CONTACT_EMAIL"),
        competition_name=os.getenv("COMPETITION_NAME"),
        early_reg_date=os.getenv("EARLY_REG_DATE"),
        reg_close_date=os.getenv("REG_CLOSE_DATE"),
        favicon_url=url_for("static", filename=get_s3_file(app.config["mediaBucket"], "favicon.png")),
        button_style=button_style,
        poster_url=url_for("static", filename=get_s3_file(app.config["mediaBucket"], "registration_poster.jpg")),
    )


@app.route("/lookup_entry")
def lookup_entry():
    email = request.args.get("email")
    name = f"{request.args.get('fname','').lower()} {request.args.get('lname','').lower()}"
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

    return entries


@app.route("/register", methods=["GET"])
def display_form():
    if date.today() > datetime.strptime(os.getenv("REG_CLOSE_DATE"), "%B %d, %Y").date():
        return render_template(
            "disabled.html",
            title="Registration Closed",
            favicon_url=url_for("static", filename=get_s3_file(app.config["mediaBucket"], "favicon.png")),
            button_style=button_style,
            competition_name=os.getenv("COMPETITION_NAME"),
            email=os.getenv("CONTACT_EMAIL"),
        )
    else:
        # Display the form
        school_list = json.load(s3.get_object(Bucket=app.config["configBucket"], Key="schools.json")["Body"])
        return render_template(
            "form.html",
            title="Registration",
            favicon_url=url_for("static", filename=get_s3_file(app.config["mediaBucket"], "favicon.png")),
            button_style=button_style,
            competition_name=os.getenv("COMPETITION_NAME"),
            competition_year=os.getenv("COMPETITION_YEAR"),
            early_reg_date=os.getenv("EARLY_REG_DATE"),
            # early_reg_coupon_amount=f'{int(early_reg_coupon["amount_off"]/100)}',
            price_dict=get_price_details(),
            schools=school_list,
            additional_scripts=[
                dict(
                    src="https://ajax.googleapis.com/ajax/libs/jquery/3.4.1/jquery.min.js",
                    integrity="sha384-vk5WoKIaW/vJyUAd9n/wmopsmNhiy+L2Z+SBxGYnUkunIxVxAv/UtMOhba/xskxh",
                ),
                dict(
                    src="https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.1.3/js/bootstrap.min.js",
                    integrity="sha384-QJHtvGhmr9XOIpI6YVutG+2QOK9T+ZnN4kzFN1RtK3zEFEIsxhlmWl5/YESvpZ13",
                ),
                dict(src=url_for("static", filename="js/form.js")),
            ],
        )


@app.route("/register", methods=["POST"])
def handle_form():
    price_dict = get_price_details()

    # Name
    fname = request.form.get("fname").strip()
    lname = request.form.get("lname").strip()
    fullName = f"{fname}_{lname}"

    school = request.form.get("school")
    if school == "unlisted":
        school = request.form.get("unlistedSchool").strip()

    # Check if registration already exists
    if not os.getenv("FLASK_DEBUG"):
        pk_school_name = school.replace(" ", "_")
        pk_exists = dynamodb.get_item(
            TableName=app.config["reg_table_name"],
            Key={"pk": {"S": f"{pk_school_name}-seminar-{fullName}"}},
        )

        if "Item" in pk_exists:
            print("registration exists")
            return redirect(f'{app.config["URL"]}/registration_error')

    belt = request.form.get("beltRank")
    if belt == "black":
        dan = request.form.get("blackBeltDan")
        if dan == "4":
            belt = "Master"
        else:
            belt = f"{dan} degree {belt}"

    # Base Form Data
    form_data = dict(
        full_name={"S": f"{fname} {lname}"},
        email={"S": request.form.get("email")},
        phone={"S": request.form.get("phone")},
        school={"S": school},
        reg_type={"S": "seminar"},
        parent={"S": request.form.get("parentName")},
        birthdate={"S": request.form.get("birthdate")},
        age={"N": request.form.get("age")},
        gender={"S": request.form.get("gender")},
        beltRank={"S": belt},
    )

    registration_items = [
        {
            "price": price_dict["Registration"]["price_id"],
            "quantity": 1,
        },
    ]

    if os.getenv("FLASK_DEBUG"):
        # For Testing Form Data
        return render_template(
            "success.html",
            title="Registration Submitted",
            competition_name=os.getenv("COMPETITION_NAME"),
            favicon_url=url_for("static", filename=get_s3_file(app.config["mediaBucket"], "favicon.png")),
            button_style=button_style,
            email=os.getenv("CONTACT_EMAIL"),
            reg_detail=form_data,
            cost_detail=registration_items,
        )
    else:
        try:
            early_reg_date = datetime.strptime(os.getenv("EARLY_REG_DATE"), "%B %d, %Y") + timedelta(days=1)
            current_time = datetime.now()
            checkout_timeout = current_time + timedelta(minutes=30)
            checkout_details = {
                "line_items": registration_items,
                "mode": "payment",
                "discounts": [],
                # "success_url": f'{app.config["URL"]}/success',
                # Code to have 'convenience fee' transfered to separate acct ###
                "success_url": f'{app.config["URL"]}/success?session_id={{CHECKOUT_SESSION_ID}}',
                "cancel_url": f'{app.config["URL"]}/register',
                "expires_at": int(checkout_timeout.timestamp()),
            }
            # if current_time < early_reg_date:
            #     checkout_details["discounts"].append({"coupon": early_reg_coupon["id"]})
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


@app.route("/tickets", methods=["GET"])
def tickets_page():
    if date.today() > datetime.strptime(os.getenv("REG_CLOSE_DATE"), "%B %d, %Y").date():
        return render_template(
            "disabled.html",
            title="Registration Closed",
            favicon_url=url_for("static", filename=get_s3_file(app.config["mediaBucket"], "favicon.png")),
            competition_name=os.getenv("COMPETITION_NAME"),
            email=os.getenv("CONTACT_EMAIL"),
        )
    else:
        # Display the form
        return render_template(
            "tickets.html",
            title="Tickets",
            favicon_url=url_for("static", filename=get_s3_file(app.config["mediaBucket"], "favicon.png")),
            button_style=button_style,
            competition_name=os.getenv("COMPETITION_NAME"),
            competition_year=os.getenv("COMPETITION_YEAR"),
            early_reg_date=os.getenv("EARLY_REG_DATE"),
            # early_reg_coupon_amount=f'{int(early_reg_coupon["amount_off"]/100)}',
            price_dict=get_price_details(),
            additional_scripts=[
                dict(
                    src="https://ajax.googleapis.com/ajax/libs/jquery/3.4.1/jquery.min.js",
                    integrity="sha384-vk5WoKIaW/vJyUAd9n/wmopsmNhiy+L2Z+SBxGYnUkunIxVxAv/UtMOhba/xskxh",
                ),
                dict(
                    src="https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.1.3/js/bootstrap.min.js",
                    integrity="sha384-QJHtvGhmr9XOIpI6YVutG+2QOK9T+ZnN4kzFN1RtK3zEFEIsxhlmWl5/YESvpZ13",
                ),
                dict(src=url_for("static", filename="js/form.js")),
            ],
        )


@app.route("/tickets", methods=["POST"])
def purchase_tickets():
    price_dict = get_price_details()

    # Name
    fname = request.form.get("fname").strip()
    lname = request.form.get("lname").strip()
    fullName = f"{fname}_{lname}"

    # Check if registration already exists
    if not os.getenv("FLASK_DEBUG"):
        pk_exists = dynamodb.get_item(
            TableName=app.config["reg_table_name"],
            Key={"pk": {"S": f"tickets-{fullName}"}},
        )

        if "Item" in pk_exists:
            print("registration exists")
            return redirect(f'{app.config["URL"]}/registration_error')

    # Base Form Data
    form_data = dict(
        full_name={"S": f"{fname} {lname}"},
        email={"S": request.form.get("email")},
        phone={"S": request.form.get("phone")},
        reg_type={"S": "tickets"},
        num_tickets={"N": request.form.get("tickets")},
    )

    registration_items = [
        {
            "price": price_dict["TKD Demonstration Show Ticket"]["price_id"],
            "quantity": request.form.get("tickets"),
        },
        {"price": price_dict["Convenience Fee"]["price_id"], "quantity": 1},
    ]

    if os.getenv("FLASK_DEBUG"):
        # For Testing Form Data
        return render_template(
            "success.html",
            title="Registration Submitted",
            competition_name=os.getenv("COMPETITION_NAME"),
            favicon_url=url_for("static", filename=get_s3_file(app.config["mediaBucket"], "favicon.png")),
            button_style=button_style,
            email=os.getenv("CONTACT_EMAIL"),
            reg_detail=form_data,
            cost_detail=registration_items,
        )
    else:
        try:
            # early_reg_date = datetime.strptime(os.getenv("EARLY_REG_DATE"), "%B %d, %Y") + timedelta(days=1)
            current_time = datetime.now()
            checkout_timeout = current_time + timedelta(minutes=30)
            checkout_details = {
                "line_items": registration_items,
                "mode": "payment",
                "discounts": [],
                # "success_url": f'{app.config["URL"]}/success',
                # Code to have 'convenience fee' transfered to separate acct ###
                "success_url": f'{app.config["URL"]}/success?session_id={{CHECKOUT_SESSION_ID}}',
                "cancel_url": f'{app.config["URL"]}/tickets',
                "expires_at": int(checkout_timeout.timestamp()),
            }
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


@app.route("/purchase", methods=["GET"])
def purchase_page():
    if date.today() > datetime.strptime(os.getenv("REG_CLOSE_DATE"), "%B %d, %Y").date():
        return render_template(
            "disabled.html",
            title="Registration Closed",
            favicon_url=url_for("static", filename=get_s3_file(app.config["mediaBucket"], "favicon.png")),
            competition_name=os.getenv("COMPETITION_NAME"),
            email=os.getenv("CONTACT_EMAIL"),
        )
    else:
        # Display the form
        return render_template(
            "purchase.html",
            title="Purchase Additional",
            favicon_url=url_for("static", filename=get_s3_file(app.config["mediaBucket"], "favicon.png")),
            button_style=button_style,
            competition_name=os.getenv("COMPETITION_NAME"),
            competition_year=os.getenv("COMPETITION_YEAR"),
            early_reg_date=os.getenv("EARLY_REG_DATE"),
            # early_reg_coupon_amount=f'{int(early_reg_coupon["amount_off"]/100)}',
            price_dict=get_price_details(),
            sizes=enumerate(app.config["sizes"]),
            additional_scripts=[
                dict(
                    src="https://ajax.googleapis.com/ajax/libs/jquery/3.4.1/jquery.min.js",
                    integrity="sha384-vk5WoKIaW/vJyUAd9n/wmopsmNhiy+L2Z+SBxGYnUkunIxVxAv/UtMOhba/xskxh",
                ),
                dict(
                    src="https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.1.3/js/bootstrap.min.js",
                    integrity="sha384-QJHtvGhmr9XOIpI6YVutG+2QOK9T+ZnN4kzFN1RtK3zEFEIsxhlmWl5/YESvpZ13",
                ),
                dict(src=url_for("static", filename="js/form.js")),
            ],
        )


@app.route("/purchase", methods=["POST"])
def purchase():
    price_dict = get_price_details()

    # Name
    fname = request.form.get("fname").strip()
    lname = request.form.get("lname").strip()
    fullName = f"{fname}_{lname}"

    # Check if registration already exists
    if not os.getenv("FLASK_DEBUG"):
        pk_exists = dynamodb.get_item(
            TableName=app.config["reg_table_name"],
            Key={"pk": {"S": f"purchase-{fullName}"}},
        )

        if "Item" in pk_exists:
            print("registration exists")
            return redirect(f'{app.config["URL"]}/registration_error')

    # Base Form Data
    form_data = dict(
        full_name={"S": f"{fname} {lname}"},
        email={"S": request.form.get("email")},
        phone={"S": request.form.get("phone")},
        reg_type={"S": "purchase"},
        num_tickets={"N": request.form.get("tickets")},
    )

    tshirts = dict(M={f"tshirt_{size}": {"N": request.form.get(f"tshirt_{size}")} for size in app.config["sizes"]})
    form_data.update(tshirts)
    tshirt_quantity = sum([int(tshirts["M"][f"tshirt_{size}"]["N"]) for size in app.config["sizes"]])

    registration_items = [
        {
            "price": price_dict["T-Shirt"]["price_id"],
            "quantity": tshirt_quantity,
        },
        {"price": price_dict["Convenience Fee"]["price_id"], "quantity": 1},
    ]

    if os.getenv("FLASK_DEBUG"):
        # For Testing Form Data
        return render_template(
            "success.html",
            title="Registration Submitted",
            competition_name=os.getenv("COMPETITION_NAME"),
            favicon_url=url_for("static", filename=get_s3_file(app.config["mediaBucket"], "favicon.png")),
            button_style=button_style,
            email=os.getenv("CONTACT_EMAIL"),
            reg_detail=form_data,
            cost_detail=registration_items,
        )
    else:
        try:
            # early_reg_date = datetime.strptime(os.getenv("EARLY_REG_DATE"), "%B %d, %Y") + timedelta(days=1)
            current_time = datetime.now()
            checkout_timeout = current_time + timedelta(minutes=30)
            checkout_details = {
                "line_items": registration_items,
                "mode": "payment",
                "discounts": [],
                # "success_url": f'{app.config["URL"]}/success',
                # Code to have 'convenience fee' transfered to separate acct ###
                "success_url": f'{app.config["URL"]}/success?session_id={{CHECKOUT_SESSION_ID}}',
                "cancel_url": f'{app.config["URL"]}/tickets',
                "expires_at": int(checkout_timeout.timestamp()),
            }
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

@app.route("/success", methods=["GET"])
def success_page():
    # Code to have 'convenience fee' transfered to separate acct ###
    price_dict = get_price_details()
    session = stripe.checkout.Session.retrieve(request.args.get("session_id"))
    paymentIntent = stripe.PaymentIntent.retrieve(session.payment_intent)
    stripe.Transfer.create(
        amount=int(price_dict["Convenience Fee"]["price"]) * 100,
        currency="usd",
        source_transaction=paymentIntent.latest_charge,
        destination="acct_1PYYvBGhUvudnYnE",
    )
    return render_template(
        "success.html",
        title="Registration Submitted",
        competition_name=os.getenv("COMPETITION_NAME"),
        favicon_url=url_for("static", filename=get_s3_file(app.config["mediaBucket"], "favicon.png")),
        button_style=button_style,
        email=os.getenv("CONTACT_EMAIL"),
    )


@app.route("/registration_error", methods=["GET"])
def error_page():
    return render_template(
        "registration_error.html",
        title="Registration Error",
        competition_name=os.getenv("COMPETITION_NAME"),
        favicon_url=url_for("static", filename=get_s3_file(app.config["mediaBucket"], "favicon.png")),
        button_style=button_style,
        email=os.getenv("CONTACT_EMAIL"),
    )


@app.route("/admin")
@login_required
def admin_page():
    entries = dynamodb.scan(
        TableName=app.config["reg_table_name"],
    )["Items"]
    return render_template(
        "admin.html",
        title="Administration",
        competition_name=os.getenv("COMPETITION_NAME"),
        favicon_url=url_for("static", filename=get_s3_file(app.config["mediaBucket"], "favicon.png")),
        button_style=button_style,
        entries=entries,
        additional_stylesheets=[
            dict(
                href="https://cdnjs.cloudflare.com/ajax/libs/twitter-bootstrap/5.3.0/css/bootstrap.min.css",
                integrity="sha384-9ndCyUaIbzAi2FUVXJi0CjmCapSmO7SnpJef0486qhLnuZ2cdeRhO02iuK6FUUVM",
            ),
            dict(
                href="https://cdn.datatables.net/1.13.7/css/dataTables.bootstrap5.min.css",
                integrity="sha384-ok3J6xA9oQqai5C9ytYveFsBeKgoGk4T+NExsr6hoIKjZdv9SJcmx2mafwUWRNf9",
            ),
            dict(
                href="https://cdn.datatables.net/searchpanes/2.2.0/css/searchPanes.bootstrap5.min.css",
                integrity="sha384-sSvv6aRPZo6vPaGdGfO1YzjvkZXlAUTygB+HHYd8C6DPz0BYxpd/K+iPavXPNy1u",
            ),
            dict(
                href="https://cdn.datatables.net/select/1.7.0/css/select.bootstrap5.min.css",
                integrity="sha384-BQuA/IRHdZd4G0fkajPKOBOE6lIuKmN2G95L52+ULcI1T/NGKY+gWsB/qDn6xxv7",
            ),
        ],
        additional_scripts=[
            dict(
                src="https://code.jquery.com/jquery-3.7.0.js",
                integrity="sha384-ogycHROOTGA//2Q8YUfjz1Sr7xMOJTUmY2ucsPVuXAg4CtpgQJQzGZsX768KqetU",
            ),
            dict(
                src="https://cdn.datatables.net/1.13.7/js/jquery.dataTables.min.js",
                integrity="sha384-cjmdOgDzOE22dUheI5E6Gzd3upfmReW8N1y/4jwKQE50KYcvFKZJA9JxWgQOzqwQ",
            ),
            dict(
                src="https://cdn.datatables.net/1.13.7/js/dataTables.bootstrap5.min.js",
                integrity="sha384-PgPBH0hy6DTJwu7pTf6bkRqPlf/+pjUBExpr/eIfzszlGYFlF9Wi9VTAJODPhgCO",
            ),
            dict(
                src="https://cdn.datatables.net/searchpanes/2.2.0/js/dataTables.searchPanes.min.js",
                integrity="sha384-j4rbW9ZgUxkxeMU1PIa5BaTj0qDOc/BV0zkbRqPAGPkIvaOzwTSVlDGGXw+XQ4uW",
            ),
            dict(
                src="https://cdn.datatables.net/searchpanes/2.2.0/js/searchPanes.bootstrap5.min.js",
                integrity="sha384-JTAq4Zc/HXNcaOy1Hv04w4mpSr7ouMGXxlXwTuwov0Wzv62QwPey9T58VPE1rVSf",
            ),
            dict(
                src="https://cdn.datatables.net/select/1.7.0/js/dataTables.select.min.js",
                integrity="sha384-5UUEYV/x07jNYpizRK5+tnFvFPDDq5s5wVr5mc802xveN8Ve7kuFu4Ym6mN+QcmZ",
            ),
            dict(
                src="https://cdn.datatables.net/responsive/2.5.0/js/dataTables.responsive.min.js",
                integrity="sha384-VUnyCeQcqiiTlSM4AISHjJWKgLSM5VSyOeipcD9S/ybCKR3OhChZrPPjjrLfVV0y",
            ),
            dict(
                src="https://cdn.datatables.net/responsive/2.5.0/js/responsive.bootstrap5.min.js",
                integrity="sha384-T6YQaHyTPTbybQQV23jtlugHCneQYjePXdcEU+KMWGQY8EUQygBW9pRx0zpSU0/i",
            ),
            dict(src=url_for("static", filename="js/admin.js")),
        ],
    )


@app.route("/edit")
@login_required
def edit_entry_form():
    pk = request.args.get("pk")
    entry = dynamodb.get_item(
        TableName=app.config["reg_table_name"],
        Key={"pk": {"S": pk}},
    )["Item"]
    school_list = json.load(s3.get_object(Bucket=app.config["configBucket"], Key="schools.json")["Body"])
    return render_template(
        "edit.html",
        title="Edit Entry",
        competition_name=os.getenv("COMPETITION_NAME"),
        favicon_url=url_for("static", filename=get_s3_file(app.config["mediaBucket"], "favicon.png")),
        button_style=button_style,
        schools=school_list,
        entry=entry,
        additional_scripts=[
            dict(
                src="https://ajax.googleapis.com/ajax/libs/jquery/3.4.1/jquery.min.js",
                integrity="sha384-vk5WoKIaW/vJyUAd9n/wmopsmNhiy+L2Z+SBxGYnUkunIxVxAv/UtMOhba/xskxh",
            ),
            dict(
                src="https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.1.3/js/bootstrap.min.js",
                integrity="sha384-QJHtvGhmr9XOIpI6YVutG+2QOK9T+ZnN4kzFN1RtK3zEFEIsxhlmWl5/YESvpZ13",
            ),
            dict(src=url_for("static", filename="js/form.js")),
        ],
    )


@app.route("/edit", methods=["POST"])
@login_required
def edit_entry():
    belt = request.form.get("beltRank")
    if belt == "black":
        dan = request.form.get("blackBeltDan")
        if dan == "4":
            belt = "Master"
        else:
            belt = f"{dan} degree {belt}"
    form_data = dict(
        full_name={"S": request.form.get("full_name")},
        email={"S": request.form.get("email")},
        phone={"S": request.form.get("phone")},
        school={"S": request.form.get("school")},
        reg_type={"S": request.form.get("regType")},
        parent={"S": request.form.get("parentName")},
        birthdate={"S": request.form.get("birthdate")},
        age={"N": request.form.get("age")},
        gender={"S": request.form.get("gender")},
        beltRank={"S": belt},
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


@app.route("/add_entry")
@login_required
def add_entry_form():
    school_list = json.load(s3.get_object(Bucket=app.config["configBucket"], Key="schools.json")["Body"])
    # Display the form
    return render_template(
        "add_entry.html",
        title="Registration",
        favicon_url=url_for("static", filename=get_s3_file(app.config["mediaBucket"], "favicon.png")),
        button_style=button_style,
        competition_name=os.getenv("COMPETITION_NAME"),
        competition_year=os.getenv("COMPETITION_YEAR"),
        early_reg_date=os.getenv("EARLY_REG_DATE"),
        # early_reg_coupon_amount=f'{int(early_reg_coupon["amount_off"]/100)}',
        price_dict=get_price_details(),
        schools=school_list,
        additional_scripts=[
            dict(
                src="https://ajax.googleapis.com/ajax/libs/jquery/3.4.1/jquery.min.js",
                integrity="sha384-vk5WoKIaW/vJyUAd9n/wmopsmNhiy+L2Z+SBxGYnUkunIxVxAv/UtMOhba/xskxh",
            ),
            dict(
                src="https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.1.3/js/bootstrap.min.js",
                integrity="sha384-QJHtvGhmr9XOIpI6YVutG+2QOK9T+ZnN4kzFN1RtK3zEFEIsxhlmWl5/YESvpZ13",
            ),
            dict(src=url_for("static", filename="js/form.js")),
        ],
    )


@app.route("/add_entry", methods=["POST"])
@login_required
def add_entry():
    # Name
    fname = request.form.get("fname").strip()
    lname = request.form.get("lname").strip()
    fullName = f"{fname}_{lname}"

    school = request.form.get("school")

    # Check if registration already exists
    if not os.getenv("FLASK_DEBUG"):
        pk_school_name = school.replace(" ", "_")
        pk_exists = dynamodb.get_item(
            TableName=app.config["reg_table_name"],
            Key={"pk": {"S": f"{pk_school_name}-seminar-{fullName}"}},
        )

        if "Item" in pk_exists:
            print("registration exists")
            return redirect(f'{app.config["URL"]}/registration_error')

    # Base Form Data
    belt = request.form.get("beltRank")
    if belt == "black":
        dan = request.form.get("blackBeltDan")
        if dan == "4":
            belt = "Master"
        else:
            belt = f"{dan} degree {belt}"
    form_data = dict(
        full_name={"S": f"{fname} {lname}"},
        email={"S": request.form.get("email")},
        phone={"S": request.form.get("phone")},
        school={"S": school},
        reg_type={"S": request.form.get("regType")},
        parent={"S": request.form.get("parentName")},
        birthdate={"S": request.form.get("birthdate")},
        age={"N": request.form.get("age")},
        gender={"S": request.form.get("gender")},
        beltRank={"S": belt},
    )

    if os.getenv("FLASK_DEBUG"):
        # For Testing Form Data
        return render_template(
            "success.html",
            title="Registration Submitted",
            competition_name=os.getenv("COMPETITION_NAME"),
            favicon_url=url_for("static", filename=get_s3_file(app.config["mediaBucket"], "favicon.png")),
            button_style=button_style,
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

        return redirect(f'{app.config["URL"]}/success', code=303)


@app.route("/export")
@login_required
def generate_csv():
    data = dynamodb.scan(
        TableName=app.config["reg_table_name"],
        FilterExpression="reg_type = :type",
        ExpressionAttributeValues={
            ":type": {
                "S": "seminar",
            },
        },
    )["Items"]
    entries = sorted(data, key=lambda item: item["full_name"]["S"].split()[-1])
    return render_template(
        "export.html",
        competition_year=os.getenv("COMPETITION_YEAR"),
        competition_name=os.getenv("COMPETITION_NAME"),
        favicon_url=url_for("static", filename=get_s3_file(app.config["mediaBucket"], "favicon.png")),
        button_style=button_style,
        entries=entries,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0")
