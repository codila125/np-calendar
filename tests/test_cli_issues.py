"""Issues source through the CLI: ShareSansar -> site/data/issues.json (AC-1)."""

import json
import shutil
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from scraper import cli, config, issues
from tests.fakes import FakeResponse, FakeSession

FIXTURES = Path(__file__).parent / "fixtures"
ISSUE_FIXTURES = FIXTURES / "issues"
SEASON_2026 = FIXTURES / "season2026"

NPL = config.SOURCE_BASE
ROBOTS = FakeResponse(200, "User-agent: *\nAllow: /\n")
KEYS = {
    "id", "category", "company", "symbol", "units", "price", "ratio", "issue_manager",
    "opening_date", "closing_date", "last_closing_date", "book_closure_date",
    "dates_announced", "url", "company_url",
}  # fmt: skip


def _npl_routes():
    def text(name):
        return (SEASON_2026 / f"{name}.json").read_text()

    return {
        f"{NPL}/robots.txt": ROBOTS,
        f"{NPL}/api/v1/teams": FakeResponse(200, text("teams")),
        f"{NPL}/api/v1/matches?season=2026": FakeResponse(200, text("matches")),
        f"{NPL}/api/v1/points?season=2026": FakeResponse(200, text("points")),
        f"{NPL}/api/v1/stats?season=2026": FakeResponse(200, text("stats")),
    }


def _issue_routes():
    routes = {
        f"{config.ISSUES_BASE}/robots.txt": FakeResponse(
            200, (ISSUE_FIXTURES / "robots.txt").read_text()
        )
    }
    for cat in config.ISSUE_CATEGORIES:
        url = (
            f"{config.ISSUES_BASE}/existing-issues?draw=1&start=0&length=50&type={cat.type_id}"
        )
        routes[url] = FakeResponse(200, (ISSUE_FIXTURES / f"{cat.slug}.json").read_text())
    return routes


def _from_dir_src(tmp_path):
    src = tmp_path / "src"
    shutil.copytree(SEASON_2026, src)
    shutil.copytree(ISSUE_FIXTURES, src / "issues")
    return src


def test_remote_run_publishes_five_categories_html_stripped(tmp_path):
    site = tmp_path / "site"
    session = FakeSession({**_npl_routes(), **_issue_routes()})

    assert cli.main(["--site-dir", str(site)], session=session) == 0

    data = json.loads((site / "data" / "issues.json").read_text())
    assert data["schema_version"] == 1
    assert len(data["issues"]) == 223
    counts = {}
    for item in data["issues"]:
        counts[item["category"]] = counts.get(item["category"], 0) + 1
        assert set(item) == KEYS
        assert "<" not in item["company"] + item["symbol"]
        assert ">" not in item["company"] + item["symbol"]
    assert counts == {
        "ipo": 50, "fpo": 23, "right-share": 50, "ipo-local": 50, "ipo-migrant": 50,
    }  # fmt: skip
    assert "Rapti Hydro & General Construction Limited" in {i["company"] for i in data["issues"]}

    issue_calls = [c for c in session.calls if "existing-issues" in c["url"]]
    types = {parse_qs(urlparse(c["url"]).query)["type"][0] for c in issue_calls}
    assert types == {"1", "2", "3", "5", "8"}
    assert all(c["headers"]["X-Requested-With"] == "XMLHttpRequest" for c in issue_calls)


def test_from_dir_without_issues_skips_the_source(tmp_path, capsys):
    site = tmp_path / "site"
    assert cli.main(["--from-dir", str(SEASON_2026), "--site-dir", str(site)]) == 0
    assert not (site / "data" / "issues.json").exists()
    assert "issues skipped" in capsys.readouterr().err


def test_from_dir_with_issues_writes_issues_json(tmp_path, capsys):
    site = tmp_path / "site"
    assert cli.main(["--from-dir", str(_from_dir_src(tmp_path)), "--site-dir", str(site)]) == 0
    assert "fetched issues=223 dated=218" in capsys.readouterr().out
    assert (site / "data" / "issues.json").read_text().endswith("}\n")


