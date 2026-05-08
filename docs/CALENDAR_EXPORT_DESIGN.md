# Maturity Calendar Export — Design Spec

This document specifies the maturity calendar export feature that will be
built in `src/justfixed/exports/calendar.py`. It is the input to the
implementation session; read it before writing any code.

## What it does

Given a portfolio of `Investment` objects, generates an iCalendar (.ics)
file containing one calendar event per investment that matures on or
after a given as-of date. Each event lists the maturity date, the issuer,
and the estimated net payout (post-IR). The user drags the file into
their calendar app (Google Calendar, Apple Calendar, etc.) and sees their
maturity dates as ordinary calendar entries.

## Scope

In scope for v1:
- One event per investment, at maturity_date
- Net amount (post-IR) shown in event title
- Future events only (filter by as_of)
- Stable UIDs for re-export deduplication (re-importing the same .ics
  updates existing events rather than creating duplicates)
- Returns bytes; caller writes to disk

Out of scope (deferred to future versions):
- Coupon payment events (juros mensais, juros semestrais)
- Bank-of-custody field in the event description
- Subscription URL / auto-refresh (would require server)
- Past events (lookback configuration)
- ICS export of FGC concentration warnings or other portfolio signals
- **Cleanup of orphaned events for removed investments.** If an
  investment is sold or otherwise removed from the portfolio, its
  previously-exported calendar event remains in the user's calendar.
  Re-importing the .ics file does NOT remove old events; calendar apps
  only update events whose UIDs appear in the new file. See
  "Future enhancements" below.

## Architectural placement

New top-level package `src/justfixed/exports/`. Layer ordering becomes:

  domain → persistence + engine → importers + exports → ui

Exports translate computed data into foreign formats. They depend on
domain types (Investment, Money) and on the engine (project() to compute
amounts). They do not depend on persistence — callers supply investments
already loaded.

For v1, only one file: `src/justfixed/exports/calendar.py`. Future
exports (CSV, PDF, Excel) live alongside it.

## Public API

```python

Notes on choices:

- **DTSTART/DTEND as DATE values, not DATETIME.** Maturities are
  conceptually all-day events; using DATE avoids timezone questions and
  matches how brokers display them.
- **DTEND is one day after DTSTART** because iCalendar treats DATE-form
  DTEND as exclusive. To make the event span only the maturity date,
  DTEND must be the *next* day.
- **UID is derived from `investment.id`** — stable across re-exports.
  If the user re-imports their statement and re-exports the calendar,
  same investment → same UID → calendar app updates the existing event
  rather than duplicating.
- **SUMMARY is short and information-dense.** Calendar apps truncate;
  the issuer name + net amount is what the user wants to see at a
  glance.
- **DESCRIPTION carries the full detail** — what the user wants when
  they click into the event for context.

## Net amount computation

For each investment:

1. Call `project(investment, as_of=as_of, assumed_cdi=assumed_cdi)`.
2. Use `result.net_at_maturity` as the calendar event's payout amount.

Why `net_at_maturity`:
- Treasury and CDB have IR withheld at maturity; the user's bank
  account receives the net.
- LCI/LCA are IR-exempt for individuals; gross == net for these.
- The projection engine handles both cases correctly via product rules.
- Net is what the user expects to receive — the calendar should reflect
  that, not pre-tax theoretical amounts.

## Filtering

After project() but before emitting events:

```python
if investment.maturity_date < as_of:
    continue
```

The boundary case `maturity_date == as_of` is included — a maturity
today is still in the future enough to put on the calendar.

## Calendar metadata

The VCALENDAR wrapper requires a few standard properties:

| Field | Value |
|---|---|
| `VERSION` | `"2.0"` (RFC 5545 standard) |
| `PRODID` | `"-//JustFixed//maturity-calendar//PT-BR"` |
| `METHOD` | omit (this is a static export, not a meeting invitation) |
| `X-WR-CALNAME` | `"JustFixed: Vencimentos"` (calendar name shown in some apps) |

## Test plan

Eight tests in `tests/exports/test_calendar.py`. The test list is the
spec — implementation that doesn't satisfy these tests is wrong.

### Group A — Empty and trivial

1. **`test_empty_portfolio_emits_empty_calendar`**
   Input: `investments=[]`. Output parses back via `icalendar.Calendar`
   and contains zero VEVENT components.

2. **`test_single_investment_emits_single_event`**
   Input: one CDB. Output has exactly 1 VEVENT. Its UID matches the
   expected pattern `justfixed-{uuid}-maturity@justfixed`.

### Group B — Event content

3. **`test_event_summary_includes_issuer_and_payout`**
   Input: one CDB. Parse the output, find the VEVENT, assert SUMMARY
   contains both the issuer name and an "R$" amount.

4. **`test_event_date_is_maturity_date`**
   Input: one CDB with maturity 2027-11-15. Parse output, assert
   DTSTART equals 2027-11-15 (as DATE, not DATETIME).

### Group C — Stability and filtering

5. **`test_event_uid_is_stable_across_exports`**
   Run the export twice on the same investment list. Assert the UIDs
   in the two outputs are identical. (DTSTAMP differs between runs;
   that's expected — only UID stability matters for calendar dedup.)

6. **`test_past_maturities_are_filtered_out`**
   Input: one investment with maturity 2024-01-01, as_of=2026-01-01.
   Output parses back to 0 VEVENTs.

### Group D — Tax handling and validity

7. **`test_treasury_investment_uses_net_after_tax`**
   Input: one TESOURO_PREFIXADO with known principal and rate. Compute
   the expected net_at_maturity by hand (or via scratch script as we
   did for FGC test 9). Assert the SUMMARY contains the post-IR amount,
   not the gross.

8. **`test_ics_output_is_valid_format`**
   Input: a small portfolio. Assert that `icalendar.Calendar.from_ical(output)`
   returns without raising. This is the smoke test that the output is
   parseable as iCalendar regardless of content.

### Test conventions

- Use the same `_bank` and `_cdb` helpers from `test_fgc.py` (or
  duplicate them if importing across test directories is awkward).
- For test 7 (net amount), use a scratch script the same way we did for
  FGC test 9 — compute the exact net_at_maturity once, hardcode the
  resulting display string in the test, document the computation in
  the test comment.

## Dependency

Add `icalendar` to `pyproject.toml` `[project.dependencies]`. As of May
2026, the current stable version is on PyPI. Pin loosely (e.g.,
`icalendar>=5.0,<7`) to allow patch updates without major-version
surprises.

## Order of work

1. Create `src/justfixed/exports/__init__.py` (empty) and
   `tests/exports/__init__.py` (empty) — the package skeletons.
2. Add `icalendar` dependency to pyproject.toml. Run `pip install -e .[dev]`
   to pick it up.
3. Write `tests/exports/test_calendar.py` with all 8 tests.
4. For test 7, write a scratch script to compute the exact
   net_at_maturity for the chosen Treasury investment. Hardcode the
   resulting display string in the test.
5. Tests fail with ImportError because `exports/calendar.py` doesn't
   exist yet — that's the expected state for this commit.
6. Implement `src/justfixed/exports/calendar.py`.
7. Tests turn green.
8. Update `docs/ARCHITECTURE.md` and `CLAUDE.md` to reflect:
   - New `exports/` layer in architectural shape
   - `exports/calendar.py` subsection
   - Status table updated
   - "What's next" — remove "Maturity calendar / ICS export"

Estimated total: ~1.5 hours, one session.