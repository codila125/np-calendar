"""ShareSansar share issues: raw rows -> ``issues.json`` data (rules I3..I6).

Pure functions, no clock (ADR-2). Rule ids: I3 row shape, I4 closing before
opening, I5 duplicate id, I6 control characters / over-long text. I1 and I2
live in ``fetch.py``.
"""

import re
from datetime import date
from html.parser import HTMLParser

from . import config
from .errors import Violation
from .validate import _check_text

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
COMPANY_URL_RE = re.compile(r"^https://www\.sharesansar\.com/company/[a-z0-9-]+$")
ANNOUNCEMENT_URL_RE = re.compile(r"^https://www\.sharesansar\.com/\S+$")
FALLBACK_URL = f"{config.ISSUES_BASE}/existing-issues"
_SLUGS = tuple(c.slug for c in config.ISSUE_CATEGORIES)


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hrefs: list[str] = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.hrefs.extend(v for k, v in attrs if k == "href" and v)


def _parse(fragment: str) -> _Text:
    parser = _Text()
    parser.feed(fragment)
    parser.close()
    return parser


def strip_html(fragment: str) -> str:
    """Text content of an HTML fragment, whitespace collapsed; a raw ``&`` is kept."""
    return " ".join("".join(_parse(fragment).parts).split())


def _first_href(fragment: str) -> str | None:
    hrefs = _parse(fragment).hrefs
    return hrefs[0] if hrefs else None


def _is_date(value) -> bool:
    if not isinstance(value, str) or not DATE_RE.match(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _optional_date_problem(row: dict, field: str) -> str | None:
    value = row.get(field)
    if value in ("", None) or _is_date(value):
        return None
    return f"{field} {value!r} is not a YYYY-MM-DD date"


def validate_issue_rows(raw: dict[str, list]) -> list[Violation]:
    """I3 (row shape) and I4 (closing before opening) on the raw source rows."""
    out: list[Violation] = []
    for slug in _SLUGS:
        for index, row in enumerate(raw.get(slug, [])):
            where = f"{slug} row {index}"
            problem = _row_problem(row)
            if problem:
                out.append(Violation("I3", f"{where}: {problem}"))
                continue
            opening, closing = row.get("opening_date"), row.get("closing_date")
            if opening and closing and closing < opening:
                symbol = strip_html(row["company"]["symbol"])
                out.append(
                    Violation(
                        "I4",
                        f"{slug} {symbol}: closing date {closing} is before opening date {opening}",
                    )
                )
    return out


def _row_problem(row) -> str | None:
    if not isinstance(row, dict):
        return "row is not an object"
    company = row.get("company")
    if not isinstance(company, dict):
        return "missing `company` object"
    for field in ("symbol", "companyname"):
        value = company.get(field)
        if not isinstance(value, str) or not strip_html(value):
            return f"company.{field} is missing or blank after stripping HTML"
    if row.get("companyid") is None:
        return "missing `companyid`"
    if not isinstance(row.get("total_units"), str) or not row["total_units"].strip():
        return "missing `total_units`"
    for field in ("opening_date", "closing_date", "final_date"):
        problem = _optional_date_problem(row, field)
        if problem:
            return problem
    return None


def _units_key(units: str) -> str:
    units = units.strip()
    if "." in units:
        units = units.rstrip("0").rstrip(".")
    return units


def _blank_to_none(value) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _normalize_row(slug: str, row: dict) -> dict:
    name_html = row["company"]["companyname"]
    symbol_html = row["company"]["symbol"]
    href = _first_href(name_html) or _first_href(symbol_html)
    company_url = href if href and COMPANY_URL_RE.match(href) else None
    link = row.get("announcement_link")
    if isinstance(link, str) and ANNOUNCEMENT_URL_RE.match(link) and link.count("://") == 1:
        url = link
    else:
        url = company_url or FALLBACK_URL
    opening = row.get("opening_date") or None
    closing = row.get("closing_date") or None
    final = row.get("final_date") or None
    is_right = slug == "right-share"
    price = row.get("issue_price")
    return {
        "id": f"{slug}-{row['companyid']}-{_units_key(row['total_units'])}",
        "category": slug,
        "company": strip_html(name_html),
        "symbol": strip_html(symbol_html),
        "units": row["total_units"],
        "price": price if price else None,
        "ratio": _blank_to_none(row.get("ratio_value")),
        "issue_manager": _blank_to_none(row.get("issue_manager")),
        "opening_date": opening,
        "closing_date": closing,
        "last_closing_date": None if is_right else final,
        "book_closure_date": final if is_right else None,
        "dates_announced": bool(opening and closing),
        "url": url,
        "company_url": company_url,
    }


def _resolve_ids(items: list[dict]) -> list[dict]:
    """ADR-4: collapse identical rows; later rows sharing a base id get a date suffix."""
    by_id: dict[str, list[dict]] = {}
    for item in items:
        group = by_id.setdefault(item["id"], [])
        if item not in group:
            group.append(item)
    out = []
    for base, group in by_id.items():
        group.sort(key=lambda i: (i["opening_date"] is None, i["opening_date"] or ""))
        for position, item in enumerate(group):
            if position:
                opening = item["opening_date"]
                suffix = opening.replace("-", "") if opening else "tba"
                item = {**item, "id": f"{base}-{suffix}"}
            out.append(item)
    return out


def normalize_issues(raw: dict[str, list]) -> dict:
    items = []
    for slug in _SLUGS:
        items.extend(_normalize_row(slug, row) for row in raw.get(slug, []))
    items = _resolve_ids(items)
    order = {slug: n for n, slug in enumerate(_SLUGS)}
    items.sort(
        key=lambda i: (
            i["opening_date"] is None,
            i["opening_date"] or "",
            i["closing_date"] or "",
            order[i["category"]],
            i["id"],
        )
    )
    return {
        "schema_version": config.ISSUES_SCHEMA_VERSION,
        "source": {"name": "sharesansar.com", "url": FALLBACK_URL},
        "categories": [
            {"slug": c.slug, "type": c.type_id, "label": c.label, "short": c.short}
            for c in config.ISSUE_CATEGORIES
        ],
        "issues": items,
    }


def validate_issues(data: dict) -> list[Violation]:
    """I5 (duplicate id) and I6 (control characters, over-long text) on normalized data."""
    out: list[Violation] = []
    seen: set[str] = set()
    for item in data["issues"]:
        if item["id"] in seen:
            out.append(Violation("I5", f"duplicate issue id {item['id']!r}"))
        seen.add(item["id"])
        for field in ("company", "symbol", "units", "price", "ratio", "issue_manager"):
            _check_text(item.get(field), f"issue {item['id']} {field}", out, "I6")
    return out
