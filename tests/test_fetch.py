"""Fetch layer: robots.txt (V1), the three API GETs (V2), and offline loading."""

import json
from pathlib import Path

import pytest
import requests

from scraper import config, fetch
from scraper.errors import ScrapeError
from scraper.fetch import load_from_dir, load_remote
from scraper.normalize import RawSource
from tests.fakes import FakeResponse, FakeSession

FIXTURES = Path(__file__).parent / "fixtures"

BASE = config.SOURCE_BASE
ROBOTS_URL = f"{BASE}/robots.txt"
TEAMS_URL = f"{BASE}/api/v1/teams"
MATCHES_URL = f"{BASE}/api/v1/matches?season={config.SEASON_YEAR}"
POINTS_URL = f"{BASE}/api/v1/points?season={config.SEASON_YEAR}"
STATS_URL = f"{BASE}/api/v1/stats?season={config.SEASON_YEAR}"

ALLOW_ALL_ROBOTS = "User-Agent: *\nAllow: /\n"
DISALLOW_API_ROBOTS = "User-Agent: *\nDisallow: /api/\n"
DISALLOW_STATS_ROBOTS = "User-Agent: *\nDisallow: /api/v1/stats\n"


def _fixture_text(name):
    return (FIXTURES / "season2026" / f"{name}.json").read_text()


def _happy_routes(overrides=None):
    routes = {
        ROBOTS_URL: FakeResponse(200, ALLOW_ALL_ROBOTS),
        TEAMS_URL: FakeResponse(200, _fixture_text("teams")),
        MATCHES_URL: FakeResponse(200, _fixture_text("matches")),
        POINTS_URL: FakeResponse(200, _fixture_text("points")),
        STATS_URL: FakeResponse(200, _fixture_text("stats")),
    }
    if overrides:
        routes.update(overrides)
    return routes


def test_load_remote_returns_raw_source():
    session = FakeSession(_happy_routes())
    raw = load_remote(session)
    assert isinstance(raw, RawSource)
    assert len(raw.teams) == 8
    assert len(raw.matches) == 32
    assert len(raw.points) == 8
    assert len(raw.stats) == 60


def test_season_parameter_on_matches_and_points_only():
    session = FakeSession(_happy_routes())
    load_remote(session)
    urls = [c["url"] for c in session.calls]
    assert MATCHES_URL in urls
    assert POINTS_URL in urls
    assert TEAMS_URL in urls
    assert all("season=" not in u for u in urls if u == TEAMS_URL)
    assert f"season={config.SEASON_YEAR}" in urls[urls.index(MATCHES_URL)]


def test_user_agent_header_present():
    session = FakeSession(_happy_routes())
    load_remote(session)
    for call in session.calls:
        assert call["headers"]["User-Agent"] == config.USER_AGENT
        assert call["headers"]["Accept"] == "application/json"


def test_robots_disallow_blocks_the_run():
    session = FakeSession(_happy_routes({ROBOTS_URL: FakeResponse(200, DISALLOW_API_ROBOTS)}))
    with pytest.raises(ScrapeError) as exc:
        load_remote(session)
    assert exc.value.rule_id == "V1"


def test_robots_404_is_allowed():
    session = FakeSession(_happy_routes({ROBOTS_URL: FakeResponse(404)}))
    raw = load_remote(session)
    assert len(raw.matches) == 32


def test_robots_403_fails():
    session = FakeSession(_happy_routes({ROBOTS_URL: FakeResponse(403)}))
    with pytest.raises(ScrapeError) as exc:
        load_remote(session)
    assert exc.value.rule_id == "V1"


def test_robots_5xx_fails():
    session = FakeSession(_happy_routes({ROBOTS_URL: FakeResponse(503)}))
    with pytest.raises(ScrapeError) as exc:
        load_remote(session)
    assert exc.value.rule_id == "V1"


def test_robots_unreachable_fails():
    session = FakeSession(_happy_routes({ROBOTS_URL: requests.ConnectionError("down")}))
    with pytest.raises(ScrapeError) as exc:
        load_remote(session)
    assert exc.value.rule_id == "V1"


def test_retries_on_5xx_then_succeeds():
    session = FakeSession(
        _happy_routes(
            {MATCHES_URL: [FakeResponse(503), FakeResponse(200, _fixture_text("matches"))]}
        )
    )
    raw = load_remote(session)
    assert len(raw.matches) == 32
    match_calls = [c for c in session.calls if c["url"] == MATCHES_URL]
    assert len(match_calls) == 2


def test_retries_exhausted_raises():
    session = FakeSession(_happy_routes({MATCHES_URL: FakeResponse(500)}))
    with pytest.raises(ScrapeError) as exc:
        load_remote(session)
    assert exc.value.rule_id == "V2"
    match_calls = [c for c in session.calls if c["url"] == MATCHES_URL]
    assert len(match_calls) == 4  # 1 initial + 3 retries


def test_retries_on_connection_error_then_succeeds():
    session = FakeSession(
        _happy_routes(
            {
                MATCHES_URL: [
                    requests.ConnectionError("down"),
                    FakeResponse(200, _fixture_text("matches")),
                ]
            }
        )
    )
    raw = load_remote(session)
    assert len(raw.matches) == 32


def test_non_json_body_raises():
    session = FakeSession(
        _happy_routes({MATCHES_URL: FakeResponse(200, "<html>Cloudflare</html>")})
    )
    with pytest.raises(ScrapeError) as exc:
        load_remote(session)
    assert exc.value.rule_id == "V2"


