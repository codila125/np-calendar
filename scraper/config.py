from datetime import date, timedelta, timezone
from typing import NamedTuple

SEASON_YEAR = 2026
SEASON_NAME = "NPL 2026 (Season 3)"
EXPECTED_TEAMS = 8
EXPECTED_MATCHES = 32
STAGES = ("league", "qualifier_1", "eliminator", "qualifier_2", "final")

SOURCE_BASE = "https://nplt20league.com"
USER_AGENT = "np-calendar-bot/1.0 (+https://github.com/codila125/np-calendar)"
SITE_URL = "https://codila125.github.io/np-calendar/"

NPT = timezone(timedelta(hours=5, minutes=45))
MATCH_DURATION = timedelta(hours=3, minutes=30)
SEASON_WINDOW = (date(2026, 10, 26), date(2026, 11, 21))  # NPT dates, inclusive

SCHEMA_VERSION = 1

PRODID = "-//codila125//np-calendar//EN"
UID_DOMAIN = "codila125.github.io"

ISSUES_BASE = "https://www.sharesansar.com"
ISSUES_PER_CATEGORY = 50
ISSUES_SCHEMA_VERSION = 1
ALARM_UTC_TIME = "031500"  # 09:00 NPT


class IssueCategory(NamedTuple):
    slug: str
    type_id: int
    label: str
    short: str


ISSUE_CATEGORIES = (
    IssueCategory("ipo", 1, "IPO", "IPO"),
    IssueCategory("fpo", 2, "FPO", "FPO"),
    IssueCategory("right-share", 3, "Right share", "Right"),
    IssueCategory("ipo-local", 5, "IPO for locals", "Local"),
    IssueCategory("ipo-migrant", 8, "IPO for migrant workers", "Migrant"),
    IssueCategory("mutual-fund", 4, "Mutual funds", "MF"),
    IssueCategory("debenture", 7, "Debentures", "Debenture"),
)
ISSUE_FEEDS = ("issues", *(c.slug for c in ISSUE_CATEGORIES))  # calendar/<name>.ics
