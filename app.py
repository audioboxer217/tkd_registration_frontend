from flask import Flask, render_template, request, abort
import json
import os

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "/data"


@app.route("/", methods=["GET", "POST"])
def handle_form():
    if request.method == "POST":
        reg_type = request.form.get("regType")
        if reg_type == "competitor":
            uploadDir = app.config["UPLOAD_FOLDER"]
            imageDir = os.path.join(uploadDir, "profile_pics")

            if request.form.get("liability") != "on":
                abort(400, "Please go back and accept the Liability Waiver Conditions")

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
                birthdate=request.form.get("birthdate"),
                age=request.form.get("age"),
                gender=request.form.get("gender"),
                weight=request.form.get("weight"),
                school=request.form.get("school"),
                coach=request.form.get("coach"),
                beltRank=request.form.get("beltRank"),
                events=request.form.get("eventList"),
                reg_type=request.form.get("regType"),
            )
            formFilename = f"{form_data['fname']}_{form_data['lname']}.json"
            with open(os.path.join(uploadDir, formFilename), "w") as f:
                json.dump(form_data, f)

            profileImg = request.files["profilePic"]
            imageExt = os.path.splitext(profileImg.filename)[1]
            imgFilename = f"{form_data['fname']}_{form_data['lname']}{imageExt}"
            profileImg.save(os.path.join(imageDir, imgFilename))

            return render_template(
                "success.html",
                form_data=form_data,
                regType="competitor",
                indent=4,
            )
        else:
            uploadDir = app.config["UPLOAD_FOLDER"]

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
    if not os.path.exists(os.path.join(app.config["UPLOAD_FOLDER"], "profile_pics")):
        os.makedirs(os.path.join(app.config["UPLOAD_FOLDER"], "profile_pics"))

    app.run(host="0.0.0.0")
