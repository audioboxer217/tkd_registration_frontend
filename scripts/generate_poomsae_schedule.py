#!/usr/bin/env python

import argparse
import csv
import json
import math
import os
from dataclasses import dataclass, field

try:
    from scripts._bootstrap import add_repo_root_to_path
except ModuleNotFoundError:  # Allows `python scripts/generate_poomsae_schedule.py`
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

BELT_ORDER = ["white", "yellow", "orange", "green", "blue", "red", "brown", "black"]
BELT_ORDER_INDEX = {belt: index for index, belt in enumerate(BELT_ORDER)}


@dataclass
class PoomsaeCompetitor:
    name: str
    school: str
    gender: str
    age: int
    belt: str
    belt_rank: int
    division: str
    age_group: str
    original_age_group: str


@dataclass
class Group:
    division: str
    gender: str
    age_group: str
    members: list[PoomsaeCompetitor] = field(default_factory=list)


def get_entries() -> list:
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
    cleaned = (gender or "").strip().lower()
    if cleaned.startswith("m"):
        return "male"
    if cleaned.startswith("f"):
        return "female"
    return "unknown"


def normalize_belt(belt: str) -> str:
    cleaned = (belt or "").strip().lower()
    for expected in BELT_ORDER:
        if expected in cleaned:
            return expected
    return cleaned or "unknown"


def belt_label(competitor: PoomsaeCompetitor) -> str:
    if competitor.belt in BELT_ORDER_INDEX:
        # Human-friendly 1-based level aligns with event rules.
        return f"{competitor.belt} (level {competitor.belt_rank + 1})"
    return competitor.belt


def parse_divisions(events: str) -> list[str]:
    event_list = [event.strip().lower() for event in (events or "").split(",") if event.strip()]
    divisions = []

    if "poomsae" in event_list:
        divisions.append("individual")
    if "world-class poomsae" in event_list:
        divisions.append("world_class")
    if "pair poomsae" in event_list:
        divisions.append("pair")
    if "team poomsae" in event_list:
        divisions.append("team")
    if "family poomsae" in event_list:
        divisions.append("family")

    return divisions


def parse_competitors(entries: list) -> list[PoomsaeCompetitor]:
    competitors = []
    for entry in entries:
        divisions = parse_divisions(entry.events or "")
        if not divisions:
            continue

        age = int(entry.age or 0)
        age_group = get_age_group(age)
        name = entry.full_name or "Unknown Competitor"
        school = entry.school.name if entry.school else "Unknown School"
        gender = normalize_gender(entry.gender or "")
        belt = normalize_belt(entry.belt_rank or "")
        belt_rank = BELT_ORDER_INDEX.get(belt, len(BELT_ORDER))

        for division in divisions:
            competitors.append(
                PoomsaeCompetitor(
                    name=name,
                    school=school,
                    gender=gender,
                    age=age,
                    belt=belt,
                    belt_rank=belt_rank,
                    division=division,
                    age_group=age_group,
                    original_age_group=age_group,
                )
            )

    return competitors


def build_age_buckets(competitors: list[PoomsaeCompetitor]) -> dict[str, list[PoomsaeCompetitor]]:
    buckets = {age_group: [] for age_group in AGE_GROUP_ORDER}
    for competitor in competitors:
        buckets[competitor.age_group].append(competitor)
    return buckets


def _age_bucket_score(count: int) -> int:
    # Lower is better: 1-person age buckets are hardest to schedule.
    if count == 1:
        return 10
    return 0


def rebalance_singletons_adjacent(buckets: dict[str, list[PoomsaeCompetitor]]) -> dict[str, list[PoomsaeCompetitor]]:
    """
    Move single-competitor age buckets by one bracket only when it improves
    bracket viability for 2-4 competitor groups. Prefer whichever adjacent move
    yields the best improvement, with upward movement as the tie-breaker.
    """
    for index, age_group in enumerate(AGE_GROUP_ORDER):
        if len(buckets[age_group]) != 1:
            continue

        source_count = len(buckets[age_group])
        source_score_before = _age_bucket_score(source_count)

        candidates = []
        for delta in (1, -1):
            neighbor_index = index + delta
            if neighbor_index < 0 or neighbor_index >= len(AGE_GROUP_ORDER):
                continue

            neighbor_group = AGE_GROUP_ORDER[neighbor_index]
            neighbor_count = len(buckets[neighbor_group])

            source_score_after = _age_bucket_score(source_count - 1)
            neighbor_score_before = _age_bucket_score(neighbor_count)
            neighbor_score_after = _age_bucket_score(neighbor_count + 1)

            before_total = source_score_before + neighbor_score_before
            after_total = source_score_after + neighbor_score_after
            improvement = before_total - after_total

            if improvement > 0:
                candidates.append((improvement, delta, neighbor_group))

        if not candidates:
            continue

        # Higher improvement first; if equal, prefer moving up (delta=1).
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        chosen_group = candidates[0][2]

        moved = buckets[age_group].pop()
        moved.age_group = chosen_group
        buckets[chosen_group].append(moved)

    return buckets


