from flask import Flask, render_template, request, abort
import json
import os

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "/data"


@app.route("/", methods=["GET", "POST"])
def handle_form():
    if request.method == "POST":
        uploadDir = app.config["UPLOAD_FOLDER"]
        reg_type = request.form.get("regType")
        if reg_type == "competitor":
            imageDir = os.path.join(uploadDir, "profile_pics")

            msg = "Please go back and accept the Liability Waiver Conditions"
            if request.form.get("liability") != "on":
                abort(400, msg)

            profileImg = request.files["profilePic"]
            imageExt = os.path.splitext(profileImg.filename)[1]
            fname = request.form.get("fname")
            lname = request.form.get("lname")
            fullName = f'{fname}_{lname}'

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
                birthdate=request.form.get("birthdate"),
                age=request.form.get("age"),
                gender=request.form.get("gender"),
                weight=request.form.get("weight"),
                imgFilename=f"{fullName}{imageExt}",
                school=request.form.get("school"),
                coach=request.form.get("coach"),
                beltRank=request.form.get("beltRank"),
                events=request.form.get("eventList"),
                reg_type=request.form.get("regType"),
            )
            formFilename = f"{fullName}.json"
            with open(os.path.join(uploadDir, formFilename), "w") as f:
                json.dump(form_data, f)

            profileImg.save(os.path.join(imageDir, form_data["imgFilename"]))

            return render_template(
                "success.html",
                form_data=form_data,
                regType="competitor",
                indent=4,
            )
        else:
            form_data = dict(
                fname=request.form.get("fname"),
                lname=request.form.get("lname"),
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
            formFilename = f"{form_data['fname']}_{form_data['lname']}.json"
            with open(os.path.join(uploadDir, formFilename), "w") as f:
                json.dump(form_data, f)

            return render_template(
                "success.html", form_data=form_data, regType="coach", indent=4
            )

    else:
        # Display the form
        return render_template(
            "form.html",
            mapsApiKey=os.getenv("MAPS_API_KEY"),
            competition_name=os.getenv("COMPETITION_NAME"),
            competition_year=os.getenv("COMPETITION_YEAR"),
        )


if __name__ == "__main__":
    profile_pics_dir = os.path.join(
        app.config["UPLOAD_FOLDER"],
        "profile_pics",
    )
    if not os.path.exists(profile_pics_dir):
        os.makedirs(profile_pics_dir)

    app.run(host="0.0.0.0")
