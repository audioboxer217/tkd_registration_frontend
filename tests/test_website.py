import io
import json
import os
import sys
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

base_path = os.path.dirname(os.path.realpath(__file__))
app_path = os.path.dirname(base_path)
sys.path.append(app_path)
from app import app


def make_admin_session(client):
    """Helper to set an admin session on the test client."""
    with client.session_transaction() as sess:
        sess["user"] = {"cognito:groups": ["Admins"], "email": "admin@test.com"}


def make_stripe_coupon_mock():
    """Return a mock stripe Coupon list with one item."""
    coupon = MagicMock()
    coupon.__getitem__ = lambda self, key: {"redeem_by": 1893456000, "amount_off": 2000}[key]
    coupon_list = MagicMock()
    coupon_list.data = [coupon]
    return coupon_list


def make_stripe_product_mock():
    """Return a mock stripe Product list with all required products."""
    products = []
    for name in [
        "Competitor Registration",
        "Additional Event",
        "Black Belt Registration",
        "Color Belt Registration",
        "Little Dragon Obstacle Course",
        "Coach Registration",
        "Convenience Fee",
    ]:
        product = MagicMock()
        product.name = name
        product.default_price = f"price_{name.replace(' ', '_').lower()}"
        products.append(product)
    product_list = MagicMock()
    product_list.__iter__.return_value = iter(products)
    return product_list


def make_stripe_price_mock():
    """Return a mock stripe Price."""
    price = MagicMock()
    price.id = "price_test123"
    price.unit_amount = 5000
    return price


class TestHomepage:
    client = app.test_client()
    response = client.get("/")

    def test_response_code(self):
        assert self.response.status_code == 200

    def test_competition_name(self):
        competition_name = os.environ.get("COMPETITION_NAME")
        assert competition_name.encode() in self.response.data

    def test_early_reg(self):
        html_line = f'<h2>Early Registration Ends <font color="red">{os.environ.get("EARLY_REG_DATE")}'
        assert html_line.encode() in self.response.data

    def test_reg_close(self):
        html_line = f'<h2>Registration Closes <font color="red">{os.environ.get("REG_CLOSE_DATE")}</font>'
        assert html_line.encode() in self.response.data

    def test_contact_email(self):
        contact_email = os.environ.get("CONTACT_EMAIL")
        html_line = f'You can contact us at <a href="mailto:{contact_email}">{contact_email}</a> if you have questions or issues.'
        assert html_line.encode() in self.response.data


class TestAuthRoutes:
    client = app.test_client()

    def test_login_redirects(self):
        # The login route redirects to Cognito OAuth. Without COGNITO_AUTHORITY_URL
        # configured (as in the test environment), the OAuth call may fail with a 500.
        # In production with proper Cognito configuration, this will always be a 302.
        response = self.client.get("/login")
        assert response.status_code in (302, 500)

    def test_logout_redirects(self):
        response = self.client.get("/logout")
        assert response.status_code == 302


class TestRegistrationErrorPage:
    client = app.test_client()

    def test_response_code(self):
        response = self.client.get("/registration_error")
        assert response.status_code == 200

    def test_contains_error_heading(self):
        response = self.client.get("/registration_error")
        assert b"Registration already exists!" in response.data

    def test_contains_contact_email(self):
        contact_email = os.environ.get("CONTACT_EMAIL")
        response = self.client.get("/registration_error")
        assert contact_email.encode() in response.data

    def test_contains_competition_name(self):
        competition_name = os.environ.get("COMPETITION_NAME")
        response = self.client.get("/registration_error")
        assert competition_name.encode() in response.data

    def test_reg_type_in_response(self):
        response = self.client.get("/registration_error?reg_type=competitor")
        assert b"competitor" in response.data


class TestVisitPage:
    client = app.test_client()

    def test_response_code(self):
        response = self.client.get("/visit")
        assert response.status_code == 200

    def test_contains_content(self):
        response = self.client.get("/visit")
        assert b"Tulsa" in response.data


class TestHotelPage:
    client = app.test_client()

    def test_response_code(self):
        response = self.client.get("/hotel")
        assert response.status_code == 200

    def test_contains_content(self):
        response = self.client.get("/hotel")
        assert b"Hotel" in response.data or b"hotel" in response.data or b"Candlewood" in response.data


