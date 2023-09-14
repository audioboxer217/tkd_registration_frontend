from flask import Flask, render_template, redirect, request, abort
import json
import os
import stripe

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "/data"
app.config["URL"] = "http://localhost"
stripe.api_key = os.getenv("STRIPE_API_KEY")

# Test Details
price_dict = dict(
    black_reg="price_1NmksyLkt5uWmF69LJZpYOBn",
    black_event="price_1NoY65Lkt5uWmF69P2HMG26V",
    color_reg="price_1NoY86Lkt5uWmF69YSVmz3P2",
    color_event="price_1NoY8ZLkt5uWmF69t47jMIo3",
    coach="price_1NoY7QLkt5uWmF69lvlzgBo6",
)


@app.route("/", methods=["GET", "POST"])
def handle_form():
    if request.method == "POST":
        uploadDir = app.config["UPLOAD_FOLDER"]
        imageDir = os.path.join(uploadDir, "profile_pics")
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

            profileImg.save(os.path.join(imageDir, form_data["imgFilename"]))

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
            )
        except Exception as e:
            return str(e)

        form_data.update(dict(checkout=checkout_session.id))
        formFilename = f"{fullName}.json"
        with open(os.path.join(uploadDir, formFilename), "w") as f:
            json.dump(form_data, f)

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
    profile_pics_dir = os.path.join(
        app.config["UPLOAD_FOLDER"],
        "profile_pics",
    )
    if not os.path.exists(profile_pics_dir):
        os.makedirs(profile_pics_dir)

    app.run(host="0.0.0.0")
