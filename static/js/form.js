function upload_img(files) {
  if (files[0]) {
    var maxSize = 2000000; // 2MB
    var MAX_WIDTH = 300;
    var MAX_HEIGHT = 300;

    let imageFile = files[0];
    // Check if the image is larger than the max size
    if (imageFile.size > maxSize) {
      // Show an error message
      alert("The image is too large. Please resize it before uploading. Max Size: 2MB");
      return;
    }
    var reader = new FileReader();
    reader.onload = function (e) {
      var img = document.createElement("img");

      img.onload = function (event) {
        var width = img.width;
        var height = img.height;
        // Change the resizing logic
        if (width > height) {
          if (width > MAX_WIDTH) {
            height = height * (MAX_WIDTH / width);
            width = MAX_WIDTH;
          }
        } else {
          if (height > MAX_HEIGHT) {
            width = width * (MAX_HEIGHT / height);
            height = MAX_HEIGHT;
          }
        }
        // Dynamically create a canvas element
        var canvas = document.createElement("canvas");
        canvas.width = width;
        canvas.height = height;

        // var canvas = document.getElementById("canvas");
        var ctx = canvas.getContext("2d");

        // Actual resizing
        ctx.drawImage(img, 0, 0, width, height);

        // Show resized image in preview element
        var dataurl = canvas.toDataURL(imageFile.type);
        document.getElementById("profileImg").src = dataurl;
        document.getElementById("profileImg").value = dataurl;
      }
      img.src = e.target.result;
    }
    reader.readAsDataURL(imageFile);
  }
}
function updateFields() {
  regChoice = document.querySelectorAll('input[name="regChoice"]:checked')[0].id
  document.getElementById("regType").value = regChoice
  if (regChoice == "competitor") {
    document.getElementById("classSection").hidden = false;
    document.getElementById("birthdate").required = true;
    document.getElementById("inputAge").required = true;
    document.getElementById("genderMale").required = true;
    document.getElementById("genderFemale").required = true;
    document.getElementById("weightKgs").required = true;

    document.getElementById("profile").hidden = false;
    document.getElementById("profilePic").required = true;

    document.getElementById("coachSection").hidden = false;
    document.getElementById("inputCoach").required = true;

    document.getElementById("beltSection").hidden = false;
    document.getElementById("blackBelt").required = true;

    document.getElementById("eventSection").hidden = false;
    document.getElementById("eventList").required = true;

    document.getElementById("liabilityTextSection").hidden = false;
    document.getElementById("liabilityAcceptSection").hidden = false;
    document.getElementById("liability").required = true;

    updateTotal()
  }
  else {
    document.getElementById("classSection").hidden = true;
    document.getElementById("birthdate").required = false;
    document.getElementById("inputAge").required = false;
    document.getElementById("genderMale").required = false;
    document.getElementById("genderFemale").required = false;
    document.getElementById("weightKgs").required = false;

    document.getElementById("profile").hidden = true;
    document.getElementById("profilePic").required = false;

    document.getElementById("coachSection").hidden = true;
    document.getElementById("inputCoach").required = false;

    document.getElementById("beltSection").hidden = true;
    document.getElementById("blackBelt").required = false;

    document.getElementById("eventSection").hidden = true;
    document.getElementById("eventList").required = false;

    document.getElementById("liabilityTextSection").hidden = true;
    document.getElementById("liabilityAcceptSection").hidden = true;
    document.getElementById("liability").required = false;

    updateTotal()
  }
}
function formatPhoneNumber(input) {
  // Remove any non-digits from the input
  var phoneNum = input.replace(/[^0-9]/g, "");

  // Check if the input is a valid phone number
  if (phoneNum.length !== 10) {
    return;
  }

  // Format the phone number
  phoneNumFormatted = phoneNum.substring(0, 3) + "-" + phoneNum.substring(3, 6) + "-" + phoneNum.substring(6);

  document.getElementById("inputPhone").value = phoneNumFormatted;
}
function updateCostDetails() {
  const today = new Date()
  const early_reg_date = window.okgp.early_reg_date
  const blackBelt = "The first event for Black Belts is $" + window.okgp.price_dict.black_belt + " and each additional event is $" + window.okgp.price_dict.addl_event
  const colorBelt = "The first event for Color Belts is $" + window.okgp.price_dict.color_belt + "  and each additional event is $" + window.okgp.price_dict.addl_event
  var early_reg_warn = ""

  if (today < early_reg_date) {
    var early_reg_date_pretty = early_reg_date.toLocaleDateString('en-us', { month:"long", day:"numeric"}) 
    var early_reg_warn = "<br>After " + early_reg_date_pretty + ", prices increase $" + window.okgp.late_reg_increase
  }

  if (document.getElementById('blackBelt').checked) {
    document.getElementById("costDetail").innerHTML = blackBelt + early_reg_warn;
    document.getElementById("sparring").hidden = true;
    document.getElementById("sparring-gr").hidden = false;
    document.getElementById("sparring-wc").hidden = false;
  }
  else {
    document.getElementById("costDetail").innerHTML = colorBelt + early_reg_warn
    document.getElementById("sparring").hidden = false;
    document.getElementById("sparring-gr").hidden = true;
    document.getElementById("sparring-wc").hidden = true;
  }
  document.getElementById("costDetail").classList = "bg-secondary text-white"
  updateTotal()
}
function updateEventList() {
  var eventList = []
  var checked_items = document.querySelectorAll('input[name="events"]:checked')
  for (i = 0; i < checked_items.length; i++) {
    eventList.push(checked_items[i].id)
  }
  document.getElementById("eventList").value = eventList.join()
  updateTotal()
}
function updateTotal() {
  regChoice = document.querySelectorAll('input[name="regChoice"]:checked')[0].id
  if (regChoice == "competitor") {
    if (
      document.querySelectorAll('input[name="beltRank"]:checked').length > 0 &&
      document.querySelectorAll('input[name="events"]:checked').length > 0
    ) {
      if (document.getElementById('blackBelt').checked) {
        var eventPrice = parseInt(window.okgp.price_dict.addl_event)
        var total = parseInt(window.okgp.price_dict.black_belt)
      }
      else {
        var eventPrice = parseInt(window.okgp.price_dict.addl_event)
        var total = parseInt(window.okgp.price_dict.color_belt)
      }
      total += eventPrice * (document.querySelectorAll('input[name="events"]:checked').length - 1)
      document.getElementById("total").value = "$" + total
    }
    else if (
      document.querySelectorAll('input[name="beltRank"]:checked').length == 0 &&
      document.querySelectorAll('input[name="events"]:checked').length > 0
    ) {
      alert("Please choose a Belt Rank to get your Total")
    }
    else {
      document.getElementById("total").value = ""
    }
  }
  else {
    document.getElementById("total").value = "$" + window.okgp.price_dict.coach
  }
}
function convertWeight(amount, unit) {
  if (unit == 'lbs') {
    document.getElementById("weightKgs").value = (amount * 0.45359237).toFixed(2)
  }
  else if (unit == 'kgs') {
    document.getElementById("weightLbs").value = (amount / 0.45359237).toFixed(2)
  }
  else {
    console.log("Error, unsupported unit " + unit)
  }
}
function calculateAge(dateString) {
  var today = new Date()
  var birthdate = new Date(dateString)
  console.log(birthdate)
  var age = today.getFullYear() - birthdate.getFullYear()//dateString.split('/')[2]
  document.getElementById("inputAge").value = age
  if (age <= 5) {
    var ageClass = "Titan"
  }
  else if (age > 5 && age <= 7) {
    var ageClass = "Tiger"
  }
  else if (age > 7 && age <= 9) {
    var ageClass = "Dragon"
  }
  else if (age > 9 && age <= 11) {
    var ageClass = "Youth"
  }
  else if (age > 11 && age <= 14) {
    var ageClass = "Cadet"
  }
  else if (age > 14 && age <= 17) {
    var ageClass = "Junior"
  }
  else if (age > 17 && age <= 32) {
    var ageClass = "Senior"
  }
  else if (age > 32) {
    var ageClass = "Ultra"
  }
  formattedBirthdate = birthdate.toLocaleDateString("en-US", {
    month: "2-digit",
    day: "2-digit",
    year: "numeric"
  });
  $('#datepicker').datepicker('update', formattedBirthdate);
  document.getElementById("birthdate").value = formattedBirthdate
  document.getElementById("ageClass").innerHTML = "Age Group is <b>" + ageClass + "</b>"
}
$(function () {
  $('#datepicker').datepicker();
});
