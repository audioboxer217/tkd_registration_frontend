"""Tests for the schedule-generation and badge scripts.

These tests cover the core logic in:
  - scripts/generate_badges.py
  - scripts/generate_breaking_schedule.py
  - scripts/generate_poomsae_schedule.py
  - scripts/generate_sparring_schedule.py
  - scripts/get_poomsae_counts.py
  - scripts/get_sparring_counts.py

All pure-logic functions are tested with mock Competitor ORM objects so that
no live database is required.  The conftest.py in this directory ensures
DATABASE_URL is set before pytest imports these test modules, which allows the
scripts' ``from app import app`` import to succeed.
"""

import csv
import io
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image as _PILImage

# ---------------------------------------------------------------------------
# Environment setup — mirrors the defaults in test_website.py.
# DATABASE_URL is set in conftest.py (runs before module collection).
# ---------------------------------------------------------------------------
os.environ.setdefault("COMPETITION_NAME", "Test Taekwondo Championship")
os.environ.setdefault("CONTACT_EMAIL", "contact@example.com")
os.environ.setdefault("EARLY_REG_DATE", "January 01, 2025")
os.environ.setdefault("REG_CLOSE_DATE", "December 31, 2099")
os.environ.setdefault("STRIPE_API_KEY", "sk_test_placeholder")
os.environ.setdefault("CONFIG_BUCKET", "test-config-bucket")
os.environ.setdefault("PUBLIC_MEDIA_BUCKET", "test-media-bucket")

base_path = os.path.dirname(os.path.realpath(__file__))
app_path = os.path.dirname(base_path)
sys.path.insert(0, app_path)

# Import script modules after path / env setup.
import scripts.generate_badges as badges_mod  # noqa: E402
import scripts.generate_breaking_schedule as breaking_mod  # noqa: E402
import scripts.generate_poomsae_schedule as poomsae_mod  # noqa: E402
import scripts.generate_sparring_schedule as sparring_mod  # noqa: E402
import scripts.get_poomsae_counts as poomsae_counts_mod  # noqa: E402
import scripts.get_sparring_counts as sparring_counts_mod  # noqa: E402


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def make_competitor(**kwargs):
    """Return a mock Competitor ORM object with sensible defaults.

    Only the attributes actually accessed by the scripts are set; everything
    else remains a MagicMock auto-attribute.
    """
    c = MagicMock()
    c.id = kwargs.get("id", 1)
    c.full_name = kwargs.get("full_name", "Test Competitor")
    school = MagicMock()
    school.name = kwargs.get("school", "Test School")
    c.school = school
    c.gender = kwargs.get("gender", "M")
    c.age = kwargs.get("age", 20)
    c.weight = kwargs.get("weight", 150.0)
    c.height = kwargs.get("height", 68)
    c.belt_rank = kwargs.get("belt_rank", "green")
    c.events = kwargs.get("events", "sparring")
    c.img_filename = kwargs.get("img_filename", None)
    return c


# ---------------------------------------------------------------------------
# generate_breaking_schedule tests
# ---------------------------------------------------------------------------


