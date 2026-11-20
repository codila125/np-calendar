"""Issues source through the CLI: ShareSansar -> site/data/issues.json (AC-1)."""

import json
import re
import shutil
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from icalendar import Calendar

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
    "dates_announced", "url", "company_url", "listing_date",
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
        url = f"{config.ISSUES_BASE}/existing-issues?draw=1&start=0&length=50&type={cat.type_id}"
        routes[url] = FakeResponse(200, (ISSUE_FIXTURES / f"{cat.slug}.json").read_text())
    return routes


def _from_dir_src(tmp_path):
    src = tmp_path / "src"
    shutil.copytree(SEASON_2026, src)
    shutil.copytree(ISSUE_FIXTURES, src / "issues")
    return src


def test_remote_run_publishes_seven_categories_html_stripped(tmp_path):
    site = tmp_path / "site"
    session = FakeSession({**_npl_routes(), **_issue_routes()})

    assert cli.main(["--site-dir", str(site)], session=session) == 0

    data = json.loads((site / "data" / "issues.json").read_text())
    assert data["schema_version"] == 1
    assert len(data["issues"]) == 323
    counts = {}
    for item in data["issues"]:
        counts[item["category"]] = counts.get(item["category"], 0) + 1
        assert set(item) == KEYS
        assert "<" not in item["company"] + item["symbol"]
        assert ">" not in item["company"] + item["symbol"]
    assert counts == {
        "ipo": 50, "fpo": 23, "right-share": 50, "ipo-local": 50, "ipo-migrant": 50,
        "mutual-fund": 50, "debenture": 50,
    }  # fmt: skip
    assert [c["slug"] for c in data["categories"]][-2:] == ["mutual-fund", "debenture"]
    assert "Rapti Hydro & General Construction Limited" in {i["company"] for i in data["issues"]}

    issue_calls = [c for c in session.calls if "existing-issues" in c["url"]]
    types = {parse_qs(urlparse(c["url"]).query)["type"][0] for c in issue_calls}
    assert types == {"1", "2", "3", "4", "5", "7", "8"}  # QII (9) stays excluded
    assert all(c["headers"]["X-Requested-With"] == "XMLHttpRequest" for c in issue_calls)

    by_id = {i["id"]: i for i in data["issues"]}
    expected = (("mutual-fund", "Mutual funds:", 50), ("debenture", "Debentures:", 43))
    for slug, prefix, count in expected:
        events = [
            e
            for e in _events(site / "calendar" / f"{slug}.ics")
            if "-listing@" not in str(e["UID"])
        ]
        assert len(events) == count
        assert all(str(e["SUMMARY"]).startswith(prefix) for e in events)
        in_all = {str(e["UID"]) for e in _events(site / "calendar" / "issues.ics")}
        assert {str(e["UID"]) for e in events} <= in_all
    raw = json.loads((ISSUE_FIXTURES / "debenture.json").read_text())["data"]
    sentinel_symbols = {
        re.sub(r"<[^>]+>", "", r["company"]["symbol"])
        for r in raw
        if r["opening_date"] == "-0001-11-30"
    }
    assert len(sentinel_symbols) == 6
    sentinel = [i for i in data["issues"] if i["symbol"] in sentinel_symbols]
    assert len(sentinel) == 6
    for item in sentinel:
        assert item["dates_announced"] is False
        assert item["opening_date"] is None and item["listing_date"] is None
    csb = by_id["debenture-1254-na"]
    assert csb["symbol"] == "CSB2084" and csb["units"] is None


def test_from_dir_without_issues_skips_the_source(tmp_path, capsys):
    site = tmp_path / "site"
    assert cli.main(["--from-dir", str(SEASON_2026), "--site-dir", str(site)]) == 0
    assert not (site / "data" / "issues.json").exists()
    assert "issues skipped" in capsys.readouterr().err


def test_from_dir_with_issues_writes_issues_json(tmp_path, capsys):
    site = tmp_path / "site"
    assert cli.main(["--from-dir", str(_from_dir_src(tmp_path)), "--site-dir", str(site)]) == 0
    assert "fetched issues=323 dated=311" in capsys.readouterr().out
    assert (site / "data" / "issues.json").read_text().endswith("}\n")


