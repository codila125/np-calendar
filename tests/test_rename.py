"""AC-6: the project is np-calendar everywhere a reader can see, NPL identifiers are unchanged."""

import re
from pathlib import Path

from scraper import config

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
OLD_REF = re.compile(r"codila125\.github\.io/npl(?!-)|github\.com/codila125/npl(?!-)")


def test_site_feeds_and_bot_use_np_calendar_name():
    assert config.SITE_URL == "https://codila125.github.io/np-calendar/"
    assert config.USER_AGENT == (
        "np-calendar-bot/1.0 (+https://github.com/codila125/np-calendar)"
    )
    assert config.PRODID == "-//codila125//np-calendar//EN"

    html = (SITE / "index.html").read_text()
    assert "np-calendar" in re.search(r"<title>(.*?)</title>", html).group(1)
    assert "np-calendar" in re.search(r"<h1[^>]*>(.*?)</h1>", html).group(1)
    assert (ROOT / "README.md").read_text().splitlines()[0] == "# np-calendar"

    feeds = sorted((SITE / "calendar").glob("*.ics"))
    assert len(feeds) == 9 + 8
    for feed in feeds:
        assert f"PRODID:{config.PRODID}\r\n".encode() in feed.read_bytes(), feed.name

    scanned = [ROOT / "worker" / "live.js", ROOT / "README.md"]
    for folder in ("site", "scraper", ".github"):
        files = (ROOT / folder).rglob("*")
        scanned += [p for p in files if p.is_file() and "__pycache__" not in p.parts]
    for path in scanned:
        assert not OLD_REF.search(path.read_text()), f"old name in {path.relative_to(ROOT)}"

    npl = (SITE / "calendar" / "npl.ics").read_bytes()
    for n in range(1, 33):
        assert f"UID:npl-2026-m{n:02d}@codila125.github.io\r\n".encode() in npl
    assert (SITE / "calendar" / "lumbini-lions.ics").is_file()
    assert len([p for p in feeds if p.stem not in config.ISSUE_FEEDS]) == 9
