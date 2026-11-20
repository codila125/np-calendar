# ADR-6 — Derived issue events get suffixed UIDs; units-less issues use `na`

- Status: accepted
- Date: 2026 (build time)
- Extends: ADR 0004

## Context

Listing days and right-share book closures become their own calendar events beside each
application event. Subscribers' calendars key events on `UID` (ADR 0001, ADR 0004). Live
debentures include a row with no `total_units`, which the ADR 0004 id needs.

## Decision

```
UID = issue-<id>-listing@codila125.github.io
UID = issue-<id>-bookclosure@codila125.github.io
```

`<id>` is the ADR 0004 id. The application UID stays `issue-<id>@…`. When `total_units` is
null or empty the `units_key` is `na` (`debenture-1254-na`). No date enters any UID.

## Consequences

- Postponed listings and book closures update in place.
- The events of one issue never collide.
- Filling in units later changes that issue's UIDs once (delete + create).
- Changing the suffixes later duplicates events for every subscriber (hard to reverse —
  therefore recorded).