def test_undated_listed_not_in_feeds_and_reversed_dates_write_nothing(tmp_path, capsys):
    src = _from_dir_src(tmp_path)
    stats = (src / "stats.json").read_bytes()
    (src / "stats.json").unlink()  # first run publishes NPL without stats
    site = tmp_path / "site"
    assert cli.main(["--from-dir", str(src), "--site-dir", str(site)]) == 0
    data = json.loads((site / "data" / "issues.json").read_text())
    undated = [i for i in data["issues"] if not i["dates_announced"]]
    assert len(undated) == 12
    assert sum(1 for i in undated if i["category"] == "ipo") == 3
    assert sum(1 for i in undated if i["category"] == "right-share") == 2
    for name in config.ISSUE_FEEDS:
        text = (site / "calendar" / f"{name}.ics").read_text()
        assert not any(f"UID:issue-{i['id']}@" in text for i in undated)

    rels = ["data/issues.json", *(f"calendar/{n}.ics" for n in config.ISSUE_FEEDS)]
    before = {rel: (site / rel).read_bytes() for rel in rels}
    npl_before = (site / "data" / "npl.json").read_bytes()
    path = src / "issues" / "ipo.json"
    body = json.loads(path.read_text())
    row = next(r for r in body["data"] if r["opening_date"] and r["closing_date"])
    row["closing_date"], row["opening_date"] = "2020-01-01", "2020-02-01"
    path.write_text(json.dumps(body))
    (src / "stats.json").write_bytes(stats)  # NPL changes too, so we can see it still publishes
    capsys.readouterr()

    assert cli.main(["--from-dir", str(src), "--site-dir", str(site)]) == 3

    assert "error: [I4]" in capsys.readouterr().err
    assert {rel: (site / rel).read_bytes() for rel in rels} == before
    assert (site / "data" / "npl.json").read_bytes() != npl_before


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


# --- issue feeds (AC-2) ----------------------------------------------------------------

UID_RE = re.compile(
    r"^issue-[a-z-]+-\d+-([\d.]+|na)(-\d{8}|-tba)?(-listing|-bookclosure)?@codila125\.github\.io$"
)


def _feeds(site):
    cal = site / "calendar"
    return {name: cal / f"{name}.ics" for name in config.ISSUE_FEEDS}


def _events(path):
    cal = Calendar.from_ical(path.read_bytes())
    return [c for c in cal.walk() if c.name == "VEVENT"]


def _snapshot(site):
    return {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in _feeds(site).values()}


def test_issue_feeds_are_all_day_alarmed_stable_and_reproducible(tmp_path, capsys):
    src = _from_dir_src(tmp_path)
    site = tmp_path / "site"
    assert cli.main(["--from-dir", str(src), "--site-dir", str(site)]) == 0
    feeds = _feeds(site)
    assert all(p.is_file() for p in feeds.values())

    data = json.loads((site / "data" / "issues.json").read_text())
    by_uid = {f"issue-{i['id']}@codila125.github.io": i for i in data["issues"]}
    all_events = _events(feeds["issues"])
    assert len(all_events) == 644
    assert all(UID_RE.match(str(e["UID"])) for e in all_events)
    app_re = re.compile(r"^issue-.*(?<!-listing)(?<!-bookclosure)@")

    def application(path):
        return [e for e in _events(path) if app_re.match(str(e["UID"]))]

    events = application(feeds["issues"])
    assert len(events) == 311
    counts = [len(application(feeds[c.slug])) for c in config.ISSUE_CATEGORIES]
    assert counts == [47, 23, 48, 50, 50, 50, 43]
    assert [len(_events(feeds[c.slug])) for c in config.ISSUE_CATEGORIES] == [
        94, 46, 141, 97, 97, 87, 82,
    ]  # fmt: skip
    for slug in (c.slug for c in config.ISSUE_CATEGORIES):
        assert {str(e["UID"]) for e in _events(feeds[slug])} <= {str(e["UID"]) for e in all_events}

    for event in events:
        uid = str(event["UID"])
        assert UID_RE.match(uid), uid
        issue = by_uid[uid]
        opening = date.fromisoformat(issue["opening_date"])
        closing = date.fromisoformat(issue["closing_date"])
        start, end = event["DTSTART"].dt, event["DTEND"].dt
        assert type(start) is date and type(end) is date
        assert start == opening and end == closing + timedelta(days=1)
        desc = str(event["DESCRIPTION"])
        assert ("Price: Rs" in desc) == bool(issue["price"])
        assert ("Units:" in desc) == (issue["units"] is not None)
        assert "sharesansar" not in desc.lower() and "URL" not in event
        if issue["issue_manager"]:
            assert "Issue manager:" in desc
        alarms = [c for c in event.subcomponents if c.name == "VALARM"]
        assert len(alarms) == 1
        assert str(alarms[0]["ACTION"]) == "DISPLAY"
        trigger = alarms[0]["TRIGGER"].dt
        assert trigger == datetime(opening.year, opening.month, opening.day, 3, 15, tzinfo=UTC)
    undated = [u for u, i in by_uid.items() if not i["dates_announced"]]
    assert len(undated) == 12
    assert not {str(e["UID"]) for e in events} & set(undated)

    before = _snapshot(site)
    capsys.readouterr()
    assert cli.main(["--from-dir", str(src), "--site-dir", str(site)]) == 0
    assert "no changes" in capsys.readouterr().out
    assert _snapshot(site) == before

    path = src / "issues" / "ipo.json"
    body = json.loads(path.read_text())
    row = next(r for r in body["data"] if r["opening_date"] and r["closing_date"])
    old_uid = f"issue-ipo-{row['companyid']}-"
    row["closing_date"] = "2099-01-01"
    path.write_text(json.dumps(body))
    assert cli.main(["--from-dir", str(src), "--site-dir", str(site)]) == 0
    new_uids = {str(e["UID"]) for e in application(feeds["issues"])}
    old_uids = {str(e["UID"]) for e in events}
    assert new_uids == old_uids
    assert any(u.startswith(old_uid) for u in new_uids)


