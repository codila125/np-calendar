"""``python -m scraper``: fetch/load -> normalize -> validate -> build -> publish.

Exit codes: ``0`` success (changed or unchanged), ``1`` any ``ScrapeError`` or
validation failure (NPL or share issues), ``2`` usage error (argparse). No file
under the site dir is touched before every output has been built and validated
in memory (ADR-3).
"""

import argparse
import json
import os
import sys
from pathlib import Path

from . import config, ics, issues, publish
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


def main(argv: list[str] | None = None, session=None) -> int:
    args = _parser().parse_args(argv)
    site_dir = Path(args.site_dir)

    try:
        raw = load_from_dir(args.from_dir) if args.from_dir else load_remote(session)
    except ScrapeError as exc:
        _report([Violation(exc.rule_id, exc.message)])
        return 1

    try:
        season = normalize(raw)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        _report([Violation("V2", f"source data could not be normalized: {exc}")])
        return 1

    previous = _previous_season(site_dir)
    violations = validate(raw, season, previous, args.allow_regression)
    if violations:
        _report(violations)
        return 1

    # Stats are optional: when missing or invalid, keep the last published ones.
    stats_violations = validate_stats(raw)
    if raw.stats is not None and not stats_violations:
        season["stats"] = normalize_stats(raw)
    else:
        for violation in stats_violations:
            print(f"warning: stats skipped: {violation}", file=sys.stderr)
        season["stats"] = (previous or {}).get("stats")

    # Interim rule (until source isolation): any issues failure exits 1, nothing written.
    try:
        raw_issues = _issues_source(args.from_dir, session)
    except ScrapeError as exc:
        _report([Violation(exc.rule_id, exc.message)])
        return 1
    issues_data = None
    if raw_issues is None:
        print("note: issues skipped (no DIR/issues/)", file=sys.stderr)
    else:
        issues_data, issue_violations = _build_issues(raw_issues)
        if issue_violations:
            _report(issue_violations)
            return 1

    outputs = {DATA_RELPATH: publish.render_json(season), **ics.build_calendars(season)}
    print(
        f"fetched teams={len(season['teams'])} matches={len(season['matches'])} "
        f"standings={len(season['standings'])}"
    )
    if issues_data is not None:
        outputs[ISSUES_RELPATH] = publish.render_json(issues_data)
        dated = sum(1 for i in issues_data["issues"] if i["dates_announced"])
        print(f"fetched issues={len(issues_data['issues'])} dated={dated}")
    changed = publish.write_outputs(site_dir, outputs, dry_run=args.dry_run)
    prefix = "would change" if args.dry_run else "changed"
    for relpath in changed:
        print(f"{prefix}: {relpath}")
    if not changed:
        print("no changes")
    return 0
