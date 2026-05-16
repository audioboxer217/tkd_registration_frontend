#!/usr/bin/env python

import argparse
import csv
import json
import math
import os
from dataclasses import dataclass, field

try:
    from scripts._bootstrap import add_repo_root_to_path
except ModuleNotFoundError:  # Allows `python scripts/generate_breaking_schedule.py`
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


@dataclass
class BreakingCompetitor:
    name: str
    school: str
    gender: str
    age: int
    weight: float
    belt_rank: str
    age_group: str
    raw: object


@dataclass
class Group:
    gender: str
    age_group: str
    members: list[BreakingCompetitor] = field(default_factory=list)


def get_entries():
    """Query all paid (complete) competitors from the database."""
    return get_eligible_competitors(status="complete")


def get_age_group(age: int) -> str:
    return next((group for group, ages in AGE_GROUPS.items() if age in ages), "ultra")


def normalize_gender(gender: str) -> str:
    gender = (gender or "").strip().lower()
    if gender.startswith("m"):
        return "male"
    if gender.startswith("f"):
        return "female"
    return "unknown"


def normalize_belt_rank(belt_rank: str) -> str:
    belt_rank = (belt_rank or "").strip().lower()
    if "black" in belt_rank:
        return "black"
    for belt in BELT_ORDER:
        if belt in belt_rank:
            return belt
    return belt_rank


def is_breaking_competitor(events: str) -> bool:
    return "breaking" in {event.strip() for event in events.split(",")}


def parse_competitors(entries: list) -> list[BreakingCompetitor]:
    competitors = []
    for entry in entries:
        events = entry.events or ""
        if not is_breaking_competitor(events):
            continue

        age = int(entry.age or 0)
        weight = float(entry.weight or 0)
        gender = normalize_gender(entry.gender or "")
        school = entry.school.name if entry.school else "Unknown School"
        name = entry.full_name or "Unknown Competitor"
        belt_rank = normalize_belt_rank(entry.belt_rank or "")
        age_group = get_age_group(age)

        competitors.append(
            BreakingCompetitor(
                name=name,
                school=school,
                gender=gender,
                age=age,
                weight=weight,
                belt_rank=belt_rank,
                age_group=age_group,
                raw=entry,
            )
        )

    return competitors


def belt_rank_index(belt_rank: str) -> int:
    try:
        return BELT_ORDER.index(belt_rank)
    except ValueError:
        return len(BELT_ORDER)


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


def _assign_school_diverse(entries: list[BreakingCompetitor], size_plan: list[int]) -> list[list[BreakingCompetitor]]:
    """Fill groups according to size_plan, minimising same-school pairings."""
    groups: list[list[BreakingCompetitor]] = [[] for _ in size_plan]
    max_sizes = list(size_plan)

    for competitor in entries:
        candidates = [index for index, group in enumerate(groups) if len(group) < max_sizes[index]]
        best_index = min(
            candidates,
            key=lambda index: (
                sum(1 for member in groups[index] if member.school == competitor.school),
                len(groups[index]),
            ),
        )
        groups[best_index].append(competitor)

    return groups


def split_by_belt_weight_and_school(entries: list[BreakingCompetitor]) -> list[list[BreakingCompetitor]]:
    """Group competitors by belt rank, merge singletons into adjacent belt groups, then split
    into groups of 2-4 with school-diversity optimisation within each belt cluster."""

    # Build per-belt buckets sorted by weight
    belt_buckets: dict[str, list[BreakingCompetitor]] = {}
    for competitor in entries:
        belt_buckets.setdefault(competitor.belt_rank, []).append(competitor)
    for key in belt_buckets:
        belt_buckets[key].sort(key=lambda c: c.weight)

    # Order buckets by belt rank (unknown belts go last)
    ordered_keys = sorted(belt_buckets.keys(), key=belt_rank_index)

    # Start with one cluster per belt rank, then merge singletons into nearest neighbor
    clusters: list[list[str]] = [[key] for key in ordered_keys]

    changed = True
    while changed:
        changed = False
        new_clusters: list[list[str]] = []
        i = 0
        while i < len(clusters):
            cluster = clusters[i]
            cluster_size = sum(len(belt_buckets[k]) for k in cluster)
            if cluster_size == 1:
                if i + 1 < len(clusters):
                    # Merge with next (higher belt)
                    new_clusters.append(cluster + clusters[i + 1])
                    i += 2
                    changed = True
                elif new_clusters:
                    # Fall back: merge with previous cluster
                    new_clusters[-1] = new_clusters[-1] + cluster
                    i += 1
                    changed = True
                else:
                    new_clusters.append(cluster)
                    i += 1
            else:
                new_clusters.append(cluster)
                i += 1
        clusters = new_clusters

    # Split each cluster into groups of 2-4 with school diversity
    all_groups: list[list[BreakingCompetitor]] = []
    for cluster in clusters:
        cluster_entries: list[BreakingCompetitor] = []
        for key in cluster:
            cluster_entries.extend(belt_buckets[key])
        size_plan = group_size_plan(len(cluster_entries))
        if not size_plan:
            continue
        all_groups.extend(_assign_school_diverse(cluster_entries, size_plan))

    return all_groups


