import email
import io
import json
import os
import smtplib
import sys
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import stripe
import pytest

base_path = os.path.dirname(os.path.realpath(__file__))
app_path = os.path.dirname(base_path)
sys.path.append(app_path)

# Ensure required env vars have defaults so tests pass without a full environment
os.environ.setdefault("COMPETITION_NAME", "Test Taekwondo Championship")
os.environ.setdefault("CONTACT_EMAIL", "contact@example.com")
os.environ.setdefault("EARLY_REG_DATE", "January 01, 2025")
os.environ.setdefault("REG_CLOSE_DATE", "December 31, 2099")
os.environ.setdefault("STRIPE_API_KEY", "sk_test_placeholder")
os.environ.setdefault("CONFIG_BUCKET", "test-config-bucket")
os.environ.setdefault("PUBLIC_MEDIA_BUCKET", "test-media-bucket")

from app import create_app
from models import Coach
from models import db as _db

_test_app = create_app(
    test_config={
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "URL": "http://localhost:5001",
    }
)

with _test_app.app_context():
    _db.create_all()

app = _test_app


def make_admin_session(client):
    """Helper to set an admin session on the test client."""
    with client.session_transaction() as sess:
        sess["user"] = {
            "id": "test-user-id",
            "email": "admin@test.com",
            "role": "admin",
        }


def make_stripe_coupon_mock():
    """Return a mock stripe Coupon list with one item."""
    coupon = MagicMock()
    coupon_data = {
        "id": "coupon_early_reg",
        "redeem_by": 1893456000,
        "amount_off": 2000,
    }
    coupon.__getitem__.side_effect = lambda key: coupon_data[key]
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


def get_or_create_test_school(name):
    """Get or create a School record in the test database by name."""
    from models import School
    from models import db as _db

    with app.app_context():
        school = School.query.filter_by(name=name).first()
        if not school:
            school = School(name=name)
            _db.session.add(school)
            _db.session.commit()
        return school.id


class TestHomepage:
    client = app.test_client()

    def setup_method(self):
        """Set up response with mocked Stripe."""
        with patch("app.stripe.Coupon.list") as mock_coupons:
            mock_coupons.return_value = MagicMock(data=[])
            self.response = self.client.get("/")

    def test_response_code(self):
        assert self.response.status_code == 200

    def test_competition_name(self):
        competition_name = os.environ.get("COMPETITION_NAME")
        assert competition_name.encode() in self.response.data

    def test_early_reg(self):
        early_reg_date_str = os.environ.get("EARLY_REG_DATE")
        early_reg_date = datetime.strptime(early_reg_date_str, "%B %d, %Y")
        html_text = self.response.data.decode()

        if datetime.now() < early_reg_date:
            assert "Early Registration Ends" in html_text
            assert early_reg_date_str in html_text
        else:
            assert "Early Registration Ends" not in html_text or early_reg_date_str not in html_text

    def test_reg_close(self):
        html_line = f'<h2>Registration Closes <font color="red">{os.environ.get("REG_CLOSE_DATE")}</font>'
        assert html_line.encode() in self.response.data

    def test_contact_email(self):
        contact_email = os.environ.get("CONTACT_EMAIL")
        html_line = f'You can contact us at <a href="mailto:{contact_email}">{contact_email}</a> if you have questions or issues.'
        assert html_line.encode() in self.response.data


class TestAuthRoutes:
    client = app.test_client()

    def test_login_get_returns_form(self):
        with patch("app.get_s3_file", return_value=None):
            response = self.client.get("/login")
        assert response.status_code == 200
        assert b"Login" in response.data or b"login" in response.data.lower()

    def test_login_post_bad_credentials_shows_error(self):
        with patch("app.get_supabase") as mock_sb:
            mock_client = MagicMock()
            mock_client.auth.sign_in_with_password.side_effect = Exception("Invalid credentials")
            mock_sb.return_value = mock_client
            with patch("app.get_s3_file", return_value=None):
                response = self.client.post("/login", data={"email": "bad@example.com", "password": "wrong"})
        assert response.status_code == 200
        assert b"Login failed" in response.data or b"danger" in response.data

    def test_logout_redirects(self):
        with patch("app.get_supabase") as mock_sb:
            mock_sb.return_value = MagicMock()
            with patch("app.get_s3_file", return_value=None):
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
        with patch("api.set_weight_class", return_value=[]):
            response = self.client.get("/api/v1/entries")
        assert response.status_code == 200

    def test_returns_json(self):
        with patch("api.set_weight_class", return_value=[]):
            response = self.client.get("/api/v1/entries")
        data = json.loads(response.data)
        assert "data" in data

    def test_returns_competitor_and_coach_entries(self):
        from models import Coach, Competitor
        from models import db as _db

        school_id = get_or_create_test_school("Entries Test School")
        with app.app_context():
            competitor = Competitor(
                full_name="Jane Doe",
                email="jane@example.com",
                school_id=school_id,
                age=15,
                gender="F",
                weight=120,
            )
            coach = Coach(
                full_name="John Coach",
                email="coach@example.com",
                school_id=school_id,
            )
            _db.session.add(competitor)
            _db.session.add(coach)
            _db.session.commit()
            c_id = competitor.id
            co_id = coach.id

        with patch("api.set_weight_class", return_value=[{"id": c_id, "full_name": "Jane Doe", "reg_type": "competitor"}]):
            response = self.client.get("/api/v1/entries")
        data = json.loads(response.data)
        entries = data["data"]
        assert any(entry.get("id") == c_id and entry.get("reg_type") == "competitor" for entry in entries)
        assert any(entry.get("id") == co_id and entry.get("reg_type") == "coach" for entry in entries)

    def test_status_filter_complete(self):
        from api import get_eligible_competitors
        from models import Competitor
        from models import db as _db

        school_id = get_or_create_test_school("Status Filter School")
        with app.app_context():
            complete = Competitor(
                full_name="Complete Competitor",
                email="complete@example.com",
                school_id=school_id,
                age=20,
                gender="M",
                status="complete",
            )
            pending = Competitor(
                full_name="Pending Competitor",
                email="pending@example.com",
                school_id=school_id,
                age=20,
                gender="M",
                status="pending",
            )
            _db.session.add_all([complete, pending])
            _db.session.commit()
            complete_id = complete.id
            pending_id = pending.id

            results = get_eligible_competitors(status="complete")
            result_ids = [c.id for c in results]
            assert complete_id in result_ids
            assert pending_id not in result_ids

    def test_status_filter_none_returns_all(self):
        from api import get_eligible_competitors
        from models import Competitor
        from models import db as _db

        school_id = get_or_create_test_school("Status None School")
        with app.app_context():
            c1 = Competitor(
                full_name="All1 Competitor",
                email="all1@example.com",
                school_id=school_id,
                age=20,
                gender="M",
                status="complete",
            )
            c2 = Competitor(
                full_name="All2 Competitor",
                email="all2@example.com",
                school_id=school_id,
                age=20,
                gender="F",
                status="failed",
            )
            _db.session.add_all([c1, c2])
            _db.session.commit()
            id1, id2 = c1.id, c2.id

            results = get_eligible_competitors(status=None)
            result_ids = [c.id for c in results]
            assert id1 in result_ids
            assert id2 in result_ids

    def test_entries_endpoint_status_query_param(self):
        from models import Competitor
        from models import db as _db

        school_id = get_or_create_test_school("Endpoint Status School")
        with app.app_context():
            complete = Competitor(
                full_name="EP Complete",
                email="ep_complete@example.com",
                school_id=school_id,
                age=20,
                gender="M",
                status="complete",
            )
            pending = Competitor(
                full_name="EP Pending",
                email="ep_pending@example.com",
                school_id=school_id,
                age=20,
                gender="F",
                status="pending",
            )
            _db.session.add_all([complete, pending])
            _db.session.commit()
            complete_id = complete.id
            pending_id = pending.id

        with patch("api.set_weight_class", side_effect=lambda entries, _: entries):
            response = self.client.get("/api/v1/entries?status=complete")
        data = json.loads(response.data)
        entries = data["data"]
        result_ids = [e.get("id") for e in entries if e.get("reg_type") == "competitor"]
        assert complete_id in result_ids
        assert pending_id not in result_ids


