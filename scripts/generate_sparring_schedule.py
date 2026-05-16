#!/usr/bin/env python

import argparse
import csv
import json
import math
import os
from dataclasses import dataclass, field

try:
    from scripts._bootstrap import add_repo_root_to_path
except ModuleNotFoundError:  # Allows `python scripts/generate_sparring_schedule.py`
    from _bootstrap import add_repo_root_to_path

add_repo_root_to_path()

from api import get_eligible_competitors  # noqa: E402
from app import app  # noqa: E402

AGE_GROUP_ORDER = ["dragon", "tiger", "youth", "cadet", "junior", "senior", "ultra"]
AGE_GROUPS = {
    "dragon": [4, 5, 6, 7],
    "tiger": [8, 9],
    "youth": [10, 11],
    "cadet": [12, 13, 14],
    "junior": [15, 16],
    "senior": list(range(17, 33)),
    "ultra": list(range(33, 100)),
}


@dataclass
class SparringCompetitor:
    name: str
    school: str
    gender: str
    age: int
    weight: float
    division: str
    age_group: str
    original_age_group: str
    raw: object


@dataclass
class Group:
    division: str
    gender: str
    age_group: str
    members: list[SparringCompetitor] = field(default_factory=list)


def get_entries():
    """Query all paid (complete) competitors from the database."""
    return get_eligible_competitors(status="complete")


def get_age_group(age: int) -> str:
    return next((group for group, ages in AGE_GROUPS.items() if age in ages), "ultra")


def age_group_move_direction(original: str, current: str) -> str:
    orig_idx = AGE_GROUP_ORDER.index(original)
    curr_idx = AGE_GROUP_ORDER.index(current)
    if curr_idx > orig_idx:
        return "up"
    if curr_idx < orig_idx:
        return "down"
    return ""


def normalize_gender(gender: str) -> str:
    gender = (gender or "").strip().lower()
    if gender.startswith("m"):
        return "male"
    if gender.startswith("f"):
        return "female"
    return "unknown"


def parse_divisions(events: str) -> list[str]:
    event_list = [event.strip() for event in events.split(",") if event.strip()]
    divisions = []
    if "sparring-wc" in event_list:
        divisions.append("world_class")
    if "sparring" in event_list:
        divisions.append("color_belt")
    if "sparring-gr" in event_list:
        divisions.append("grass_roots")
    return divisions


def parse_competitors(entries: list) -> list[SparringCompetitor]:
    competitors = []
    for entry in entries:
        divisions = parse_divisions(entry.events or "")
        if not divisions:
            continue

        age = int(entry.age or 0)
        weight = float(entry.weight or 0)
        gender = normalize_gender(entry.gender or "")
        school = entry.school.name if entry.school else "Unknown School"
        name = entry.full_name or "Unknown Competitor"
        age_group = get_age_group(age)

        for division in divisions:
            competitors.append(
                SparringCompetitor(
                    name=name,
                    school=school,
                    gender=gender,
                    age=age,
                    weight=weight,
                    division=division,
                    age_group=age_group,
                    original_age_group=age_group,
                    raw=entry,
                )
            )

    return competitors


def build_age_buckets(competitors: list[SparringCompetitor]) -> dict[str, list[SparringCompetitor]]:
    buckets = {age_group: [] for age_group in AGE_GROUP_ORDER}
    for competitor in competitors:
        buckets[competitor.age_group].append(competitor)
    return buckets


def can_form_valid_groups(count: int) -> bool:
    if count == 0:
        return True
    size_plan = group_size_plan(count)
    return bool(size_plan) and min(size_plan) >= 2


def choose_singleton_target(
    buckets: dict[str, list[SparringCompetitor]],
    source_index: int,
) -> str | None:
    source_age_group = AGE_GROUP_ORDER[source_index]
    source_count = len(buckets[source_age_group])
    if source_count != 1:
        return None

    candidate_indices = []
    if source_index - 1 >= 0:
        candidate_indices.append(source_index - 1)
    if source_index + 1 < len(AGE_GROUP_ORDER):
        candidate_indices.append(source_index + 1)

    candidates = []
    for candidate_index in candidate_indices:
        candidate_age_group = AGE_GROUP_ORDER[candidate_index]
        candidate_count = len(buckets[candidate_age_group])

        # Moving into an empty bracket creates a new singleton and doesn't help.
        if candidate_count == 0:
            continue

        before_invalid = int(not can_form_valid_groups(source_count)) + int(not can_form_valid_groups(candidate_count))
        after_invalid = int(not can_form_valid_groups(0)) + int(not can_form_valid_groups(candidate_count + 1))

        # Only move if this improves local grouping viability.
        if after_invalid >= before_invalid:
            continue

        candidates.append(
            (
                abs((candidate_count + 1) - 3),
                0 if candidate_index > source_index else 1,
                candidate_age_group,
            )
        )

    if not candidates:
        return None

    _, _, target_age_group = min(candidates)
    return target_age_group