class TestBreakingSchedule:
    def test_get_age_group_known_ages(self):
        assert breaking_mod.get_age_group(5) == "dragon"
        assert breaking_mod.get_age_group(9) == "tiger"
        assert breaking_mod.get_age_group(11) == "youth"
        assert breaking_mod.get_age_group(13) == "cadet"
        assert breaking_mod.get_age_group(16) == "junior"
        assert breaking_mod.get_age_group(25) == "senior"
        assert breaking_mod.get_age_group(50) == "ultra"

    def test_get_age_group_boundaries(self):
        assert breaking_mod.get_age_group(4) == "dragon"
        assert breaking_mod.get_age_group(7) == "dragon"
        assert breaking_mod.get_age_group(8) == "tiger"
        assert breaking_mod.get_age_group(17) == "senior"
        assert breaking_mod.get_age_group(32) == "senior"
        assert breaking_mod.get_age_group(33) == "ultra"

    def test_normalize_gender(self):
        assert breaking_mod.normalize_gender("M") == "male"
        assert breaking_mod.normalize_gender("F") == "female"
        assert breaking_mod.normalize_gender("male") == "male"
        assert breaking_mod.normalize_gender("female") == "female"
        assert breaking_mod.normalize_gender("") == "unknown"
        assert breaking_mod.normalize_gender(None) == "unknown"

    def test_normalize_belt_rank(self):
        assert breaking_mod.normalize_belt_rank("green") == "green"
        assert breaking_mod.normalize_belt_rank("black 1") == "black"
        assert breaking_mod.normalize_belt_rank("black 2") == "black"
        assert breaking_mod.normalize_belt_rank("BLACK") == "black"
        assert breaking_mod.normalize_belt_rank("Blue") == "blue"
        assert breaking_mod.normalize_belt_rank("") == ""
        assert breaking_mod.normalize_belt_rank(None) == ""

    def test_is_breaking_competitor_true(self):
        assert breaking_mod.is_breaking_competitor("breaking") is True
        assert breaking_mod.is_breaking_competitor("sparring,breaking") is True
        assert breaking_mod.is_breaking_competitor("sparring, breaking , poomsae") is True

    def test_is_breaking_competitor_false(self):
        assert breaking_mod.is_breaking_competitor("sparring,poomsae") is False
        assert breaking_mod.is_breaking_competitor("") is False

    def test_belt_rank_index_known(self):
        assert breaking_mod.belt_rank_index("white") == 0
        assert breaking_mod.belt_rank_index("black") == 7
        assert breaking_mod.belt_rank_index("green") == 3

    def test_belt_rank_index_unknown(self):
        assert breaking_mod.belt_rank_index("unknown_belt") == len(breaking_mod.BELT_ORDER)

    def test_group_size_plan_small(self):
        assert breaking_mod.group_size_plan(0) == []
        assert breaking_mod.group_size_plan(1) == [1]
        assert breaking_mod.group_size_plan(3) == [3]
        assert breaking_mod.group_size_plan(4) == [4]

    def test_group_size_plan_split(self):
        # 5 competitors → 2 groups (sizes must total 5, each ≤ 4)
        plan = breaking_mod.group_size_plan(5)
        assert sum(plan) == 5
        assert all(1 <= s <= 4 for s in plan)

        # 8 competitors → 2 groups of 4
        plan = breaking_mod.group_size_plan(8)
        assert sum(plan) == 8
        assert all(s == 4 for s in plan)

        # 9 competitors → 3 groups (each ≤ 4, total 9)
        plan = breaking_mod.group_size_plan(9)
        assert sum(plan) == 9
        assert all(s <= 4 for s in plan)

    def test_parse_competitors_filters_non_breaking(self):
        entries = [
            make_competitor(full_name="Alice", events="sparring,breaking", age=12, gender="F"),
            make_competitor(full_name="Bob", events="poomsae", age=20, gender="M"),
        ]
        result = breaking_mod.parse_competitors(entries)
        assert len(result) == 1
        assert result[0].name == "Alice"

    def test_parse_competitors_field_mapping(self):
        entry = make_competitor(
            full_name="Carol",
            school="Tiger TKD",
            gender="F",
            age=15,
            weight=110.0,
            belt_rank="blue",
            events="breaking",
        )
        result = breaking_mod.parse_competitors([entry])
        assert len(result) == 1
        c = result[0]
        assert c.name == "Carol"
        assert c.school == "Tiger TKD"
        assert c.gender == "female"
        assert c.age == 15
        assert c.weight == 110.0
        assert c.belt_rank == "blue"
        assert c.age_group == "junior"

    def test_parse_competitors_no_school(self):
        entry = make_competitor(events="breaking", age=10)
        entry.school = None
        result = breaking_mod.parse_competitors([entry])
        assert result[0].school == "Unknown School"

    def test_parse_competitors_empty(self):
        assert breaking_mod.parse_competitors([]) == []

    def test_generate_groups_structure(self):
        entries = [
            make_competitor(
                full_name=f"F{i}",
                school=f"School{i}",
                gender="F",
                age=12,
                weight=float(80 + i),
                belt_rank="green",
                events="breaking",
            )
            for i in range(4)
        ]
        competitors = breaking_mod.parse_competitors(entries)
        groups = breaking_mod.generate_groups(competitors)
        assert len(groups) >= 1
        for group in groups:
            assert len(group.members) >= 1
            assert group.gender in ("female", "male", "unknown")
            assert group.age_group in breaking_mod.AGE_GROUP_ORDER

    def test_generate_groups_empty(self):
        assert breaking_mod.generate_groups([]) == []

    def test_groups_to_rows(self):
        entries = [
            make_competitor(
                full_name=n,
                school=s,
                gender="M",
                age=20,
                weight=w,
                belt_rank="blue",
                events="breaking",
            )
            for n, s, w in [("Dave", "School A", 160.0), ("Eve", "School B", 165.0)]
        ]
        competitors = breaking_mod.parse_competitors(entries)
        groups = breaking_mod.generate_groups(competitors)
        rows = breaking_mod.groups_to_rows(groups)
        assert len(rows) == 2
        assert all("group_number" in row for row in rows)
        assert all("competitor_name" in row for row in rows)
        assert all("belt_rank" in row for row in rows)

    def test_export_groups_csv(self, tmp_path):
        entries = [
            make_competitor(
                full_name=f"P{i}",
                school=f"School{i}",
                gender="M",
                age=20,
                weight=float(150 + i),
                belt_rank="green",
                events="breaking",
            )
            for i in range(4)
        ]
        competitors = breaking_mod.parse_competitors(entries)
        groups = breaking_mod.generate_groups(competitors)
        files = breaking_mod.export_groups(groups, "csv", str(tmp_path))
        assert len(files) == 1
        assert files[0].endswith(".csv")
        with open(files[0]) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 4
        assert "group_number" in rows[0]

    def test_export_groups_json(self, tmp_path):
        entries = [
            make_competitor(
                full_name=f"Q{i}",
                school=f"School{i}",
                gender="M",
                age=20,
                weight=float(150 + i),
                belt_rank="green",
                events="breaking",
            )
            for i in range(2)
        ]
        competitors = breaking_mod.parse_competitors(entries)
        groups = breaking_mod.generate_groups(competitors)
        files = breaking_mod.export_groups(groups, "json", str(tmp_path))
        assert len(files) == 1
        with open(files[0]) as f:
            data = json.load(f)
        assert isinstance(data, list)
        assert len(data) == 2

    def test_export_groups_both(self, tmp_path):
        entries = [
            make_competitor(
                full_name=f"R{i}",
                school=f"School{i}",
                gender="M",
                age=20,
                weight=float(150 + i),
                belt_rank="green",
                events="breaking",
            )
            for i in range(3)
        ]
        competitors = breaking_mod.parse_competitors(entries)
        groups = breaking_mod.generate_groups(competitors)
        files = breaking_mod.export_groups(groups, "both", str(tmp_path))
        assert len(files) == 2
        exts = {Path(f).suffix for f in files}
        assert exts == {".csv", ".json"}


