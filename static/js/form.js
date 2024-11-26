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
function toggleBlackBeltDanSection() {
  if (document.getElementById('blackBelt').checked) {
    document.getElementById("blackBeltDanSection").hidden = false;
    document.getElementById("blackBeltDan").required = true;
  }
  else {
    document.getElementById("blackBeltDanSection").hidden = true;
    document.getElementById("blackBeltDan").required = false;
  }
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
function enableSize(size) {
  if (document.getElementById("bool_tshirt_" + size).checked) {
    document.getElementById("section_tshirt_" + size).hidden = false;
    document.getElementById("tshirt_" + size).required = true;
    document.getElementById("tshirt_" + size).min = 1;
    document.getElementById("tshirt_" + size).value = 1;
    updateTotal();
  }
  else {
    document.getElementById("section_tshirt_" + size).hidden = true;
    document.getElementById("tshirt_" + size).required = false;
    document.getElementById("tshirt_" + size).min = 0;
    document.getElementById("tshirt_" + size).value = 0;
    updateTotal();
  }
}
function updateTotal() {
  const today = new Date()


  if (document.getElementById('regType').value == "seminar") {
    total = Number(window.tkdreg.price_dict.registration) + Number(window.tkdreg.price_dict.convfee);
  }
  else {
    total = Number(window.tkdreg.price_dict.convfee);
    tshirt_count = 0;
    tshirt_sizes = document.querySelectorAll('[name^=tshirt_]');
    tshirt_sizes.forEach((element) => tshirt_count += element.valueAsNumber);
    
    total += Number(window.tkdreg.price_dict.tickets) * document.getElementById("tickets").value;
    total += Number(window.tkdreg.price_dict.tshirts) * tshirt_count;
  }

  document.getElementById("total").value = "$" + total;
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
  formattedBirthdate = birthdate.toLocaleDateString("en-US", {
    month: "2-digit",
    day: "2-digit",
    year: "numeric"
  });

  if (age < 7) {
    document.getElementById("ageError").hidden = false;
    document.getElementById("submitBtn").disabled = true;
  }
  else {
    document.getElementById("ageError").hidden = true;
    document.getElementById("submitBtn").disabled = false;
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
}
updateTotal()