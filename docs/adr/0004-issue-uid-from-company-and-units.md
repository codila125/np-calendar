# ADR-4 — Share-issue UID is `issue-<category>-<companyid>-<units>@codila125.github.io`

- Status: accepted
- Date: 2026 (build time)

## Context

Subscribers' calendars key events on `UID` (RFC 5545 §3.8.4.7, ADR 0001). ShareSansar has no
issue id. `companyid` repeats within a category (four right-share companies appear twice in
one page), and `DT_Row_Index` is positional. Dates are announced late and get postponed or
extended, so a date-based UID would churn exactly when users care.

## Decision

```
id  = <category slug>-<companyid>-<units_key>
UID = issue-<id>@codila125.github.io
```

`units_key` is `total_units` with fractional trailing zeros and a bare `.` removed
(`600000.00` → `600000`, `18512792.20` → `18512792.2`).

Rows with the same base id are first collapsed when they are identical after normalisation.
The rest are ordered by opening date (undated last). The first keeps the base id; each later
one gets `-<YYYYMMDD of opening>`, or `-tba` when undated. An id that still collides is
violation `I5`, and the issues source fails. Seen live: company 527 right shares, two rows of
`5670000.00` units in 2020 and 2021.

The same `UID` appears in `issues.ics` and in the category feed.

## Consequences

- Extensions and postponements update in place, because dates are not part of the `UID`.
- A units revision, or an older colliding row leaving the 50-row window, changes a `UID`
  (one delete + create for subscribers).
- Changing the scheme later duplicates events for everyone who imported a feed (hard to
  reverse — therefore recorded).