def test_missing_data_key_raises():
    session = FakeSession(_happy_routes({MATCHES_URL: FakeResponse(200, '{"foo": [1, 2]}')}))
    with pytest.raises(ScrapeError) as exc:
        load_remote(session)
    assert exc.value.rule_id == "V2"


def test_empty_data_list_raises():
    session = FakeSession(_happy_routes({MATCHES_URL: FakeResponse(200, '{"data": []}')}))
    with pytest.raises(ScrapeError) as exc:
        load_remote(session)
    assert exc.value.rule_id == "V2"


def test_load_from_dir_reads_fixtures():
    raw = load_from_dir(FIXTURES / "season2026")
    assert len(raw.teams) == 8
    assert len(raw.matches) == 32
    assert len(raw.points) == 8


def test_stats_failure_leaves_stats_none_and_the_run_continues(capsys):
    session = FakeSession(_happy_routes({STATS_URL: FakeResponse(404)}))
    raw = load_remote(session)
    assert raw.stats is None
    assert len(raw.matches) == 32
    assert "warning: stats unavailable" in capsys.readouterr().err


def test_stats_disallowed_by_robots_is_skipped_not_fetched():
    session = FakeSession(_happy_routes({ROBOTS_URL: FakeResponse(200, DISALLOW_STATS_ROBOTS)}))
    raw = load_remote(session)
    assert raw.stats is None
    assert STATS_URL not in [c["url"] for c in session.calls]


def test_load_from_dir_without_stats_file(tmp_path):
    for name in ("teams", "matches", "points"):
        (tmp_path / f"{name}.json").write_text(_fixture_text(name))
    assert load_from_dir(tmp_path).stats is None


# --- share issues source (I1, I2) -------------------------------------------

ISSUES_FIXTURES = FIXTURES / "issues"
ISSUES_ROBOTS = f"{config.ISSUES_BASE}/robots.txt"


def _issue_url(type_id):
    return fetch.issues_url(type_id)


def _issue_routes(overrides=None):
    routes = {ISSUES_ROBOTS: FakeResponse(200, "User-agent: *\nDisallow:\n")}
    for cat in config.ISSUE_CATEGORIES:
        text = (ISSUES_FIXTURES / f"{cat.slug}.json").read_text()
        routes[_issue_url(cat.type_id)] = FakeResponse(200, text)
    routes.update(overrides or {})
    return routes


def test_issues_robots_disallow_is_i1():
    session = FakeSession(
        _issue_routes({ISSUES_ROBOTS: FakeResponse(200, "User-agent: *\nDisallow: /\n")})
    )
    with pytest.raises(ScrapeError) as exc:
        fetch.load_issues_remote(session)
    assert exc.value.rule_id == "I1"


def test_issues_html_body_is_i2():
    url = _issue_url(1)
    session = FakeSession(_issue_routes({url: FakeResponse(200, "<html>page</html>")}))
    with pytest.raises(ScrapeError) as exc:
        fetch.load_issues_remote(session)
    assert exc.value.rule_id == "I2"


def test_issues_empty_data_is_i2():
    url = _issue_url(2)
    session = FakeSession(_issue_routes({url: FakeResponse(200, '{"data": []}')}))
    with pytest.raises(ScrapeError) as exc:
        fetch.load_issues_remote(session)
    assert exc.value.rule_id == "I2"


def test_issues_retry_on_5xx_then_succeed():
    url = _issue_url(1)
    good = (ISSUES_FIXTURES / "ipo.json").read_text()
    session = FakeSession(_issue_routes({url: [FakeResponse(503), FakeResponse(200, good)]}))
    raw = fetch.load_issues_remote(session)
    assert len(raw["ipo"]) == 50
    assert [c["url"] for c in session.calls].count(url) == 2


def test_issues_requests_send_xhr_header_and_only_the_five_types():
    session = FakeSession(_issue_routes())
    fetch.load_issues_remote(session)
    data_calls = [c for c in session.calls if "existing-issues" in c["url"]]
    assert [c["url"] for c in data_calls] == [_issue_url(t) for t in (1, 2, 3, 5, 8)]
    for call in data_calls:
        assert call["headers"]["X-Requested-With"] == "XMLHttpRequest"
        assert call["headers"]["User-Agent"] == config.USER_AGENT


def test_issues_keeps_at_most_fifty_rows_per_category():
    rows = [{"n": n} for n in range(80)]
    url = _issue_url(1)
    session = FakeSession(_issue_routes({url: FakeResponse(200, json.dumps({"data": rows}))}))
    assert len(fetch.load_issues_remote(session)["ipo"]) == 50


def test_load_issues_from_dir_is_none_without_issues_subdir(tmp_path):
    assert fetch.load_issues_from_dir(tmp_path) is None


def test_load_issues_from_dir_missing_file_is_i2(tmp_path):
    (tmp_path / "issues").mkdir()
    with pytest.raises(ScrapeError) as exc:
        fetch.load_issues_from_dir(tmp_path)
    assert exc.value.rule_id == "I2"


def test_load_issues_from_dir_reads_every_category():
    raw = fetch.load_issues_from_dir(FIXTURES)
    assert {k: len(v) for k, v in raw.items()} == {
        "ipo": 50, "fpo": 23, "right-share": 50, "ipo-local": 50, "ipo-migrant": 50,
    }  # fmt: skip