def test_issues_skipped_or_failed_run_keeps_existing_issue_feeds(tmp_path):
    src = _from_dir_src(tmp_path)
    site = tmp_path / "site"
    assert cli.main(["--from-dir", str(src), "--site-dir", str(site)]) == 0
    before = _snapshot(site)
    assert cli.main(["--from-dir", str(SEASON_2026), "--site-dir", str(site)]) == 0
    assert _snapshot(site) == before


# --- listing-day and book-closure events (AC-1, AC-2) ---------------------------------

DOMAIN = "codila125.github.io"


def _alarm_triggers(event):
    alarms = [c for c in event.subcomponents if c.name == "VALARM"]
    assert len(alarms) == 1 and str(alarms[0]["ACTION"]) == "DISPLAY"
    return alarms[0]["TRIGGER"].dt


def _by_uid(path):
    return {str(e["UID"]): e for e in _events(path)}


def test_listing_day_events_in_own_feed_and_issues_ics(tmp_path, capsys):
    src = _from_dir_src(tmp_path)
    path = src / "issues" / "ipo.json"
    body = json.loads(path.read_text())
    dated = [r for r in body["data"] if r["opening_date"] and r["listing_date"]]
    before_opening = date.fromisoformat(dated[0]["opening_date"]) - timedelta(days=1)
    dated[0]["listing_date"] = before_opening.isoformat()
    dated[1]["listing_date"] = ""
    dated[2]["listing_date"] = dated[2]["opening_date"]  # boundary: kept
    dated[3]["closing_date"] = ""  # opening known, closing not: still lists
    path.write_text(json.dumps(body))
    site = tmp_path / "site"

    assert cli.main(["--from-dir", str(src), "--site-dir", str(site)]) == 0

    data = json.loads((site / "data" / "issues.json").read_text())
    feeds = _feeds(site)
    all_events = _by_uid(feeds["issues"])
    app_uids = {f"issue-{i['id']}@{DOMAIN}" for i in data["issues"] if i["dates_announced"]}
    assert {u for u in all_events if "-listing@" not in u and "-bookclosure@" not in u} == app_uids

    listed = [i for i in data["issues"] if i["listing_date"]]
    raw: dict[tuple, set] = {}
    for f in (src / "issues").glob("*.json"):
        for r in json.loads(f.read_text())["data"]:
            key = (f.stem, r["companyid"], issues._units_key(r["total_units"]))
            raw.setdefault(key, set()).add(r["listing_date"] or None)
    for issue in listed:
        prefixes = [
            k for k in raw
            if issue["id"] == f"{k[0]}-{k[1]}-{k[2]}"
            or issue["id"].startswith(f"{k[0]}-{k[1]}-{k[2]}-")
        ]  # fmt: skip
        assert prefixes
        assert any(issue["listing_date"] in raw[k] for k in prefixes)  # equals the source value

        uid = f"issue-{issue['id']}-listing@{DOMAIN}"
        assert uid != f"issue-{issue['id']}@{DOMAIN}"
        listing = date.fromisoformat(issue["listing_date"])
        for name in ("issues", issue["category"]):
            event = _by_uid(feeds[name])[uid]
            assert str(event["SUMMARY"]) == f"Lists today: {issue['company']} ({issue['symbol']})"
            assert type(event["DTSTART"].dt) is date and event["DTSTART"].dt == listing
            assert event["DTEND"].dt == listing + timedelta(days=1)
            assert _alarm_triggers(event) == datetime(
                listing.year, listing.month, listing.day, 3, 15, tzinfo=UTC
            )
        for name, path_ in feeds.items():
            if name not in ("issues", issue["category"]):
                assert uid not in _by_uid(path_)
    # the two mutated rows publish no listing event anywhere and no `listing_date`
    mutated = [dated[0]["companyid"], dated[1]["companyid"]]
    for cid in mutated:
        ids = [i for i in data["issues"] if i["id"].startswith(f"ipo-{cid}-")]
        assert ids and all(i["listing_date"] is None for i in ids)
        assert not any(f"issue-ipo-{cid}-" in u and "-listing@" in u for u in all_events)
    for row in (dated[2], dated[3]):
        ids = [
            i for i in data["issues"]
            if i["id"].startswith(f"ipo-{row['companyid']}-")
            and i["opening_date"] == row["opening_date"]
        ]  # fmt: skip
        assert ids
        for issue in ids:
            assert issue["listing_date"] == row["listing_date"]
            uid = f"issue-{issue['id']}-listing@{DOMAIN}"
            assert uid in _by_uid(feeds["issues"]) and uid in _by_uid(feeds["ipo"])
    assert dated[3]["closing_date"] == ""
    counts = [
        sum(1 for u in _by_uid(feeds[c.slug]) if u.endswith(f"-listing@{DOMAIN}"))
        for c in config.ISSUE_CATEGORIES
    ]
    assert counts == [47 - 2, 23, 45, 47, 47, 37, 39]

    snapshot = _snapshot(site)
    capsys.readouterr()
    assert cli.main(["--from-dir", str(src), "--site-dir", str(site)]) == 0
    assert "no changes" in capsys.readouterr().out
    assert _snapshot(site) == snapshot


