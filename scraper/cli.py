"""``python -m scraper``: fetch/load -> normalize -> validate -> build -> publish.

Exit codes: ``0`` success (changed or unchanged), ``1`` nothing written (every
source failed, or an uncaught crash), ``2`` usage error (argparse), ``3`` partial
(one source failed, the healthy one was written). Each source (NPL, share issues)
builds and validates all of its outputs in memory before it writes anything
(ADR-3, amended by ADR-5), and a failed source leaves its published files alone.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from . import config, ics, issues, issues_ics, publish
from .errors import ScrapeError, Violation
from .fetch import load_from_dir, load_issues_from_dir, load_issues_remote, load_remote
from .normalize import normalize, normalize_stats
from .validate import validate, validate_stats

DATA_RELPATH = "data/npl.json"
ISSUES_RELPATH = "data/issues.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scraper",
        description=(
            "Scrape NPL 2026 and ShareSansar share-issue data and rebuild "
            "site/data and the calendar feeds."
        ),
    )
    parser.add_argument("--site-dir", default="site", help="output root (default: site)")
    parser.add_argument(
        "--from-dir",
        metavar="DIR",
        help="read teams/matches/points JSON (and optional issues/) from DIR, no network",
    )
    parser.add_argument("--dry-run", action="store_true", help="report changes, write nothing")
    parser.add_argument(
        "--allow-regression",
        action="store_true",
        help="permit fewer completed matches than the committed data (rule V15)",
    )
    return parser


def _report(violations: list[Violation]) -> None:
    in_actions = os.environ.get("GITHUB_ACTIONS") == "true"
    for violation in violations:
        print(f"error: {violation}", file=sys.stderr)
        if in_actions:
            print(f"::error title={violation.rule_id}::{violation.message}", file=sys.stderr)


def _previous_season(site_dir: Path) -> dict | None:
    """The committed season, when it is a valid-looking file for the same season."""
    try:
        season = json.loads((site_dir / DATA_RELPATH).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(season, dict):
        return None
    if season.get("schema_version") != config.SCHEMA_VERSION:
        return None
    if season.get("season", {}).get("year") != config.SEASON_YEAR:
        return None
    return season


def _issues_source(from_dir, session) -> dict | None:
    """Raw issue rows, or None when skipped (--from-dir without issues/). May raise ScrapeError."""
    if from_dir:
        return load_issues_from_dir(from_dir)
    return load_issues_remote(session)


def _build_issues(raw_issues: dict) -> tuple[dict | None, list[Violation]]:
    violations = issues.validate_issue_rows(raw_issues)
    if violations:
        return None, violations
    try:
        data = issues.normalize_issues(raw_issues)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        return None, [Violation("I3", f"issue rows could not be normalized: {exc}")]
    violations = issues.validate_issues(data)
    return (None, violations) if violations else (data, [])


def _build_npl(args, session, site_dir: Path):
    """``(season, violations)``: the validated season, or why the NPL source failed."""
    try:
        raw = load_from_dir(args.from_dir) if args.from_dir else load_remote(session)
    except ScrapeError as exc:
        return None, [Violation(exc.rule_id, exc.message)]

    try:
        season = normalize(raw)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        return None, [Violation("V2", f"source data could not be normalized: {exc}")]

    previous = _previous_season(site_dir)
    violations = validate(raw, season, previous, args.allow_regression)
    if violations:
        return None, violations

    # Stats are optional: when missing or invalid, keep the last published ones.
    stats_violations = validate_stats(raw)
    if raw.stats is not None and not stats_violations:
        season["stats"] = normalize_stats(raw)
    else:
        for violation in stats_violations:
            print(f"warning: stats skipped: {violation}", file=sys.stderr)
        season["stats"] = (previous or {}).get("stats")
    return season, []


def _fetch_issues(args, session):
    """``(issues_data, violations, skipped)`` for the share-issues source."""
    try:
        raw_issues = _issues_source(args.from_dir, session)
    except ScrapeError as exc:
        return None, [Violation(exc.rule_id, exc.message)], False
    if raw_issues is None:
        print("note: issues skipped (no DIR/issues/)", file=sys.stderr)
        return None, [], True
    data, violations = _build_issues(raw_issues)
    return data, violations, False


def main(argv: list[str] | None = None, session=None) -> int:
    args = _parser().parse_args(argv)
    site_dir = Path(args.site_dir)

    season, npl_violations = _build_npl(args, session, site_dir)
    issues_data, issue_violations, issues_skipped = _fetch_issues(args, session)

    npl_ok = season is not None
    issues_ok = not issue_violations  # skipped counts as ok
    _report(npl_violations)
    if not npl_ok:
        print(
            "error: npl source failed; kept the published NPL data and feeds", file=sys.stderr
        )
    _report(issue_violations)
    if not issues_ok:
        print(
            "error: issues source failed; kept the published issues data and feeds",
            file=sys.stderr,
        )
    if not npl_ok and (not issues_ok or issues_skipped):
        return 1

    outputs: dict[str, bytes] = {}
    if npl_ok:
        outputs[DATA_RELPATH] = publish.render_json(season)
        outputs.update(ics.build_calendars(season))
        print(
            f"fetched teams={len(season['teams'])} matches={len(season['matches'])} "
            f"standings={len(season['standings'])}"
        )
    if issues_data is not None:
        outputs[ISSUES_RELPATH] = publish.render_json(issues_data)
        outputs.update(issues_ics.build_issue_calendars(issues_data))
        dated = sum(1 for i in issues_data["issues"] if i["dates_announced"])
        print(f"fetched issues={len(issues_data['issues'])} dated={dated}")
    keep = {f"calendar/{name}.ics" for name in config.ISSUE_FEEDS}
    changed = publish.write_outputs(
        site_dir, outputs, dry_run=args.dry_run, prune=npl_ok, keep=keep
    )
    prefix = "would change" if args.dry_run else "changed"
    for relpath in changed:
        print(f"{prefix}: {relpath}")
    if not changed:
        print("no changes")
    return 0 if npl_ok and issues_ok else 3
