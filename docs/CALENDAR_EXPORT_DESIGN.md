# Maturity Calendar Export — Design Spec

This document specifies the maturity calendar export feature implemented in
`src/justfixed/exports/calendar.py`, and describes its as-built behavior. The
test suite in `tests/exports/test_calendar.py` is the executable form of this
spec.

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
- ~~Bank-of-custody field in the event description~~ — SHIPPED (B3):
  custodian appears as a "Custodiante:" line in the DESCRIPTION when set,
  omitted entirely when null.
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
def export_maturity_calendar(
    investments: list[Investment],
    *,
    as_of: date,
    assumed_cdi: Decimal,
    assumed_ipca: Decimal | None = None,
) -> bytes:
    """Generate an iCalendar (.ics) file with one event per upcoming maturity."""
```

Returns the .ics file as `bytes`; the caller writes it to disk. Investments
whose `maturity_date < as_of` are excluded (the boundary `maturity_date ==
as_of` is included). `assumed_cdi` is required for post-fixed investments and
`assumed_ipca` only when the portfolio holds IPCA-linked investments.

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

1. Call `project(investment, as_of=as_of, assumed_cdi=assumed_cdi, assumed_ipca=assumed_ipca)`.
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

Eleven tests in `tests/exports/test_calendar.py` (9 original + 2 added
for B3 custodian). The test list is the spec — implementation that
doesn't satisfy these tests is wrong.

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

5. **`test_event_description_includes_custodian_when_present`** *(B3)*
   Input: one CDB with `custodian="XP"`. Assert DESCRIPTION contains
   "Custodiante: XP" and that "XP" does NOT appear in SUMMARY (custodian
   is description-only).

6. **`test_event_description_omits_custodian_when_none`** *(B3)*
   Input: one CDB with `custodian=None`. Assert "Custodiante" does NOT
   appear anywhere in the DESCRIPTION (line is absent, not blank).

### Group C — Stability and filtering

7. **`test_event_uid_is_stable_across_exports`**
   Run the export twice on the same investment list. Assert the UIDs
   in the two outputs are identical. (DTSTAMP differs between runs;
   that's expected — only UID stability matters for calendar dedup.)

8. **`test_past_maturities_are_filtered_out`**
   Input: one investment with maturity 2024-01-01, as_of=2026-01-01.
   Output parses back to 0 VEVENTs.

9. **`test_maturity_on_as_of_date_is_included`** *(added at implementation)*
   Boundary case: maturity == as_of is included (still relevant today).

### Group D — Tax handling and validity

10. **`test_treasury_investment_uses_net_after_tax`**
    Input: one TESOURO_PREFIXADO with known principal and rate. Compute
    the expected net_at_maturity by hand (or via scratch script as we
    did for FGC test 9). Assert the SUMMARY contains the post-IR amount,
    not the gross.

11. **`test_ics_output_is_valid_format`**
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

`icalendar` is in `pyproject.toml` `[project.dependencies]`, pinned
`icalendar>=6.0,<7` — a loose floor that allows patch and minor updates
without a major-version surprise.

## How it was built

1. Created `src/justfixed/exports/__init__.py` and `tests/exports/__init__.py`
   (the package skeletons).
2. Added the `icalendar` dependency to `pyproject.toml` and ran
   `pip install -e .[dev]` to pick it up.
3. Wrote `tests/exports/test_calendar.py` (TDD — tests failed with
   `ImportError` until `exports/calendar.py` existed). For the Treasury
   net-amount test, a scratch script computed the exact `net_at_maturity`
   once and the resulting display string was hardcoded into the test.
4. Implemented `src/justfixed/exports/calendar.py` until the tests turned
   green.
5. Updated `docs/ARCHITECTURE.md` and `CLAUDE.md` (new `exports/` layer, the
   `exports/calendar.py` subsection, the status table, and removing
   "Maturity calendar / ICS export" from "What's next").

The custodian "Custodiante:" line in the DESCRIPTION was added later as B3,
bringing the suite to its current eleven tests.