class TestRegistrationsAPI:
    client = app.test_client()

    def test_create_pending_competitor_registration(self):
        payload = {
            "reg_type": "competitor",
            "full_name": "Webhook Pending Competitor",
            "email": "pending_competitor@example.com",
            "phone": "555-0100",
            "school": "Webhook School",
        }

        response = self.client.post("/api/v1/registrations", json=payload)

        assert response.status_code == 201
        response_data = json.loads(response.data)
        assert "id" in response_data["data"]
        assert "checkout_url" not in response_data["data"]

        from models import Competitor

        with app.app_context():
            competitor = Competitor.query.filter_by(email="pending_competitor@example.com").first()
            assert competitor is not None
            assert competitor.status == "pending"
            assert competitor.checkout_session_id is None
            assert competitor.school.name == "Webhook School"

    def test_create_competitor_registration_links_coach(self):
        from models import Coach
        from models import db as _db

        school_id = get_or_create_test_school("Coach Link School")
        with app.app_context():
            coach = Coach(
                full_name="Linked Coach",
                email="linked_coach@example.com",
                school_id=school_id,
            )
            _db.session.add(coach)
            _db.session.commit()
            coach_id = coach.id

        payload = {
            "reg_type": "competitor",
            "full_name": "Coach Link Competitor",
            "email": "coach_link_competitor@example.com",
            "phone": "555-0200",
            "school": "Coach Link School",
            "coach": "Linked Coach",
        }

        with patch("api.stripe.checkout.Session.create") as mock_create:
            response = self.client.post("/api/v1/registrations", json=payload)

        mock_create.assert_not_called()
        assert response.status_code == 201

        from models import Competitor

        with app.app_context():
            competitor = Competitor.query.filter_by(email="coach_link_competitor@example.com").first()
            assert competitor is not None
            assert competitor.coach_id == coach_id

    def test_create_competitor_registration_unknown_coach_sets_null(self):
        payload = {
            "reg_type": "competitor",
            "full_name": "Unknown Coach Competitor",
            "email": "unknown_coach_competitor@example.com",
            "phone": "555-0201",
            "school": "Unknown Coach School",
            "coach": "Nonexistent Coach",
        }

        response = self.client.post("/api/v1/registrations", json=payload)

        assert response.status_code == 201

        from models import Competitor

        with app.app_context():
            competitor = Competitor.query.filter_by(email="unknown_coach_competitor@example.com").first()
            assert competitor is not None
            assert competitor.coach_id is None

    def test_create_pending_coach_registration(self):
        payload = {
            "reg_type": "coach",
            "full_name": "Webhook Pending Coach",
            "email": "pending_coach@example.com",
            "phone": "555-0101",
            "school": "Webhook School",
        }

        with patch("api.stripe.checkout.Session.create") as mock_create:
            response = self.client.post("/api/v1/registrations", json=payload)

        # Coaches do not go through Stripe; Stripe must NOT be called.
        mock_create.assert_not_called()
        assert response.status_code == 201

        data = json.loads(response.data)
        assert "id" in data["data"]
        assert "checkout_url" not in data["data"]

        from models import Coach

        with app.app_context():
            coach = Coach.query.filter_by(email="pending_coach@example.com").first()
            assert coach is not None
            assert coach.school.name == "Webhook School"

    def test_create_registration_returns_409_for_duplicate_competitor(self):
        from models import Competitor
        from models import db as _db

        school_id = get_or_create_test_school("Duplicate API School")
        with app.app_context():
            existing = Competitor(
                full_name="Duplicate Person",
                email="first_duplicate@example.com",
                school_id=school_id,
                status="pending",
            )
            _db.session.add(existing)
            _db.session.commit()

        payload = {
            "reg_type": "competitor",
            "full_name": "Duplicate Person",
            "email": "second_duplicate@example.com",
            "phone": "555-0199",
            "school": "Duplicate API School",
        }

        with patch("api.stripe.checkout.Session.create") as mock_create:
            response = self.client.post("/api/v1/registrations", json=payload)

        mock_create.assert_not_called()
        assert response.status_code == 409
        data = json.loads(response.data)
        assert data["error"] == "Duplicate registration for Duplicate Person"

    def test_create_registration_validation_error_returns_string_error(self):
        response = self.client.post("/api/v1/registrations", json={})

        assert response.status_code == 422
        data = json.loads(response.data)
        assert isinstance(data.get("error", data.get("message")), str)

    def test_create_registration_does_not_send_school_alert_when_commit_fails(self):
        payload = {
            "reg_type": "coach",
            "full_name": "Commit Failure Coach",
            "email": "commit.failure.coach@example.com",
            "phone": "555-0198",
            "school": "Commit Failure School",
        }

        with (
            patch("api.send_admin_school_alert") as send_alert,
            patch("api.db.session.commit", side_effect=RuntimeError("commit failed")),
        ):
            with pytest.raises(RuntimeError, match="commit failed"):
                self.client.post("/api/v1/registrations", json=payload)

        send_alert.assert_not_called()

    def test_registration_status_coach_returns_null_status(self):
        from models import Coach
        from models import db as _db

        school_id = get_or_create_test_school("Status Coach School")
        with app.app_context():
            coach = Coach(
                full_name="Status Coach",
                email="status_coach@example.com",
                school_id=school_id,
            )
            _db.session.add(coach)
            _db.session.commit()
            coach_id = coach.id

        response = self.client.get(f"/api/v1/registrations/{coach_id}/status?type=coach")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["data"]["reg_type"] == "coach"
        assert data["data"]["status"] is None

    def test_registration_status_returns_status(self):
        from models import Competitor
        from models import db as _db

        school_id = get_or_create_test_school("Status API School")
        with app.app_context():
            competitor = Competitor(
                full_name="Status Competitor",
                email="status_competitor@example.com",
                school_id=school_id,
                status="complete",
                checkout_session_id="cs_test_status",
            )
            _db.session.add(competitor)
            _db.session.commit()
            reg_id = competitor.id

        response = self.client.get(f"/api/v1/registrations/{reg_id}/status")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["data"]["status"] == "complete"

    def test_webhook_completed_updates_status_and_payment_intent(self):
        from models import Competitor
        from models import db as _db

        school_id = get_or_create_test_school("Webhook Complete School")
        with app.app_context():
            competitor = Competitor(
                full_name="Webhook Complete Competitor",
                email="webhook_complete@example.com",
                school_id=school_id,
                status="pending",
                checkout_session_id="cs_test_complete",
            )
            _db.session.add(competitor)
            _db.session.commit()
            reg_id = competitor.id

        event = {
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_test_complete", "payment_intent": "pi_test_complete"}},
        }

        with (
            patch.dict(os.environ, {"STRIPE_WEBHOOK_SECRET": "whsec_test"}),
            patch("api.stripe.Webhook.construct_event", return_value=event),
            patch("api._send_confirmation_email") as send_email,
        ):
            response = self.client.post("/api/v1/webhooks/stripe", data=b"{}", headers={"Stripe-Signature": "sig_test"})

        assert response.status_code == 200
        send_email.assert_called_once()

        with app.app_context():
            competitor = _db.session.get(Competitor, reg_id)
            assert competitor.status == "complete"
            assert competitor.payment_intent == "pi_test_complete"

    def test_webhook_expired_sets_status_failed(self):
        from models import Competitor
        from models import db as _db

        school_id = get_or_create_test_school("Webhook Expired School")
        with app.app_context():
            competitor = Competitor(
                full_name="Webhook Expired Competitor",
                email="webhook_expired@example.com",
                school_id=school_id,
                status="pending",
                checkout_session_id="cs_test_expired",
            )
            _db.session.add(competitor)
            _db.session.commit()
            reg_id = competitor.id

        event = {
            "type": "checkout.session.expired",
            "data": {"object": {"id": "cs_test_expired", "payment_intent": None}},
        }

        with (
            patch.dict(os.environ, {"STRIPE_WEBHOOK_SECRET": "whsec_test"}),
            patch("api.stripe.Webhook.construct_event", return_value=event),
        ):
            response = self.client.post("/api/v1/webhooks/stripe", data=b"{}", headers={"Stripe-Signature": "sig_test"})

        assert response.status_code == 200

        with app.app_context():
            competitor = _db.session.get(Competitor, reg_id)
            assert competitor.status == "failed"

    def test_webhook_invalid_signature_returns_400(self):
        with (
            patch.dict(os.environ, {"STRIPE_WEBHOOK_SECRET": "whsec_test"}),
            patch(
                "api.stripe.Webhook.construct_event",
                side_effect=stripe.error.SignatureVerificationError("Invalid signature", "sig_test"),
            ),
        ):
            response = self.client.post("/api/v1/webhooks/stripe", data=b"{}", headers={"Stripe-Signature": "sig_test"})

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["error"] == "Invalid payload or signature"

    def test_send_confirmation_email_sends_directly_via_smtp(self):
        from api import _send_confirmation_email
        from models import Competitor
        from models import db as _db

        school_id = get_or_create_test_school("Confirmation School")
        with app.app_context():
            competitor = Competitor(
                full_name="Email Competitor",
                email="email_competitor@example.com",
                school_id=school_id,
                events="sparring,poomsae",
                status="complete",
                belt_rank="Black",
                poomsae_form="1",
            )
            _db.session.add(competitor)
            _db.session.commit()
            _db.session.refresh(competitor)

            smtp_mock = MagicMock()
            with (
                patch("api.smtplib.SMTP_SSL") as smtp_cls_mock,
                patch.dict(
                    "os.environ",
                    {
                        "EMAIL_SERVER": "smtp.example.com",
                        "EMAIL_PORT": "465",
                        "FROM_EMAIL": "no-reply@example.com",
                        "EMAIL_PASSWD": "secret",
                        "CONTACT_EMAIL": "contact@example.com",
                    },
                ),
            ):
                smtp_cls_mock.return_value.__enter__ = MagicMock(return_value=smtp_mock)
                smtp_cls_mock.return_value.__exit__ = MagicMock(return_value=False)
                _send_confirmation_email(competitor)

        smtp_mock.login.assert_called_once_with("no-reply@example.com", "secret")
        smtp_mock.sendmail.assert_called_once()
        _, to_addr, msg_str = smtp_mock.sendmail.call_args.args
        assert to_addr == "email_competitor@example.com"
        parsed = email.message_from_string(msg_str)
        body = parsed.get_payload(decode=True).decode()
        assert "Email Competitor" in body
        assert "sparring" in body.lower()
        assert "Taegeuk 1 Jang" in body

    def test_send_admin_school_alert_sends_via_smtp(self):
        from api import _send_admin_school_alert

        smtp_mock = MagicMock()
        with (
            patch("api.smtplib.SMTP_SSL") as smtp_cls_mock,
            patch.dict(
                "os.environ",
                {
                    "EMAIL_SERVER": "smtp.example.com",
                    "EMAIL_PORT": "465",
                    "FROM_EMAIL": "no-reply@example.com",
                    "EMAIL_PASSWD": "secret",
                    "ADMIN_EMAIL": "admin@example.com",
                },
            ),
        ):
            smtp_cls_mock.return_value.__enter__ = MagicMock(return_value=smtp_mock)
            smtp_cls_mock.return_value.__exit__ = MagicMock(return_value=False)
            with app.app_context():
                _send_admin_school_alert("Some Unknown School")

        smtp_mock.login.assert_called_once_with("no-reply@example.com", "secret")
        smtp_mock.sendmail.assert_called_once()
        _, to_addr, msg_str = smtp_mock.sendmail.call_args.args
        assert to_addr == "admin@example.com"
        parsed = email.message_from_string(msg_str)
        body = parsed.get_payload(decode=True).decode()
        assert "Some Unknown School" in body

    def test_send_admin_school_alert_swallows_smtp_errors(self):
        from api import _send_admin_school_alert

        smtp_mock = MagicMock()
        smtp_mock.login.side_effect = smtplib.SMTPAuthenticationError(535, b"Auth failed")
        with (
            patch("api.smtplib.SMTP_SSL") as smtp_cls_mock,
            patch.dict(
                "os.environ",
                {
                    "EMAIL_SERVER": "smtp.example.com",
                    "EMAIL_PORT": "465",
                    "FROM_EMAIL": "no-reply@example.com",
                    "EMAIL_PASSWD": "secret",
                    "ADMIN_EMAIL": "admin@example.com",
                },
            ),
        ):
            smtp_cls_mock.return_value.__enter__ = MagicMock(return_value=smtp_mock)
            smtp_cls_mock.return_value.__exit__ = MagicMock(return_value=False)
            with app.app_context():
                _send_admin_school_alert("Some Unknown School")

    def test_create_registration_with_unknown_school_sends_admin_alert(self):
        """Registering with a school not yet in the DB should trigger an admin alert."""
        payload = {
            "reg_type": "competitor",
            "full_name": "New School Competitor",
            "email": "newschool.competitor@example.com",
            "phone": "555-0302",
            "school": "Brand New Unknown School",
        }

        with patch("api.send_admin_school_alert") as mock_alert:
            response = self.client.post("/api/v1/registrations", json=payload)

        assert response.status_code == 201
        mock_alert.assert_called_once_with("Brand New Unknown School")

    def test_registration_status_includes_payment_intent(self):
        """registration_status endpoint should return payment_intent field."""
        from models import Competitor
        from models import db as _db

        school_id = get_or_create_test_school("Payment Intent School")
        with app.app_context():
            competitor = Competitor(
                full_name="PayIntent Competitor",
                email="payintent_competitor@example.com",
                school_id=school_id,
                status="complete",
                checkout_session_id="cs_test_payintent",
                payment_intent="pi_test_payintent",
            )
            _db.session.add(competitor)
            _db.session.commit()
            reg_id = competitor.id

        response = self.client.get(f"/api/v1/registrations/{reg_id}/status")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["data"]["payment_intent"] == "pi_test_payintent"