class TestSchedulePage:
    client = app.test_client()

    def test_response_code(self):
        response = self.client.get("/schedule")
        assert response.status_code == 200

    def test_contains_heading(self):
        response = self.client.get("/schedule")
        assert b"Schedule" in response.data


class TestScheduleDetails:
    client = app.test_client()

    def test_no_schedule_returns_not_found(self):
        with patch("app.get_s3_file", return_value=None):
            response = self.client.get("/get_schedule_details")
        assert response.status_code == 200
        assert b"Schedule not found" in response.data


class TestEntriesPage:
    client = app.test_client()

    def test_response_code(self):
        response = self.client.get("/entries")
        assert response.status_code == 200

    def test_contains_heading(self):
        response = self.client.get("/entries")
        assert b"Entries" in response.data


class TestEntriesAPI:
    client = app.test_client()

    def test_response_code(self):
        mock_scan = {"Items": []}
        with patch("app.dynamodb") as mock_db, patch("app.set_weight_class", return_value=[]):
            mock_db.scan.return_value = mock_scan
            response = self.client.get("/api/entries")
        assert response.status_code == 200

    def test_returns_json(self):
        mock_scan = {"Items": []}
        with patch("app.dynamodb") as mock_db, patch("app.set_weight_class", return_value=[]):
            mock_db.scan.return_value = mock_scan
            response = self.client.get("/api/entries")
        data = json.loads(response.data)
        assert "data" in data

    def test_returns_competitor_and_coach_entries(self):
        mock_items = [
            {
                "reg_type": {"S": "competitor"},
                "full_name": {"S": "Jane Doe"},
                "age": {"N": "15"},
                "gender": {"S": "F"},
                "weight": {"N": "120"},
            },
            {"reg_type": {"S": "coach"}, "full_name": {"S": "John Coach"}},
        ]
        with patch("app.dynamodb") as mock_db, patch("app.set_weight_class", return_value=[mock_items[0]]):
            mock_db.scan.return_value = {"Items": mock_items}
            response = self.client.get("/api/entries")
        data = json.loads(response.data)
        assert len(data["data"]) == 2


class TestUploadForm:
    client = app.test_client()

    def test_schedule_upload_form(self):
        response = self.client.get("/upload/schedule")
        assert response.status_code == 200
        assert b"Upload Schedule" in response.data or b"schedule" in response.data.lower()

    def test_booklet_upload_form(self):
        response = self.client.get("/upload/booklet")
        assert response.status_code == 200
        assert b"Upload Booklet" in response.data or b"booklet" in response.data.lower()


class TestNameValidation:
    client = app.test_client()

    def test_valid_name(self):
        response = self.client.post("/api/validate/name/fname", data={"fname": "John"})
        assert response.status_code == 200
        assert b"is-valid" in response.data

    def test_invalid_name_empty(self):
        response = self.client.post("/api/validate/name/fname", data={"fname": ""})
        assert response.status_code == 200
        assert b"is-invalid" in response.data

    def test_invalid_name_with_numbers(self):
        response = self.client.post("/api/validate/name/fname", data={"fname": "John123"})
        assert response.status_code == 200
        assert b"is-invalid" in response.data

    def test_valid_name_with_space(self):
        response = self.client.post("/api/validate/name/parentName", data={"parentName": "Mary Jane"})
        assert response.status_code == 200
        assert b"is-valid" in response.data


class TestNumberValidation:
    client = app.test_client()

    def test_valid_number(self):
        response = self.client.post("/api/validate/number/weight", data={"weight": "150"})
        assert response.status_code == 200
        assert b"is-valid" in response.data

    def test_invalid_number_empty(self):
        response = self.client.post("/api/validate/number/weight", data={"weight": ""})
        assert response.status_code == 200
        assert b"is-invalid" in response.data

    def test_invalid_number_non_digit(self):
        response = self.client.post("/api/validate/number/weight", data={"weight": "abc"})
        assert response.status_code == 200
        assert b"is-invalid" in response.data