# ---------------------------------------------------------------------------
# generate_poomsae_schedule tests
# ---------------------------------------------------------------------------


class TestPoomsaeSchedule:
    def test_get_age_group(self):
        assert poomsae_mod.get_age_group(6) == "dragon"
        assert poomsae_mod.get_age_group(8) == "tiger"
        assert poomsae_mod.get_age_group(10) == "youth"
        assert poomsae_mod.get_age_group(14) == "cadet"
        assert poomsae_mod.get_age_group(15) == "junior"
        assert poomsae_mod.get_age_group(20) == "senior"
        assert poomsae_mod.get_age_group(45) == "ultra"

    def test_normalize_gender(self):
        assert poomsae_mod.normalize_gender("M") == "male"
        assert poomsae_mod.normalize_gender("F") == "female"
        assert poomsae_mod.normalize_gender("") == "unknown"
        assert poomsae_mod.normalize_gender(None) == "unknown"

    def test_normalize_belt(self):
        assert poomsae_mod.normalize_belt("green") == "green"
        assert poomsae_mod.normalize_belt("BLACK 1") == "black"
        assert poomsae_mod.normalize_belt("Blue") == "blue"
        assert poomsae_mod.normalize_belt("") == "unknown"
        assert poomsae_mod.normalize_belt(None) == "unknown"

    def test_belt_label_known_belt(self):
        c = poomsae_mod.PoomsaeCompetitor(
            name="T",
            school="S",
            gender="male",
            age=20,
            belt="white",
            belt_rank=0,
            division="individual",
            age_group="senior",
            original_age_group="senior",
        )
        label = poomsae_mod.belt_label(c)
        assert "white" in label
        assert "level 1" in label

    def test_belt_label_unknown_belt(self):
        c = poomsae_mod.PoomsaeCompetitor(
            name="T",
            school="S",
            gender="male",
            age=20,
            belt="unknown",
            belt_rank=99,
            division="individual",
            age_group="senior",
            original_age_group="senior",
        )
        assert poomsae_mod.belt_label(c) == "unknown"

    def test_parse_divisions(self):
        assert poomsae_mod.parse_divisions("poomsae") == ["individual"]
        assert poomsae_mod.parse_divisions("world-class poomsae") == ["world_class"]
        assert poomsae_mod.parse_divisions("pair poomsae") == ["pair"]
        assert poomsae_mod.parse_divisions("team poomsae") == ["team"]
        assert poomsae_mod.parse_divisions("family poomsae") == ["family"]
        assert poomsae_mod.parse_divisions("poomsae,world-class poomsae,pair poomsae") == [
            "individual",
            "world_class",
            "pair",
        ]
        assert poomsae_mod.parse_divisions("sparring") == []
        assert poomsae_mod.parse_divisions("") == []

    def test_age_group_move_direction(self):
        assert poomsae_mod.age_group_move_direction("dragon", "tiger") == "up"
        assert poomsae_mod.age_group_move_direction("tiger", "dragon") == "down"
        assert poomsae_mod.age_group_move_direction("senior", "senior") == ""

    def test_group_size_plan(self):
        assert poomsae_mod.group_size_plan(0) == []
        assert poomsae_mod.group_size_plan(4) == [4]
        plan = poomsae_mod.group_size_plan(5)
        assert sum(plan) == 5

    def test_parse_competitors_multi_division(self):
        entry = make_competitor(
            full_name="Alice",
            school="Eagle TKD",
            gender="F",
            age=20,
            belt_rank="black 1",
            events="poomsae,world-class poomsae",
        )
        result = poomsae_mod.parse_competitors([entry])
        assert len(result) == 2
        divisions = {c.division for c in result}
        assert "individual" in divisions
        assert "world_class" in divisions

    def test_parse_competitors_no_poomsae(self):
        entry = make_competitor(events="sparring")
        assert poomsae_mod.parse_competitors([entry]) == []

    def test_parse_competitors_field_mapping(self):
        entry = make_competitor(
            full_name="Bob",
            school="Tiger School",
            gender="M",
            age=12,
            belt_rank="blue",
            events="poomsae",
        )
        result = poomsae_mod.parse_competitors([entry])
        assert len(result) == 1
        c = result[0]
        assert c.name == "Bob"
        assert c.school == "Tiger School"
        assert c.gender == "male"
        assert c.age == 12
        assert c.belt == "blue"
        assert c.age_group == "cadet"

    def test_parse_competitors_no_school(self):
        entry = make_competitor(events="poomsae", age=20)
        entry.school = None
        result = poomsae_mod.parse_competitors([entry])
        assert result[0].school == "Unknown School"

    def test_generate_grouped_division_structure(self):
        entries = [
            make_competitor(
                full_name=f"P{i}",
                school=f"School{i}",
                gender="F",
                age=20,
                belt_rank="green",
                events="poomsae",
            )
            for i in range(4)
        ]
        competitors = poomsae_mod.parse_competitors(entries)
        groups = poomsae_mod.generate_grouped_division(competitors, "individual")
        assert len(groups) >= 1
        for group in groups:
            assert group.division == "individual"
            assert group.gender == "female"

    def test_generate_grouped_division_empty(self):
        assert poomsae_mod.generate_grouped_division([], "individual") == []

    def test_export_report_csv(self, tmp_path):
        entries = [
            make_competitor(
                full_name=f"X{i}",
                school=f"School{i}",
                gender="M",
                age=20,
                belt_rank="green",
                events="poomsae",
            )
            for i in range(4)
        ]
        competitors = poomsae_mod.parse_competitors(entries)
        individual_groups = poomsae_mod.generate_grouped_division(competitors, "individual")
        rows = poomsae_mod.report_rows(individual_groups, [], [], [], [])
        files = poomsae_mod.export_report(rows, "csv", str(tmp_path))
        assert len(files) == 1
        with open(files[0]) as f:
            csv_rows = list(csv.DictReader(f))
        assert len(csv_rows) == len(rows)

    def test_export_report_json(self, tmp_path):
        entries = [
            make_competitor(
                full_name=f"Y{i}",
                school=f"School{i}",
                gender="M",
                age=20,
                belt_rank="green",
                events="poomsae",
            )
            for i in range(3)
        ]
        competitors = poomsae_mod.parse_competitors(entries)
        individual_groups = poomsae_mod.generate_grouped_division(competitors, "individual")
        rows = poomsae_mod.report_rows(individual_groups, [], [], [], [])
        files = poomsae_mod.export_report(rows, "json", str(tmp_path))
        assert len(files) == 1
        with open(files[0]) as f:
            data = json.load(f)
        assert isinstance(data, list)

    def test_export_report_both(self, tmp_path):
        entries = [
            make_competitor(
                full_name=f"Z{i}",
                school=f"School{i}",
                gender="F",
                age=20,
                belt_rank="green",
                events="poomsae",
            )
            for i in range(2)
        ]
        competitors = poomsae_mod.parse_competitors(entries)
        individual_groups = poomsae_mod.generate_grouped_division(competitors, "individual")
        rows = poomsae_mod.report_rows(individual_groups, [], [], [], [])
        files = poomsae_mod.export_report(rows, "both", str(tmp_path))
        assert len(files) == 2
        exts = {Path(f).suffix for f in files}
        assert exts == {".csv", ".json"}