class TestRegistrationEndToEnd:
    """End-to-end tests covering the full registration lifecycle."""

    client = app.test_client()

    def test_competitor_registration_full_end_to_end(self):
        """End-to-end: UI form → Stripe checkout → webhook completed → confirmation email.

        1. POST /register submits the competitor form and creates a DB record.
        2. A Stripe checkout session is created (mocked); checkout_session_id is saved.
        3. Webhook processing for checkout.session.completed event sets status="complete".
        4. A confirmation email is sent after the webhook is processed.
        """
        from models import Competitor
        from models import db as _db

        form_data = {
            "regType": "competitor",
            "fname": "E2E",
            "lname": "Competitor",
            "school": "E2E End-to-End School",
            "email": "e2e.competitor@example.com",
            "phone": "555-0300",
            "coach": "",
            "liability": "on",
            "eventList": "sparring",
            "heightFt": "5",
            "heightIn": "8",
            "weight": "150",
            "age": "20",
            "gender": "M",
            "beltRank": "red",
            "poomsae form": "",
            "wc poomsae form": "",
            "pair poomsae form": "",
            "team poomsae form": "",
            "family poomsae form": "",
            "parentName": "",
            "birthdate": "2004-01-01",
            "contacts": "",
            "medicalConditionsList": "",
            "allergy_list": "",
            "meds_list": "",
        }

        mock_checkout_session = MagicMock()
        mock_checkout_session.id = "cs_test_e2e_comp"
        mock_checkout_session.url = "https://checkout.stripe.test/e2e_comp"

        with (
            patch(
                "app.get_price_details",
                return_value={
                    "Color Belt Registration": {"price_id": "price_color", "unit_amount": 8000},
                    "Black Belt Registration": {"price_id": "price_black", "unit_amount": 8000},
                    "Additional Event": {"price_id": "price_add", "unit_amount": 2000},
                    "Little Dragon Obstacle Course": {"price_id": "price_ld", "unit_amount": 3000},
                    "Convenience Fee": {"price_id": "price_fee", "unit_amount": 300},
                },
            ),
            patch("app.stripe.Coupon.list", return_value=make_stripe_coupon_mock()),
            patch("app.stripe.checkout.Session.create", return_value=mock_checkout_session),
        ):
            form_response = self.client.post("/register", data=form_data)

        # Step 1: form submission creates a pending record and returns a Stripe redirect
        assert form_response.status_code == 200
        assert b"checkout.stripe.test" in form_response.data

        with app.app_context():
            competitor = Competitor.query.filter_by(email="e2e.competitor@example.com").first()
            assert competitor is not None
            assert competitor.checkout_session_id == "cs_test_e2e_comp"
            assert competitor.status == "pending"
            reg_id = competitor.id

        # Step 2: Stripe sends a webhook event for successful payment
        event = {
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_test_e2e_comp", "payment_intent": "pi_e2e_comp"}},
        }

        with (
            patch.dict(os.environ, {"STRIPE_WEBHOOK_SECRET": "whsec_e2e_test"}),
            patch("api.stripe.Webhook.construct_event", return_value=event),
            patch("api._send_confirmation_email") as mock_email,
        ):
            webhook_response = self.client.post(
                "/api/v1/webhooks/stripe",
                data=b"{}",
                headers={"Stripe-Signature": "sig_e2e"},
            )

        assert webhook_response.status_code == 200
        mock_email.assert_called_once()

        # Step 3: DB record reflects payment completion
        with app.app_context():
            competitor = _db.session.get(Competitor, reg_id)
            assert competitor.status == "complete"
            assert competitor.payment_intent == "pi_e2e_comp"

    def test_coach_registration_full_end_to_end(self):
        """End-to-end coach registration: UI form → DB record created → redirect to success.

        Coaches skip Stripe payment entirely and are immediately redirected to /success.
        """
        from models import Coach

        form_data = {
            "regType": "coach",
            "fname": "E2E",
            "lname": "Coach",
            "school": "E2E Coach School",
            "email": "e2e.coach@example.com",
            "phone": "555-0301",
            "coach": "",
        }

        form_response = self.client.post("/register", data=form_data)

        assert form_response.status_code == 302
        assert "/success" in form_response.headers["Location"]
        assert "reg_type=coach" in form_response.headers["Location"]

        with app.app_context():
            coach = Coach.query.filter_by(email="e2e.coach@example.com").first()
            assert coach is not None
            assert coach.full_name == "E2E Coach"
            assert coach.phone == "555-0301"
            assert coach.school is not None
            assert coach.school.name == "E2E Coach School"


