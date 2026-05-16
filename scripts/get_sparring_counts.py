#!/usr/bin/env python

try:
    from scripts._bootstrap import add_repo_root_to_path
except ModuleNotFoundError:  # Allows `python scripts/get_sparring_counts.py`
    from _bootstrap import add_repo_root_to_path

add_repo_root_to_path()

from api import get_eligible_competitors  # noqa: E402
from app import app  # noqa: E402


def get_entries():
    """Query all paid (complete) competitors from the database."""
    return get_eligible_competitors(status="complete")


def get_age_group(entry):
    age_groups = {
        "dragon": [4, 5, 6, 7],
        "tiger": [8, 9],
        "youth": [10, 11],
        "cadet": [12, 13, 14],
        "junior": [15, 16],
        "senior": list(range(17, 33)),
        "ultra": list(range(33, 100)),
    }

    try:
        age = int(entry.age or 0)
    except (TypeError, ValueError):
        # Invalid or missing age; signal no age group
        return None

    age_group = next(
        (group for group, ages in age_groups.items() if age in ages),
        None,
    )
    return age_group


def divide_age_groups(entries):
    dragon = [entry for entry in entries if get_age_group(entry) == "dragon"]
    tiger = [entry for entry in entries if get_age_group(entry) == "tiger"]
    youth = [entry for entry in entries if get_age_group(entry) == "youth"]
    cadet = [entry for entry in entries if get_age_group(entry) == "cadet"]
    junior = [entry for entry in entries if get_age_group(entry) == "junior"]
    senior = [entry for entry in entries if get_age_group(entry) == "senior"]
    ultra = [entry for entry in entries if get_age_group(entry) == "ultra"]

    return {
        "dragon": dragon,
        "tiger": tiger,
        "youth": youth,
        "cadet": cadet,
        "junior": junior,
        "senior": senior,
        "ultra": ultra,
    }


def has_event(entry, event_name: str) -> bool:
    """Check if a competitor has a specific event."""
    events = [e.strip() for e in (entry.events or "").split(",")]
    return event_name in events


def main():
    age_groups = ["dragon", "tiger", "youth", "cadet", "junior", "senior", "ultra"]

    with app.app_context():
        entries = get_entries()
        sparring = [entry for entry in entries if has_event(entry, "sparring")]
        gr_sparring = [entry for entry in entries if has_event(entry, "sparring-gr")]
        wc_sparring = [entry for entry in entries if has_event(entry, "sparring-wc")]
        sparring_groups = divide_age_groups(sparring)
        gr_sparring_groups = divide_age_groups(gr_sparring)
        wc_sparring_groups = divide_age_groups(wc_sparring)

        print(f"World Class (Total: {len(wc_sparring)})")
        for ag in age_groups:
            female = [entry for entry in wc_sparring_groups[ag] if entry.gender == "F"]
            male = [entry for entry in wc_sparring_groups[ag] if entry.gender == "M"]
            print(f"  {ag.capitalize()}")
            print(f"    Female: {len(female)}")
            print(f"      Male: {len(male)}")
            print()

        print(f"Grass Roots (Total: {len(gr_sparring)})")
        for ag in age_groups:
            female = [entry for entry in gr_sparring_groups[ag] if entry.gender == "F"]
            male = [entry for entry in gr_sparring_groups[ag] if entry.gender == "M"]
            print(f"  {ag.capitalize()}")
            print(f"    Female: {len(female)}")
            print(f"      Male: {len(male)}")
            print()

        print(f"Color Belts (Total: {len(sparring)})")
        for ag in age_groups:
            female = [entry for entry in sparring_groups[ag] if entry.gender == "F"]
            male = [entry for entry in sparring_groups[ag] if entry.gender == "M"]
            print(f"  {ag.capitalize()}")
            print(f"    Female: {len(female)}")
            print(f"      Male: {len(male)}")
            print()

        print(f"Color Belts + Grass Roots (Total: {len(sparring) + len(gr_sparring)})")
        for ag in age_groups:
            female = [entry for entry in sparring_groups[ag] if entry.gender == "F"] + [
                entry for entry in gr_sparring_groups[ag] if entry.gender == "F"
            ]
            male = [entry for entry in sparring_groups[ag] if entry.gender == "M"] + [
                entry for entry in gr_sparring_groups[ag] if entry.gender == "M"
            ]
            print(f"  {ag.capitalize()}")
            print(f"    Female: {len(female)}")
            print(f"      Male: {len(male)}")
            print()


if __name__ == "__main__":
    main()