def rebalance_singletons_adjacent(buckets: dict[str, list[SparringCompetitor]]) -> dict[str, list[SparringCompetitor]]:
    # Re-check repeatedly because moving one competitor can enable another valid move.
    changed = True
    while changed:
        changed = False
        for index, age_group in enumerate(AGE_GROUP_ORDER):
            if len(buckets[age_group]) != 1:
                continue

            target_age_group = choose_singleton_target(buckets, index)
            if not target_age_group:
                continue

            competitor = buckets[age_group].pop()
            competitor.age_group = target_age_group
            buckets[target_age_group].append(competitor)
            changed = True

    return buckets


def group_size_plan(count: int) -> list[int]:
    if count <= 0:
        return []
    if count <= 4:
        return [count]

    groups = math.ceil(count / 4)
    sizes = [count // groups] * groups

    for index in range(count % groups):
        sizes[index] += 1

    return sizes


def split_by_weight_and_school(entries: list[SparringCompetitor]) -> list[list[SparringCompetitor]]:
    entries = sorted(entries, key=lambda competitor: competitor.weight)
    size_plan = group_size_plan(len(entries))

    if not size_plan:
        return []

    # Assign competitors to contiguous weight-based groups so similar weights stay together.
    groups: list[list[SparringCompetitor]] = []
    offset = 0
    for size in size_plan:
        groups.append(list(entries[offset : offset + size]))
        offset += size

    # Secondary pass: swap members between adjacent groups to reduce same-school conflicts
    # without significantly disrupting the weight-based groupings.
    def school_conflicts(group: list[SparringCompetitor]) -> int:
        school_counts: dict[str, int] = {}
        for member in group:
            school_counts[member.school] = school_counts.get(member.school, 0) + 1
        return sum(count - 1 for count in school_counts.values() if count > 1)

    changed = True
    while changed:
        changed = False
        for i in range(len(groups) - 1):
            improved = True
            while improved:
                improved = False
                for a_idx, a_comp in enumerate(groups[i]):
                    for b_idx, b_comp in enumerate(groups[i + 1]):
                        before = school_conflicts(groups[i]) + school_conflicts(groups[i + 1])
                        new_a = groups[i][:a_idx] + [b_comp] + groups[i][a_idx + 1 :]
                        new_b = groups[i + 1][:b_idx] + [a_comp] + groups[i + 1][b_idx + 1 :]
                        after = school_conflicts(new_a) + school_conflicts(new_b)
                        if after < before:
                            groups[i] = new_a
                            groups[i + 1] = new_b
                            improved = True
                            changed = True
                            break
                    if improved:
                        break

    return groups


def should_combine_color_and_grass(color_entries: list[SparringCompetitor], grass_entries: list[SparringCompetitor]) -> bool:
    # Only use the combined division label when both divisions have competitors
    # and at least one side is too small to stand alone.
    if not color_entries or not grass_entries:
        return False
    if len(color_entries) < 2 or len(grass_entries) < 2:
        return True
    return False


def generate_division_gender_age_groups(
    division_name: str,
    gender: str,
    buckets: dict[str, list[SparringCompetitor]],
) -> list[Group]:
    groups = []
    for age_group in AGE_GROUP_ORDER:
        entries = buckets[age_group]
        if not entries:
            continue

        split_groups = split_by_weight_and_school(entries)
        for members in split_groups:
            groups.append(
                Group(
                    division=division_name,
                    gender=gender,
                    age_group=age_group,
                    members=members,
                )
            )
    return groups


def generate_groups(competitors: list[SparringCompetitor]) -> list[Group]:
    groups = []

    for gender in ["female", "male", "unknown"]:
        world_entries = [
            competitor for competitor in competitors if competitor.division == "world_class" and competitor.gender == gender
        ]
        world_buckets = rebalance_singletons_adjacent(build_age_buckets(world_entries))
        groups.extend(generate_division_gender_age_groups("world_class", gender, world_buckets))

        color_entries = [
            competitor for competitor in competitors if competitor.division == "color_belt" and competitor.gender == gender
        ]
        grass_entries = [
            competitor for competitor in competitors if competitor.division == "grass_roots" and competitor.gender == gender
        ]

        color_buckets = rebalance_singletons_adjacent(build_age_buckets(color_entries))
        grass_buckets = rebalance_singletons_adjacent(build_age_buckets(grass_entries))

        for age_group in AGE_GROUP_ORDER:
            age_color = color_buckets[age_group]
            age_grass = grass_buckets[age_group]

            if should_combine_color_and_grass(age_color, age_grass):
                combined = age_color + age_grass
                split_groups = split_by_weight_and_school(combined)
                for members in split_groups:
                    groups.append(
                        Group(
                            division="color_belt+grass_roots",
                            gender=gender,
                            age_group=age_group,
                            members=members,
                        )
                    )
            else:
                for members in split_by_weight_and_school(age_color):
                    groups.append(
                        Group(
                            division="color_belt",
                            gender=gender,
                            age_group=age_group,
                            members=members,
                        )
                    )
                for members in split_by_weight_and_school(age_grass):
                    groups.append(
                        Group(
                            division="grass_roots",
                            gender=gender,
                            age_group=age_group,
                            members=members,
                        )
                    )

    return groups


def print_groups(groups: list[Group]) -> None:
    order = {
        "world_class": 0,
        "color_belt": 1,
        "grass_roots": 2,
        "color_belt+grass_roots": 3,
    }

    gender_order = {"female": 0, "male": 1, "unknown": 2}

    groups = sorted(
        groups,
        key=lambda group: (
            order.get(group.division, 99),
            gender_order.get(group.gender, 99),
            AGE_GROUP_ORDER.index(group.age_group),
            len(group.members),
        ),
    )

    if not groups:
        print("No sparring competitors found.")
        return

    print("Sparring Groups (target size: 2-4 competitors)")
    print("=" * 80)

    for index, group in enumerate(groups, start=1):
        print(
            f"Group {index:02d} | division={group.division} | gender={group.gender} | "
            f"age={group.age_group} | size={len(group.members)}"
        )

        for member in sorted(group.members, key=lambda competitor: competitor.weight):
            moved_tag = ""
            if member.original_age_group != member.age_group:
                moved_tag = f" (moved from {member.original_age_group})"
            print(f"  - {member.name} | {member.school} | age={member.age} | weight={member.weight:.1f}{moved_tag}")

        if len(group.members) < 2:
            print("  ! Needs manual merge (single competitor group)")

        schools = [member.school for member in group.members]
        duplicates = {school for school in schools if schools.count(school) > 1}
        if duplicates:
            print(f"  ! Same-school matchup present: {', '.join(sorted(duplicates))}")

        print()


def groups_to_rows(groups: list[Group]) -> list[dict]:
    rows = []
    for group_index, group in enumerate(groups, start=1):
        for competitor in sorted(group.members, key=lambda member: member.weight):
            rows.append(
                {
                    "group_number": group_index,
                    "division": group.division,
                    "gender": group.gender,
                    "age_group": group.age_group,
                    "group_size": len(group.members),
                    "competitor_name": competitor.name,
                    "school": competitor.school,
                    "age": competitor.age,
                    "weight": competitor.weight,
                    "original_age_group": competitor.original_age_group,
                    "age_group_move_direction": age_group_move_direction(competitor.original_age_group, competitor.age_group),
                }
            )
    return rows


def write_csv(groups: list[Group], output_path: str) -> None:
    rows = groups_to_rows(groups)
    fieldnames = [
        "group_number",
        "division",
        "gender",
        "age_group",
        "group_size",
        "competitor_name",
        "school",
        "age",
        "weight",
        "original_age_group",
        "age_group_move_direction",
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(groups: list[Group], output_path: str) -> None:
    rows = groups_to_rows(groups)
    with open(output_path, "w", encoding="utf-8") as file_handle:
        json.dump(rows, file_handle, indent=2)


def export_groups(groups: list[Group], output_format: str, output_dir: str = "output") -> list[str]:
    os.makedirs(output_dir, exist_ok=True)
    written_files = []

    if output_format in {"csv", "both"}:
        csv_path = os.path.join(output_dir, "sparring_groups.csv")
        write_csv(groups, csv_path)
        written_files.append(csv_path)

    if output_format in {"json", "both"}:
        json_path = os.path.join(output_dir, "sparring_groups.json")
        write_json(groups, json_path)
        written_files.append(json_path)

    return written_files


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate 2-4 person sparring groups.")
    parser.add_argument(
        "--output-format",
        choices=["csv", "json", "both"],
        default="csv",
        help="Output format for saved group data. Defaults to csv.",
    )
    parser.add_argument(
        "--output-dir",
        default="output/schedules",
        help="Directory for generated schedule files. Defaults to output/schedules/.",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    with app.app_context():
        entries = get_entries()
        competitors = parse_competitors(entries)
        groups = generate_groups(competitors)
        print_groups(groups)
        written_files = export_groups(groups, args.output_format, args.output_dir)

    print("Saved group data to:")
    for file_path in written_files:
        print(f"  - {file_path}")


if __name__ == "__main__":
    main()
