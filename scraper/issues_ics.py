"""Deterministic iCalendar feeds for share issues from an ``issues.json`` dict (pure).

``build_issue_calendars`` returns ``{relpath: bytes}`` for ``calendar/issues.ics`` and one
``calendar/<slug>.ics`` per category. Only issues with announced dates become events, each
an all-day event from the opening date through the closing date inclusive. No wall clock is
read anywhere in this module (ADR-2): DTSTAMP derives from the opening date.
"""

from datetime import date, timedelta
from decimal import Decimal

from . import config
from .ics import escape_text, fold

ALL_NAME = "All stock issues"
CALDESC = "Opening and closing dates of stock issues in Nepal."


def format_amount(value: str) -> str:
    """``600000.00`` -> ``600,000``; ``24851236.18`` -> ``24,851,236.18``."""
    whole, _, frac = value.strip().partition(".")
    frac = frac.rstrip("0")
    sign = "-" if whole.startswith("-") else ""
    digits = whole.lstrip("-")
    text = f"{Decimal(digits or '0'):,.0f}"
    return f"{sign}{text}" + (f".{frac}" if frac else "")


def _human(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%b %Y')}"


def _compact(iso: str) -> str:
    return iso.replace("-", "")


def _description(issue: dict, label: str) -> str:
    lines = [f"{label} · {issue['symbol']}"]
    if issue.get("price"):
        lines.append(f"Price: Rs {format_amount(issue['price'])}")
    if issue.get("units"):
        lines.append(f"Units: {format_amount(issue['units'])}")
    right = issue["category"] == "right-share"
    if right and issue.get("ratio"):
        lines.append(f"Ratio: {issue['ratio']}")
    if right and issue.get("book_closure_date"):
        lines.append(f"Book closure: {_human(issue['book_closure_date'])}")
    lines.append(f"Opens {_human(issue['opening_date'])}, closes {_human(issue['closing_date'])}")
    last = issue.get("last_closing_date")
    if not right and last and last > issue["closing_date"]:
        lines.append(f"May stay open until {_human(last)}")
    if issue.get("issue_manager"):
        lines.append(f"Issue manager: {issue['issue_manager']}")
    return "\n".join(lines)


def _vevent(issue: dict, label: str) -> str:
    opening = _compact(issue["opening_date"])
    end = date.fromisoformat(issue["closing_date"]) + timedelta(days=1)
    who = f"{issue['company']} ({issue['symbol']})"
    lines = [
        "BEGIN:VEVENT",
        f"UID:issue-{issue['id']}@{config.UID_DOMAIN}",
        f"DTSTAMP:{opening}T000000Z",
        f"DTSTART;VALUE=DATE:{opening}",
        f"DTEND;VALUE=DATE:{end.strftime('%Y%m%d')}",
        f"SUMMARY:{escape_text(f'{label}: {who}')}",
        f"DESCRIPTION:{escape_text(_description(issue, label))}",
        "STATUS:CONFIRMED",
        "TRANSP:TRANSPARENT",
        "BEGIN:VALARM",
        "ACTION:DISPLAY",
        f"DESCRIPTION:{escape_text(f'{label} opens today: {who}')}",
        f"TRIGGER;VALUE=DATE-TIME:{opening}T{config.ALARM_UTC_TIME}Z",
        "END:VALARM",
        "END:VEVENT",
    ]
    return "\r\n".join(fold(line) for line in lines)


def _calendar(name: str, events: list[str]) -> bytes:
    lines = [
        fold("BEGIN:VCALENDAR"),
        fold("VERSION:2.0"),
        fold(f"PRODID:{config.PRODID}"),
        fold("CALSCALE:GREGORIAN"),
        fold("METHOD:PUBLISH"),
        fold(f"X-WR-CALNAME:{escape_text(f'np-calendar — {name}')}"),
        fold(f"X-WR-CALDESC:{escape_text(CALDESC)}"),
        fold("REFRESH-INTERVAL;VALUE=DURATION:PT1H"),
        fold("X-PUBLISHED-TTL:PT1H"),
        *events,
        "END:VCALENDAR",
    ]
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def build_issue_calendars(data: dict) -> dict[str, bytes]:
    """Return the six issue feeds as ``{relpath: bytes}``; undated issues are left out."""
    order = {c.slug: n for n, c in enumerate(config.ISSUE_CATEGORIES)}
    labels = {c.slug: c.label for c in config.ISSUE_CATEGORIES}
    dated = sorted(
        (i for i in data["issues"] if i.get("dates_announced")),
        key=lambda i: (i["opening_date"], i["closing_date"], order[i["category"]], i["id"]),
    )
    events = [(i["category"], _vevent(i, labels[i["category"]])) for i in dated]
    outputs = {"calendar/issues.ics": _calendar(ALL_NAME, [e for _, e in events])}
    for cat in config.ISSUE_CATEGORIES:
        outputs[f"calendar/{cat.slug}.ics"] = _calendar(
            cat.label, [e for slug, e in events if slug == cat.slug]
        )
    return outputs