class TestUploadForm:
    def test_schedule_upload_form(self):
        client = app.test_client()
        make_admin_session(client)
        with patch("app.get_s3_file", return_value=None):
            response = client.get("/upload/schedule")
        assert response.status_code == 200
        assert b"Upload Schedule" in response.data or b"schedule" in response.data.lower()

    def test_booklet_upload_form(self):
        client = app.test_client()
        make_admin_session(client)
        with patch("app.get_s3_file", return_value=None):
            response = client.get("/upload/booklet")
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
        with patch("app._s3") as mock_s3_factory:
            mock_s3 = MagicMock()
            mock_s3.get_object.return_value = {"Body": io.BytesIO(json.dumps(schools).encode())}
            mock_s3_factory.return_value = mock_s3
            response = self.client.post("/api/validate/school", data={"school": "School A"})
        assert response.status_code == 200
        assert b"is-valid" in response.data

    def test_invalid_school_empty(self):
        schools = ["School A", "School B"]
        with patch("app._s3") as mock_s3_factory:
            mock_s3 = MagicMock()
            mock_s3.get_object.return_value = {"Body": io.BytesIO(json.dumps(schools).encode())}
            mock_s3_factory.return_value = mock_s3
            response = self.client.post("/api/validate/school", data={"school": ""})
        assert response.status_code == 200
        assert b"is-invalid" in response.data


class TestLookupEntry:
    client = app.test_client()

    def test_lookup_no_results(self):
        response = self.client.post("/lookup_entry", data={"email": "nobody@example.com", "fname": "", "lname": ""})
        assert response.status_code == 200

    def test_lookup_with_results(self):
        from models import Competitor
        from models import db as _db

        school_id = get_or_create_test_school("Lookup Test School")
        with app.app_context():
            competitor = Competitor(
                full_name="john doe",
                email="john@example.com",
                school_id=school_id,
                birthdate="01/01/2000",
            )
            _db.session.add(competitor)
            _db.session.commit()

        response = self.client.post("/lookup_entry", data={"email": "john@example.com", "fname": "john", "lname": "doe"})
        assert response.status_code == 200
        assert b"john" in response.data.lower()


