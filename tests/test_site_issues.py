"""Static proof for the share-issues tab shell (AC-5): markup, script and tokens."""

import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

from scraper.issues import normalize_issues
from scraper.issues_ics import format_amount
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
    assert [t.all_text().strip() for t in tabs] == ["Stocks", "NPL"]
    for tab in tabs:
        assert tab.parent is tablists[0]
    issues_tab, npl_tab = by_id["tab-stocks"], by_id["tab-npl"]
    issues_panel, npl_panel = by_id["panel-stocks"], by_id["panel-npl"]
    assert issues_tab.attrs["aria-controls"] == "panel-stocks"
    assert npl_tab.attrs["aria-controls"] == "panel-npl"
    assert issues_panel.attrs["aria-labelledby"] == "tab-stocks"
    assert npl_panel.attrs["aria-labelledby"] == "tab-npl"
    assert issues_panel.attrs["role"] == npl_panel.attrs["role"] == "tabpanel"
    assert issues_tab.attrs["aria-selected"] == "true"
    assert npl_tab.attrs["aria-selected"] == "false"
    assert npl_tab.attrs["tabindex"] == "-1"
    assert "hidden" in npl_panel.attrs and "hidden" not in issues_panel.attrs
    # Panels are plain containers, never <section>: the numbered section grid in
    # style.css would otherwise indent the whole panel and shift the numbering.
    assert issues_panel.tag == npl_panel.tag == "div"
    # Stocks mirrors the NPL tab: a numbered section nav, then one section per entry.
    stocks_nav = [n for n in nodes if n.tag == "nav"
                  and n.attrs.get("aria-label") == "Stocks sections"]
    assert len(stocks_nav) == 1 and stocks_nav[0].parent is issues_panel
    links = [n.attrs["href"] for n in stocks_nav[0].walk() if n.tag == "a"]
    assert links == ["#stocks-calendar", "#stocks-issues", "#stocks-subscribe"]
    for href, heading in zip(links, ("Calendar", "Issues", "Subscribe"), strict=True):
        sec = by_id[href[1:]]
        assert sec.tag == "section" and sec.parent is issues_panel, href
        assert not [n for n in sec.walk() if n is not sec and n.tag == "section"], href
        assert by_id[f"{href[1:]}-heading"].all_text().strip() == heading
    assert by_id["issues-month"].inside("stocks-calendar")
    assert by_id["issues-list"].inside("stocks-issues")
    assert by_id["issues-feed-list"].inside("stocks-subscribe")

    assert any(n.tag == "nav" and n.attrs.get("aria-label") == "Sections"
               and n.inside("panel-npl") for n in nodes)
    for ident in ("standings", "stats", "schedule", "calendar", "live"):
        assert by_id[ident].inside("panel-npl"), ident
    assert by_id["issues-status"].attrs["role"] == "status"
    assert "Loading stock issues…" in by_id["issues-status"].all_text()

    assert "<title>np-calendar" in html
    assert "<h1>np-calendar</h1>" in html
    assert '<script src="issues.js" defer></script>' in html
    assert html.index("Skip to content") < html.index("<header")

    rows = [n for n in by_id["panel-stocks"].walk()
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
                   "replaceState", "Loading stock issues…",
                   "Couldn't load stock issues.", "Retry",
                   "No stock issues published yet."):
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

    # The tab bar spans the full width: every tab grows to an equal share.
    tab_rule = css[css.index('.tabs [role="tab"] {'):]
    tab_rule = tab_rule[:tab_rule.index("}")]
    assert re.search(r"flex:\s*1 1 0", tab_rule) and "text-align: center" in tab_rule
    panel_rule = css[css.index('[role="tabpanel"] {'):]
    assert "counter-reset: section" in panel_rule[:panel_rule.index("}")]


def test_no_data_source_branding_on_the_page_or_in_issue_feeds():
    texts = {"index.html": (SITE / "index.html").read_text(),
             "issues.js": (SITE / "issues.js").read_text()}
    for feed in FEEDS:
        texts[feed] = (SITE / "calendar" / f"{feed}.ics").read_text()
    for name, text in texts.items():
        assert "sharesansar" not in text.lower(), name


