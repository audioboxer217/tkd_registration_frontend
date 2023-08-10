function upload_img(files) {
  if (files[0]) {

    var MAX_WIDTH = 300;
    var MAX_HEIGHT = 300;

    let imageFile = files[0];
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
  var blackBelt = "The first event for Black Belts is $100 and each additional event is $25"
  var colorBelt = "The first event for Color Belts is $90 and each additional event is $20"
  if (document.getElementById('blackBelt').checked) {
    document.getElementById("costDetail").innerHTML = blackBelt;
  }
  else {
    document.getElementById("costDetail").innerHTML = colorBelt;
  }
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
  if (
    document.querySelectorAll('input[name="beltRank"]:checked').length > 0 &&
    document.querySelectorAll('input[name="events"]:checked').length > 0
  ) {
    if (document.getElementById('blackBelt').checked) {
      var eventPrice = 25
      var total = 75
    }
    else {
      var eventPrice = 20
      var total = 70
    }
    total += eventPrice * document.querySelectorAll('input[name="events"]:checked').length
    document.getElementById("total").value = "$" + total
  }
  else if (
    document.querySelectorAll('input[name="beltRank"]:checked').length == 0 &&
    document.querySelectorAll('input[name="events"]:checked').length > 0
  ) {
    alert("Please choose a Belt Rank to get your Total")
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