def group_size_plan(count: int) -> list[int]:
    if count <= 0:
        return []
    if count <= 4:
        return [count]

    group_count = math.ceil(count / 4)
    sizes = [count // group_count] * group_count
    for index in range(count % group_count):
        sizes[index] += 1

    return sizes


def split_even_belt_groups(entries: list[PoomsaeCompetitor]) -> list[list[PoomsaeCompetitor]]:
    entries = sorted(entries, key=lambda competitor: (competitor.belt_rank, competitor.name.lower()))
    size_plan = group_size_plan(len(entries))
    if not size_plan:
        return []

    groups = [[] for _ in size_plan]

    def belt_fit_score(group: list[PoomsaeCompetitor], competitor: PoomsaeCompetitor) -> tuple[int, int]:
        if not group:
            # Prefer adding to a compatible existing belt cluster before opening a new one.
            return (2, 0)

        belt_values = [member.belt_rank for member in group]
        min_belt = min(belt_values)
        max_belt = max(belt_values)

        if competitor.belt_rank < min_belt:
            distance = min_belt - competitor.belt_rank
        elif competitor.belt_rank > max_belt:
            distance = competitor.belt_rank - max_belt
        else:
            distance = 0

        new_min = min(min_belt, competitor.belt_rank)
        new_max = max(max_belt, competitor.belt_rank)
        new_range = new_max - new_min

        return (distance, new_range)

    for competitor in entries:
        candidates = [index for index, group in enumerate(groups) if len(group) < size_plan[index]]
        best_index = min(
            candidates,
            key=lambda index: (
                belt_fit_score(groups[index], competitor),
                sum(1 for member in groups[index] if member.school == competitor.school),
                len(groups[index]),
                index,
            ),
        )
        groups[best_index].append(competitor)

    return groups


def generate_grouped_division(
    competitors: list[PoomsaeCompetitor],
    division_name: str,
) -> list[Group]:
    groups = []
    for gender in ["female", "male", "unknown"]:
        division_entries = [
            competitor for competitor in competitors if competitor.division == division_name and competitor.gender == gender
        ]
        if not division_entries:
            continue

        buckets = rebalance_singletons_adjacent(build_age_buckets(division_entries))
        for age_group in AGE_GROUP_ORDER:
            age_entries = buckets[age_group]
            if not age_entries:
                continue
            split_groups = split_even_belt_groups(age_entries)
            for members in split_groups:
                groups.append(Group(division=division_name, gender=gender, age_group=age_group, members=members))

    return groups


def competitors_for_division(competitors: list[PoomsaeCompetitor], division_name: str) -> list[PoomsaeCompetitor]:
    division_entries = [competitor for competitor in competitors if competitor.division == division_name]

    gender_order = {"female": 0, "male": 1, "unknown": 2}
    return sorted(
        division_entries,
        key=lambda competitor: (
            AGE_GROUP_ORDER.index(competitor.age_group),
            gender_order.get(competitor.gender, 99),
            competitor.belt_rank,
            competitor.name.lower(),
        ),
    )


def print_grouped_division(title: str, groups: list[Group]) -> None:
    print(f"{title} Groups (target size: 2-4 competitors)")
    print("=" * 88)

    if not groups:
        print("No competitors found.\n")
        return

    gender_order = {"female": 0, "male": 1, "unknown": 2}
    sorted_groups = sorted(
        groups,
        key=lambda group: (
            gender_order.get(group.gender, 99),
            AGE_GROUP_ORDER.index(group.age_group),
            len(group.members),
        ),
    )

    for index, group in enumerate(sorted_groups, start=1):
        print(f"Group {index:02d} | gender={group.gender} | age={group.age_group} | size={len(group.members)}")

        for competitor in sorted(group.members, key=lambda member: (member.belt_rank, member.name.lower())):
            moved_tag = ""
            if competitor.original_age_group != competitor.age_group:
                moved_tag = f" (moved from {competitor.original_age_group})"
            print(
                f"  - {competitor.name} | {competitor.school} | age={competitor.age} | belt={belt_label(competitor)}{moved_tag}"
            )

        if len(group.members) < 2:
            print("  ! Needs manual merge (single competitor group)")

        schools = [competitor.school for competitor in group.members]
        duplicates = {school for school in schools if schools.count(school) > 1}
        if duplicates:
            print(f"  ! Same-school pairing present: {', '.join(sorted(duplicates))}")

        print()


def print_counted_list(title: str, competitors: list[PoomsaeCompetitor]) -> None:
    print(f"{title} Competitors (count: {len(competitors)})")
    print("=" * 88)

    if not competitors:
        print("No competitors found.\n")
        return

    for index, competitor in enumerate(competitors, start=1):
        print(
            f"{index:02d}. {competitor.name} | {competitor.school} | "
            f"age={competitor.age} ({competitor.age_group}) | "
            f"gender={competitor.gender} | belt={belt_label(competitor)}"
        )

    print()


def grouped_rows(groups: list[Group], division_label: str) -> list[dict]:
    rows = []
    for group_index, group in enumerate(groups, start=1):
        for competitor in sorted(group.members, key=lambda member: (member.belt_rank, member.name.lower())):
            rows.append(
                {
                    "section": "grouped",
                    "division": division_label,
                    "group_number": group_index,
                    "group_size": len(group.members),
                    "name": competitor.name,
                    "school": competitor.school,
                    "gender": competitor.gender,
                    "age": competitor.age,
                    "age_group": competitor.age_group,
                    "original_age_group": competitor.original_age_group,
                    "age_group_move_direction": age_group_move_direction(competitor.original_age_group, competitor.age_group),
                    "belt": competitor.belt,
                }
            )
    return rows


def list_rows(competitors: list[PoomsaeCompetitor], division_label: str) -> list[dict]:
    rows = []
    for index, competitor in enumerate(competitors, start=1):
        rows.append(
            {
                "section": "list",
                "division": division_label,
                "group_number": "",
                "group_size": "",
                "name": competitor.name,
                "school": competitor.school,
                "gender": competitor.gender,
                "age": competitor.age,
                "age_group": competitor.age_group,
                "original_age_group": competitor.original_age_group,
                "age_group_move_direction": age_group_move_direction(competitor.original_age_group, competitor.age_group),
                "belt": competitor.belt,
                "list_position": index,
            }
        )
    return rows


def report_rows(
    individual_groups: list[Group],
    world_class_groups: list[Group],
    pair_list: list[PoomsaeCompetitor],
    team_list: list[PoomsaeCompetitor],
    family_list: list[PoomsaeCompetitor],
) -> list[dict]:
    rows = []
    rows.extend(grouped_rows(individual_groups, "individual"))
    rows.extend(grouped_rows(world_class_groups, "world_class"))
    rows.extend(list_rows(pair_list, "pair"))
    rows.extend(list_rows(team_list, "team"))
    rows.extend(list_rows(family_list, "family"))
    return rows


def write_csv(rows: list[dict], output_path: str) -> None:
    fieldnames = [
        "section",
        "division",
        "group_number",
        "group_size",
        "list_position",
        "name",
        "school",
        "gender",
        "age",
        "age_group",
        "original_age_group",
        "age_group_move_direction",
        "belt",
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(rows: list[dict], output_path: str) -> None:
    with open(output_path, "w", encoding="utf-8") as file_handle:
        json.dump(rows, file_handle, indent=2)


def export_report(rows: list[dict], output_format: str, output_dir: str) -> list[str]:
    os.makedirs(output_dir, exist_ok=True)
    written_files = []

    if output_format in {"csv", "both"}:
        csv_path = os.path.join(output_dir, "poomsae_groups.csv")
        write_csv(rows, csv_path)
        written_files.append(csv_path)

    if output_format in {"json", "both"}:
        json_path = os.path.join(output_dir, "poomsae_groups.json")
        write_json(rows, json_path)
        written_files.append(json_path)

    return written_files


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate grouped poomsae schedules with optional exports.")
    parser.add_argument(
        "--output-format",
        choices=["csv", "json", "both"],
        default="csv",
        help="Output format for saved schedule data. Defaults to csv.",
    )
    parser.add_argument(
        "--output-dir",
        default="output/schedules",
        help="Directory for generated schedule files. Defaults to output/schedules/.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    with app.app_context():
        entries = get_entries()
        competitors = parse_competitors(entries)

        individual_groups = generate_grouped_division(competitors, "individual")
        world_class_groups = generate_grouped_division(competitors, "world_class")

        print_grouped_division("Individual Poomsae", individual_groups)
        print_grouped_division("World Class Poomsae", world_class_groups)

        pair_list = competitors_for_division(competitors, "pair")
        team_list = competitors_for_division(competitors, "team")
        family_list = competitors_for_division(competitors, "family")

        print_counted_list("Pair Poomsae", pair_list)
        print_counted_list("Team Poomsae", team_list)
        print_counted_list("Family Poomsae", family_list)

        rows = report_rows(individual_groups, world_class_groups, pair_list, team_list, family_list)
        written_files = export_report(rows, args.output_format, args.output_dir)

    print("Saved schedule data to:")
    for file_path in written_files:
        print(f"  - {file_path}")


if __name__ == "__main__":
    main()