# ---------------------------------------------------------------------------
# generate_sparring_schedule tests
# ---------------------------------------------------------------------------


class TestSparringSchedule:
    def test_get_age_group(self):
        assert sparring_mod.get_age_group(5) == "dragon"
        assert sparring_mod.get_age_group(9) == "tiger"
        assert sparring_mod.get_age_group(20) == "senior"
        assert sparring_mod.get_age_group(40) == "ultra"

    def test_normalize_gender(self):
        assert sparring_mod.normalize_gender("M") == "male"
        assert sparring_mod.normalize_gender("F") == "female"
        assert sparring_mod.normalize_gender("") == "unknown"
        assert sparring_mod.normalize_gender(None) == "unknown"

    def test_parse_divisions(self):
        assert sparring_mod.parse_divisions("sparring") == ["color_belt"]
        assert sparring_mod.parse_divisions("sparring-gr") == ["grass_roots"]
        assert sparring_mod.parse_divisions("sparring-wc") == ["world_class"]
        assert sparring_mod.parse_divisions("sparring,sparring-gr") == ["color_belt", "grass_roots"]
        assert sparring_mod.parse_divisions("poomsae") == []
        assert sparring_mod.parse_divisions("") == []

    def test_group_size_plan(self):
        assert sparring_mod.group_size_plan(0) == []
        assert sparring_mod.group_size_plan(2) == [2]
        plan = sparring_mod.group_size_plan(6)
        assert sum(plan) == 6
        assert all(s <= 4 for s in plan)

    def test_should_combine_color_and_grass_true(self):
        # grass too small to stand alone → combine
        color = [MagicMock(), MagicMock()]
        grass = [MagicMock()]
        assert sparring_mod.should_combine_color_and_grass(color, grass) is True

    def test_should_combine_color_and_grass_false(self):
        # both sides large enough
        color = [MagicMock(), MagicMock()]
        grass = [MagicMock(), MagicMock()]
        assert sparring_mod.should_combine_color_and_grass(color, grass) is False

    def test_should_combine_color_and_grass_empty(self):
        # empty side → do not combine
        assert sparring_mod.should_combine_color_and_grass([], [MagicMock()]) is False
        assert sparring_mod.should_combine_color_and_grass([MagicMock()], []) is False

    def test_parse_competitors_multi_division(self):
        entry = make_competitor(full_name="Maya", gender="F", age=15, weight=115.0, events="sparring,sparring-gr")
        result = sparring_mod.parse_competitors([entry])
        assert len(result) == 2
        divisions = {c.division for c in result}
        assert "color_belt" in divisions
        assert "grass_roots" in divisions

    def test_parse_competitors_no_sparring(self):
        entry = make_competitor(events="poomsae")
        assert sparring_mod.parse_competitors([entry]) == []

    def test_parse_competitors_field_mapping(self):
        entry = make_competitor(
            full_name="Sam",
            school="Summit TKD",
            gender="M",
            age=18,
            weight=155.0,
            events="sparring",
        )
        result = sparring_mod.parse_competitors([entry])
        assert len(result) == 1
        c = result[0]
        assert c.name == "Sam"
        assert c.school == "Summit TKD"
        assert c.gender == "male"
        assert c.age == 18
        assert c.weight == 155.0
        assert c.division == "color_belt"
        assert c.age_group == "senior"

    def test_parse_competitors_no_school(self):
        entry = make_competitor(events="sparring", age=20)
        entry.school = None
        result = sparring_mod.parse_competitors([entry])
        assert result[0].school == "Unknown School"

    def test_generate_groups_structure(self):
        entries = [
            make_competitor(
                full_name=f"A{i}",
                school=f"School{i}",
                gender="M",
                age=20,
                weight=float(150 + i * 5),
                events="sparring",
            )
            for i in range(4)
        ]
        competitors = sparring_mod.parse_competitors(entries)
        groups = sparring_mod.generate_groups(competitors)
        assert len(groups) >= 1
        for group in groups:
            assert group.division in ("color_belt", "grass_roots", "world_class", "color_belt+grass_roots")
            assert group.age_group in sparring_mod.AGE_GROUP_ORDER

    def test_generate_groups_empty(self):
        assert sparring_mod.generate_groups([]) == []

    def test_split_by_weight_and_school_groups_four(self):
        entries = [
            sparring_mod.SparringCompetitor(
                name=f"P{i}",
                school="School",
                gender="male",
                age=20,
                weight=float(100 + i * 10),
                division="color_belt",
                age_group="senior",
                original_age_group="senior",
                raw=None,
            )
            for i in range(4)
        ]
        groups = sparring_mod.split_by_weight_and_school(entries)
        # 4 entries → 1 group of 4
        assert len(groups) == 1
        assert len(groups[0]) == 4

    def test_split_by_weight_and_school_five(self):
        entries = [
            sparring_mod.SparringCompetitor(
                name=f"P{i}",
                school=f"School{i}",
                gender="male",
                age=20,
                weight=float(100 + i * 10),
                division="color_belt",
                age_group="senior",
                original_age_group="senior",
                raw=None,
            )
            for i in range(5)
        ]
        groups = sparring_mod.split_by_weight_and_school(entries)
        assert sum(len(g) for g in groups) == 5
        assert all(len(g) <= 4 for g in groups)

    def test_export_groups_csv(self, tmp_path):
        entries = [
            make_competitor(
                full_name=f"B{i}",
                school=f"School{i}",
                gender="M",
                age=20,
                weight=float(150 + i),
                events="sparring",
            )
            for i in range(4)
        ]
        competitors = sparring_mod.parse_competitors(entries)
        groups = sparring_mod.generate_groups(competitors)
        files = sparring_mod.export_groups(groups, "csv", str(tmp_path))
        assert len(files) == 1
        with open(files[0]) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 4

    def test_export_groups_json(self, tmp_path):
        entries = [
            make_competitor(
                full_name=f"C{i}",
                school=f"School{i}",
                gender="M",
                age=20,
                weight=float(150 + i),
                events="sparring",
            )
            for i in range(3)
        ]
        competitors = sparring_mod.parse_competitors(entries)
        groups = sparring_mod.generate_groups(competitors)
        files = sparring_mod.export_groups(groups, "json", str(tmp_path))
        assert len(files) == 1
        with open(files[0]) as f:
            data = json.load(f)
        assert isinstance(data, list)


