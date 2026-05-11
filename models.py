from datetime import datetime

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Numeric, String, Text
from sqlalchemy.types import JSON

db = SQLAlchemy()


class School(db.Model):
    """Reference table for schools/clubs."""
    __tablename__ = "schools"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(String(200), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    coaches = db.relationship("Coach", back_populates="school", cascade="all, delete-orphan")
    competitors = db.relationship("Competitor", back_populates="school", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Coach(db.Model):
    """Coach registration."""
    __tablename__ = "coaches"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    full_name = db.Column(String(200), nullable=False)
    email = db.Column(String(200), nullable=False, index=True)
    phone = db.Column(String(20))
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False)
    img_filename = db.Column(String(200))
    # Coaches do not go through a Stripe checkout flow; payment fields are on Competitor only.
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    school = db.relationship("School", back_populates="coaches")
    competitors = db.relationship("Competitor", back_populates="coach_rel")

    def to_dict(self):
        return {
            "id": self.id,
            "full_name": self.full_name,
            "email": self.email,
            "phone": self.phone,
            "school_id": self.school_id,
            "school": self.school.name if self.school else None,
            "reg_type": "coach",
            "img_filename": self.img_filename,
            # Competitor form-specific fields (empty for coaches)
            "parent": None,
            "birthdate": None,
            "age": None,
            "gender": None,
            "weight": None,
            "height": None,
            "belt_rank": None,
            "events": [],
            "poomsae_form": None,
            "wc_poomsae_form": None,
            "pair_poomsae_form": None,
            "team_poomsae_form": None,
            "family_poomsae_form": None,
            "medical_contacts": None,
            "medical_conditions": [],
            "allergies": [],
            "medications": [],
            "tshirt": None,
            "coach_id": None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Competitor(db.Model):
    """Competitor registration."""
    __tablename__ = "competitors"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    # Core fields
    full_name = db.Column(String(200), nullable=False)
    email = db.Column(String(200), nullable=False, index=True)
    phone = db.Column(String(20))
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False)
    coach_id = db.Column(db.Integer, db.ForeignKey("coaches.id"), nullable=True)

    # Competitor-specific fields
    parent = db.Column(String(200))
    birthdate = db.Column(String(10))  # stored as MM/DD/YYYY string to match form data
    age = db.Column(db.Integer)
    gender = db.Column(String(1))
    weight = db.Column(Numeric(6, 1))
    height = db.Column(db.Integer)  # total inches
    belt_rank = db.Column(String(50))

    # Events (comma-separated list matching existing format)
    events = db.Column(Text)

    # Poomsae form selections
    poomsae_form = db.Column(String(100))
    wc_poomsae_form = db.Column(String(100))
    pair_poomsae_form = db.Column(String(100))
    team_poomsae_form = db.Column(String(100))
    family_poomsae_form = db.Column(String(100))

    # Medical info (stored as JSON arrays)
    medical_contacts = db.Column(Text)
    medical_conditions = db.Column(JSON)
    allergies = db.Column(JSON)
    medications = db.Column(JSON)

    # Optional feature fields
    img_filename = db.Column(String(200))  # ENABLE_BADGES
    tshirt = db.Column(String(20))  # little dragon t-shirt size

    # Payment
    status = db.Column(String(20), nullable=False, default="pending")
    checkout_session_id = db.Column(String(100), index=True)  # Stripe Checkout Session ID
    payment_intent = db.Column(String(100))

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    school = db.relationship("School", back_populates="competitors")
    coach_rel = db.relationship("Coach", back_populates="competitors")

    def to_dict(self):
        """Return a JSON-serializable dict representation."""
        return {
            "id": self.id,
            "full_name": self.full_name,
            "email": self.email,
            "phone": self.phone,
            "school": self.school.name if self.school else None,
            "school_id": self.school_id,
            "coach": self.coach_rel.full_name if self.coach_rel else None,
            "coach_id": self.coach_id,
            "parent": self.parent,
            "birthdate": self.birthdate,
            "age": self.age,
            "gender": self.gender,
            "weight": float(self.weight) if self.weight is not None else None,
            "height": self.height,
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
            "payment_intent": self.payment_intent,
            "status": self.status,
            "reg_type": "competitor",
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }



class Registration(db.Model):
    """
    Legacy registration model - kept for historical reference and backward compatibility.
    NEW RECORDS should use Competitor or Coach models instead.
    This table remains as an archive of all registrations.
    """
    __tablename__ = "registrations"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    # Core fields (competitor and coach)
    full_name = db.Column(String(200), nullable=False)
    email = db.Column(String(200), nullable=False, index=True)
    phone = db.Column(String(20))
    school = db.Column(String(200))
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"))
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