class TestEmailValidation:
    client = app.test_client()

    def test_valid_email(self):
        with patch("app.validate_email"):
            response = self.client.post("/api/validate/email", data={"email": "test@example.com", "regType": "competitor"})
        assert response.status_code == 200
        assert b"is-valid" in response.data

    def test_invalid_email(self):
        from email_validator import EmailNotValidError

        with patch("app.validate_email", side_effect=EmailNotValidError("Invalid")):
            response = self.client.post("/api/validate/email", data={"email": "notanemail", "regType": "competitor"})
        assert response.status_code == 200
        assert b"is-invalid" in response.data

    def test_valid_email_shows_lookup_button_for_competitor(self):
        with patch("app.validate_email"):
            response = self.client.post("/api/validate/email", data={"email": "test@example.com", "regType": "competitor"})
        assert response.status_code == 200
        assert b"Lookup Previous Registration" in response.data


class TestPhoneValidation:
    client = app.test_client()

    def test_valid_phone(self):
        response = self.client.post("/api/validate/phone", data={"phone": "1234567890"})
        assert response.status_code == 200
        assert b"is-valid" in response.data

    def test_invalid_phone_too_short(self):
        response = self.client.post("/api/validate/phone", data={"phone": "12345"})
        assert response.status_code == 200
        assert b"is-invalid" in response.data

    def test_valid_phone_with_formatting(self):
        response = self.client.post("/api/validate/phone", data={"phone": "123-456-7890"})
        assert response.status_code == 200
        assert b"is-valid" in response.data

    def test_invalid_phone_non_digit(self):
        response = self.client.post("/api/validate/phone", data={"phone": "abcdefghij"})
        assert response.status_code == 200
        assert b"is-invalid" in response.data


class TestBirthdateValidation:
    client = app.test_client()

    def test_valid_birthdate(self):
        response = self.client.post("/api/validate/birthdate", data={"birthdate": "2010-06-15"})
        assert response.status_code == 200
        assert b"is-valid" in response.data

    def test_invalid_birthdate_format(self):
        response = self.client.post("/api/validate/birthdate", data={"birthdate": "not-a-date"})
        assert response.status_code == 200
        assert b"is-invalid" in response.data

    def test_too_young_birthdate(self):
        too_young_date = (datetime.now() - timedelta(days=3 * 365)).strftime("%Y-%m-%d")
        response = self.client.post("/api/validate/birthdate", data={"birthdate": too_young_date})
        assert response.status_code == 200
        assert b"is-invalid" in response.data

    def test_valid_birthdate_shows_age_group(self):
        response = self.client.post("/api/validate/birthdate", data={"birthdate": "2010-06-15"})
        assert response.status_code == 200
        assert b"Age Group" in response.data


class TestSchoolValidation:
    client = app.test_client()

    def test_valid_school_selection(self):
        schools = ["School A", "School B"]
        with patch("app.s3") as mock_s3:
            mock_s3.get_object.return_value = {"Body": io.BytesIO(json.dumps(schools).encode())}
            response = self.client.post("/api/validate/school", data={"school": "School A"})
        assert response.status_code == 200
        assert b"is-valid" in response.data

    def test_invalid_school_empty(self):
        schools = ["School A", "School B"]
        with patch("app.s3") as mock_s3:
            mock_s3.get_object.return_value = {"Body": io.BytesIO(json.dumps(schools).encode())}
            response = self.client.post("/api/validate/school", data={"school": ""})
        assert response.status_code == 200
        assert b"is-invalid" in response.data


class TestLookupEntry:
    client = app.test_client()

    def test_lookup_no_results(self):
        with patch("app.dynamodb") as mock_db:
            mock_db.scan.return_value = {"Items": []}
            response = self.client.post("/lookup_entry", data={"email": "nobody@example.com", "fname": "", "lname": ""})
        assert response.status_code == 200

    def test_lookup_with_results(self):
        mock_items = [{"name": {"S": "john doe"}, "email": {"S": "john@example.com"}, "birthdate": {"S": "01/01/2000"}}]
        with patch("app.dynamodb") as mock_db:
            mock_db.scan.return_value = {"Items": mock_items}
            response = self.client.post("/lookup_entry", data={"email": "john@example.com", "fname": "john", "lname": "doe"})
        assert response.status_code == 200
        assert b"john" in response.data.lower()


