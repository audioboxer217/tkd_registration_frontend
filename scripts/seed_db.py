"""Seed the database with sample registrations for testing."""

try:
    from scripts._bootstrap import add_repo_root_to_path, confirm_db_url
except ModuleNotFoundError:  # Allows `python scripts/seed_db.py`
    from _bootstrap import add_repo_root_to_path, confirm_db_url

add_repo_root_to_path()

import os
import uuid
from pathlib import Path

from app import app
from models import Registration, db

COMPETITORS = [
    # (full_name, email, age, birthdate, gender, weight_lbs, height_in, belt_rank, events, school, coach, poomsae_form)
    (
        "Liam Nguyen", "liam.nguyen@example.com", 8, "03/15/2017", "M", 55.0, 48,
        "white", "little_dragon,poomsae",
        "Tiger Taekwondo", "Master Park", "Taegeuk 1 Jang",
    ),
    (
        "Sophia Patel", "sophia.patel@example.com", 10, "07/22/2015", "F", 65.0, 54,
        "yellow", "poomsae,sparring",
        "Eagle TKD Academy", "Master Kim", "Taegeuk 2 Jang",
    ),
    (
        "Ethan Brooks", "ethan.brooks@example.com", 13, "11/04/2012", "M", 110.0, 62,
        "green", "sparring,poomsae,pair poomsae",
        "Summit TKD", "Coach Lee", "Taegeuk 4 Jang",
    ),
    (
        "Ava Martinez", "ava.martinez@example.com", 15, "05/30/2010", "F", 125.0, 65,
        "blue", "poomsae,sparring",
        "Blue Dragon Academy", "Master Chen", "Taegeuk 5 Jang",
    ),
    (
        "Noah Johnson", "noah.johnson@example.com", 17, "09/12/2008", "M", 155.0, 70,
        "red", "sparring,poomsae,freestyle poomsae",
        "Summit TKD", "Coach Lee", "Taegeuk 7 Jang",
    ),
    (
        "Isabella Kim", "isabella.kim@example.com", 20, "02/28/2005", "F", 130.0, 64,
        "black 1", "poomsae,sparring-gr,pair poomsae",
        "Elite TKD Center", "Master Park", "Koryo",
    ),
    (
        "Mason Thompson", "mason.thompson@example.com", 25, "08/14/2000", "M", 175.0, 72,
        "black 2", "sparring-gr,poomsae,team poomsae",
        "Champions TKD", "Master Yoon", "Geumgang",
    ),
    (
        "Emma Wilson", "emma.wilson@example.com", 35, "01/05/1990", "F", 145.0, 66,
        "black 3", "poomsae,world-class poomsae",
        "Elite TKD Center", "Master Park", "Taeback",
    ),
    (
        "Oliver Davis", "oliver.davis@example.com", 45, "06/20/1980", "M", 195.0, 74,
        "black 4", "sparring-gr,poomsae,family poomsae",
        "Champions TKD", "Master Yoon", "Sipjin",
    ),
    (
        "Grace Lee", "grace.lee@example.com", 12, "12/01/2013", "F", 90.0, 58,
        "orange", "little_dragon,poomsae,sparring",
        "Tiger Taekwondo", "Master Park", "Taegeuk 3 Jang",
    ),
]

COACHES = [
    ("Master Jin Park", "jin.park@example.com", "Tiger Taekwondo"),
    ("Coach Sarah Yoon", "sarah.yoon@example.com", "Summit TKD"),
]


def make_checkout_session_id():
    return "cs_test_" + uuid.uuid4().hex[:24]


def seed():
    with app.app_context():
        confirm_db_url(app.config["SQLALCHEMY_DATABASE_URI"])
        db.create_all()

        existing = db.session.query(Registration).count()
        if existing > 0:
            print(f"Database already has {existing} registration(s). Skipping seed.")
            print("Run scripts/reset_db.py first if you want a fresh seed.")
            return

        for full_name, email, age, birthdate, gender, weight, height, belt_rank, events, school, coach, poomsae_form in COMPETITORS:
            reg = Registration(
                full_name=full_name,
                email=email,
                phone="555-010-0001",
                school=school,
                reg_type="competitor",
                age=age,
                birthdate=birthdate,
                gender=gender,
                weight=weight,
                height=height,
                coach=coach,
                belt_rank=belt_rank,
                events=events,
                poomsae_form=poomsae_form if "poomsae" in events else None,
                pair_poomsae_form="Taegeuk 1 Jang" if "pair poomsae" in events else None,
                team_poomsae_form="Taegeuk 1 Jang" if "team poomsae" in events else None,
                family_poomsae_form="Taegeuk 1 Jang" if "family poomsae" in events else None,
                wc_poomsae_form="Koryo" if "world-class poomsae" in events else None,
                medical_conditions=[],
                allergies=[],
                medications=[],
                checkout_session_id=make_checkout_session_id(),
            )
            db.session.add(reg)

        for full_name, email, school in COACHES:
            reg = Registration(
                full_name=full_name,
                email=email,
                phone="555-020-0001",
                school=school,
                reg_type="coach",
                checkout_session_id=make_checkout_session_id(),
            )
            db.session.add(reg)

        db.session.commit()
        total = db.session.query(Registration).count()
        print(f"Seeded {total} registrations ({len(COMPETITORS)} competitors, {len(COACHES)} coaches).")


if __name__ == "__main__":
    seed()