class TestLoadHistoricalEntries:
    """Unit tests for the _load_historical_entries helper."""

    def test_returns_entries_matching_email(self):
        from app import _load_historical_entries

        entries = [
            {"full_name": "Alice Smith", "email": "alice@example.com", "reg_type": "competitor"},
            {"full_name": "Bob Jones", "email": "bob@example.com", "reg_type": "coach"},
        ]
        with (
            patch("app._s3") as mock_s3_factory,
            app.app_context(),
        ):
            mock_s3 = MagicMock()
            mock_s3.get_object.return_value = {"Body": io.BytesIO(json.dumps(entries).encode())}
            mock_s3_factory.return_value = mock_s3
            result = _load_historical_entries("alice@example.com")

        assert len(result) == 1
        assert result[0]["full_name"] == "Alice Smith"

    def test_excludes_entries_with_different_email(self):
        from app import _load_historical_entries

        entries = [
            {"full_name": "Alice Smith", "email": "alice@example.com"},
            {"full_name": "Bob Jones", "email": "bob@example.com"},
        ]
        with (
            patch("app._s3") as mock_s3_factory,
            app.app_context(),
        ):
            mock_s3 = MagicMock()
            mock_s3.get_object.return_value = {"Body": io.BytesIO(json.dumps(entries).encode())}
            mock_s3_factory.return_value = mock_s3
            result = _load_historical_entries("bob@example.com")

        assert len(result) == 1
        assert result[0]["full_name"] == "Bob Jones"

    def test_returns_empty_list_when_no_email_match(self):
        from app import _load_historical_entries

        entries = [{"full_name": "Alice Smith", "email": "alice@example.com"}]
        with (
            patch("app._s3") as mock_s3_factory,
            app.app_context(),
        ):
            mock_s3 = MagicMock()
            mock_s3.get_object.return_value = {"Body": io.BytesIO(json.dumps(entries).encode())}
            mock_s3_factory.return_value = mock_s3
            result = _load_historical_entries("nobody@example.com")

        assert result == []

    def test_returns_empty_list_on_s3_exception(self):
        from app import _load_historical_entries

        with (
            patch("app._s3") as mock_s3_factory,
            app.app_context(),
        ):
            mock_s3 = MagicMock()
            mock_s3.get_object.side_effect = Exception("S3 unavailable")
            mock_s3_factory.return_value = mock_s3
            result = _load_historical_entries("anyone@example.com")

        assert result == []

    def test_returns_empty_list_on_malformed_json(self):
        from app import _load_historical_entries

        with (
            patch("app._s3") as mock_s3_factory,
            app.app_context(),
        ):
            mock_s3 = MagicMock()
            mock_s3.get_object.return_value = {"Body": io.BytesIO(b"not valid json")}
            mock_s3_factory.return_value = mock_s3
            result = _load_historical_entries("anyone@example.com")

        assert result == []


class TestLookupEntryWithHistory:
    """Tests for lookup_entry merging current DB results with historical S3 entries."""

    client = app.test_client()

    _historical_entries = [
        {
            "full_name": "Historical Person",
            "email": "historical@example.com",
            "reg_type": "competitor",
            "school": "Old School",
            "belt_rank": "2 degree black",
        }
    ]

    def _mock_s3_with_history(self, mock_s3_factory, entries=None):
        data = entries if entries is not None else self._historical_entries
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = {"Body": io.BytesIO(json.dumps(data).encode())}
        mock_s3_factory.return_value = mock_s3
        return mock_s3

    def test_returns_historical_entry_when_not_in_current_db(self):
        with patch("app._s3") as mock_s3_factory:
            self._mock_s3_with_history(mock_s3_factory)
            response = self.client.post(
                "/lookup_entry",
                data={"email": "historical@example.com", "fname": "", "lname": ""},
            )
        assert response.status_code == 200
        assert b"Historical Person" in response.data

    def test_current_db_entry_takes_precedence_over_historical_same_name(self):
        from models import Competitor

        school_id = get_or_create_test_school("Precedence Test School")
        with app.app_context():
            competitor = Competitor(
                full_name="Duplicate Person",
                email="dup@example.com",
                school_id=school_id,
            )
            _db.session.add(competitor)
            _db.session.commit()

        historical = [{"full_name": "Duplicate Person", "email": "dup@example.com", "reg_type": "competitor"}]
        with patch("app._s3") as mock_s3_factory:
            self._mock_s3_with_history(mock_s3_factory, historical)
            response = self.client.post(
                "/lookup_entry",
                data={"email": "dup@example.com", "fname": "", "lname": ""},
            )
        assert response.status_code == 200
        # Name appears exactly once (deduplication — only the DB entry is kept)
        assert response.data.lower().count(b"duplicate person") == 1

    def test_merges_historical_and_current_db_different_names(self):
        from models import Competitor

        school_id = get_or_create_test_school("Merge Test School")
        with app.app_context():
            competitor = Competitor(
                full_name="Current Person",
                email="merge@example.com",
                school_id=school_id,
            )
            _db.session.add(competitor)
            _db.session.commit()

        historical = [{"full_name": "Historical Person 2", "email": "merge@example.com", "reg_type": "competitor"}]
        with patch("app._s3") as mock_s3_factory:
            self._mock_s3_with_history(mock_s3_factory, historical)
            response = self.client.post(
                "/lookup_entry",
                data={"email": "merge@example.com", "fname": "", "lname": ""},
            )
        assert response.status_code == 200
        assert b"Current Person" in response.data
        assert b"Historical Person 2" in response.data

    def test_name_filter_applies_to_merged_results(self):
        from models import Competitor

        school_id = get_or_create_test_school("Filter Test School")
        with app.app_context():
            competitor = Competitor(
                full_name="Alice Filter",
                email="filter@example.com",
                school_id=school_id,
            )
            _db.session.add(competitor)
            _db.session.commit()

        historical = [{"full_name": "Bob Filter", "email": "filter@example.com", "reg_type": "competitor"}]
        with patch("app._s3") as mock_s3_factory:
            self._mock_s3_with_history(mock_s3_factory, historical)
            response = self.client.post(
                "/lookup_entry",
                data={"email": "filter@example.com", "fname": "alice", "lname": "filter"},
            )
        assert response.status_code == 200
        assert b"Alice Filter" in response.data
        assert b"Bob Filter" not in response.data

    def test_gracefully_falls_back_to_db_only_when_s3_unavailable(self):
        from models import Competitor

        school_id = get_or_create_test_school("Fallback Test School")
        with app.app_context():
            competitor = Competitor(
                full_name="DB Only Person",
                email="fallback@example.com",
                school_id=school_id,
            )
            _db.session.add(competitor)
            _db.session.commit()

        with patch("app._s3") as mock_s3_factory:
            mock_s3 = MagicMock()
            mock_s3.get_object.side_effect = Exception("S3 down")
            mock_s3_factory.return_value = mock_s3
            response = self.client.post(
                "/lookup_entry",
                data={"email": "fallback@example.com", "fname": "", "lname": ""},
            )
        assert response.status_code == 200
        assert b"DB Only Person" in response.data

    def test_no_results_returns_200_when_s3_unavailable(self):
        with patch("app._s3") as mock_s3_factory:
            mock_s3 = MagicMock()
            mock_s3.get_object.side_effect = Exception("S3 down")
            mock_s3_factory.return_value = mock_s3
            response = self.client.post(
                "/lookup_entry",
                data={"email": "ghost@example.com", "fname": "", "lname": ""},
            )
        assert response.status_code == 200


