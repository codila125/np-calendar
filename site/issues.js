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

  function validateIssuesData(data) {
    return !!data && typeof data === "object" && data.schema_version === 1 &&
      Array.isArray(data.issues) && Array.isArray(data.categories);
  }

  if (typeof module === "object" && module.exports) {
    module.exports = { parseHash: parseHash, validateIssuesData: validateIssuesData,
      nptToday: nptToday };
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

  function render(data) {
    panels.issues.setAttribute("aria-busy", "false");
    if (!data.issues.length) {
      setStatus("No share issues published yet.");
      return;
    }
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
  load();
})();