def test_issues_violation_exits_1_and_writes_nothing(tmp_path, capsys):
    src = _from_dir_src(tmp_path)
    path = src / "issues" / "ipo.json"
    body = json.loads(path.read_text())
    row = next(r for r in body["data"] if r["opening_date"] and r["closing_date"])
    row["closing_date"], row["opening_date"] = "2020-01-01", "2020-02-01"
    path.write_text(json.dumps(body))
    site = tmp_path / "site"
    assert cli.main(["--from-dir", str(src), "--site-dir", str(site)]) == 1
    assert "error: [I4]" in capsys.readouterr().err
    assert not site.exists()


def _row(**kw):
    base = {
        "companyid": 1, "total_units": "100.00", "issue_price": "10.00", "ratio_value": None,
        "opening_date": "2026-11-30", "closing_date": "2026-12-14", "final_date": "",
        "announcement_link": None, "issue_manager": None,
        "company": {
            "symbol": "<a href='https://www.sharesansar.com/company/x'>X</a>",
            "companyname": "<a href='https://www.sharesansar.com/company/x'>X Ltd</a>",
        },
    }  # fmt: skip
    base.update(kw)
    return base


def _norm(rows, slug="ipo"):
    return issues.normalize_issues({slug: rows})["issues"]


def test_blank_symbol_and_impossible_date_are_i3():
    blank = _row(company={"symbol": "<a href='x'> </a>", "companyname": "<a>X</a>"})
    bad_date = _row(opening_date="2026-02-30")
    assert [v.rule_id for v in issues.validate_issue_rows({"ipo": [blank]})] == ["I3"]
    assert [v.rule_id for v in issues.validate_issue_rows({"ipo": [bad_date]})] == ["I3"]


def test_doubled_announcement_link_falls_back_to_company_url():
    good = "https://www.sharesansar.com/announcementdetail/a"
    doubled = good + good
    [item] = _norm([_row(announcement_link=doubled)])
    assert item["url"] == "https://www.sharesansar.com/company/x"
    [item] = _norm([_row(announcement_link=good)])
    assert item["url"] == good
    [item] = _norm([_row(company={"symbol": "S", "companyname": "N"})])
    assert item["url"] == "https://www.sharesansar.com/existing-issues"


def test_ampersand_kept_and_entities_decoded():
    name = "<a href='https://www.sharesansar.com/company/x'>Rapti &amp; Co &lt;1&gt; &</a>"
    [item] = _norm([_row(company={"symbol": "R", "companyname": name})])
    assert item["company"] == "Rapti & Co <1> &"


def test_same_company_and_units_gets_dated_suffix_for_the_later_row():
    older = _row(companyid=527, total_units="5670000.00", opening_date="2020-10-30",
                 closing_date="2020-11-10")  # fmt: skip
    newer = _row(companyid=527, total_units="5670000.00", opening_date="2021-06-03",
                 closing_date="2021-06-20")  # fmt: skip
    ids = [i["id"] for i in _norm([newer, older], "right-share")]
    assert sorted(ids) == ["right-share-527-5670000", "right-share-527-5670000-20210603"]
    assert issues.validate_issues(issues.normalize_issues({"right-share": [newer, older]})) == []


def test_units_key_drops_fractional_trailing_zeros():
    ids = [
        _norm([_row(companyid=n, total_units=u)])[0]["id"]
        for n, u in [(1, "600000.00"), (2, "24851236.18"), (3, "18512792.20")]
    ]
    assert ids == ["ipo-1-600000", "ipo-2-24851236.18", "ipo-3-18512792.2"]


def test_undated_issue_is_kept_and_marked():
    [item] = _norm([_row(opening_date="", closing_date="", final_date="2026-11-27")])
    assert item["dates_announced"] is False
    assert item["opening_date"] is None and item["last_closing_date"] == "2026-11-27"


def test_right_share_final_date_is_book_closure():
    [item] = _norm([_row(final_date="2026-12-01", ratio_value=" 1:1 ")], "right-share")
    assert item["book_closure_date"] == "2026-12-01"
    assert item["last_closing_date"] is None
    assert item["ratio"] == "1:1"


def test_control_char_and_long_text_are_i6():
    data = issues.normalize_issues({"ipo": [_row(issue_manager="a\x07b")]})
    assert [v.rule_id for v in issues.validate_issues(data)] == ["I6"]
