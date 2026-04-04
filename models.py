from datetime import datetime

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Numeric, String, Text
from sqlalchemy.types import JSON

db = SQLAlchemy()


class Registration(db.Model):
    __tablename__ = "registrations"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    # Core fields (competitor and coach)
    full_name = db.Column(String(200), nullable=False)
    email = db.Column(String(200), nullable=False, index=True)
    phone = db.Column(String(20))
    school = db.Column(String(200))
    reg_type = db.Column(String(20), nullable=False)  # 'competitor' or 'coach'

    # Competitor-only fields
    parent = db.Column(String(200))
    birthdate = db.Column(String(10))  # stored as MM/DD/YYYY string to match form data
    age = db.Column(db.Integer)
    gender = db.Column(String(1))
    weight = db.Column(Numeric(6, 1))
    height = db.Column(db.Integer)  # total inches
    coach = db.Column(String(200))
    belt_rank = db.Column(String(50))

    # Events (comma-separated list matching existing format)
    events = db.Column(Text)

    # Poomsae form selections
    poomsae_form = db.Column(String(100))
    wc_poomsae_form = db.Column(String(100))
    pair_poomsae_form = db.Column(String(100))
    team_poomsae_form = db.Column(String(100))
    family_poomsae_form = db.Column(String(100))

    # Medical info (stored as JSON arrays, compatible with SQLite and PostgreSQL)
    medical_contacts = db.Column(Text)
    medical_conditions = db.Column(JSON)
    allergies = db.Column(JSON)
    medications = db.Column(JSON)

    # Optional feature fields
    img_filename = db.Column(String(200))  # ENABLE_BADGES
    tshirt = db.Column(String(20))  # little dragon t-shirt size

    # Payment
    checkout_session_id = db.Column(String(100), index=True)  # Stripe Checkout Session ID

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self):
        """Return a JSON-serializable dict representation."""
        return {
            "id": self.id,
            "full_name": self.full_name,
            "email": self.email,
            "phone": self.phone,
            "school": self.school,
            "reg_type": self.reg_type,
            "parent": self.parent,
            "birthdate": self.birthdate,
            "age": self.age,
            "gender": self.gender,
            "weight": float(self.weight) if self.weight is not None else None,
            "height": self.height,
            "coach": self.coach,
            "belt_rank": self.belt_rank,
            "events": self.events.split(",") if self.events else [],
            "poomsae_form": self.poomsae_form,
            "wc_poomsae_form": self.wc_poomsae_form,
            "pair_poomsae_form": self.pair_poomsae_form,
            "team_poomsae_form": self.team_poomsae_form,
            "family_poomsae_form": self.family_poomsae_form,
            "medical_contacts": self.medical_contacts,
            "medical_conditions": self.medical_conditions or [],
            "allergies": self.allergies or [],
            "medications": self.medications or [],
            "img_filename": self.img_filename,
            "tshirt": self.tshirt,
            "checkout_session_id": self.checkout_session_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


def init_db(app):
    """Bind SQLAlchemy to the Flask app."""
    db.init_app(app)