# ---------------------------------------------------------------------------
# get_poomsae_counts tests
# ---------------------------------------------------------------------------


class TestPoomsaeCounts:
    def test_has_event_present(self):
        entry = make_competitor(events="poomsae,sparring")
        assert poomsae_counts_mod.has_event(entry, "poomsae") is True
        assert poomsae_counts_mod.has_event(entry, "sparring") is True

    def test_has_event_absent(self):
        entry = make_competitor(events="poomsae,sparring")
        assert poomsae_counts_mod.has_event(entry, "breaking") is False

    def test_has_event_strips_whitespace(self):
        entry = make_competitor(events=" poomsae , sparring ")
        assert poomsae_counts_mod.has_event(entry, "poomsae") is True

    def test_has_event_empty_events(self):
        entry = make_competitor(events="")
        assert poomsae_counts_mod.has_event(entry, "poomsae") is False

    def test_get_age_group_known(self):
        assert poomsae_counts_mod.get_age_group(make_competitor(age=6)) == "dragon"
        assert poomsae_counts_mod.get_age_group(make_competitor(age=9)) == "tiger"
        assert poomsae_counts_mod.get_age_group(make_competitor(age=11)) == "youth"
        assert poomsae_counts_mod.get_age_group(make_competitor(age=13)) == "cadet"
        assert poomsae_counts_mod.get_age_group(make_competitor(age=16)) == "junior"
        assert poomsae_counts_mod.get_age_group(make_competitor(age=25)) == "senior"
        assert poomsae_counts_mod.get_age_group(make_competitor(age=60)) == "ultra"

    def test_get_age_group_out_of_range_returns_none(self):
        # age=0 is out of every defined group (groups start at 4)
        result = poomsae_counts_mod.get_age_group(make_competitor(age=0))
        assert result is None

    def test_get_age_group_invalid_age_returns_none(self):
        entry = make_competitor(age=None)
        assert poomsae_counts_mod.get_age_group(entry) is None

    def test_divide_age_groups(self):
        entries = [
            make_competitor(age=6, events="poomsae"),
            make_competitor(age=9, events="poomsae"),
            make_competitor(age=20, events="poomsae"),
        ]
        groups = poomsae_counts_mod.divide_age_groups(entries)
        assert len(groups["dragon"]) == 1
        assert len(groups["tiger"]) == 1
        assert len(groups["senior"]) == 1
        assert len(groups["youth"]) == 0

    def test_divide_age_groups_empty(self):
        groups = poomsae_counts_mod.divide_age_groups([])
        assert all(len(v) == 0 for v in groups.values())

    def test_divide_age_groups_all_age_groups_present(self):
        groups = poomsae_counts_mod.divide_age_groups([])
        expected_keys = {"dragon", "tiger", "youth", "cadet", "junior", "senior", "ultra"}
        assert set(groups.keys()) == expected_keys

    def test_has_event_family_poomsae(self):
        entry = make_competitor(events="family poomsae,sparring")
        assert poomsae_counts_mod.has_event(entry, "family poomsae") is True

    def test_family_poomsae_counted_separately(self):
        """family poomsae registrations are filtered separately from individual/pair/team."""
        entries = [
            make_competitor(age=20, gender="F", events="family poomsae"),
            make_competitor(age=20, gender="M", events="family poomsae"),
            make_competitor(age=20, gender="F", events="poomsae"),
        ]
        family = [e for e in entries if poomsae_counts_mod.has_event(e, "family poomsae")]
        individual = [e for e in entries if poomsae_counts_mod.has_event(e, "poomsae")]
        assert len(family) == 2
        assert len(individual) == 1
        family_groups = poomsae_counts_mod.divide_age_groups(family)
        assert len(family_groups["senior"]) == 2


