"""The committed site data and feeds are valid and reproducible."""

import json
from pathlib import Path

from scraper import config, ics
from scraper.fetch import load_from_dir
from scraper.issues_ics import build_issue_calendars
from scraper.publish import render_json
from scraper.validate import validate

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
FIXTURES = Path(__file__).parent / "fixtures"


def committed_season() -> dict:
    return json.loads((SITE / "data" / "npl.json").read_text())


def test_committed_data_passes_validation():
    season = committed_season()
    raw = load_from_dir(FIXTURES / "season2026")
    assert validate(raw, season) == []


def committed_issues() -> dict:
    return json.loads((SITE / "data" / "issues.json").read_text())


def test_committed_calendars_are_the_generator_output():
    season = committed_season()
    expected = ics.build_calendars(season)
    written = {p.name for p in (SITE / "calendar").glob("*.ics")}
    assert written == {
        *(Path(relpath).name for relpath in expected),
        *(f"{name}.ics" for name in config.ISSUE_FEEDS),
    }
    assert set(expected) == {
        "calendar/npl.ics",
        *(f"calendar/{team['slug']}.ics" for team in season["teams"]),
    }
    for relpath, data in expected.items():
        assert (SITE / relpath).read_bytes() == data


def test_committed_issues_json_is_canonical():
    path = SITE / "data" / "issues.json"
    assert path.read_bytes() == render_json(committed_issues())


def test_committed_issue_feeds_are_the_generator_output():
    expected = build_issue_calendars(committed_issues())
    assert {Path(r).name for r in expected} == {f"{n}.ics" for n in config.ISSUE_FEEDS}
    for relpath, data in expected.items():
        assert (SITE / relpath).read_bytes() == data
