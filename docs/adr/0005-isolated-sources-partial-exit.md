# ADR-5 — Sources are isolated; exit 3 means partial; git stays the last good store per source

- Status: accepted
- Date: 2026 (build time)
- Amends: ADR-3

## Context

AC-4 needs each source (NPL, ShareSansar) to refresh even when the other fails. ADR 0003's
"any failure exits 1 before a single file is touched" would let one flaky source freeze both.
Exiting 0 on a partial failure would hide the outage, because GitHub emails only on failed
runs.

## Decision

Each source fetches, validates and builds in memory on its own, and only a fully valid source
contributes outputs. Exit 0 = all ok, 3 = at least one source failed and the others were
written, 1 = nothing written, 2 = usage. Orphan pruning runs only when the NPL source
succeeded, and never touches the issue feeds. The workflow commits and deploys on 0 and 3,
then a `report` job fails the run on 3. That job reads the job output of a *successful*
scrape job, so nothing relies on outputs from failed jobs, which the docs do not promise.

## Consequences

- A partial run publishes and is red. Exit 1 keeps ADR 0003's meaning, and a crash (also 1)
  is never committed.
- Any future source must plug into the same per-source contract.