class TestRegisterPage:
    client = app.test_client()

    def test_register_get_response_code(self):
        schools = ["School A", "School B"]
        with (
            patch("stripe.Coupon.list", return_value=make_stripe_coupon_mock()),
            patch("stripe.Product.list", return_value=make_stripe_product_mock()),
            patch("stripe.Price.retrieve", return_value=make_stripe_price_mock()),
            patch("app._s3") as mock_s3_factory,
            patch("app.get_s3_file", return_value=None),
        ):
            mock_s3 = MagicMock()
            mock_s3.get_object.return_value = {"Body": io.BytesIO(json.dumps(schools).encode())}
            mock_s3_factory.return_value = mock_s3
            response = self.client.get("/register")
        assert response.status_code == 200

    def test_register_get_contains_form(self):
        schools = ["School A", "School B"]
        with (
            patch("stripe.Coupon.list", return_value=make_stripe_coupon_mock()),
            patch("stripe.Product.list", return_value=make_stripe_product_mock()),
            patch("stripe.Price.retrieve", return_value=make_stripe_price_mock()),
            patch("app._s3") as mock_s3_factory,
            patch("app.get_s3_file", return_value=None),
        ):
            mock_s3 = MagicMock()
            mock_s3.get_object.return_value = {"Body": io.BytesIO(json.dumps(schools).encode())}
            mock_s3_factory.return_value = mock_s3
            response = self.client.get("/register")
        assert b"eventRegistration" in response.data or b"form" in response.data.lower()


class TestHandleForm:
    """Tests for POST /register — validates that the UI route delegates to create_registration_record
    for DB writes, handles Stripe checkout for competitors, and redirects coaches directly."""

    client = app.test_client()

    def _base_competitor_form(self):
        return {
            "regType": "competitor",
            "fname": "John",
            "lname": "Doe",
            "school": "Handle Form School",
            "email": "john.doe.handleform@example.com",
            "phone": "555-9999",
            "coach": "",
            "liability": "on",
            "eventList": "sparring",
            "heightFt": "5",
            "heightIn": "8",
            "weight": "150",
            "age": "20",
            "gender": "male",
            "beltRank": "red",
            "poomsae form": "",
            "wc poomsae form": "",
            "pair poomsae form": "",
            "team poomsae form": "",
            "family poomsae form": "",
            "parentName": "",
            "birthdate": "2004-01-01",
            "contacts": "",
            "medicalConditionsList": "",
            "allergy_list": "",
            "meds_list": "",
        }

    def test_register_post_competitor_redirects_to_stripe(self):
        """Competitor POST should create a DB record and meta-refresh to Stripe checkout URL."""
        from models import Competitor

        form_data = self._base_competitor_form()

        with (
            patch(
                "app.get_price_details",
                return_value={
                    "Color Belt Registration": {"price_id": "price_color", "unit_amount": 8000},
                    "Black Belt Registration": {"price_id": "price_black", "unit_amount": 8000},
                    "Additional Event": {"price_id": "price_add", "unit_amount": 2000},
                    "Little Dragon Obstacle Course": {"price_id": "price_ld", "unit_amount": 3000},
                    "Convenience Fee": {"price_id": "price_fee", "unit_amount": 300},
                },
            ),
            patch("app.stripe.Coupon.list", return_value=make_stripe_coupon_mock()),
            patch("app.stripe.checkout.Session.create") as mock_stripe,
        ):
            mock_stripe.return_value = MagicMock(id="cs_test_ui_123", url="https://checkout.stripe.test/ui")
            response = self.client.post("/register", data=form_data)

        assert response.status_code == 200
        assert b"checkout.stripe.test" in response.data

        with app.app_context():
            comp = Competitor.query.filter_by(email="john.doe.handleform@example.com").first()
            assert comp is not None
            assert comp.checkout_session_id == "cs_test_ui_123"

    def test_register_post_coach_redirects_to_success(self):
        """Coach POST should create a DB Coach record and redirect to /success."""
        from models import Coach

        form_data = {
            "regType": "coach",
            "fname": "Coach",
            "lname": "TestPerson",
            "school": "Handle Form School",
            "email": "coach.testperson.handleform@example.com",
            "phone": "555-8888",
            "coach": "",
        }

        response = self.client.post("/register", data=form_data)

        assert response.status_code == 302
        assert "/success" in response.headers["Location"]
        assert "reg_type=coach" in response.headers["Location"]

        with app.app_context():
            coach = Coach.query.filter_by(email="coach.testperson.handleform@example.com").first()
            assert coach is not None

    def test_register_post_duplicate_redirects_to_error_page(self):
        """Duplicate competitor submission should redirect to /registration_error."""
        from models import Competitor
        from models import db as _db

        school_id = get_or_create_test_school("Handle Form School")
        with app.app_context():
            existing = Competitor(
                full_name="Dup Handle Form",
                email="dup.handleform.existing@example.com",
                school_id=school_id,
                status="pending",
            )
            _db.session.add(existing)
            _db.session.commit()

        form_data = self._base_competitor_form()
        form_data["fname"] = "Dup"
        form_data["lname"] = "Handle Form"
        form_data["email"] = "dup.handleform.new@example.com"

        with (
            patch("app.get_price_details", return_value={}),
            patch("app.stripe.Coupon.list", return_value=make_stripe_coupon_mock()),
        ):
            response = self.client.post("/register", data=form_data)

        assert response.status_code == 302
        assert "/registration_error" in response.headers["Location"]

    def test_register_post_missing_name_returns_400(self):
        form_data = {
            "regType": "coach",
            "fname": "",
            "lname": "TestPerson",
            "school": "Handle Form School",
            "email": "coach.missingname@example.com",
            "phone": "555-8888",
            "coach": "",
        }

        response = self.client.post("/register", data=form_data)

        assert response.status_code == 400

    def test_register_post_unlisted_school_missing_name_returns_400(self):
        form_data = {
            "regType": "coach",
            "fname": "Coach",
            "lname": "TestPerson",
            "school": "unlisted",
            "unlistedSchool": "",
            "email": "coach.unlistedmissing@example.com",
            "phone": "555-8888",
            "coach": "",
        }

        response = self.client.post("/register", data=form_data)

        assert response.status_code == 400

    def test_register_post_missing_email_returns_400(self):
        form_data = {
            "regType": "coach",
            "fname": "Coach",
            "lname": "TestPerson",
            "school": "Handle Form School",
            "email": "",
            "phone": "555-8888",
            "coach": "",
        }

        response = self.client.post("/register", data=form_data)

        assert response.status_code == 400

    def test_register_post_invalid_competitor_height_returns_400(self):
        form_data = self._base_competitor_form()
        form_data["heightFt"] = "five"

        response = self.client.post("/register", data=form_data)

        assert response.status_code == 400

    def test_register_post_invalid_competitor_weight_returns_400(self):
        form_data = self._base_competitor_form()
        form_data["weight"] = "heavy"

        response = self.client.post("/register", data=form_data)

        assert response.status_code == 400

    def test_register_duplicate_with_badges_does_not_upload_profile_image(self):
        from models import Competitor
        from models import db as _db

        school_id = get_or_create_test_school("Handle Form School")
        with app.app_context():
            existing = Competitor(
                full_name="Dup Handle Form",
                email="dup.badges.existing@example.com",
                school_id=school_id,
                status="pending",
            )
            _db.session.add(existing)
            _db.session.commit()

        form_data = self._base_competitor_form()
        form_data["fname"] = "Dup"
        form_data["lname"] = "Handle Form"
        form_data["email"] = "dup.badges.new@example.com"
        form_data["profilePic"] = (io.BytesIO(b"avatar"), "avatar.jpg", "image/jpeg")

        with (
            patch.dict(app.config, {"ENABLE_BADGES": True, "profilePicBucket": "test-profile-bucket"}),
            patch("app._s3") as mock_s3_factory,
            patch("app.get_price_details", return_value={}),
            patch("app.stripe.Coupon.list", return_value=make_stripe_coupon_mock()),
        ):
            mock_s3 = MagicMock()
            mock_s3_factory.return_value = mock_s3
            response = self.client.post("/register", data=form_data, content_type="multipart/form-data")

        assert response.status_code == 302
        assert "/registration_error" in response.headers["Location"]
        mock_s3.upload_fileobj.assert_not_called()

    def test_register_stripe_failure_cleans_up_uploaded_badge_and_returns_502(self):
        form_data = self._base_competitor_form()
        form_data["fname"] = "Stripe"
        form_data["lname"] = "Failure"
        form_data["email"] = "stripe.failure.cleanup@example.com"
        form_data["profilePic"] = (io.BytesIO(b"avatar"), "avatar.jpg", "image/jpeg")

        with (
            patch.dict(app.config, {"ENABLE_BADGES": True, "profilePicBucket": "test-profile-bucket"}),
            patch("app._s3") as mock_s3_factory,
            patch(
                "app.get_price_details",
                return_value={
                    "Color Belt Registration": {"price_id": "price_color", "unit_amount": 8000},
                    "Black Belt Registration": {"price_id": "price_black", "unit_amount": 8000},
                    "Additional Event": {"price_id": "price_add", "unit_amount": 2000},
                    "Little Dragon Obstacle Course": {"price_id": "price_ld", "unit_amount": 3000},
                    "Convenience Fee": {"price_id": "price_fee", "unit_amount": 300},
                },
            ),
            patch("app.stripe.Coupon.list", return_value=make_stripe_coupon_mock()),
            patch("app.stripe.checkout.Session.create", side_effect=stripe.error.StripeError("Stripe unavailable")),
        ):
            mock_s3 = MagicMock()
            mock_s3_factory.return_value = mock_s3
            response = self.client.post("/register", data=form_data, content_type="multipart/form-data")

        assert response.status_code == 502
        mock_s3.upload_fileobj.assert_called_once()
        mock_s3.delete_object.assert_called_once()
        _, upload_bucket, upload_key = mock_s3.upload_fileobj.call_args.args
        assert upload_bucket == "test-profile-bucket"
        assert upload_key == "Handle Form School_competitor_Stripe_Failure.jpg"
        mock_s3.delete_object.assert_called_once_with(Bucket=upload_bucket, Key=upload_key)


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
        with patch("app.get_s3_file", return_value=None):
            response = client.get("/admin")
        assert response.status_code == 200

    def test_admin_page_contains_export_link(self):
        client = app.test_client()
        make_admin_session(client)
        with patch("app.get_s3_file", return_value=None):
            response = client.get("/admin")
        assert b"Export" in response.data or b"export" in response.data.lower()


