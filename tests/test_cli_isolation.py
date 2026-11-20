"""Source isolation (AC-4, ADR 0005): one source failing never blocks the other."""

import json
import shutil
from pathlib import Path

import pytest
import requests

from scraper import cli, config
from tests.fakes import FakeResponse, FakeSession
from tests.test_cli_issues import _issue_routes, _npl_routes

FIXTURES = Path(__file__).parent / "fixtures"


def _snapshot(site):
    files = (p for p in sorted(site.rglob("*")) if p.is_file())
    return {str(p.relative_to(site)): p.read_bytes() for p in files}


def _issue_part(snap):
    return {k: v for k, v in snap.items() if k == "data/issues.json" or "calendar/" in k and
            k.rsplit("/", 1)[1] in {f"{n}.ics" for n in config.ISSUE_FEEDS}}  # fmt: skip


def _npl_part(snap):
    issue = _issue_part(snap)
    return {k: v for k, v in snap.items() if k not in issue}


def _seed(tmp_path, *, stale):
    """A previous good run whose NPL stats (stale='npl') or issues (stale='issues') differ."""
    src = tmp_path / "seed"
    shutil.copytree(FIXTURES / "season2026", src)
    shutil.copytree(FIXTURES / "issues", src / "issues")
    if stale == "npl":
        (src / "stats.json").unlink()
    else:
        path = src / "issues" / "ipo.json"
        body = json.loads(path.read_text())
        body["data"] = body["data"][:-1]
        path.write_text(json.dumps(body))
    site = tmp_path / "site"
    assert cli.main(["--from-dir", str(src), "--site-dir", str(site)]) == 0
    return site


def _issue_url(type_id):
    return f"{config.ISSUES_BASE}/existing-issues?draw=1&start=0&length=50&type={type_id}"


def _break_issues(kind, routes):
    if kind == "connection":
        routes[_issue_url(1)] = requests.ConnectionError("down")
    elif kind == "robots":
        disallow = FakeResponse(200, "User-agent: *\nDisallow: /\n")
        routes[f"{config.ISSUES_BASE}/robots.txt"] = disallow
    elif kind == "html":
        routes[_issue_url(1)] = FakeResponse(200, "<html>blocked</html>")


def _break_npl(routes):
    url = f"{config.SOURCE_BASE}/api/v1/matches?season=2026"
    body = json.loads(routes[url].text)
    body["data"] = body["data"][:-1]
    routes[url] = FakeResponse(200, json.dumps(body))


@pytest.mark.parametrize(
    ("kind", "rule"),
    [("connection", "I2"), ("robots", "I1"), ("html", "I2")],
)
def test_each_source_failure_keeps_its_files_and_the_other_source_refreshes(
    tmp_path, capsys, kind, rule
):
    site = _seed(tmp_path, stale="npl")
    before = _snapshot(site)
    routes = {**_npl_routes(), **_issue_routes()}
    _break_issues(kind, routes)
    capsys.readouterr()

    assert cli.main(["--site-dir", str(site)], session=FakeSession(routes)) == 3

    after = _snapshot(site)
    assert _issue_part(after) == _issue_part(before)  # kept, none deleted
    assert _npl_part(after) != _npl_part(before)  # NPL refreshed (stats now present)
    err = capsys.readouterr().err
    assert f"[{rule}]" in err
    assert "error: issues source failed; kept the published issues data and feeds" in err


def test_npl_failure_keeps_npl_files_and_issues_refresh(tmp_path, capsys):
    site = _seed(tmp_path, stale="issues")
    before = _snapshot(site)
    routes = {**_npl_routes(), **_issue_routes()}
    _break_npl(routes)
    capsys.readouterr()

    assert cli.main(["--site-dir", str(site)], session=FakeSession(routes)) == 3

    after = _snapshot(site)
    assert _npl_part(after) == _npl_part(before)  # team feeds survive, no pruning
    assert _issue_part(after) != _issue_part(before)
    err = capsys.readouterr().err
    assert "[V5]" in err
    assert "error: npl source failed; kept the published NPL data and feeds" in err


def test_both_sources_failing_exits_1_and_writes_nothing(tmp_path, capsys):
    site = _seed(tmp_path, stale="npl")
    before = _snapshot(site)
    routes = {**_npl_routes(), **_issue_routes()}
    _break_npl(routes)
    _break_issues("connection", routes)

    assert cli.main(["--site-dir", str(site)], session=FakeSession(routes)) == 1

    assert _snapshot(site) == before
    err = capsys.readouterr().err
    assert "[V5]" in err
    assert "[I2]" in err


def test_issues_skipped_with_failing_npl_exits_1(tmp_path):
    src = tmp_path / "src"
    shutil.copytree(FIXTURES / "season2026", src)
    (src / "teams.json").unlink()
    assert cli.main(["--from-dir", str(src), "--site-dir", str(tmp_path / "site")]) == 1
    assert not (tmp_path / "site").exists()