# ---------------------------------------------------------------------------
# get_sparring_counts tests
# ---------------------------------------------------------------------------


class TestSparringCounts:
    def test_has_event_present(self):
        entry = make_competitor(events="sparring,poomsae")
        assert sparring_counts_mod.has_event(entry, "sparring") is True

    def test_has_event_absent(self):
        entry = make_competitor(events="sparring,poomsae")
        assert sparring_counts_mod.has_event(entry, "sparring-gr") is False

    def test_has_event_strips_whitespace(self):
        entry = make_competitor(events=" sparring-gr , poomsae ")
        assert sparring_counts_mod.has_event(entry, "sparring-gr") is True

    def test_get_age_group_known(self):
        assert sparring_counts_mod.get_age_group(make_competitor(age=8)) == "tiger"
        assert sparring_counts_mod.get_age_group(make_competitor(age=25)) == "senior"
        assert sparring_counts_mod.get_age_group(make_competitor(age=50)) == "ultra"

    def test_get_age_group_invalid_age_returns_none(self):
        entry = make_competitor()
        entry.age = "bad_value"
        result = sparring_counts_mod.get_age_group(entry)
        assert result is None

    def test_divide_age_groups(self):
        entries = [
            make_competitor(age=8, events="sparring"),
            make_competitor(age=8, events="sparring"),
            make_competitor(age=25, events="sparring-gr"),
        ]
        groups = sparring_counts_mod.divide_age_groups(entries)
        assert len(groups["tiger"]) == 2
        assert len(groups["senior"]) == 1
        assert all(len(groups[ag]) == 0 for ag in ["dragon", "youth", "cadet", "junior", "ultra"])

    def test_divide_age_groups_empty(self):
        groups = sparring_counts_mod.divide_age_groups([])
        assert all(len(v) == 0 for v in groups.values())

    def test_divide_age_groups_all_keys_present(self):
        groups = sparring_counts_mod.divide_age_groups([])
        expected_keys = {"dragon", "tiger", "youth", "cadet", "junior", "senior", "ultra"}
        assert set(groups.keys()) == expected_keys


