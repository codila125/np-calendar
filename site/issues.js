/* np-calendar — share-issues tab: tabs, hash routing, feed rows, issues.json loading. */
"use strict";

(function () {
  var NPT_OFFSET_MS = (5 * 60 + 45) * 60 * 1000;
  var DATA_URL = "data/issues.json";
  var STALE_MS = 5 * 60 * 1000;
  var FEED_SLUGS = ["issues", "ipo", "fpo", "right-share", "ipo-local", "ipo-migrant"];

  function nptToday(nowMs) {
    var d = new Date((nowMs === undefined ? Date.now() : nowMs) + NPT_OFFSET_MS);
    return d.getUTCFullYear() + "-" + String(d.getUTCMonth() + 1).padStart(2, "0") +
      "-" + String(d.getUTCDate()).padStart(2, "0");
  }

  // "npl" for #npl and for any anchor inside the NPL panel; everything else is issues.
  function parseHash(hash, nplIds) {
    var id = String(hash || "").replace(/^#/, "");
    if (id === "npl") {
      return "npl";
    }
    if (id && nplIds && nplIds.indexOf(id) !== -1) {
      return "npl";
    }
    if (id === "standings" || id === "stats" || id === "schedule" || id === "calendar" ||
        id === "live") {
      return "npl";
    }
    return "issues";
  }

  var MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December"];
  var DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  var CATEGORIES = [
    { slug: "ipo", label: "IPO", short: "IPO" },
    { slug: "fpo", label: "FPO", short: "FPO" },
    { slug: "right-share", label: "Right share", short: "Right" },
    { slug: "ipo-local", label: "IPO for locals", short: "Local" },
    { slug: "ipo-migrant", label: "IPO for migrant workers", short: "Migrant" }
  ];

  function pad(n) {
    return String(n).padStart(2, "0");
  }

  // Weeks (Sunday first) of a month; month is 0-based. Cells outside it are null.
  function monthWeeks(year, month) {
    var first = new Date(Date.UTC(year, month, 1)).getUTCDay();
    var count = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
    var cells = [];
    var i;
    for (i = 0; i < first; i++) {
      cells.push(null);
    }
    for (i = 1; i <= count; i++) {
      cells.push(year + "-" + pad(month + 1) + "-" + pad(i));
    }
    while (cells.length % 7) {
      cells.push(null);
    }
    var weeks = [];
    for (i = 0; i < cells.length; i += 7) {
      weeks.push(cells.slice(i, i + 7));
    }
    return weeks;
  }

  // Issues open on an ISO date (opening <= day <= closing); undated ones never match.
  function issuesOn(data, iso) {
    return data.issues.filter(function (issue) {
      return !!issue.opening_date && !!issue.closing_date &&
        issue.opening_date <= iso && iso <= issue.closing_date;
    });
  }

  function groupIssues(data, today) {
    var groups = { open: [], upcoming: [], undated: [] };
    data.issues.forEach(function (issue) {
      if (!issue.opening_date || !issue.closing_date) {
        groups.undated.push(issue);
      } else if (issue.opening_date > today) {
        groups.upcoming.push(issue);
      } else if (today <= issue.closing_date) {
        groups.open.push(issue);
      }
    });
    return groups;
  }

  function categoryOf(slug) {
    return CATEGORIES.filter(function (c) { return c.slug === slug; })[0] ||
      { slug: slug, label: slug, short: slug };
  }

  function validateIssuesData(data) {
    return !!data && typeof data === "object" && data.schema_version === 1 &&
      Array.isArray(data.issues) && Array.isArray(data.categories);
  }

  if (typeof module === "object" && module.exports) {
    module.exports = { parseHash: parseHash, validateIssuesData: validateIssuesData,
      nptToday: nptToday, monthWeeks: monthWeeks, issuesOn: issuesOn,
      groupIssues: groupIssues };
  }
  if (typeof document === "undefined") {
    return;
  }

  var tabs = Array.prototype.slice.call(document.querySelectorAll('[role="tab"]'));
  var panels = {
    issues: document.getElementById("panel-issues"),
    npl: document.getElementById("panel-npl")
  };
  var status = document.getElementById("issues-status");
  var currentData = null;
  var lastHiddenAt = null;

  function make(tag, className, text) {
    var el = document.createElement(tag);
    if (className) {
      el.className = className;
    }
    if (text !== undefined) {
      el.textContent = text;
    }
    return el;
  }

  function nplIds() {
    return Array.prototype.map.call(panels.npl.querySelectorAll("[id]"), function (el) {
      return el.id;
    });
  }

  function activate(name, focus) {
    tabs.forEach(function (tab) {
      var on = tab.id === "tab-" + name;
      tab.setAttribute("aria-selected", on ? "true" : "false");
      tab.tabIndex = on ? 0 : -1;
      if (on && focus) {
        tab.focus();
      }
    });
    panels.issues.hidden = name !== "issues";
    panels.npl.hidden = name !== "npl";
  }

  function select(name, focus) {
    activate(name, focus);
    history.replaceState(null, "", "#" + name);
  }

  function applyHash() {
    var id = location.hash.replace(/^#/, "");
    if (id === "main") {
      return;
    }
    var name = parseHash(location.hash, nplIds());
    activate(name, false);
    if (name === "npl" && id && id !== "npl") {
      var target = document.getElementById(id);
      if (target) {
        target.scrollIntoView();
      }
    }
  }

  tabs.forEach(function (tab, index) {
    tab.addEventListener("click", function () {
      select(tab.id.replace("tab-", ""), false);
    });
    tab.addEventListener("keydown", function (event) {
      var next = null;
      if (event.key === "ArrowRight") {
        next = (index + 1) % tabs.length;
      } else if (event.key === "ArrowLeft") {
        next = (index - 1 + tabs.length) % tabs.length;
      } else if (event.key === "Home") {
        next = 0;
      } else if (event.key === "End") {
        next = tabs.length - 1;
      }
      if (next !== null) {
        event.preventDefault();
        select(tabs[next].id.replace("tab-", ""), true);
      }
    });
  });
  window.addEventListener("hashchange", applyHash);

  function webcalUrl(url) {
    var parsed = new URL(url);
    return "webcal://" + parsed.host + parsed.pathname;
  }

  function rewriteFeedRows() {
    var base = new URL(".", document.baseURI).href;
    var rows = document.querySelectorAll("#issues-feed-list .calendar-row");
    Array.prototype.forEach.call(rows, function (row, i) {
      var url = base + "calendar/" + FEED_SLUGS[i] + ".ics";
      row.querySelector(".subscribe").href = webcalUrl(url);
      row.querySelector(".google").href =
        "https://calendar.google.com/calendar/r?cid=" + encodeURIComponent(webcalUrl(url));
      row.querySelector(".copy").dataset.url = url;
    });
  }

  function setStatus(text, retry) {
    while (status.firstChild) {
      status.removeChild(status.firstChild);
    }
    status.appendChild(document.createTextNode(text));
    if (retry) {
      var button = make("button", "btn", "Retry");
      button.type = "button";
      button.addEventListener("click", load);
      status.appendChild(document.createTextNode(" "));
      status.appendChild(button);
    }
  }

  var monthEl = document.getElementById("issues-month");
  var legendEl = document.getElementById("issues-legend");
  var listEl = document.getElementById("issues-list");
  var viewYear = 0;
  var viewMonth = 0;
  var labelEl = null;
  var gridEl = null;

  function clear(el) {
    while (el.firstChild) {
      el.removeChild(el.firstChild);
    }
  }

  function monthName(year, month) {
    return MONTHS[month] + " " + year;
  }

  function buildLegend() {
    clear(legendEl);
    CATEGORIES.forEach(function (c) {
      var li = make("li", "legend-item");
      var swatch = make("span", "swatch cat-" + c.slug);
      swatch.setAttribute("aria-hidden", "true");
      li.appendChild(swatch);
      li.appendChild(make("span", null, c.label));
      legendEl.appendChild(li);
    });
  }

  function shiftMonth(delta) {
    var d = new Date(Date.UTC(viewYear, viewMonth + delta, 1));
    viewYear = d.getUTCFullYear();
    viewMonth = d.getUTCMonth();
    renderGrid();
  }

  function goToday() {
    var parts = nptToday().split("-");
    viewYear = Number(parts[0]);
    viewMonth = Number(parts[1]) - 1;
    renderGrid();
  }

  function buildMonthShell() {
    clear(monthEl);
    var nav = make("div", "issues-nav");
    [["Previous", function () { shiftMonth(-1); }], ["Today", goToday],
      ["Next", function () { shiftMonth(1); }]].forEach(function (spec) {
      var button = make("button", "btn", spec[0]);
      button.type = "button";
      button.addEventListener("click", spec[1]);
      nav.appendChild(button);
    });
    labelEl = make("span", "issues-month-label");
    labelEl.id = "issues-month-label";
    labelEl.setAttribute("aria-live", "polite");
    nav.appendChild(labelEl);
    monthEl.appendChild(nav);
    gridEl = make("div", "table-wrap");
    gridEl.id = "issues-grid";
    monthEl.appendChild(gridEl);
  }

  function chip(issue) {
    var cat = categoryOf(issue.category);
    var el = make("span", "chip cat-" + cat.slug);
    el.appendChild(make("span", "chip-tag", cat.short));
    el.appendChild(document.createTextNode(" " + issue.symbol));
    el.title = issue.company + " (" + cat.label + ")";
    return el;
  }

  function renderGrid() {
    var title = monthName(viewYear, viewMonth);
    labelEl.textContent = title;
    clear(gridEl);
    var data = currentData || { issues: [] };
    var today = nptToday();
    var table = make("table");
    table.appendChild(make("caption", null, "Share issues in " + title));
    var head = make("tr");
    DAYS.forEach(function (day) {
      var th = make("th", null, day.slice(0, 3));
      th.scope = "col";
      th.setAttribute("abbr", day);
      head.appendChild(th);
    });
    table.appendChild(make("thead")).appendChild(head);
    var body = make("tbody");
    var any = false;
    monthWeeks(viewYear, viewMonth).forEach(function (week) {
      var tr = make("tr");
      week.forEach(function (iso) {
        var td = make("td", iso ? "day" : "day empty");
        if (iso) {
          if (iso === today) {
            td.setAttribute("aria-current", "date");
            td.className += " today";
          }
          td.appendChild(make("span", "day-num", String(Number(iso.slice(8)))));
          issuesOn(data, iso).forEach(function (issue) {
            any = true;
            td.appendChild(chip(issue));
          });
        }
        tr.appendChild(td);
      });
      body.appendChild(tr);
    });
    table.appendChild(body);
    gridEl.appendChild(table);
    if (!any && currentData) {
      gridEl.appendChild(make("p", "issues-empty",
        "No share issues open in " + title + "."));
    }
  }

  function dateText(issue) {
    return issue.opening_date && issue.closing_date ?
      issue.opening_date + " to " + issue.closing_date : "Dates not announced yet";
  }

  function listItem(issue) {
    var cat = categoryOf(issue.category);
    var li = make("li", "issue-item");
    var tag = make("span", "chip-tag cat-" + cat.slug, cat.label);
    li.appendChild(tag);
    li.appendChild(make("strong", null, " " + issue.company + " (" + issue.symbol + ")"));
    var bits = [dateText(issue)];
    if (issue.price) {
      bits.push("Price " + issue.price);
    }
    bits.push("Units " + issue.units);
    li.appendChild(make("div", "issue-meta", bits.join(" · ")));
    var link = make("a", null, "Details on ShareSansar");
    link.href = issue.url;
    link.target = "_blank";
    link.rel = "noopener";
    li.appendChild(link);
    return li;
  }

  function renderList(data) {
    clear(listEl);
    var groups = groupIssues(data, nptToday());
    if (!groups.open.length && !groups.upcoming.length) {
      listEl.appendChild(make("p", "issues-empty",
        "No share issues are open or coming up right now."));
    }
    [["Open now", groups.open], ["Upcoming", groups.upcoming],
      ["Dates not announced yet", groups.undated]].forEach(function (spec) {
      if (!spec[1].length) {
        return;
      }
      listEl.appendChild(make("h3", null, spec[0]));
      var ul = make("ul", "issue-list");
      spec[1].forEach(function (issue) {
        ul.appendChild(listItem(issue));
      });
      listEl.appendChild(ul);
    });
  }

  function render(data) {
    panels.issues.setAttribute("aria-busy", "false");
    renderGrid();
    if (!data.issues.length) {
      clear(listEl);
      setStatus("No share issues published yet.");
      return;
    }
    renderList(data);
    setStatus(data.issues.length + " share issues listed. Source: ShareSansar.");
  }

  function load() {
    panels.issues.setAttribute("aria-busy", "true");
    if (!currentData) {
      setStatus("Loading share issues…");
    }
    fetch(DATA_URL, { cache: "no-cache" }).then(function (response) {
      if (!response.ok) {
        throw new Error("HTTP " + response.status);
      }
      return response.json();
    }).then(function (data) {
      if (!validateIssuesData(data)) {
        throw new Error("bad schema");
      }
      currentData = data;
      render(data);
    }).catch(function () {
      currentData = null;
      clear(listEl);
      renderGrid();
      panels.issues.setAttribute("aria-busy", "false");
      setStatus("Couldn't load share issues.", true);
    });
  }

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") {
      lastHiddenAt = Date.now();
    } else if (lastHiddenAt !== null && Date.now() - lastHiddenAt > STALE_MS) {
      load();
    }
  });

  applyHash();
  rewriteFeedRows();
  buildLegend();
  buildMonthShell();
  goToday();
  load();
})();