def test_right_share_book_closure_event_with_three_day_alarm(tmp_path):
    site = tmp_path / "site"
    assert cli.main(["--from-dir", str(_from_dir_src(tmp_path)), "--site-dir", str(site)]) == 0
    data = json.loads((site / "data" / "issues.json").read_text())
    feeds = _feeds(site)
    right = [i for i in data["issues"] if i["category"] == "right-share"]
    closing = [i for i in right if i["book_closure_date"]]
    assert len(closing) == 48

    for issue in closing:
        uid = f"issue-{issue['id']}-bookclosure@{DOMAIN}"
        bc = date.fromisoformat(issue["book_closure_date"])
        for name in ("issues", "right-share"):
            event = _by_uid(feeds[name])[uid]
            assert str(event["SUMMARY"]) == f"Book closure: {issue['company']} ({issue['symbol']})"
            assert event["DTSTART"].dt == bc and event["DTEND"].dt == bc + timedelta(days=1)
            desc = str(event["DESCRIPTION"])
            assert "must hold" in desc and "T+2" in desc and "3 trading days" in desc
            assert (f"Ratio: {issue['ratio']}" in desc) == bool(issue["ratio"])
            if not issue["ratio"]:
                assert "Ratio:" not in desc
            first = bc - timedelta(days=3)
            assert _alarm_triggers(event) == datetime(
                first.year, first.month, first.day, 3, 15, tzinfo=UTC
            )
        for name, path in feeds.items():
            if name not in ("issues", "right-share"):
                assert uid not in _by_uid(path)
    assert sum("-bookclosure@" in u for u in _by_uid(feeds["issues"])) == 48
    assert sum("-bookclosure@" in u for u in _by_uid(feeds["right-share"])) == 48

    nica = next(i for i in right if i["symbol"] == "NICA")
    assert nica["opening_date"] is None
    event = _by_uid(feeds["right-share"])[f"issue-{nica['id']}-bookclosure@{DOMAIN}"]
    assert event["DTSTART"].dt == date(2026, 11, 27)
    assert _alarm_triggers(event) == datetime(2026, 11, 24, 3, 15, tzinfo=UTC)
    without = [i for i in right if not i["book_closure_date"]]
    assert len(without) == 2
    for issue in without:
        assert not any(issue["id"] in u and "-bookclosure@" in u for u in _by_uid(feeds["issues"]))
