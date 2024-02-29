from flask import Flask, render_template, redirect, request, abort, url_for
from datetime import datetime, timedelta, date
import boto3
import json
import os
import stripe

app = Flask(__name__)
app.config["profilePicBucket"] = os.getenv("PROFILE_PIC_BUCKET")
app.config["configBucket"] = os.getenv("CONFIG_BUCKET")
app.config["mediaBucket"] = os.getenv("PUBLIC_MEDIA_BUCKET")
app.config["URL"] = os.getenv("REG_URL")
app.config["SQS_QUEUE_URL"] = os.getenv("SQS_QUEUE_URL")
app.config["table_name"] = os.getenv("DB_TABLE")
stripe.api_key = os.getenv("STRIPE_API_KEY")
s3 = boto3.client("s3")
sqs = boto3.client("sqs")
dynamodb = boto3.client("dynamodb")

# Price Details
early_reg_date = datetime.strptime(os.getenv("EARLY_REG_DATE"), "%B %d, %Y").date()
today = date.today()
price_dict = {"Additional Event": "addl_event", "Coach Registration": "coach_reg"}
if today < early_reg_date + timedelta(days=1):
    price_dict["Color Belt Registration"] = "color_early_reg"
    price_dict["Black Belt Registration"] = "black_early_reg"
else:
    price_dict["Color Belt Registration"] = "color_late_reg"
    price_dict["Black Belt Registration"] = "black_late_reg"
for k, v in price_dict.items():
    price_detail = stripe.Price.list(lookup_keys=[v]).data[0]
    price_dict[k] = {
        "price_id": price_detail.id,
        "price": f"{int(price_detail.unit_amount/100)}",
    }


@app.route("/")
def index_page():
    return render_template(
        "index.html",
        title=os.getenv("COMPETITION_NAME"),
        email=os.getenv("CONTACT_EMAIL"),
        competition_name=os.getenv("COMPETITION_NAME"),
        favicon_url=f'https://{app.config["mediaBucket"]}.s3.us-east-2.amazonaws.com/favicon.png',
        poster_url=f'https://{app.config["mediaBucket"]}.s3.us-east-2.amazonaws.com/registration_poster.jpg',
    )