NODE_SCRIPT = """
const h = require(process.argv[1]);
const data = JSON.parse(require("fs").readFileSync(process.argv[2], "utf8"));
const ids = (list) => list.map((i) => i.category + ":" + i.symbol).sort();
const g = h.groupIssues(data, "2026-11-20");
const mid = h.groupIssues(data, "2026-11-27");
console.log(JSON.stringify({
  hash: [h.parseHash("#npl"), h.parseHash("#standings"), h.parseHash(""), h.parseHash("#x"),
    h.parseHash("#stocks-calendar")],
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

    assert out["hash"] == ["npl", "npl", "stocks", "stocks", "stocks"]
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


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_page_formats_amounts_like_the_feeds():
    data = json.loads((SITE / "data" / "issues.json").read_text())
    values = sorted({v for i in data["issues"] for v in (i.get("units"), i.get("price")) if v})
    values += ["600000.00", "24851236.18", "1000.50", "100", "0.00"]
    script = ("const h = require(process.argv[1]);"
              "console.log(JSON.stringify(JSON.parse(process.argv[2]).map(h.formatAmount)));")
    result = subprocess.run(
        [shutil.which("node"), "-e", script, str(SITE / "issues.js"), json.dumps(values)],
        capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == [format_amount(v) for v in values]
    assert "600,000" in json.loads(result.stdout)


DOM_SCRIPT = r"""
const path = require("path");
const target = path.resolve(process.argv[2]);
const sampleData = JSON.parse(require("fs").readFileSync(process.argv[3], "utf8"));
const flush = () => new Promise((r) => setImmediate(r));

class El {
  constructor(tag) {
    this.tag = tag; this.children = []; this.attrs = {}; this.listeners = {};
    this.dataset = {}; this.className = ""; this.hidden = false; this.tabIndex = 0;
    this.id = ""; this.title = ""; this.href = ""; this._text = "";
  }
  get firstChild() { return this.children[0] || null; }
  appendChild(c) { this.children.push(c); return c; }
  removeChild(c) { this.children.splice(this.children.indexOf(c), 1); return c; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k]; }
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
  fire(t, ev) {
    ev = ev || {};
    ev.prevented = false;
    ev.preventDefault = () => { ev.prevented = true; };
    (this.listeners[t] || []).forEach((f) => f(ev));
    return ev;
  }
  focus() { global.document.activeElement = this; }
  scrollIntoView() { global.document.scrolled = this.id; }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(""); }
  set textContent(v) { this._text = String(v); this.children = []; }
  walk() { return [this].concat(...this.children.map((c) => c.walk())); }
  removeAttribute(k) { delete this.attrs[k]; }
  querySelectorAll(sel) {
    if (sel === "[id]") { return this.walk().slice(1).filter((e) => e.id); }
    if (sel === "nav a") {
      return [].concat(...this.walk().filter((e) => e.tag === "nav").map(
        (n) => n.walk().filter((e) => e.tag === "a")));
    }
    return [];
  }
}

const NAVS = {
  "panel-stocks": ["stocks-calendar", "stocks-issues", "stocks-subscribe"],
  "panel-npl": ["standings", "stats", "schedule", "calendar"],
};

function boot(hash, fetchImpl, withIO) {
  const observers = [];
  if (withIO === false) { delete global.IntersectionObserver; }
  else {
    global.IntersectionObserver = function (cb) {
      this.cb = cb; this.observed = []; observers.push(this);
      this.observe = (t) => { this.observed.push(t.id); };
    };
  }
  const mk = (tag, id) => { const e = new El(tag); e.id = id || ""; return e; };
  const tabs = [mk("button", "tab-stocks"), mk("button", "tab-npl")];
  tabs[0].setAttribute("aria-selected", "true");
  tabs[1].setAttribute("aria-selected", "false");
  tabs[1].tabIndex = -1;
  const els = {};
  ["panel-stocks", "panel-npl", "issues-status", "issues-month", "issues-legend",
   "issues-list"].forEach((id) => { els[id] = mk("div", id); });
  els["panel-npl"].hidden = true;
  Object.keys(NAVS).forEach((panel) => {
    const nav = mk("nav");
    NAVS[panel].forEach((id) => {
      const a = mk("a"); a.setAttribute("href", "#" + id); nav.appendChild(a);
    });
    els[panel].appendChild(nav);
    NAVS[panel].forEach((id) => els[panel].appendChild(mk("section", id)));
  });
  const win = new El("window");
  const doc = new El("document");
  Object.assign(doc, {
    baseURI: "https://example.test/np-calendar/", visibilityState: "visible",
    activeElement: null, scrolled: null,
    querySelectorAll: (sel) => (sel === '[role="tab"]' ? tabs : []),
    getElementById: (id) => els[id] ||
      els["panel-npl"].walk().concat(els["panel-stocks"].walk()).find((e) => e.id === id) || null,
    createElement: (tag) => new El(tag),
    createTextNode: (t) => { const e = new El("#text"); e._text = t; return e; },
  });
  const loc = { hash: hash };
  global.document = doc; global.window = win; global.location = loc;
  global.history = { writes: [], replaceState(_s, _t, h) { loc.hash = h; this.writes.push(h); } };
  global.fetch = fetchImpl;
  Date.now = () => Date.UTC(2026, 10, 20, 6, 0, 0);
  delete require.cache[target];
  require(target);
  const state = () => ({
    selected: tabs.map((t) => t.getAttribute("aria-selected")),
    tabindex: tabs.map((t) => t.tabIndex),
    hidden: [els["panel-stocks"].hidden, els["panel-npl"].hidden],
    focused: doc.activeElement && doc.activeElement.id,
    hash: loc.hash, writes: global.history.writes.slice(),
  });
  return { tabs, els, win, doc, loc, state, observers };
}

