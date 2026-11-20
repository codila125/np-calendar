"""Static proof for the share-issues tab shell (AC-5): markup, script and tokens."""

import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

from scraper.issues import normalize_issues
from tests.test_site_contrast import _contrast

SITE = Path(__file__).resolve().parent.parent / "site"
FEEDS = ["issues", "ipo", "fpo", "right-share", "ipo-local", "ipo-migrant"]
CATS = ["ipo", "fpo", "right-share", "ipo-local", "ipo-migrant"]


class Node:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent = tag, dict(attrs), parent
        self.children, self.text = [], ""

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()

    def inside(self, ancestor_id):
        node = self.parent
        while node:
            if node.attrs.get("id") == ancestor_id:
                return True
            node = node.parent
        return False

    def all_text(self):
        return self.text + "".join(c.all_text() for c in self.children)


class Parser(HTMLParser):
    VOID = {"meta", "link", "img", "br", "input"}

    def __init__(self):
        super().__init__()
        self.root = Node("root", [], None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.cur)
        self.cur.children.append(node)
        if tag not in self.VOID:
            self.cur = node

    def handle_endtag(self, tag):
        node = self.cur
        while node.parent and node.tag != tag:
            node = node.parent
        if node.parent:
            self.cur = node.parent

    def handle_data(self, data):
        self.cur.text += data


def _dom():
    parser = Parser()
    parser.feed((SITE / "index.html").read_text())
    nodes = list(parser.root.walk())
    return nodes, {n.attrs["id"]: n for n in nodes if "id" in n.attrs}


def test_tabs_markup_panels_feeds_and_states():
    html = (SITE / "index.html").read_text()
    nodes, by_id = _dom()

    tablists = [n for n in nodes if n.attrs.get("role") == "tablist"]
    assert len(tablists) == 1 and tablists[0].attrs.get("aria-label")
    tabs = [n for n in nodes if n.attrs.get("role") == "tab"]
    assert [t.all_text().strip() for t in tabs] == ["Share issues", "NPL"]
    for tab in tabs:
        assert tab.parent is tablists[0]
    issues_tab, npl_tab = by_id["tab-issues"], by_id["tab-npl"]
    issues_panel, npl_panel = by_id["panel-issues"], by_id["panel-npl"]
    assert issues_tab.attrs["aria-controls"] == "panel-issues"
    assert npl_tab.attrs["aria-controls"] == "panel-npl"
    assert issues_panel.attrs["aria-labelledby"] == "tab-issues"
    assert npl_panel.attrs["aria-labelledby"] == "tab-npl"
    assert issues_panel.attrs["role"] == npl_panel.attrs["role"] == "tabpanel"
    assert issues_tab.attrs["aria-selected"] == "true"
    assert npl_tab.attrs["aria-selected"] == "false"
    assert npl_tab.attrs["tabindex"] == "-1"
    assert "hidden" in npl_panel.attrs and "hidden" not in issues_panel.attrs

    assert any(n.tag == "nav" and n.attrs.get("aria-label") == "Sections"
               and n.inside("panel-npl") for n in nodes)
    for ident in ("standings", "stats", "schedule", "calendar", "live"):
        assert by_id[ident].inside("panel-npl"), ident
    assert by_id["issues-status"].attrs["role"] == "status"
    assert "Loading share issues…" in by_id["issues-status"].all_text()

    assert "<title>np-calendar" in html
    assert "<h1>np-calendar</h1>" in html
    assert '<script src="issues.js" defer></script>' in html
    assert html.index("Skip to content") < html.index("<header")

    rows = [n for n in by_id["panel-issues"].walk()
            if n.tag == "li" and "calendar-row" in n.attrs.get("class", "")]
    assert len(rows) == 6
    for row, feed in zip(rows, FEEDS, strict=True):
        url = f"https://codila125.github.io/np-calendar/calendar/{feed}.ics"
        hrefs = [n.attrs.get("href", "") for n in row.walk()]
        assert f"webcal://codila125.github.io/np-calendar/calendar/{feed}.ics" in hrefs
        assert any(h.startswith("https://calendar.google.com/calendar/r?cid=")
                   and f"{feed}.ics" in h for h in hrefs)
        assert any(n.tag == "button" and n.attrs.get("data-url") == url
                   for n in row.walk())
    assert "codila125.github.io/npl/" not in html

    js = (SITE / "issues.js").read_text()
    for needle in ("ArrowLeft", "ArrowRight", "Home", "End", "hashchange",
                   "replaceState", "Loading share issues…",
                   "Couldn't load share issues.", "Retry",
                   "No share issues published yet."):
        assert needle in js, needle

    css = (SITE / "style.css").read_text()
    blocks = [css[css.index(m):css.index("}", css.index(m))]
              for m in ("/* tokens:light */", "/* tokens:dark */")]
    prefers = css[css.index("@media (prefers-color-scheme: dark)"):]
    prefers = prefers[:prefers.index("}")]

    def cat_tokens(block):
        return {c: re.search(rf"--cat-{c}\s*:\s*(#[0-9a-fA-F]{{6}})", block) for c in CATS}

    light, dark, pdark = (cat_tokens(b) for b in (*blocks, prefers))
    for tokens in (light, dark, pdark):
        assert all(tokens.values())
    bg_light = re.search(r"--bg:\s*(#\w+)", blocks[0]).group(1)
    bg_dark = re.search(r"--bg:\s*(#\w+)", blocks[1]).group(1)
    for c in CATS:
        assert _contrast(light[c].group(1), bg_light) >= 4.5, c
        assert _contrast(dark[c].group(1), bg_dark) >= 4.5, c
        assert pdark[c].group(1) == dark[c].group(1), c


