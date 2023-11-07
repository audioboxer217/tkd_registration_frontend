from flask import Flask, render_template, redirect, request, abort
from datetime import datetime, timedelta
import boto3
import json
import os
import stripe

app = Flask(__name__)
app.config["profilePicBucket"] = os.getenv("PROFILE_PIC_BUCKET")
app.config["configBucket"] = os.getenv("CONFIG_BUCKET")
app.config["URL"] = os.getenv("REG_URL")
app.config["SQS_QUEUE_URL"] = os.getenv("SQS_QUEUE_URL")
app.config["table_name"] = os.getenv("DB_TABLE")
stripe.api_key = os.getenv("STRIPE_API_KEY")
s3 = boto3.client("s3")
sqs = boto3.client("sqs")
dynamodb = boto3.client("dynamodb")

# Price Details
price_json = s3.get_object(
    Bucket=app.config["configBucket"],
    Key="stripe_prices.json",
)["Body"].read()
price_dict = json.loads(price_json)


@app.route("/")
def index_page():
    return render_template(
        "index.html",
        email=os.getenv("CONTACT_EMAIL"),
        org=os.getenv("COMPETITION_NAME"),
    )


@app.route("/register", methods=["GET", "POST"])
def handle_form():
    if request.method == "POST":
        reg_type = request.form.get("regType")
        school = request.form.get("school").replace(" ", "-")

        # Name
        fname = request.form.get("fname")
        lname = request.form.get("lname")
        fullName = f"{fname}_{lname}"

        # Check if registration already exists
        pk_exists = dynamodb.get_item(
            TableName=app.config["table_name"],
            Key={"pk": {"S": f"{school}-{reg_type}-{fullName}"}},
        )

        if "Item" in pk_exists:
            print("registration exists")
            return redirect(f'{app.config["URL"]}/registration_error')

        # Base Form Data
        form_data = dict(
            full_name={"S": f"{fname} {lname}"},
            email={"S": request.form.get("email")},
            phone={"S": request.form.get("phone")},
            address1={"S": request.form.get("address1")},
            address2={"S": request.form.get("address2")},
            city={"S": request.form.get("city")},
            state={"S": request.form.get("state")},
            zip={"S": request.form.get("zip")},
            school={"S": request.form.get("school")},
            reg_type={"S": request.form.get("regType")},
        )

        # Add Competitor Form Data
        if reg_type == "competitor":
            msg = "Please go back and accept the Liability Waiver Conditions"
            if request.form.get("liability") != "on":
                abort(400, msg)

            profileImg = request.files["profilePic"]
            imageExt = os.path.splitext(profileImg.filename)[1]

            form_data.update(
                dict(
                    birthdate={"S": request.form.get("birthdate")},
                    age={"N": request.form.get("age")},
                    gender={"S": request.form.get("gender")},
                    weight={"N": request.form.get("weight")},
                    imgFilename={"S": f"{school}_{reg_type}_{fullName}{imageExt}"},
                    coach={"S": request.form.get("coach")},
                    beltRank={"S": request.form.get("beltRank")},
                    events={"S": request.form.get("eventList")},
                )
            )

            s3.upload_fileobj(
                profileImg,
                app.config["profilePicBucket"],
                form_data["imgFilename"]["S"],
            )

            num_add_event = len(form_data["events"]["S"].split(",")) - 1
            if form_data["beltRank"]["S"] == "black":
                registration_items = [
                    {
                        "price": price_dict["black_reg"],
                        "quantity": 1,
                    },
                ]
                if num_add_event > 0:
                    registration_items.append(
                        {
                            "price": price_dict["black_event"],
                            "quantity": num_add_event,
                        },
                    )
            else:
                registration_items = [
                    {
                        "price": price_dict["color_reg"],
                        "quantity": 1,
                    },
                ]
                if num_add_event > 0:
                    registration_items.append(
                        {
                            "price": price_dict["color_event"],
                            "quantity": num_add_event,
                        },
                    )
        else:
            registration_items = [
                {
                    "price": price_dict["coach"],
                    "quantity": 1,
                }
            ]

        try:
            checkout_timeout = datetime.utcnow() + timedelta(minutes=30)
            checkout_session = stripe.checkout.Session.create(
                line_items=registration_items,
                mode="payment",
                success_url=f'{app.config["URL"]}/success',
                cancel_url=f'{app.config["URL"]}',
                expires_at=int(checkout_timeout.timestamp()),
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

    else:
        reg_type = request.args.get("reg_type")
        # Display the form
        return render_template(
            "form.html",
            title="Registration",
            competition_name=os.getenv("COMPETITION_NAME"),
            competition_year=os.getenv("COMPETITION_YEAR"),
            reg_type=reg_type,
            additional_scripts=[
                dict(
                    src=f'https://maps.googleapis.com/maps/api/js?key={os.getenv("MAPS_API_KEY")}&libraries=places&callback=initMap&solution_channel=GMP_QB_addressselection_v1_cA',
                    async_bool="true",
                    defer="true",
                ),
                dict(
                    src="https://ajax.googleapis.com/ajax/libs/jquery/3.4.1/jquery.min.js",
                    integrity="sha384-vk5WoKIaW/vJyUAd9n/wmopsmNhiy+L2Z+SBxGYnUkunIxVxAv/UtMOhba/xskxh",
                ),
                dict(
                    src="https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.1.3/js/bootstrap.min.js",
                    integrity="sha384-QJHtvGhmr9XOIpI6YVutG+2QOK9T+ZnN4kzFN1RtK3zEFEIsxhlmWl5/YESvpZ13",
                ),
                dict(
                    src="https://cdnjs.cloudflare.com/ajax/libs/bootstrap-datepicker/1.9.0/js/bootstrap-datepicker.min.js",
                    integrity="sha384-duAtk5RV7s42V6Zuw+tRBFcqD8RjRKw6RFnxmxIj1lUGAQJyum/vtcUQX8lqKQjp",
                ),
            ],
        )


@app.route("/schedule", methods=["GET"])
def schedule_page():
    return render_template("placeholder.html", title="Page to be Created")


@app.route("/information", methods=["GET"])
def information_page():
    return render_template("placeholder.html", title="Page to be Created")


@app.route("/visit-tulsa", methods=["GET"])
def visitor_page():
    return redirect("https://www.visittulsa.com", code=303)


@app.route("/events", methods=["GET"])
def events_page():
    return render_template("placeholder.html", title="Page to be Created")


@app.route("/success", methods=["GET"])
def success_page():
    return render_template(
        "success.html",
        title="Registration Submitted",
        email=os.getenv("CONTACT_EMAIL"),
        org=os.getenv("COMPETITION_NAME"),
    )


@app.route("/registration_error", methods=["GET"])
def error_page():
    return render_template(
        "registration_error.html",
        title="Registration Error",
        email=os.getenv("CONTACT_EMAIL"),
        org=os.getenv("COMPETITION_NAME"),
    )


@app.route("/test", methods=["GET"])
def test_page():
    return render_template(
        "test.html",
        email=os.getenv("CONTACT_EMAIL"),
        org=os.getenv("COMPETITION_NAME"),
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0")