const okFetch = (data) => () => Promise.resolve({ ok: true, json: () => Promise.resolve(data) });
const out = {};

(async () => {
  // keyboard pattern + state sync + hash written on activation
  let p = boot("", okFetch(sampleData));
  await flush();
  out.initial = p.state();
  const press = (i, key) => { const ev = p.tabs[i].fire("keydown", { key }); return ev.prevented; };
  out.right = (press(0, "ArrowRight"), p.state());
  out.rightWrap = (press(1, "ArrowRight"), p.state());
  out.leftWrap = (press(0, "ArrowLeft"), p.state());
  out.left = (press(1, "ArrowLeft"), p.state());
  out.end = (press(0, "End"), p.state());
  out.home = (press(1, "Home"), p.state());
  out.otherKeyPrevented = press(0, "a");
  out.afterOther = p.state();
  p.tabs[1].fire("click");
  out.click = p.state();

  // hash restore on load
  out.loadNpl = boot("#npl", okFetch(sampleData)).state();
  p = boot("#standings", okFetch(sampleData));
  out.loadStandings = p.state();
  out.standingsScrolled = p.doc.scrolled;
  out.loadEmpty = boot("", okFetch(sampleData)).state();
  p = boot("", okFetch(sampleData));
  p.loc.hash = "#npl"; p.win.fire("hashchange");
  out.hashchange = p.state();
  p.loc.hash = ""; p.win.fire("hashchange");
  out.hashchangeBack = p.state();

  // loading -> loaded
  p = boot("", okFetch(sampleData));
  out.loading = p.els["issues-status"].textContent;
  out.busyWhileLoading = p.els["panel-stocks"].getAttribute("aria-busy");
  await flush();
  out.loaded = p.els["issues-status"].textContent;
  out.busyAfter = p.els["panel-stocks"].getAttribute("aria-busy");
  out.listText = p.els["issues-list"].textContent;

  // error with retry wired to refetch
  let calls = 0, fail = true;
  p = boot("", () => {
    calls += 1;
    return fail ? Promise.reject(new Error("down")) : okFetch(sampleData)();
  });
  await flush();
  const retryBtn = () => p.els["issues-status"].children.find((c) => c.tag === "button");
  out.error = p.els["issues-status"].textContent;
  out.errorHasRetry = !!retryBtn() && retryBtn().textContent === "Retry";
  out.callsBeforeRetry = calls;
  fail = false;
  retryBtn().fire("click");
  await flush();
  out.callsAfterRetry = calls;
  out.afterRetry = p.els["issues-status"].textContent;
  out.retryGone = !retryBtn();

  // HTTP error state and bad schema state
  p = boot("", () => Promise.resolve({ ok: false, status: 500 }));
  await flush();
  out.http500 = p.els["issues-status"].textContent;
  p = boot("", okFetch({ schema_version: 9 }));
  await flush();
  out.badSchema = p.els["issues-status"].textContent;

  // empty state
  p = boot("", okFetch({ schema_version: 1, issues: [], categories: [] }));
  await flush();
  out.empty = p.els["issues-status"].textContent;

  // month navigation
  p = boot("", okFetch(sampleData));
  await flush();
  const month = () => p.els["issues-month"].walk();
  const label = () => month().find((e) => e.id === "issues-month-label").textContent;
  const nav = (t) => month().find((e) => e.tag === "button" && e.textContent === t);
  out.nav = [label()];
  nav("Next").fire("click"); out.nav.push(label());
  nav("Next").fire("click"); out.nav.push(label());
  nav("Previous").fire("click"); nav("Previous").fire("click"); nav("Previous").fire("click");
  out.nav.push(label());
  nav("Today").fire("click"); out.nav.push(label());
  out.chipsNov = p.els["issues-month"].walk().filter((e) => /chip /.test(e.className)).length;
  nav("Next").fire("click");
  out.chipsDec = p.els["issues-month"].walk().filter((e) => /chip /.test(e.className)).length;

  // scrollspy
  p = boot("", okFetch(sampleData));
  await flush();
  out.spy = { count: p.observers.length };
  if (p.observers.length === 2) {
  const [oS, oN] = p.observers;
  const current = (panel) => p.els[panel].walk().filter(
    (e) => e.tag === "a" && e.attrs["aria-current"] === "true").map((e) => e.attrs.href);
  const fire = (o, m) => o.cb(
    Object.keys(m).map((id) => ({ target: { id }, isIntersecting: m[id] })));
  Object.assign(out.spy, { observedS: oS.observed, observedN: oN.observed });
  out.spy.initial = [current("panel-stocks"), current("panel-npl")];
  fire(oS, { "stocks-issues": true });
  out.spy.one = current("panel-stocks");
  fire(oS, { "stocks-issues": false, "stocks-subscribe": true });
  out.spy.moved = current("panel-stocks");
  fire(oS, { "stocks-calendar": true, "stocks-subscribe": true });
  out.spy.navOrder = current("panel-stocks");
  fire(oS, { "stocks-calendar": false, "stocks-subscribe": false });
  out.spy.allFalse = current("panel-stocks");
  fire(oN, { schedule: true });
  out.spy.npl = current("panel-npl");
  out.spy.stocksKept = current("panel-stocks");
  }
  p = boot("", okFetch(sampleData), false);
  await flush();
  out.spy.noIO = [p.els["issues-status"].textContent,
    p.els["panel-stocks"].walk().concat(p.els["panel-npl"].walk()).filter(
      (e) => e.attrs["aria-current"]).length];
  console.log(JSON.stringify(out));
})();
"""


@pytest.fixture(scope="module")
def dom(tmp_path_factory):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    tmp = tmp_path_factory.mktemp("dom")
    fixtures = Path(__file__).parent / "fixtures" / "issues"
    raw = {s: json.loads((fixtures / f"{s}.json").read_text())["data"] for s in CATS}
    (tmp / "issues.json").write_text(json.dumps(normalize_issues(raw)))
    (tmp / "dom.js").write_text(DOM_SCRIPT)
    result = subprocess.run(
        [shutil.which("node"), str(tmp / "dom.js"), str(SITE / "issues.js"),
         str(tmp / "issues.json")],
        capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def _tab(state, selected, focused=None, hash_=None):
    assert state["selected"] == ["true" if selected == 0 else "false",
                                 "true" if selected == 1 else "false"]
    assert state["tabindex"] == [0 if selected == 0 else -1, 0 if selected == 1 else -1]
    assert state["hidden"] == [selected != 0, selected != 1]
    if focused:
        assert state["focused"] == focused
    if hash_:
        assert state["hash"] == hash_


def test_tab_keyboard_pattern_and_state_sync(dom):
    _tab(dom["initial"], 0)
    assert dom["initial"]["writes"] == []
    _tab(dom["right"], 1, "tab-npl", "#npl")
    _tab(dom["rightWrap"], 0, "tab-stocks", "#stocks")
    _tab(dom["leftWrap"], 1, "tab-npl", "#npl")
    _tab(dom["left"], 0, "tab-stocks", "#stocks")
    _tab(dom["end"], 1, "tab-npl", "#npl")
    _tab(dom["home"], 0, "tab-stocks", "#stocks")
    assert dom["otherKeyPrevented"] is False
    assert dom["afterOther"]["writes"] == dom["home"]["writes"]
    _tab(dom["click"], 1, hash_="#npl")


def test_hash_restored_on_load_and_hashchange(dom):
    _tab(dom["loadNpl"], 1)
    _tab(dom["loadStandings"], 1)
    assert dom["standingsScrolled"] == "standings"
    _tab(dom["loadEmpty"], 0)
    assert dom["loadEmpty"]["writes"] == []
    _tab(dom["hashchange"], 1)
    _tab(dom["hashchangeBack"], 0)


def test_loading_error_retry_and_empty_states(dom):
    assert dom["loading"] == "Loading stock issues…"
    assert dom["busyWhileLoading"] == "true" and dom["busyAfter"] == "false"
    assert dom["loaded"].startswith("223 stock issues listed")
    assert "Upcoming" in dom["listText"] and "Dates not announced yet" in dom["listText"]
    assert "Price Rs 100 · Units 90,000" in dom["listText"]
    assert dom["error"].startswith("Couldn't load stock issues.")
    assert dom["errorHasRetry"] is True
    assert dom["callsAfterRetry"] == dom["callsBeforeRetry"] + 1
    assert dom["afterRetry"].startswith("223 stock issues listed") and dom["retryGone"]
    assert dom["http500"].startswith("Couldn't load stock issues.")
    assert dom["badSchema"].startswith("Couldn't load stock issues.")
    assert dom["empty"] == "No stock issues published yet."


def test_month_navigation_prev_next_today(dom):
    assert dom["nav"] == ["November 2026", "December 2026", "January 2027",
                          "October 2026", "November 2026"]
    assert dom["chipsNov"] > 0 and dom["chipsDec"] > 0


def _media_block(css, query):
    start = css.index(query)
    i = css.index("{", start)
    depth, j = 0, i
    while True:
        depth += css[j] == "{"
        depth -= css[j] == "}"
        j += 1
        if depth == 0:
            return css[i + 1:j - 1], css[:start] + css[j:]


def _rule(css, selector):
    m = re.search(r"(?:^|\n)\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, selector
    return m.group(1)


def test_section_navs_become_a_sticky_left_toc_on_wide_screens():
    css = (SITE / "style.css").read_text()
    wide, outside = _media_block(css, "@media (min-width: 64rem)")
    panel = _rule(wide, '[role="tabpanel"]')
    assert "display: grid" in panel
    assert re.search(r"grid-template-columns:\s*\S+\s+\S+", panel)
    nav = _rule(wide, '[role="tabpanel"] > nav')
    assert "grid-column: 1" in nav and "align-self: start" in nav and re.search(r"top:\s*\S", nav)
    assert "flex-direction: column" in _rule(wide, '[role="tabpanel"] > nav ul')
    assert "grid-column: 2" in _rule(wide, '[role="tabpanel"] > :not(nav)')
    base = _rule(outside, "nav")
    assert "position: sticky" in base and "top: 0" in base
    assert "flex-direction: column" not in _rule(outside, "nav ul")
    assert "background-size: 100% 2px" in _rule(css, 'nav a[aria-current="true"]')

    nodes, by_id = _dom()
    assert sorted(n.attrs.get("src") for n in nodes if n.tag == "script" and "src" in n.attrs) \
        == ["app.js", "issues.js"]
    assert sorted(n.attrs["href"] for n in nodes if n.tag == "link") == ["data:,", "style.css"]
    for pid in ("panel-stocks", "panel-npl"):
        kids = by_id[pid].children
        assert kids[0].tag == "nav"
        sections = {c.attrs.get("id") for c in kids if c.tag == "section"}
        links = [a.attrs["href"][1:] for a in kids[0].walk() if a.tag == "a"]
        assert links and set(links) <= sections


def test_scrollspy_marks_the_section_in_view(dom):
    spy = dom["spy"]
    assert spy["count"] == 2
    assert spy["observedS"] == ["stocks-calendar", "stocks-issues", "stocks-subscribe"]
    assert spy["observedN"] == ["standings", "stats", "schedule", "calendar"]
    assert spy["initial"] == [[], []]
    assert spy["one"] == ["#stocks-issues"]
    assert spy["moved"] == ["#stocks-subscribe"]
    assert spy["navOrder"] == ["#stocks-calendar"]
    assert spy["allFalse"] == ["#stocks-calendar"]
    assert spy["npl"] == ["#schedule"] and spy["stocksKept"] == ["#stocks-calendar"]
    assert spy["noIO"][0].endswith("stock issues listed.") and spy["noIO"][1] == 0
