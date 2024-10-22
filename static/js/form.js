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
function lookup_entry(email) {
  fname = document.getElementById("fname").value;
  lname = document.getElementById("lname").value;

  query = "email=" + email;
  if (fname != '') {
    query += "&fname=" + fname;
  }
  if (lname != '') {
    query += "&lname=" + lname;
  }

  fetch('/lookup_entry?' + query)
    .then(response => response.json())
    .then(data => {
        if (data.length == 1) {autofillEntry(data[0])}
        else if (data.length > 1) {
          entryLookupDialog = document.getElementById('entryLookupDialog')
          entryLookupDialog.addEventListener('show.bs.modal', event => {
            const entrySelect = document.getElementById('entrySelect')
            for (a in entrySelect.options) { entrySelect.options.remove(0); }
            for (i=0; i < data.length; i++) {
              entrySelect.options[entrySelect.options.length] = new Option(data[i].name.S, i);
              }
          });
          entryLookupDialog.addEventListener('hide.bs.modal', event => {
            selection = document.getElementById('entrySelect').value
            if( selection ) {autofillEntry(data[selection])}
          });
          const entryLookupModal = new bootstrap.Modal('#entryLookupDialog')
          entryLookupModal.show(data);
        }
    });
}
function autofillEntry(data) {
  document.getElementById("fname").value = (data.name.S).split(" ")[0];
  document.getElementById("lname").value = (data.name.S).split(" ")[1];
  document.getElementById("inputPhone").value = data.phone.S;
  document.getElementById("inputSchool").value = data.school.S;
  if (document.getElementById('regType').value == "competitor") {
    document.getElementById("birthdate").value = (data.birthdate.S).replace(/(\d\d)\/(\d\d)\/(\d{4})/, "$3-$1-$2");
    calculateAge(document.getElementById("birthdate").value);
    document.getElementById("inputParentName").value = data.parent.S;
    document.getElementById("inputCoach").value = data.coach.S;
    if (data.gender.S == 'male') {
      document.getElementById("genderMale").checked = true;
    }
    else if (data.gender.S == 'female') {
      document.getElementById("genderFemale").checked = true;
    }
    console.log(data.medical_form.M)
    const allergies = data.medical_form.M.allergies.L;
    const medications = data.medical_form.M.medications.L;
    const contacts = data.medical_form.M.contacts.S;
    const medConditions = data.medical_form.M.medicalConditions.L;
    if (allergies.length > 0) {
      document.getElementById("allergyYes").checked = true;
      toggleAllergyList();
      allergyList = []
      for (const allergy of allergies){
        allergyList.push(allergy.S);
      }
      document.getElementById("allergy_list").value = allergyList.join('\n');
    }
    else {
      document.getElementById("allergyNo").checked = true;
      toggleAllergyList();
    }
    if (medications.length > 0) {
      document.getElementById("medsYes").checked = true;
      toggleMedsList();
      medsList = []
      for (const med of medConditions) {
        medsList.push(med.S);
      }
      document.getElementById("meds_list").value = medsList.join('\n');
    }
    else {
      document.getElementById("medsNo").checked = true;
      toggleMedsList();
    }
    if (contacts == "Y") {
      document.getElementById("contactsYes").checked = true;
    }
    else {
      document.getElementById("contactsNo").checked = true;
    }
    // Reset checked medicalConditions boxes
    for (const medCondition of ["epilepsy","lungDisease","heartDisease","diabetes","highBp"]) {
      document.getElementById(medCondition).checked = false;
    }
    if (medConditions.length > 0) {
      for (const mc of medConditions) {
        document.getElementById(mc.S).checked = true;
      }
    }
    document.getElementById("medicalWaiver").checked = true;
  }
}
function updateFields() {
  if (document.getElementById('regType').value == "competitor") {
    document.getElementById("classSection").hidden = false;
    document.getElementById("birthdate").required = true;
    document.getElementById("inputAge").required = true;
    document.getElementById("genderMale").required = true;
    document.getElementById("genderFemale").required = true;
    document.getElementById("weight").required = true;

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
    document.getElementById("weight").required = false;

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
function updateEventOptions() {
  const today = new Date()
  const early_reg_date = window.tkdreg.early_reg_date
  const little_tiger_msg = "Little Tiger Showcase Registration is $" + window.tkdreg.price_dict.little_tiger
  const competitive_msg = "Competitive Events Registration is $" + window.tkdreg.price_dict.registration + "  with 1 event.<br>Each additional event is $" + window.tkdreg.price_dict.addl_event
  var early_reg_warn = ""

  if (today < early_reg_date) {
    var early_reg_date_pretty = early_reg_date.toLocaleDateString('en-us', { month:"long", day:"numeric"}) 
    var early_reg_warn = "<br>Register before " + early_reg_date_pretty + " to get a $" + window.tkdreg.price_dict.coupon + " discount on registration."
  }

  if (
    document.getElementById("inputAge").value == '' || 
    document.getElementById("inputAge").value < 4
  ) {
    document.getElementById("beltSection").hidden = true;
    document.getElementById("eventSection").hidden = true;
  }
  else {
    document.getElementById("beltSection").hidden = false;
    document.getElementById("eventSection").hidden = false;
    document.getElementById("little_tiger_option").hidden = true;
    // document.getElementById("competitive").disabled = true;

    if (document.getElementById("inputAge").value <= 7) {
      document.getElementById("little_tiger_option").hidden = false;
      document.getElementById("costDetail").innerHTML = little_tiger_msg + '<br>' + competitive_msg + early_reg_warn;
      // document.getElementById("competitive").disabled = false;
    }
    else {
      document.getElementById("little_tiger_option").hidden = true;
      document.getElementById("little_tiger").checked = false;
      document.getElementById("costDetail").innerHTML = competitive_msg + early_reg_warn;
      // document.getElementById("competitive").checked = true;
      // document.getElementById("competitive").disabled = false;
    }

    // eventType = document.querySelectorAll('input[name="eventType"]:checked')[0].id
    // if (eventType == "little_tiger") {
    //   document.getElementById("costDetail").innerHTML = little_tiger_msg + early_reg_warn;
    //   document.getElementById("competitiveEventsSection").hidden = true;
    //   updateTotal(eventType)
    // }
    // else if (eventType == "competitive") {
    //   document.getElementById("costDetail").innerHTML = competitive_msg + early_reg_warn;
    //   document.getElementById("competitiveEventsSection").hidden = false;
    
    //   toggleBlackBeltDanSection()
    // }
  }

  toggleBlackBeltDanSection()
  document.getElementById("costDetail").classList = "bg-secondary text-white"
  updateTotal()
}
function toggleBlackBeltDanSection() {
  if (document.getElementById('blackBelt').checked) {
    // document.getElementById("sparringInput").hidden = true;
    // document.getElementById("sparring").checked = false;
    // document.getElementById("sparring-grInput").hidden = false;
    // document.getElementById("sparring-wcInput").hidden = false;
    document.getElementById("blackBeltDanSection").hidden = false;
    document.getElementById("blackBeltDan").required = true;
  }
  else {
    // document.getElementById("sparringInput").hidden = false;
    // document.getElementById("sparring-grInput").hidden = true;
    // document.getElementById("sparring-gr").checked = false;
    // document.getElementById("sparring-wcInput").hidden = true;
    // document.getElementById("sparring-wc").checked = false;
    document.getElementById("blackBeltDanSection").hidden = true;
    document.getElementById("blackBeltDan").required = false;
  }
}
function updateEventList(clickedEvent) {
  var eventList = []

  if (clickedEvent == 'sparring-wc') {
    document.getElementById("sparring-gr").checked = false;
  }
  else if (clickedEvent == 'sparring-gr') {
    document.getElementById("sparring-wc").checked = false;
  }
  else if (clickedEvent.endsWith('poomsae') && clickedEvent != 'freestyle poomsae') {
    eventElement = document.getElementById(clickedEvent)
    choicesElement = document.getElementById(clickedEvent + " form")
    if (eventElement.clicked == true) {
      choicesElement.required = true;
    }
    else {
      choicesElement.required = false;
      choicesElement.value = '';
    }
  }

  var checked_items = document.querySelectorAll('input[name="events"]:checked')
  for (i = 0; i < checked_items.length; i++) {
    eventList.push(checked_items[i].id)
  }
  document.getElementById("eventList").value = eventList.join()
  updateTotal()
  getPoomsaeForms("poomsae")
  getPoomsaeForms("pair poomsae")
  getPoomsaeForms("team poomsae")
  getPoomsaeForms("family poomsae")
}
function checkForUnlisted(school) {
  if (school == "unlisted") {
    document.getElementById("unlistedSchoolSection").hidden = false;
    document.getElementById("inputUnlistedSchool").required = true;
  }
  else {
    document.getElementById("unlistedSchoolSection").hidden = true;
    document.getElementById("inputUnlistedSchool").required = false;
  }
}
function updateMedicalConditionsList() {
  var conditionList = []

  var checked_items = document.querySelectorAll('input[name="medicalConditions"]:checked')
  for (i = 0; i < checked_items.length; i++) {
    conditionList.push(checked_items[i].id)
  }
  document.getElementById("medicalConditionsList").value = conditionList.join()
}
function updateTotal() {
  const today = new Date()
  const early_reg_date = window.tkdreg.early_reg_date

  if (document.getElementById('regType').value == "competitor") {
    if (
      document.querySelectorAll('input[name="beltRank"]:checked').length > 0 &&
      document.querySelectorAll('input[name="events"]:checked').length > 0
    ) {
      var eventCount = document.querySelectorAll('input[name="events"]:checked').length - 1
      var eventPrice = parseInt(window.tkdreg.price_dict.addl_event)
      var total = parseInt(window.tkdreg.price_dict.registration)
      if (document.getElementById('sparring-wc').checked) {
        total += parseInt(window.tkdreg.price_dict.world_class);
        // if (eventCount > 0){
        //   eventCount -= 1;
        // }
        // else {
        //   total -= eventPrice
        // }
      }
      if (document.getElementById('breaking').checked) {
        total += parseInt(window.tkdreg.price_dict.breaking);
        // if (eventCount > 0){
        //   eventCount -= 1;
        // }
        // else {
        //   total -= eventPrice
        // }
      }
      if (document.getElementById('little_tiger').checked) {
        if (eventCount > 0){
          total += parseInt(window.tkdreg.price_dict.little_tiger);
          eventCount -= 1;
        }
        else {
          total = parseInt(window.tkdreg.price_dict.little_tiger);
        }
      }
      total += eventPrice * eventCount;
      if (today < early_reg_date) {
        total -= parseInt(window.tkdreg.price_dict.coupon);
      }
      document.getElementById("total").value = "$" + total;
    }
    else if (
      document.querySelectorAll('input[name="beltRank"]:checked').length == 0 &&
      document.querySelectorAll('input[name="events"]:checked').length > 0
    ) {
      alert("Please choose a Belt Rank to get your Total")
    }
  }
  else {
    document.getElementById("total").value = "$" + window.tkdreg.price_dict.coach
  }
}
function getPoomsaeForms(fieldName) {
  sectionName = fieldName + 'FormSection'
  inputName = fieldName + ' form'
  if (document.getElementById(fieldName).checked) {
    document.getElementById(sectionName).hidden = false;
    document.getElementById(inputName).required = true;
  }
  else {
    document.getElementById(sectionName).hidden = true;
    document.getElementById(inputName).required = false;
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
  if (age < 4) {
    var ageClass = ""
  }
  else if (age >= 4 && age <= 7) {
    var ageClass = "Little Tiger"
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

  if (ageClass == "") {
    document.getElementById("ageClass").innerHTML = "<b style='color:red;'>Competitors must be at least 4 years old!</b>"
  }
  else {
    document.getElementById("ageClass").innerHTML = "Age Group is <b>" + ageClass + "</b>"
  }
  if (age < 18) {
    document.getElementById("inputParentName").required = true;
    document.getElementById("parentNameSection").hidden = false;
  }
  else {
    document.getElementById("inputParentName").required = false;
    document.getElementById("inputParentName").value = '';
    document.getElementById("parentNameSection").hidden = true;
  }
  updateEventOptions()
}
function toggleAllergyList() {
  allergies = document.querySelectorAll('input[name="allergies"]:checked')[0].id
  if (allergies == "allergyYes") {
    document.getElementById("allergyListSection").hidden = false;
    document.getElementById("allergy_list").required = true;
  }
  else {
    document.getElementById("allergyListSection").hidden = true;
    document.getElementById("allergy_list").required = false;
    document.getElementById("allergy_list").value = '';
  }
}
function toggleMedsList() {
  allergies = document.querySelectorAll('input[name="medications"]:checked')[0].id
  if (allergies == "medsYes") {
    document.getElementById("medsListSection").hidden = false;
    document.getElementById("meds_list").required = true;
  }
  else {
    document.getElementById("medsListSection").hidden = true;
    document.getElementById("meds_list").required = false;
    document.getElementById("meds_list").value = '';
  }
}