class TestSchoolsPage:
    """Test schools admin page with authenticated admin session."""

    def test_schools_page_accessible_with_session(self):
        client = app.test_client()
        make_admin_session(client)
        get_or_create_test_school("School A")

        with patch("app.get_s3_file", return_value=None):
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
            patch("app._s3") as mock_s3_factory,
            patch("app.get_s3_file", return_value=None),
        ):
            mock_s3 = MagicMock()
            mock_s3.get_object.return_value = {"Body": io.BytesIO(json.dumps(schools).encode())}
            mock_s3_factory.return_value = mock_s3
            response = client.get("/add_entry")
        assert response.status_code == 200


class TestAddEntryPost:
    """Test add entry POST flow for admin manual entry."""

    def test_add_entry_post_coach_creates_record_without_sqs(self):
        client = app.test_client()
        make_admin_session(client)

        form_data = {
            "regType": "coach",
            "fname": "Coach",
            "lname": "Manual",
            "email": "coach.manual@example.com",
            "phone": "555-555-1212",
            "school": "Manual Entry School",
        }

        response = client.post("/add_entry", data=form_data)
        assert response.status_code == 303
        assert response.headers["Location"].endswith("/admin")

        with app.app_context():
            coach = Coach.query.filter_by(full_name="Coach Manual").first()
            assert coach is not None
            assert coach.email == "coach.manual@example.com"


class TestEditEntryForm:
    """Test edit entry form with authenticated admin session."""

    def test_edit_entry_form_accessible_with_session(self):
        client = app.test_client()
        make_admin_session(client)
        from models import Competitor
        from models import db as _db

        school_id = get_or_create_test_school("Edit Test School")
        with app.app_context():
            competitor = Competitor(
                full_name="John Doe",
                email="john@example.com",
                phone="123-456-7890",
                school_id=school_id,
                birthdate="2005-06-15",
                age=19,
                gender="M",
                weight=150,
                height=68,
                belt_rank="1 degree black",
                events="sparring",
            )
            _db.session.add(competitor)
            _db.session.commit()
            reg_id = competitor.id

        with patch("app.get_s3_file", return_value=None):
            response = client.get(f"/edit_entry?pk={reg_id}")
        assert response.status_code == 200

    def test_edit_entry_updates_events(self):
        client = app.test_client()
        make_admin_session(client)
        from models import Competitor
        from models import db as _db

        school_id = get_or_create_test_school("Update Test School")
        with app.app_context():
            competitor = Competitor(
                full_name="John Doe",
                email="john@example.com",
                phone="123-456-7890",
                school_id=school_id,
                birthdate="2005-06-15",
                age=19,
                gender="M",
                weight=150,
                height=68,
                belt_rank="1 degree black",
                events="sparring",
            )
            _db.session.add(competitor)
            _db.session.commit()
            reg_id = competitor.id

        form_data = {
            "full_name": "John Doe",
            "email": "john@example.com",
            "phone": "123-456-7890",
            "school": "Update Test School",
            "regType": "competitor",
            "parentName": "",
            "birthdate": "2005-06-15",
            "age": "19",
            "gender": "M",
            "weight": "150",
            "height": "68",
            "coach": "",
            "beltRank": "black",
            "blackBeltDan": "1",
            "eventList": "sparring,breaking",
            "poomsae form": "",
            "pair poomsae form": "",
            "team poomsae form": "",
            "family poomsae form": "",
        }
        with patch("app.get_s3_file", return_value=None):
            response = client.post(f"/edit?pk={reg_id}", data=form_data)
        assert response.status_code == 303
        with app.app_context():
            updated = _db.session.get(Competitor, reg_id)
            assert updated.events == "sparring,breaking"


