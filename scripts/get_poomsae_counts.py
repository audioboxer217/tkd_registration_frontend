#!/usr/bin/env python

try:
    from scripts._bootstrap import add_repo_root_to_path
except ModuleNotFoundError:  # Allows `python scripts/get_poomsae_counts.py`
    from _bootstrap import add_repo_root_to_path

add_repo_root_to_path()

from app import app  # noqa: E402
from models import Competitor  # noqa: E402


def get_entries():
    """Query all competitors from the database."""
    return Competitor.query.all()


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

    # Safely parse the age field; if it's missing or invalid, skip this entry.
    try:
        age_value = int(entry.age or 0)
    except (TypeError, ValueError):
        print(f"Skipping entry with invalid or missing age: {entry.full_name}")
        return None

    # Use a default with next() so that out-of-range ages don't raise StopIteration.
    age_group = next(
        (group for group, ages in age_groups.items() if age_value in ages),
        None,
    )

    if age_group is None:
        print(f"Skipping entry with out-of-range age {age_value}: {entry.full_name}")
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
        poomsae = [entry for entry in entries if has_event(entry, "poomsae")]
        world_class_poomsae = [entry for entry in entries if has_event(entry, "world-class poomsae")]
        pair_poomsae = [entry for entry in entries if has_event(entry, "pair poomsae")]
        team_poomsae = [entry for entry in entries if has_event(entry, "team poomsae")]
        poomsae_groups = divide_age_groups(poomsae)
        world_class_poomsae_groups = divide_age_groups(world_class_poomsae)
        pair_poomsae_groups = divide_age_groups(pair_poomsae)
        team_poomsae_groups = divide_age_groups(team_poomsae)

        print(f"World Class (Total: {len(world_class_poomsae)})")
        for ag in age_groups:
            female = [entry for entry in world_class_poomsae_groups[ag] if entry.gender == "F"]
            male = [entry for entry in world_class_poomsae_groups[ag] if entry.gender == "M"]
            print(f"  {ag.capitalize()}")
            print(f"    Female: {len(female)}")
            print(f"      Male: {len(male)}")
            print()

        print(f"Individual Poomsae (Total: {len(poomsae)})")
        for ag in age_groups:
            female = [entry for entry in poomsae_groups[ag] if entry.gender == "F"]
            male = [entry for entry in poomsae_groups[ag] if entry.gender == "M"]
            print(f"  {ag.capitalize()}")
            print(f"    Female: {len(female)}")
            print(f"      Male: {len(male)}")
            print()

        print(f"Pair Poomsae (Total: {len(pair_poomsae)})")
        for ag in age_groups:
            female = [entry for entry in pair_poomsae_groups[ag] if entry.gender == "F"]
            male = [entry for entry in pair_poomsae_groups[ag] if entry.gender == "M"]
            print(f"  {ag.capitalize()}")
            print(f"    Female: {len(female)}")
            print(f"      Male: {len(male)}")
            print()

        print(f"Team Poomsae (Total: {len(team_poomsae)})")
        for ag in age_groups:
            female = [entry for entry in team_poomsae_groups[ag] if entry.gender == "F"]
            male = [entry for entry in team_poomsae_groups[ag] if entry.gender == "M"]
            print(f"  {ag.capitalize()}")
            print(f"    Female: {len(female)}")
            print(f"      Male: {len(male)}")
            print()


if __name__ == "__main__":
    main()