NODE_SCRIPT = """
const h = require(process.argv[1]);
const data = JSON.parse(require("fs").readFileSync(process.argv[2], "utf8"));
const ids = (list) => list.map((i) => i.category + ":" + i.symbol).sort();
const g = h.groupIssues(data, "2026-11-20");
const mid = h.groupIssues(data, "2026-11-27");
console.log(JSON.stringify({
  hash: [h.parseHash("#npl"), h.parseHash("#standings"), h.parseHash(""), h.parseHash("#x")],
  weeks: h.monthWeeks(2026, 10),
  nov30: ids(h.issuesOn(data, "2026-11-30")),
  nov25: ids(h.issuesOn(data, "2026-11-25")),
  dec3: ids(h.issuesOn(data, "2026-12-03")),
  dec4: ids(h.issuesOn(data, "2026-12-04")),
  open20: ids(g.open), upcoming20: ids(g.upcoming), undated20: ids(g.undated),
  open27: ids(mid.open), upcoming27: ids(mid.upcoming),
}));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_issue_logic_in_node(tmp_path):
    fixtures = Path(__file__).parent / "fixtures" / "issues"
    names = {"ipo": "ipo", "fpo": "fpo", "right-share": "right-share",
             "ipo-local": "ipo-local", "ipo-migrant": "ipo-migrant"}
    raw = {slug: json.loads((fixtures / f"{name}.json").read_text())["data"]
           for slug, name in names.items()}
    data_file = tmp_path / "issues.json"
    data_file.write_text(json.dumps(normalize_issues(raw)))
    result = subprocess.run(
        [shutil.which("node"), "-e", NODE_SCRIPT, str(SITE / "issues.js"), str(data_file)],
        capture_output=True, text=True, check=True)
    out = json.loads(result.stdout)

    assert out["hash"] == ["npl", "npl", "issues", "issues"]
    weeks = out["weeks"]
    assert len(weeks) == 5 and all(len(w) == 7 for w in weeks)
    assert weeks[0][0] == "2026-11-01"  # November 2026 starts on a Sunday
    assert weeks[4][:2] == ["2026-11-29", "2026-11-30"] and weeks[4][2:] == [None] * 5

    assert out["nov30"] == ["ipo-local:AELTD", "ipo-local:KPL", "ipo-migrant:AELTD",
                            "ipo-migrant:KPL"]
    assert out["nov25"] == []
    # the closing day is inclusive: migrant AELTD closes on Dec 3
    assert out["dec3"] == ["ipo-local:AELTD", "ipo-local:KPL", "ipo-migrant:AELTD"]
    assert out["dec4"] == ["ipo-local:AELTD", "ipo-local:KPL"]
    assert out["open20"] == []
    assert out["upcoming20"] == ["ipo-local:AELTD", "ipo-local:KPL", "ipo-migrant:AELTD",
                                 "ipo-migrant:KPL"]
    assert len(out["undated20"]) == 5
    assert out["open27"] == ["ipo-local:KPL", "ipo-migrant:KPL"]
    assert out["upcoming27"] == ["ipo-local:AELTD", "ipo-migrant:AELTD"]