def generate_groups(competitors: list[BreakingCompetitor]) -> list[Group]:
    groups = []

    for gender in ["female", "male", "unknown"]:
        gender_competitors = [c for c in competitors if c.gender == gender]
        if not gender_competitors:
            continue

        by_age_group: dict[str, list[BreakingCompetitor]] = {age_group: [] for age_group in AGE_GROUP_ORDER}
        for competitor in gender_competitors:
            by_age_group[competitor.age_group].append(competitor)

        for age_group in AGE_GROUP_ORDER:
            entries = by_age_group[age_group]
            if not entries:
                continue

            for members in split_by_belt_weight_and_school(entries):
                groups.append(Group(gender=gender, age_group=age_group, members=members))

    return groups


def print_groups(groups: list[Group]) -> None:
    gender_order = {"female": 0, "male": 1, "unknown": 2}

    groups = sorted(
        groups,
        key=lambda group: (
            gender_order.get(group.gender, 99),
            AGE_GROUP_ORDER.index(group.age_group),
            len(group.members),
        ),
    )

    if not groups:
        print("No breaking competitors found.")
        return

    print("Breaking Groups (target size: 2-4 competitors)")
    print("=" * 80)

    for index, group in enumerate(groups, start=1):
        print(f"Group {index:02d} | gender={group.gender} | age={group.age_group} | size={len(group.members)}")

        for member in sorted(group.members, key=lambda c: (belt_rank_index(c.belt_rank), c.weight)):
            print(
                f"  - {member.name} | {member.school} | age={member.age} | belt={member.belt_rank} | weight={member.weight:.1f}"
            )

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
        for competitor in sorted(group.members, key=lambda m: (belt_rank_index(m.belt_rank), m.weight)):
            rows.append(
                {
                    "group_number": group_index,
                    "gender": group.gender,
                    "age_group": group.age_group,
                    "group_size": len(group.members),
                    "competitor_name": competitor.name,
                    "school": competitor.school,
                    "age": competitor.age,
                    "belt_rank": competitor.belt_rank,
                    "weight": competitor.weight,
                }
            )
    return rows


def write_csv(groups: list[Group], output_path: str) -> None:
    rows = groups_to_rows(groups)
    fieldnames = [
        "group_number",
        "gender",
        "age_group",
        "group_size",
        "competitor_name",
        "school",
        "age",
        "belt_rank",
        "weight",
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(groups: list[Group], output_path: str) -> None:
    rows = groups_to_rows(groups)
    with open(output_path, "w", encoding="utf-8") as file_handle:
        json.dump(rows, file_handle, indent=2)


def export_groups(groups: list[Group], output_format: str, output_dir: str = "output/schedules") -> list[str]:
    os.makedirs(output_dir, exist_ok=True)
    written_files = []

    if output_format in {"csv", "both"}:
        csv_path = os.path.join(output_dir, "breaking_groups.csv")
        write_csv(groups, csv_path)
        written_files.append(csv_path)

    if output_format in {"json", "both"}:
        json_path = os.path.join(output_dir, "breaking_groups.json")
        write_json(groups, json_path)
        written_files.append(json_path)

    return written_files


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate 2-4 person breaking groups.")
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
