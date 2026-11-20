"""scrape.yml maps the partial exit code to a red run after committing (AC-4, ADR 0005)."""

import re
from pathlib import Path

WORKFLOW = (Path(__file__).parent.parent / ".github" / "workflows" / "scrape.yml").read_text()


def _job(name):
    match = re.search(rf"^  {name}:\n(.*?)(?=^  \w[\w-]*:\n|\Z)", WORKFLOW, re.S | re.M)
    assert match, f"job {name} missing"
    return match.group(1)


def test_partial_exit_commits_then_fails_the_run():
    scrape = _job("scrape")
    assert "id: scrape" in scrape
    run = scrape[scrape.index("run: |") :]
    assert "set +e" in run
    assert run.index("set +e") < run.index("python -m scraper")
    lines = [line.strip() for line in run.splitlines()]
    assert lines[lines.index(next(x for x in lines if x.startswith("python -m scraper"))) + 1] == (
        "code=$?"
    )
    assert "partial: ${{ steps.scrape.outputs.partial }}" in scrape
    assert '"$code" -eq 3' in scrape
    assert "partial=true" in scrape
    assert '"$code" -ne 0 ] && [ "$code" -ne 3 ]' in scrape
    # the commit step runs after the scrape step with no `if:` that skips it on exit 3
    assert scrape.index("id: scrape") < scrape.index("id: commit")
    commit = scrape[scrape.index("Commit data if changed") :]
    assert "if:" not in commit.split("run:")[0]
    assert 'git commit -m "chore(data): refresh data"' in commit

    report = _job("report")
    assert "needs: scrape" in report
    assert "needs.scrape.outputs.partial == 'true'" in report
    assert "exit 1" in report
    assert "::error::" in report