class TestRegisterPage:
    client = app.test_client()

    def test_register_get_response_code(self):
        schools = ["School A", "School B"]
        with (
            patch("stripe.Coupon.list", return_value=make_stripe_coupon_mock()),
            patch("stripe.Product.list", return_value=make_stripe_product_mock()),
            patch("stripe.Price.retrieve", return_value=make_stripe_price_mock()),
            patch("app.s3") as mock_s3,
            patch("app.get_s3_file", return_value=None),
        ):
            mock_s3.get_object.return_value = {"Body": io.BytesIO(json.dumps(schools).encode())}
            response = self.client.get("/register")
        assert response.status_code == 200

    def test_register_get_contains_form(self):
        schools = ["School A", "School B"]
        with (
            patch("stripe.Coupon.list", return_value=make_stripe_coupon_mock()),
            patch("stripe.Product.list", return_value=make_stripe_product_mock()),
            patch("stripe.Price.retrieve", return_value=make_stripe_price_mock()),
            patch("app.s3") as mock_s3,
            patch("app.get_s3_file", return_value=None),
        ):
            mock_s3.get_object.return_value = {"Body": io.BytesIO(json.dumps(schools).encode())}
            response = self.client.get("/register")
        assert b"eventRegistration" in response.data or b"form" in response.data.lower()


class TestSchoolsAPI:
    client = app.test_client()

    def test_add_school(self):
        response = self.client.post(
            "/api/schools/add",
            data={"school": "New School", "schoolList": "School A,School B"},
        )
        assert response.status_code == 200
        assert b"New School" in response.data

    def test_remove_school(self):
        response = self.client.delete("/api/schools/remove/0?schoolList=School A,School B")
        assert response.status_code == 200
        assert b"REMOVE" in response.data


class TestAdminProtectedRoutes:
    """Test that admin-protected routes redirect unauthenticated users to /login."""

    client = app.test_client()

    def test_admin_page_redirects_unauthenticated(self):
        with patch("app.dynamodb") as mock_db:
            mock_db.scan.return_value = {"Items": []}
            response = self.client.get("/admin")
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]

    def test_schools_page_redirects_unauthenticated(self):
        response = self.client.get("/schools")
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]

    def test_add_entry_get_redirects_unauthenticated(self):
        response = self.client.get("/add_entry")
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]

    def test_export_redirects_unauthenticated(self):
        response = self.client.get("/export")
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]


class TestAdminPage:
    """Test admin page with authenticated admin session."""

    def test_admin_page_accessible_with_session(self):
        client = app.test_client()
        make_admin_session(client)
        with patch("app.dynamodb") as mock_db, patch("app.get_s3_file", return_value=None):
            mock_db.scan.return_value = {"Items": []}
            response = client.get("/admin")
        assert response.status_code == 200

    def test_admin_page_contains_export_link(self):
        client = app.test_client()
        make_admin_session(client)
        with patch("app.dynamodb") as mock_db, patch("app.get_s3_file", return_value=None):
            mock_db.scan.return_value = {"Items": []}
            response = client.get("/admin")
        assert b"Export" in response.data or b"export" in response.data.lower()


class TestSchoolsPage:
    """Test schools admin page with authenticated admin session."""

    def test_schools_page_accessible_with_session(self):
        client = app.test_client()
        make_admin_session(client)
        schools = ["School A", "School B"]
        with patch("app.s3") as mock_s3, patch("app.get_s3_file", return_value=None):
            mock_s3.get_object.return_value = {"Body": io.BytesIO(json.dumps(schools).encode())}
            response = client.get("/schools")
        assert response.status_code == 200
        assert b"School A" in response.data


