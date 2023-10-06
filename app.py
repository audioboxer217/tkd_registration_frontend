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
stripe.api_key = os.getenv("STRIPE_API_KEY")
s3 = boto3.client('s3')
sqs = boto3.client('sqs')

# Price Details
price_json = s3.get_object(Bucket=app.config["configBucket"], Key='stripe_prices.json')['Body'].read()
price_dict = json.loads(price_json)


@app.route("/", methods=["GET", "POST"])
def handle_form():
    if request.method == "POST":
        reg_type = request.form.get("regType")

        # Name
        fname = request.form.get("fname")
        lname = request.form.get("lname")
        fullName = f"{fname}_{lname}"

        # Base Form Data
        form_data = dict(
            fname=fname,
            lname=lname,
            email=request.form.get("email"),
            phone=request.form.get("phone"),
            address1=request.form.get("address1"),
            address2=request.form.get("address2"),
            city=request.form.get("city"),
            state=request.form.get("state"),
            zip=request.form.get("zip"),
            school=request.form.get("school"),
            reg_type=request.form.get("regType"),
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
                    birthdate=request.form.get("birthdate"),
                    age=request.form.get("age"),
                    gender=request.form.get("gender"),
                    weight=request.form.get("weight"),
                    imgFilename=f"{fullName}{imageExt}",
                    coach=request.form.get("coach"),
                    beltRank=request.form.get("beltRank"),
                    events=request.form.get("eventList"),
                )
            )

            s3.upload_fileobj(profileImg, app.config["profilePicBucket"], form_data["imgFilename"] )

            num_add_event = len(form_data["events"].split(",")) - 1
            if form_data["beltRank"] == "black":
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
                            "quantity": len(form_data["events"].split(",")) - 1,
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
                            "quantity": len(form_data["events"].split(",")) - 1,
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
            checkout_session = stripe.checkout.Session.create(
                line_items=registration_items,
                mode="payment",
                success_url=f'{app.config["URL"]}/success',
                cancel_url=f'{app.config["URL"]}',
                expires_at=int((datetime.utcnow() + timedelta(minutes=30)).timestamp())
            )
        except Exception as e:
            return str(e)

        form_data.update(dict(checkout=checkout_session.id))
        sqs.send_message(
            QueueUrl=app.config["SQS_QUEUE_URL"],
            DelaySeconds=120,
            MessageAttributes={
                'Name': {
                    'DataType': 'String',
                    'StringValue': fullName
                },
                'Transaction': {
                    'DataType': 'String',
                    'StringValue': checkout_session.id
                }
            },
            MessageBody=json.dumps(form_data)
        )

        return redirect(checkout_session.url, code=303)

    else:
        # Display the form
        return render_template(
            "form.html",
            mapsApiKey=os.getenv("MAPS_API_KEY"),
            competition_name=os.getenv("COMPETITION_NAME"),
            competition_year=os.getenv("COMPETITION_YEAR"),
        )


@app.route("/success", methods=["GET"])
def success_page():
    return render_template(
        "success.html",
        email=os.getenv("CONTACT_EMAIL"),
        org=os.getenv("COMPETITION_NAME"),
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0")