@app.route("/register", methods=["GET", "POST"])
def handle_form():
    if (
        date.today()
        > datetime.strptime(os.getenv("REG_CLOSE_DATE"), "%B %d, %Y").date()
    ):
        return render_template(
            "disabled.html",
            title="Registration Closed",
            favicon_url=f'https://{app.config["mediaBucket"]}.s3.us-east-2.amazonaws.com/favicon.png',
            competition_name=os.getenv("COMPETITION_NAME"),
            email=os.getenv("CONTACT_EMAIL"),
        )
    if request.method == "POST":
        reg_type = request.form.get("regType")
        school = request.form.get("school").strip().replace(" ", "-")

        # Name
        fname = request.form.get("fname").strip()
        lname = request.form.get("lname").strip()
        fullName = f"{fname}_{lname}"

        school = request.form.get("school").strip()
        coach = request.form.get("coach").strip()

        # Check if registration already exists
        pk_exists = dynamodb.get_item(
            TableName=app.config["table_name"],
            Key={"pk": {"S": f"{school}-{reg_type}-{fullName}"}},
        )

        if "Item" in pk_exists:
            print("registration exists")
            return redirect(
                f'{app.config["URL"]}/registration_error?reg_type={reg_type}'
            )

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
            school={"S": school},
            reg_type={"S": request.form.get("regType")},
        )

        # Add Competitor Form Data
        if reg_type == "competitor":
            if request.form.get("liability") != "on":
                msg = "Please go back and accept the Liability Waiver Conditions"
                abort(400, msg)

            profileImg = request.files["profilePic"]
            imageExt = os.path.splitext(profileImg.filename)[1]
            if profileImg.content_type == "" or imageExt == "":
                msg = "There was an error uploading your profile pic. Please go back and try again."
                abort(400, msg)

            if request.form.get("eventList") == "":
                msg = "You must choose at least one event"
                abort(400, msg)

            form_data.update(
                dict(
                    birthdate={"S": request.form.get("birthdate")},
                    age={"N": request.form.get("age")},
                    gender={"S": request.form.get("gender")},
                    weight={"N": request.form.get("weight")},
                    imgFilename={"S": f"{school}_{reg_type}_{fullName}{imageExt}"},
                    coach={"S": coach},
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
            if num_add_event > 0:
                registration_items.append(
                    {
                        "price": price_dict["Additional Event"]["price_id"],
                        "quantity": num_add_event,
                    },
                )
        else:
            registration_items = [
                {
                    "price": price_dict["Coach Registration"]["price_id"],
                    "quantity": 1,
                }
            ]

        try:
            checkout_timeout = datetime.utcnow() + timedelta(minutes=30)
            checkout_session = stripe.checkout.Session.create(
                line_items=registration_items,
                mode="payment",
                success_url=f'{app.config["URL"]}/success',
                cancel_url=f'{app.config["URL"]}/register?reg_type={reg_type}',
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
            favicon_url=f'https://{app.config["mediaBucket"]}.s3.us-east-2.amazonaws.com/favicon.png',
            competition_name=os.getenv("COMPETITION_NAME"),
            competition_year=os.getenv("COMPETITION_YEAR"),
            early_reg_date=os.getenv("EARLY_REG_DATE"),
            late_reg_price_increase="10",
            price_dict=price_dict,
            reg_type=reg_type,
            additional_stylesheets=[
                dict(
                    href="https://cdnjs.cloudflare.com/ajax/libs/bootstrap-datepicker/1.9.0/css/bootstrap-datepicker.min.css",
                    integrity="sha384-5IbgsdqrjF6rAX1mxBZkKRyUOgEr0/xCGkteJIaRKpvW0Ag0tf6lru4oL2ZhcMvo",
                )
            ],
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
                dict(src=url_for("static", filename="js/form.js")),
            ],
        )


@app.route("/schedule", methods=["GET"])
def schedule_page():
    return render_template(
        "schedule.html",
        title="Schedule",
        competition_name=os.getenv("COMPETITION_NAME"),
        favicon_url=f'https://{app.config["mediaBucket"]}.s3.us-east-2.amazonaws.com/favicon.png',
    )


@app.route("/events", methods=["GET"])
def events_page():
    return render_template(
        "placeholder.html",
        title="Page to be Created",
        competition_name=os.getenv("COMPETITION_NAME"),
        favicon_url=f'https://{app.config["mediaBucket"]}.s3.us-east-2.amazonaws.com/favicon.png',
    )


@app.route("/information", methods=["GET"])
def info_page():
    return render_template(
        "information.html",
        title="Information",
        competition_name=os.getenv("COMPETITION_NAME"),
        favicon_url=f'https://{app.config["mediaBucket"]}.s3.us-east-2.amazonaws.com/favicon.png',
        information_booklet_url=f'https://{app.config["mediaBucket"]}.s3.us-east-2.amazonaws.com/information_booklet.pdf',
        icross_img_url=f'https://{app.config["mediaBucket"]}.s3.us-east-2.amazonaws.com/icross_info.png',
    )


@app.route("/coaches", methods=["GET"])
def coaches_page():
    coaches_json = s3.get_object(
        Bucket=app.config["configBucket"],
        Key="coaches.json",
    )["Body"].read()
    return render_template(
        "coaches.html",
        title="Coaches",
        competition_name=os.getenv("COMPETITION_NAME"),
        favicon_url=f'https://{app.config["mediaBucket"]}.s3.us-east-2.amazonaws.com/favicon.png',
        coaches_dict=json.loads(coaches_json),
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
            dict(src=url_for("static", filename="js/coaches.js")),
        ],
    )


@app.route("/competitors", methods=["GET"])
def competitors_page():
    competitor_json = s3.get_object(
        Bucket=app.config["configBucket"],
        Key="entries.json",
    )["Body"].read()
    return render_template(
        "competitors.html",
        title="Competitors",
        competition_name=os.getenv("COMPETITION_NAME"),
        favicon_url=f'https://{app.config["mediaBucket"]}.s3.us-east-2.amazonaws.com/favicon.png',
        competitor_dict=json.loads(competitor_json),
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
            dict(src=url_for("static", filename="js/competitors.js")),
        ],
    )


@app.route("/success", methods=["GET"])
def success_page():
    return render_template(
        "success.html",
        title="Registration Submitted",
        competition_name=os.getenv("COMPETITION_NAME"),
        favicon_url=f'https://{app.config["mediaBucket"]}.s3.us-east-2.amazonaws.com/favicon.png',
        email=os.getenv("CONTACT_EMAIL"),
    )


@app.route("/registration_error", methods=["GET"])
def error_page():
    reg_type = request.args.get("reg_type")
    return render_template(
        "registration_error.html",
        title="Registration Error",
        competition_name=os.getenv("COMPETITION_NAME"),
        favicon_url=f'https://{app.config["mediaBucket"]}.s3.us-east-2.amazonaws.com/favicon.png',
        email=os.getenv("CONTACT_EMAIL"),
        reg_type=reg_type,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0")
