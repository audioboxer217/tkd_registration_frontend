"""Seed the database with sample registrations for testing."""

try:
    from scripts._bootstrap import add_repo_root_to_path, confirm_db_url
except ModuleNotFoundError:  # Allows `python scripts/seed_db.py`
    from _bootstrap import add_repo_root_to_path, confirm_db_url

add_repo_root_to_path()

import uuid

from app import app
from models import Coach, Competitor, School, db

COMPETITORS = [
    # (full_name, email, age, birthdate, gender, weight_lbs, height_in, belt_rank, events, school, coach, poomsae_form)
    (
        "Liam Nguyen",
        "liam.nguyen@example.com",
        8,
        "03/15/2017",
        "M",
        55.0,
        48,
        "white",
        "little_dragon,poomsae",
        "Tiger Taekwondo",
        "Master Park",
        "Taegeuk 1 Jang",
    ),
    (
        "Sophia Patel",
        "sophia.patel@example.com",
        10,
        "07/22/2015",
        "F",
        65.0,
        54,
        "yellow",
        "poomsae,sparring",
        "Eagle TKD Academy",
        "Master Kim",
        "Taegeuk 2 Jang",
    ),
    (
        "Ethan Brooks",
        "ethan.brooks@example.com",
        13,
        "11/04/2012",
        "M",
        110.0,
        62,
        "green",
        "sparring,poomsae,pair poomsae",
        "Summit TKD",
        "Coach Lee",
        "Taegeuk 4 Jang",
    ),
    (
        "Ava Martinez",
        "ava.martinez@example.com",
        15,
        "05/30/2010",
        "F",
        125.0,
        65,
        "blue",
        "poomsae,sparring",
        "Blue Dragon Academy",
        "Master Chen",
        "Taegeuk 5 Jang",
    ),
    (
        "Noah Johnson",
        "noah.johnson@example.com",
        17,
        "09/12/2008",
        "M",
        155.0,
        70,
        "red",
        "sparring,poomsae,freestyle poomsae",
        "Summit TKD",
        "Coach Lee",
        "Taegeuk 7 Jang",
    ),
    (
        "Isabella Kim",
        "isabella.kim@example.com",
        20,
        "02/28/2005",
        "F",
        130.0,
        64,
        "black 1",
        "poomsae,sparring-gr,pair poomsae",
        "Elite TKD Center",
        "Master Park",
        "Koryo",
    ),
    (
        "Mason Thompson",
        "mason.thompson@example.com",
        25,
        "08/14/2000",
        "M",
        175.0,
        72,
        "black 2",
        "sparring-gr,poomsae,team poomsae",
        "Champions TKD",
        "Master Yoon",
        "Geumgang",
    ),
    (
        "Emma Wilson",
        "emma.wilson@example.com",
        35,
        "01/05/1990",
        "F",
        145.0,
        66,
        "black 3",
        "poomsae,world-class poomsae",
        "Elite TKD Center",
        "Master Park",
        "Taeback",
    ),
    (
        "Oliver Davis",
        "oliver.davis@example.com",
        45,
        "06/20/1980",
        "M",
        195.0,
        74,
        "black 4",
        "sparring-gr,poomsae,family poomsae",
        "Champions TKD",
        "Master Yoon",
        "Sipjin",
    ),
    (
        "Grace Lee",
        "grace.lee@example.com",
        12,
        "12/01/2013",
        "F",
        90.0,
        58,
        "orange",
        "little_dragon,poomsae,sparring",
        "Tiger Taekwondo",
        "Master Park",
        "Taegeuk 3 Jang",
    ),
]

COACHES = [
    ("Master Jin Park", "jin.park@example.com", "Tiger Taekwondo"),
    ("Coach Sarah Yoon", "sarah.yoon@example.com", "Summit TKD"),
]


def make_checkout_session_id():
    return "cs_test_" + uuid.uuid4().hex[:24]


def _get_or_create_school(session, name):
    """Get or create a School by name, returning the School object."""
    school = session.query(School).filter_by(name=name).first()
    if not school:
        school = School(name=name)
        session.add(school)
        session.flush()  # Get the ID without committing
    return school


def seed():
    with app.app_context():
        confirm_db_url(app.config["SQLALCHEMY_DATABASE_URI"])
        db.create_all()

        existing = db.session.query(Competitor).count() + db.session.query(Coach).count()
        if existing > 0:
            print(f"Database already has {existing} registration(s). Skipping seed.")
            print("Run scripts/reset_db.py first if you want a fresh seed.")
            return

        # Create coaches first (so competitors can reference them)
        coach_map = {}  # school_name -> {coach_display_name: Coach object}
        for full_name, email, school_name in COACHES:
            school = _get_or_create_school(db.session, school_name)
            coach = Coach(
                full_name=full_name,
                email=email,
                phone="555-020-0001",
                school_id=school.id,
            )
            db.session.add(coach)
            db.session.flush()
            coach_map.setdefault(school_name, {})[full_name] = coach

        for (
            full_name,
            email,
            age,
            birthdate,
            gender,
            weight,
            height,
            belt_rank,
            events,
            school_name,
            coach_name,
            poomsae_form,
        ) in COMPETITORS:
            school = _get_or_create_school(db.session, school_name)
            # Try to find a matching coach in the same school
            coach_obj = coach_map.get(school_name, {}).get(coach_name)
            competitor = Competitor(
                full_name=full_name,
                email=email,
                phone="555-010-0001",
                school_id=school.id,
                coach_id=coach_obj.id if coach_obj else None,
                age=age,
                birthdate=birthdate,
                gender=gender,
                weight=weight,
                height=height,
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
            db.session.add(competitor)

        db.session.commit()
        competitor_count = db.session.query(Competitor).count()
        coach_count = db.session.query(Coach).count()
        print(f"Seeded {competitor_count + coach_count} registrations ({competitor_count} competitors, {coach_count} coaches).")


if __name__ == "__main__":
    seed()