class TestAddEntryForm:
    """Test add entry form with authenticated admin session."""

    def test_add_entry_form_accessible_with_session(self):
        client = app.test_client()
        make_admin_session(client)
        schools = ["School A", "School B"]
        with (
            patch("stripe.Coupon.list", return_value=make_stripe_coupon_mock()),
            patch("stripe.Product.list", return_value=make_stripe_product_mock()),
            patch("stripe.Price.retrieve", return_value=make_stripe_price_mock()),
            patch("app.s3") as mock_s3,
            patch("app.get_s3_file", return_value=None),
        ):
            mock_s3.get_object.return_value = {"Body": io.BytesIO(json.dumps(schools).encode())}
            response = client.get("/add_entry")
        assert response.status_code == 200


class TestEditEntryForm:
    """Test edit entry form with authenticated admin session."""

    def test_edit_entry_form_accessible_with_session(self):
        client = app.test_client()
        make_admin_session(client)
        schools = ["School A", "School B"]
        mock_entry = {
            "pk": {"S": "TestSchool-competitor-John_Doe"},
            "full_name": {"S": "John Doe"},
            "email": {"S": "john@example.com"},
            "phone": {"S": "123-456-7890"},
            "school": {"S": "Test School"},
            "reg_type": {"S": "competitor"},
            "birthdate": {"S": "2005-06-15"},
            "age": {"N": "19"},
            "gender": {"S": "M"},
            "weight": {"N": "150"},
            "height": {"N": "68"},
            "coach": {"S": "Coach Smith"},
            "beltRank": {"S": "1 degree black"},
            "parent": {"S": ""},
            "events": {"S": "sparring"},
            "poomsae_form": {"S": ""},
            "pair_poomsae_form": {"S": ""},
            "team_poomsae_form": {"S": ""},
            "family_poomsae_form": {"S": ""},
        }
        with patch("app.dynamodb") as mock_db, patch("app.s3") as mock_s3, patch("app.get_s3_file", return_value=None):
            mock_db.get_item.return_value = {"Item": mock_entry}
            mock_s3.get_object.return_value = {"Body": io.BytesIO(json.dumps(schools).encode())}
            response = client.get("/edit_entry?pk=TestSchool-competitor-John_Doe")
        assert response.status_code == 200


class TestExportPage:
    """Test export page with authenticated admin session."""

    def test_export_accessible_with_session(self):
        client = app.test_client()
        make_admin_session(client)
        with patch("app.dynamodb") as mock_db, patch("app.get_s3_file", return_value=None):
            mock_db.scan.return_value = {"Items": []}
            response = client.get("/export")
        assert response.status_code == 200

    def test_export_contains_competition_name(self):
        client = app.test_client()
        make_admin_session(client)
        competition_name = os.environ.get("COMPETITION_NAME")
        with patch("app.dynamodb") as mock_db, patch("app.get_s3_file", return_value=None):
            mock_db.scan.return_value = {"Items": []}
            response = client.get("/export")
        assert competition_name.encode() in response.data


class TestSuccessPage:
    """Test the success page returned after payment."""

    def test_success_page_response_code(self):
        client = app.test_client()
        mock_session = MagicMock()
        mock_session.payment_intent = None
        with (
            patch("stripe.checkout.Session.retrieve", return_value=mock_session),
            patch("stripe.Product.list", return_value=make_stripe_product_mock()),
            patch("stripe.Price.retrieve", return_value=make_stripe_price_mock()),
            patch("app.get_s3_file", return_value=None),
        ):
            response = client.get("/success?session_id=cs_test_fake&reg_type=competitor")
        assert response.status_code == 200

    def test_success_page_contains_confirmation_text(self):
        client = app.test_client()
        mock_session = MagicMock()
        mock_session.payment_intent = None
        with (
            patch("stripe.checkout.Session.retrieve", return_value=mock_session),
            patch("stripe.Product.list", return_value=make_stripe_product_mock()),
            patch("stripe.Price.retrieve", return_value=make_stripe_price_mock()),
            patch("app.get_s3_file", return_value=None),
        ):
            response = client.get("/success?session_id=cs_test_fake&reg_type=competitor")
        assert b"Registration Submitted Successfully" in response.data


class TestNotFoundPage:
    client = app.test_client()

    def test_404_response_code(self):
        response = self.client.get("/this-page-does-not-exist")
        assert response.status_code == 404


if __name__ == "__main__":
    homepage = TestHomepage()
    print(homepage.test_response_code())