class TestExportPage:
    """Test export page with authenticated admin session."""

    def test_export_accessible_with_session(self):
        client = app.test_client()
        make_admin_session(client)
        with patch("app.get_s3_file", return_value=None):
            response = client.get("/export")
        assert response.status_code == 200

    def test_export_contains_competition_name(self):
        client = app.test_client()
        make_admin_session(client)
        competition_name = os.environ.get("COMPETITION_NAME")
        with patch("app.get_s3_file", return_value=None):
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


class TestAdminAlertBranches:
    """Tests that verify admin-alert emails are sent for critical error paths.

    Covers the three branches added in the logging/alerting PR:
    - Stripe checkout session creation failure (app.py add_entry / handle_form)
    - Confirmation email SMTP failure (api.py _send_confirmation_email)
    - Unhandled 500 error handler (app.py internal_server_error)
    """

    client = app.test_client()

    def _base_competitor_form(self):
        return {
            "regType": "competitor",
            "fname": "Alert",
            "lname": "TestUser",
            "school": "Alert Branch School",
            "email": "alert.branch.test@example.com",
            "phone": "555-6666",
            "coach": "",
            "liability": "on",
            "eventList": "sparring",
            "heightFt": "5",
            "heightIn": "8",
            "weight": "150",
            "age": "20",
            "gender": "M",
            "beltRank": "red",
            "poomsae form": "",
            "wc poomsae form": "",
            "pair poomsae form": "",
            "team poomsae form": "",
            "family poomsae form": "",
            "parentName": "",
            "birthdate": "2004-01-01",
            "contacts": "",
            "medicalConditionsList": "",
            "allergy_list": "",
            "meds_list": "",
        }

    def test_stripe_checkout_failure_sends_admin_alert(self):
        """Stripe Session.create failure should invoke send_admin_alert with the expected subject."""
        form_data = self._base_competitor_form()
        form_data["email"] = "stripe.alert.branch@example.com"

        with (
            patch(
                "app.get_price_details",
                return_value={
                    "Color Belt Registration": {"price_id": "price_color", "unit_amount": 8000},
                    "Black Belt Registration": {"price_id": "price_black", "unit_amount": 8000},
                    "Additional Event": {"price_id": "price_add", "unit_amount": 2000},
                    "Little Dragon Obstacle Course": {"price_id": "price_ld", "unit_amount": 3000},
                    "Convenience Fee": {"price_id": "price_fee", "unit_amount": 300},
                },
            ),
            patch("app.stripe.Coupon.list", return_value=make_stripe_coupon_mock()),
            patch("app.stripe.checkout.Session.create", side_effect=stripe.error.StripeError("Stripe down")),
            patch("app.send_admin_alert") as mock_alert,
        ):
            response = self.client.post("/register", data=form_data)

        assert response.status_code == 502
        mock_alert.assert_called_once()
        subject = mock_alert.call_args[0][0]
        assert subject == "Stripe checkout session creation failed"

    def test_confirmation_email_failure_sends_admin_alert(self):
        """SMTP failure in _send_confirmation_email should invoke _send_admin_alert with the expected subject."""
        from api import _send_confirmation_email
        from models import Competitor
        from models import db as _db

        school_id = get_or_create_test_school("Confirm Alert School")
        with app.app_context():
            competitor = Competitor(
                full_name="Confirm Alert Competitor",
                email="confirm.alert.branch@example.com",
                school_id=school_id,
                status="complete",
                belt_rank="Black",
                events="sparring",
                poomsae_form="1",
            )
            _db.session.add(competitor)
            _db.session.commit()
            _db.session.refresh(competitor)

            smtp_mock = MagicMock()
            smtp_mock.sendmail.side_effect = smtplib.SMTPException("Send failed")
            with (
                patch("api.smtplib.SMTP_SSL") as smtp_cls_mock,
                patch.dict(
                    "os.environ",
                    {
                        "EMAIL_SERVER": "smtp.example.com",
                        "EMAIL_PORT": "465",
                        "FROM_EMAIL": "no-reply@example.com",
                        "EMAIL_PASSWD": "secret",
                        "ADMIN_EMAIL": "admin@example.com",
                    },
                ),
                patch("api._send_admin_alert") as mock_admin_alert,
            ):
                smtp_cls_mock.return_value.__enter__ = MagicMock(return_value=smtp_mock)
                smtp_cls_mock.return_value.__exit__ = MagicMock(return_value=False)
                _send_confirmation_email(competitor)

        mock_admin_alert.assert_called_once()
        subject = mock_admin_alert.call_args[0][0]
        assert "CRITICAL: Confirmation email failed" in subject

    def test_500_handler_sends_admin_alert_and_renders_page(self):
        """Unhandled 500 error handler should call send_admin_alert and return 500.html content."""
        import app as app_module
        from app import internal_server_error

        app_module._last_500_alert_time = None  # reset throttle state

        with (
            app.test_request_context("/test-path", method="GET"),
            patch("app.send_admin_alert") as mock_alert,
        ):
            response_body, status_code = internal_server_error(RuntimeError("boom"))

        assert status_code == 500
        mock_alert.assert_called_once()
        subject = mock_alert.call_args[0][0]
        assert "500 Server Error" in subject
        assert "GET" in subject
        assert "/test-path" in subject
        assert "unexpected error" in response_body.lower()

    def test_500_handler_throttles_repeated_alerts(self):
        """Within the cooldown window, only the first 500 error sends an admin alert."""
        import app as app_module
        from app import internal_server_error

        app_module._last_500_alert_time = None  # reset throttle state

        with (
            app.test_request_context("/test-path", method="GET"),
            patch("app.send_admin_alert") as mock_alert,
        ):
            internal_server_error(RuntimeError("first error"))
            internal_server_error(RuntimeError("second error within cooldown"))

        # Only the first call should have triggered an alert email
        mock_alert.assert_called_once()

    def test_500_page_renders_mailto_link_when_contact_email_set(self):
        """500.html should render a mailto link when CONTACT_EMAIL is configured."""
        import app as app_module
        from app import internal_server_error

        app_module._last_500_alert_time = None  # reset throttle state

        with (
            app.test_request_context("/test-path", method="GET"),
            patch("app.send_admin_alert"),
            patch.dict("os.environ", {"CONTACT_EMAIL": "ops@example.com"}),
        ):
            response_body, status_code = internal_server_error(RuntimeError("boom"))

        assert status_code == 500
        assert "mailto:ops@example.com" in response_body
        assert "ops@example.com" in response_body

    def test_500_page_renders_administrator_fallback_when_contact_email_missing(self):
        """500.html should show 'Administrator' instead of a mailto link when CONTACT_EMAIL is unset."""
        import app as app_module
        from app import internal_server_error

        app_module._last_500_alert_time = None  # reset throttle state

        env_without_contact = {k: v for k, v in os.environ.items() if k != "CONTACT_EMAIL"}
        with (
            app.test_request_context("/test-path", method="GET"),
            patch("app.send_admin_alert"),
            patch.dict("os.environ", env_without_contact, clear=True),
        ):
            response_body, status_code = internal_server_error(RuntimeError("boom"))

        assert status_code == 500
        assert "Administrator" in response_body
        assert "mailto:None" not in response_body


if __name__ == "__main__":
    homepage = TestHomepage()
    print(homepage.test_response_code())