# ---------------------------------------------------------------------------
# generate_badges tests
# ---------------------------------------------------------------------------


class TestDownloadS3ProfileImage:
    def test_returns_none_when_no_bucket_env_var(self, monkeypatch):
        monkeypatch.delenv("PROFILE_PIC_BUCKET", raising=False)
        result = badges_mod.get_s3_profile_image("photo.jpg")
        assert result is None

    def test_downloads_image_from_s3(self, monkeypatch):
        """When PROFILE_PIC_BUCKET is set, the image is fetched via boto3."""
        monkeypatch.setenv("PROFILE_PIC_BUCKET", "test-profile-bucket")

        img_buf = io.BytesIO()
        _PILImage.new("RGB", (50, 50), color="red").save(img_buf, format="JPEG")
        img_bytes = img_buf.getvalue()

        def fake_download_fileobj(bucket, key, fileobj):
            fileobj.write(img_bytes)

        mock_s3 = MagicMock()
        mock_s3.download_fileobj.side_effect = fake_download_fileobj

        with patch("scripts.generate_badges.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_s3
            result = badges_mod.get_s3_profile_image("photo.jpg")

        assert result is not None
        assert mock_s3.download_fileobj.called

    def test_returns_none_on_s3_error(self, monkeypatch):
        monkeypatch.setenv("PROFILE_PIC_BUCKET", "test-profile-bucket")
        mock_s3 = MagicMock()
        mock_s3.download_fileobj.side_effect = Exception("S3 error")

        with patch("scripts.generate_badges.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_s3
            result = badges_mod.get_s3_profile_image("photo.jpg")

        assert result is None


class TestGenerateBadges:
    @pytest.fixture(autouse=True)
    def set_working_dir(self, monkeypatch):
        """Change CWD to the repo root so relative font paths resolve."""
        monkeypatch.chdir(app_path)

    def test_generate_badge_creates_file(self, tmp_path):
        competitor = make_competitor(
            id=42,
            full_name="Jane Doe",
            school="Eagle TKD",
            gender="F",
            age=14,
            weight=110.0,
            belt_rank="blue",
            events="sparring,poomsae",
        )
        result = badges_mod.generate_badge(competitor, str(tmp_path))
        assert "generated" in result
        assert (tmp_path / "42_badge.jpg").exists()

    def test_generate_badge_uses_s3_image(self, tmp_path, monkeypatch):
        """When img_filename is set, the profile image is fetched from S3."""
        img_buf = io.BytesIO()
        _PILImage.new("RGB", (100, 100), color="blue").save(img_buf, format="JPEG")
        img_bytes = img_buf.getvalue()

        def fake_download_fileobj(bucket, key, fileobj):
            fileobj.write(img_bytes)

        monkeypatch.setenv("PROFILE_PIC_BUCKET", "test-profile-bucket")
        mock_s3 = MagicMock()
        mock_s3.download_fileobj.side_effect = fake_download_fileobj

        competitor = make_competitor(
            id=43,
            full_name="S3 Photo User",
            img_filename="43_profile.jpg",
            events="sparring",
        )
        with patch("scripts.generate_badges.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_s3
            result = badges_mod.generate_badge(competitor, str(tmp_path))

        assert "generated" in result
        assert (tmp_path / "43_badge.jpg").exists()
        assert mock_s3.download_fileobj.called

    def test_generate_badge_falls_back_when_s3_fails(self, tmp_path, monkeypatch):
        """If S3 download fails, badge is still generated without a profile photo."""
        monkeypatch.setenv("PROFILE_PIC_BUCKET", "test-profile-bucket")
        mock_s3 = MagicMock()
        mock_s3.download_fileobj.side_effect = Exception("S3 unavailable")

        competitor = make_competitor(
            id=44,
            full_name="S3 Fail User",
            img_filename="44_profile.jpg",
            events="poomsae",
        )
        with patch("scripts.generate_badges.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_s3
            result = badges_mod.generate_badge(competitor, str(tmp_path))

        assert "generated" in result
        assert (tmp_path / "44_badge.jpg").exists()

    def test_generate_badge_no_img_filename_uses_local_fallback(self, tmp_path, monkeypatch):
        """When img_filename is None, fall back to local BADGE_IMG_FILENAME (if set)."""
        # No BADGE_IMG_FILENAME set — no local fallback either; badge still generates.
        monkeypatch.delenv("BADGE_IMG_FILENAME", raising=False)
        competitor = make_competitor(id=45, full_name="No Photo", img_filename=None, events="sparring")
        result = badges_mod.generate_badge(competitor, str(tmp_path))
        assert "generated" in result

    def test_generate_badge_black_belt_normalized(self, tmp_path):
        competitor = make_competitor(
            id=99,
            full_name="Mr. Black",
            belt_rank="black 2 dan",
            events="poomsae",
        )
        result = badges_mod.generate_badge(competitor, str(tmp_path))
        assert "generated" in result

    def test_generate_badge_no_events(self, tmp_path):
        competitor = make_competitor(id=7, full_name="Empty Events", events="")
        result = badges_mod.generate_badge(competitor, str(tmp_path))
        assert "generated" in result

    def test_generate_badge_no_school(self, tmp_path):
        competitor = make_competitor(id=8, full_name="No School")
        competitor.school = None
        result = badges_mod.generate_badge(competitor, str(tmp_path))
        assert "generated" in result

    def test_generate_badge_null_weight(self, tmp_path):
        competitor = make_competitor(id=9, full_name="No Weight", weight=None)
        result = badges_mod.generate_badge(competitor, str(tmp_path))
        assert "generated" in result

    def test_generate_badge_all_event_categories(self, tmp_path):
        """Badge generation handles both 'left column' and 'right column' event types."""
        competitor = make_competitor(
            id=55,
            full_name="All Events",
            events="sparring,poomsae,world-class poomsae,pair poomsae,breaking",
        )
        result = badges_mod.generate_badge(competitor, str(tmp_path))
        assert "generated" in result
