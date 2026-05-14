# JustFixed Architecture

This document is the map for an engineer joining the project. It explains *how* the codebase is organized, *why* it's organized that way, and *where* to look when adding a feature or fixing a bug.

## Audience

You are an engineer who knows Python, has used SQLAlchemy and pytest, and has a basic grasp of fixed-income investing. You don't need to know Brazilian financial markets in depth — this doc explains the relevant idiosyncrasies as they come up.

## Status

| Layer | Status | Test count |
|---|---|---|
| Domain | Complete | 151 |
| Persistence | Complete | 73 |
| Engine | Complete | 119 |
| Importer (parser, mapper) | Complete | 77 |
| Importer (loader / DB persistence) | Complete | 9 |
| UI (PySide6) | A′-plus complete (read-only viewer + dev tooling) | 0 |
| FGC concentration check | Complete | 13 |
| Exports (calendar / ICS) | Complete | 9 |

462 tests pass in ~5 seconds. If any test fails on a fresh checkout, treat that as the first bug to fix.

## Architectural shape

Clean architecture with strict dependency rules:

```
domain ←─── persistence
   ↑
   └────── engine
              ↑
              ├─── importers
              ├─── exports
              └─── ui ───────┐
                             │
                       depends on all
                       layers above
```

**Rules:**
- `domain` depends on nothing inside the project
- `persistence` and `engine` depend on `domain` only
- `importers` depend on `domain`, `engine`, `persistence`
- `exports` depend on `domain` and `engine` only (not persistence — callers supply loaded investments)
- `ui` depends on domain, persistence, engine, importers, and exports; nothing depends on `ui`

If you find yourself wanting `domain` to import from `engine`, or `persistence` to know about importers, **stop and reconsider**. The dependency direction is the architecture; violating it once gives permission to violate it again, and the project devolves.

---

## Domain layer (`src/justfixed/domain/`)

Pure value objects and entities. No I/O, no database, no time-of-day awareness. Every domain type validates its invariants in `__post_init__` — a malformed object cannot exist.

### `money.py`

Currency-safe `Decimal` arithmetic. Brazilian display format (`R$ 1.234,56`).

Key constraints:
- **Floats are rejected** at construction. `Money(0.01)` raises; you must pass `Decimal("0.01")` or use `Money.from_reais("0.01")`.
- **Cross-currency arithmetic raises** — you can't accidentally add R$ to USD.
- Money cannot be multiplied by Money (dimensional sanity).

### `rates.py`

A sealed hierarchy of four rate types. **The full taxonomy of Brazilian retail rate quotes:**

| Class | Quoted as | Math |
|---|---|---|
| `Prefixed` | "+12,00%" | `(1 + annual_rate)^(Du/252)` |
| `PostFixedCDI` | "95,50% CDI" | `(1 + cdi_pct × CDI_annual)^(Du/252)` |
| `PostFixedCDIPlusSpread` | "CDI +2,05%" | Fisher: `(1 + CDI + spread + CDI×spread)^(Du/252)` |
| `PostFixedIPCA` | "IPC-A +7,31%" | Fisher: `(1 + IPCA + spread + IPCA×spread)^(Du/252)` |

**Why four classes instead of one with a "kind" field?** Each type has different math and different inputs. Encoding that in the type system means:
- The accrual engine `match`-dispatches on type; adding a new rate kind is one new `case` arm and the existing arms keep working
- A future engineer can't accidentally pass a `PostFixedIPCA` to code that handles `Prefixed` — it won't typecheck
- Parsing failures land in one place (`parse_rate` in `importers/xp_mapper.py`)

**Critical correctness note:** `PostFixedCDI("110% CDI")` and `PostFixedCDIPlusSpread("CDI + 10%")` are **not the same**. Effective annual rates differ by ~700 basis points. Test `test_distinct_from_post_fixed_cdi_at_same_label` enforces this.

### `issuer.py`

Banks, treasuries, development banks. Has a `kind` (commercial_bank / development_bank / treasury) which gates two things:

- Which `ProductType`s this issuer is allowed to issue (e.g. only treasuries issue Tesouro)
- FGC coverage eligibility (treasuries are not FGC-covered)

Tesouro Nacional has a hard-coded factory `Issuer.treasury()` because there's only one of it.

### `product.py`

`ProductType` enum (CDB, LCI, LCA, LCD, LC, TESOURO_SELIC, TESOURO_PREFIXADO, TESOURO_IPCA) plus a `PRODUCT_RULES` table that's the **single source of truth** for:

- Which `IssuerKind`s can issue this product
- Tax treatment (`IR_REGRESSIVE` for CDB/LC/Tesouro; `IR_EXEMPT` for LCI/LCA/LCD)
- FGC coverage
- Allowed coupon frequencies (NONE / MONTHLY / SEMI_ANNUAL)
- Minimum term (LCD has a 365-day minimum)

If Brazilian regulation changes, **this table is where you change it**. The downstream code reads rules from this table at runtime.

### `investment.py`

The aggregate root. An `Investment` knows its product, issuer, principal, rate, dates, coupon frequency. Validates seven invariants in `__post_init__`:

1. Principal is positive
2. `maturity > issue_date` and `maturity > purchase_date`
3. `purchase_date >= issue_date` (secondary-market case: purchase later than issue)
4. The issuer's `kind` is valid for this product type
5. The coupon frequency is allowed for this product
6. The full security term meets product minimums (LCD)
7. Identity uses a UUID, not field-based equality

Two date fields exist:
- `issue_date`: when the security was originally issued
- `purchase_date`: when *this user* acquired it (may be later if bought on secondary market)

`security_term_days` (issue → maturity) and `holding_term_days` (purchase → maturity) are derived properties. The existing tests cover both primary and secondary market cases.

---

## Persistence layer (`src/justfixed/persistence/`)

SQLAlchemy 2.0 declarative. SQLite. The database lives at `~/.justfixed/justfixed.db` by default.

### `database.py`

Engine setup, session factory, and a `session_scope` context manager that handles commit/rollback. Every repository method uses `with session_scope() as session:` — short-lived sessions, no leaks.

SQLite-specific: foreign-key enforcement is not on by default. We turn it on via a `PRAGMA foreign_keys = ON` event listener on every new connection. **Don't remove this** — without it, FK constraints are silently ignored and dangling references creep in.

### `models.py`

ORM row classes (`IssuerRow`, `InvestmentRow`). These are *not* domain types — they're flat tables with strings, Decimals, dates, and `(rate_kind, rate_value)` two-column polymorphic rate encoding.

**The polymorphic rate encoding is load-bearing.** Storing rates as `(kind: str, value: Decimal)` means adding `PostFixedCDIPlusSpread` required *zero* schema change and *zero* migration — just a new kind value. If we'd modeled rates as separate columns per type, every new rate would mean a migration.

### `mappers.py`

Pure functions converting between domain types and ORM rows. **Mappers do no I/O** — they're testable without a database. The repository layer is what actually opens sessions.

`investment_from_row(row, issuer)` re-runs domain validation when reconstructing — meaning a corrupt database row fails to load with a clear error rather than producing a half-broken Investment. This is paranoid, in a good way.

### `repositories.py`

`IssuerRepository` and `InvestmentRepository`. Methods use `session.merge()` for upserts, open short-lived sessions per operation, and order results predictably (issuers by name, investments by maturity).

`InvestmentRepository.save()` requires the issuer to already exist (FK constraint). The "always save the issuer first" workflow is enforced by the database, not by trust.

### Migrations (`alembic/`)

Workflow:

```powershell
# Edit src/justfixed/persistence/models.py
alembic revision --autogenerate -m "describe change"
# Review the generated file in alembic/versions/
alembic upgrade head
git add . && git commit -m "..."
```

The autogeneration is good but not perfect. Always review what's generated.

---

## Engine layer (`src/justfixed/engine/`)

Pure financial logic. No DB, no I/O. Inputs are domain types and assumption parameters; outputs are domain types or structured results.

### `calendar.py`

Wraps the `bizdays` library against the ANBIMA Brazilian holiday calendar. Provides:

- `business_days_between(start, end)` — half-open interval `[start, end)`
- `is_business_day(date)`
- `add_business_days(date, n)` — handles negatives
- `next_business_day(date)` — used to roll coupon dates off weekends/holidays

`BUSINESS_DAYS_PER_YEAR = 252`. This is the **convention**, not a literal count. Real years have 250-254 business days; rate math always divides by 252 regardless. This is correct per Brazilian market practice.

### `accrual.py`

The 252-basis math. One function:

```python
accrue(principal, rate, business_days, *, assumed_cdi=None, assumed_ipca=None)
```

Dispatches on rate type via `match`. PostFixedCDI and PostFixedCDIPlusSpread require `assumed_cdi`; PostFixedIPCA requires `assumed_ipca`. Missing-required-assumption raises a clear `ValueError`.

**The "assumed" parameters exist because CDI and IPCA are post-fixed**: their actual values are only known after the fact. Phase 1 (current) takes user-provided assumptions. Phase 2 will replace assumptions with historical data from B3 and IBGE — but the engine signature doesn't change, only how the parameter values are computed before calling.

### `tax.py`

Brazilian IR (Imposto de Renda):

- **Regressive table** for CDB/LC/Tesouro — 22.5% / 20% / 17.5% / 15% by holding period in **calendar days** (not bizdays — this is per IN RFB 1585/2015)
- **Exempt** for LCI/LCA/LCD (pessoa física)

Tax is on **gain**, not principal. `compute_ir(principal, gross, treatment, holding_days)` returns a `TaxResult` with the full breakdown so the UI can show "gross R$ 11,200 − IR R$ 180 = net R$ 11,020".

The bracket boundaries use `<=` (day 180 → 22.5%, day 181 → 20%). Off-by-one errors at boundaries are a frequent class of tax bug; the explicit boundary tests catch them.

### `cashflow.py`

Generates the schedule of payments an investment will produce.

For bullets (most products): one `CashFlow` at maturity, kind `PRINCIPAL`.

For coupon products (Tesouro Prefixado/IPCA com Juros, some CDBs): N coupons + final `COUPON_AND_PRINCIPAL` payment. Coupon dates are computed by walking *backward* from maturity in 1- or 6-month steps, then rolling forward to the next business day if a coupon would fall on a weekend or holiday.

Each coupon's amount is the interest accrued over its period — the principal stays at face value, and the final payment combines the last coupon with principal. This is the standard Brazilian convention for these securities. It's a simplification relative to constant-coupon Tesouro Prefixado bonds, but appropriate for our accrual-only engine; documented in the module docstring.

### `projection.py`

The engine's top-level API. **One function, one result type.** Everything downstream calls this:

```python
project(investment, *, as_of, assumed_cdi=None, assumed_ipca=None) → ProjectionResult
```

`ProjectionResult` contains: `current_value`, `cash_flows`, `gross_at_maturity`, `tax_breakdown`, `net_at_maturity`. Plus convenience properties (`gain_at_maturity`, `tax_amount`).

Behavior at edges:
- `as_of < purchase_date`: `current_value == principal` (hasn't started)
- `as_of >= maturity_date`: `current_value == gross_at_maturity` (capped, no extrapolation past maturity)
- otherwise: accrual from purchase to as_of

**Documented simplification:** for coupon products, IR is computed on the *total gain* using the holding-period bracket. The real Brazilian rule withholds per coupon at its own date (early coupons get worse brackets). The current behavior produces slightly more favorable numbers; refining is a future enhancement.

### `fgc.py`

Computes per-conglomerate FGC exposure. Given a list of investments and an as-of date, returns an `FGCReport` listing each conglomerate's current and peak gross exposure with status flags (under, approaching, over the R$250k limit). Treasury holdings are filtered out (FGC doesn't cover sovereign debt). Investments are grouped by `issuer.conglomerate`; issuers whose conglomerate begins with `UNVERIFIED_CONGLOMERATE_PREFIX` are flagged as needing human review. Peak exposure is a deliberate conservative overestimate — each investment's value at its own maturity, summed; simultaneous peaks are physically impossible but the false positive is safe.

---

## Importers (`src/justfixed/importers/`)

The XP Investimentos pipeline is split into three layers, all complete. Multi-broker importers (BTG, Itaú, Nu) are Phase 2.

### Layer 1: `xp.py` — XLSX → strings

`read_renda_fixa_rows(path) → list[XPRow]`

Walks the XLSX, finds the `Renda Fixa` section, slices each rate sub-section (Pós-Fixado / Prefixado / Inflação), and returns one `XPRow` per position. Every field is a raw string exactly as it appeared in the spreadsheet — no parsing yet.

State machine handles:
- Top-level groups before Renda Fixa (Previdência Privada, Fundos de Investimentos) — skipped silently
- Section-header rows that *also* contain the column labels (XP-specific layout quirk)
- Blank-row separators between sections
- Variable trailing columns (some rows in real files have fewer than 13 cells)

### Layer 2: `xp_mapper.py` — strings → typed values

Five small parsers, each tested in isolation, then composed:

| Parser | Input → Output |
|---|---|
| `parse_brazilian_money` | `"R$ 45.000,00"` → `Money` |
| `parse_brazilian_date` | `"02/04/2025"` → `date(2025, 4, 2)` |
| `parse_rate` | `"95,50% CDI"` → `PostFixedCDI(0.955)` |
| `parse_product_and_coupon` | `"LCI CEF - JURO MENSAL - ABR/2027"` → `(LCI, MONTHLY)` |
| `parse_issuer_name` | `"LCA BANCO BV S/A - JURO MENSAL - MAR/2029"` → `"BANCO BV S/A"` |

**Strict parsing**: malformed input raises `ValueError` with a contextual message. We do not silently default. A future XP format change will fail loudly rather than producing wrong numbers.

The composition function `parse_row(XPRow) → ParsedXPRow` produces a typed bundle but **does not create an `Issuer` instance**. That's deliberate: the parser is database-free, fully unit-testable.

### Layer 3: `xp_loader.py` — parsed rows → persisted Investments

The seam between "data parsed from a spreadsheet" and "rows in the database." Public surface is one function:

```python
def load_xp_statement(path: Path, session_factory) -> LoadResult:
    ...
```

It reads the file via layer 1, parses each row via layer 2, then for each parsed row resolves the issuer (creating if needed) and persists the Investment (or skips if already present). Returns a `LoadResult` summarizing what happened: `inserted`, `skipped`, `issuers_created`, `issuers_reused`.

#### Issuer reconciliation

Issuer matching uses **normalized name** as the key. `Issuer.normalize_name(s)` is the classmethod: strip outer whitespace, collapse internal whitespace, uppercase. Punctuation and accents are preserved — `"Banco BV S/A"` and `"Banco BV SA"` stay distinct, as do `"Itaú"` and `"Itau"`.

The normalized form is stored on `IssuerRow.normalized_name` with a unique database index. Two issuers cannot share a normalized name; the database enforces this, not application code.

Treasury rows route specially: parsed name `"Tesouro Nacional"` resolves via `Issuer.treasury()` (the canonical factory with the right CNPJ and `IssuerKind.TREASURY`). Everything else creates as `IssuerKind.COMMERCIAL_BANK` with conglomerate marked unverified — see below.

#### The `[unverified]` conglomerate convention

The loader has only one piece of issuer information: the parser-emitted name. It can't know whether `"BMG"` and `"PAN"` belong to the same conglomerate, or whether `"CEF"` is part of a holding company. So new commercial-bank issuers are created with `conglomerate=f"[unverified] {name}"` — a string convention that signals "this needs human review."

The FGC concentration check (when built) will surface these for the user to merge into real conglomerates. Until then, the prefix is honest about what we don't know. This is a string convention, not a schema constraint, so future migration to a nullable conglomerate field is a one-line UPDATE.

The constant `UNVERIFIED_CONGLOMERATE_PREFIX` is exported from `xp_loader` for callers (notably the FGC layer) to import.

#### Investment idempotency

Re-importing the same statement does not duplicate investments. The natural key is the 5-tuple `(issuer_id, product, principal, purchase_date, maturity_date)`. Before insert, the loader queries `InvestmentRepository.find_by_natural_key(...)`; if a match exists, the row is skipped.

There is **no unique constraint** on this key in the database. A user can legitimately hold two identical positions through separate orders; the database doesn't reject this, it's the importer's idempotency contract that prevents accidental re-insertion. Other entry paths (manual UI entry in Phase 2) are free to create natural-key duplicates.

#### Lessons from real-world data

The synthetic fixture (6 rows, all 4 rate types) is not enough. Running against a real `PosicaoDetalhada.xlsx` (~94 positions) immediately surfaced one over-strict rule: the domain rejected LCAs with monthly coupons, but real LCAs in the Brazilian market commonly pay monthly. The fix was a one-line domain change (`allowed_coupons=frozenset(CouponFrequency)` for LCA), discovered only because real data forced it. **Audit when crashes happen, not preemptively.** The rule for LCI is still NONE-only and stays that way until a real LCI-with-coupons crashes the loader.

Further examples from the A′-plus testing cycle (commits `0099c02`, `897e66e`, `f975aad`, `1582ee5`):

- **LCAs from development banks rejected by `ProductRule`.** The issuer-kind constraint was a single value; generalized to a frozenset so both commercial and development banks can issue LCA.
- **BDMG created as a commercial bank.** BDMG is a development bank; the loader gained an explicit `_DEVELOPMENT_BANK_NAMES` lookup set so known development banks get the right `IssuerKind` at creation time.
- **Parser read past the Renda Fixa section.** The XLSX has non-investment sections (Dividendos, Custódia Remunerada) after Renda Fixa. The parser gained a `_RENDA_FIXA_TERMINATORS` frozenset; hitting a terminator string breaks the reading loop.

---

## Exports (`src/justfixed/exports/`)

Translates computed data into foreign formats. Depends on domain types and
the engine; does not touch persistence — callers supply investments already
loaded from wherever they came from.

### `calendar.py`

```python
export_maturity_calendar(
    investments: list[Investment],
    *,
    as_of: date,
    assumed_cdi: Decimal,
    assumed_ipca: Decimal | None = None,
) -> bytes
```

Generates an iCalendar (.ics) file with one VEVENT per investment that matures
on or after `as_of`. The user drags the file into Google Calendar, Apple
Calendar, etc. and sees maturity dates as ordinary calendar entries.

Design choices:
- **DTSTART/DTEND as DATE (not DATETIME).** Maturities are conceptually all-day
  events; DATE avoids timezone questions.
- **DTEND is maturity + 1 day.** iCalendar treats DATE-form DTEND as exclusive.
- **UID derived from `investment.id`.** Stable across re-exports — re-importing
  updates existing events rather than creating duplicates.
- **SUMMARY shows post-IR net amount.** That's what the user's bank account
  receives; gross would be misleading.
- **Orphan cleanup deferred to v2.** Removed investments leave stale events in
  the user's calendar. Re-importing only updates/adds; calendar apps don't
  delete absent UIDs.

---

## UI layer (`src/justfixed/ui/`)

### `main.py`

PySide6 single-window desktop application. Imports an XP statement, displays investments in a read-only table with per-row FGC concentration badges, projects current values as of today, and exports the maturity calendar to an `.ics` file. Background work (statement loading, projection) runs on `QThread` workers; a single `_set_busy` guard prevents overlapping operations. Empty state (no investments loaded) swaps the table for a centered prompt via `QStackedWidget`.

The module imports from `domain`, `persistence`, `engine.projection`, `engine.fgc`, `exports.calendar`, and `importers.xp_loader`. It introduces no new architectural layer between itself and those — direct calls, no service or presenter layer.

CDI is hardcoded as a module-level constant (`_ASSUMED_CDI`) for postfixed-rate projections. Replace with the current Selic/CDI value at each rebuild until ROADMAP B10 (real index data fetching) is implemented.

This module has no automated tests by deliberate design — UI verification is the human "build, run, look at it" loop, per `docs/UI_DESIGN.md`. Backend changes touched by UI work are still tested at the engine/persistence level.

See `docs/UI_DESIGN.md` for the design rationale, milestone A′ scope, and the deferred B′/C′ surfaces (curation, manual-entry form, projection detail view).

---

## Test discipline

**462 tests, ~5 second runtime, no skips.** The test suite is the spec; if behavior changes, the test changes first.

### Test organization mirrors source

```
tests/
  domain/
  persistence/
  engine/
  importers/
    fixtures/
      synthetic_xp_statement.xlsx  # 6 rows, all 4 rate types, JURO MENSAL coverage
```

### Conventions

- **One concern per test method.** Don't bundle "test creation and validation" — split into `test_creates_correctly` and `test_rejects_invalid`.
- **Test names are specs.** `test_distinct_from_post_fixed_cdi_at_same_label` says exactly what it asserts.
- **Brazilian-finance tests use exact expected values, not approximations.** The expected number should be verified by hand or by running the function once and copying the result. Tolerances are at most a few cents, *not* dozens.
- **Property tests where they apply.** `test_full_year_equals_two_half_years` (compounding consistency) and `test_net_plus_tax_equals_gross` (invariant) catch entire bug classes.

### Running tests

```powershell
# Full suite
pytest tests/ -v

# One file
pytest tests/engine/test_accrual.py -v

# Stop on first failure with short traceback
pytest tests/ -v --tb=short -x
```

---

## Things that have caused trouble

A short list of footguns this project has hit. If you encounter one, you're not alone.

### Indentation on multi-line paste

Python is unforgiving about indentation. VS Code sometimes auto-indents in surprising ways when pasting a method into an existing class. Three-space indentation creeping in where 4-space should be is the most common silent corruption.

**Defense:** turn on **View → Render Whitespace** in VS Code. Mixed tabs/spaces and 3-vs-4-space indentation become visually obvious.

After every multi-line paste:
```powershell
Get-Content path/to/file.py -Tail 5
```
to verify the file ends where it should.

### PowerShell command concatenation

Pasting `pytest tests/ -v` immediately followed by `git add .` on the same physical line produces `pytest tests/ -vgit add .` and chaos. Always one command per line.

### Test expected values for financial code

Decimals are *exact*; mental approximations are not. A 1-year CDB at "110% CDI, CDI=12%" doesn't yield exactly R$ 11,320 — it yields R$ 11,325.57 because the year is 253 business days, not 252. Off-by-cent test failures usually mean *the expected value was approximated* rather than that the code is wrong.

**Defense:** when writing financial tests, run the function once first to find the actual output, then hard-code that as the expected. Use a few-cent tolerance only to absorb representational artifacts, not "I'm not sure of the exact answer."

### Module file vs test file confusion

When `xp_mapper.py` and `test_xp_mapper.py` are both open, pasting into the wrong one is easy. **Always glance at the title bar before pasting.**

---

## Conventions

### Code style

- Type hints everywhere. `from __future__ import annotations` at the top of every file.
- `Decimal` for money, never `float`.
- Frozen dataclasses for value objects; UUID-keyed dataclasses for entities.
- Docstrings on public functions describing inputs, outputs, and `Raises`.
- Comments explain *why*, not *what*. The code is the *what*.

### Git

One change per commit. Commit messages are imperative ("Add X" / "Fix Y") and describe the change, not the file. Tests pass on every commit.

### Dependencies

The project uses what's in `pyproject.toml` and nothing else. Don't add a new dependency without reading what existing code does — Decimal handles math, openpyxl handles XLSX, bizdays handles holidays. Most "I need a library for this" reactions are wrong.

---

## What's next

In rough order:

1. **UI — milestone B′ (curation)** — extend `ui/main.py` to support reviewing and editing `[unverified]` conglomerate values inline, with autocomplete from existing DB values. Resolves the deferred contract created by the loader's `[unverified]` prefix convention. See `docs/UI_DESIGN.md`. ~2-3 sessions.
2. **UI — milestone C′ (manual entry, detail view)** — manual-entry form for investments outside XP statements, per-investment detail view (accrual breakdown, IR tax, net at maturity). ~3-4 sessions.
3. **Windows installer** — PyInstaller + Inno Setup. 1-2 sessions.

Phase 2 (post-MVP):
- DI-curve mark-to-market
- Real index data fetching (B3 for CDI history, IBGE for IPCA)
- Multi-broker importers (BTG, Itaú, Nu)
- Backup/restore for the SQLite database

---

## When you get stuck

The codebase is small enough to grep through. Three useful starting points:

- **What does feature X do?** Find its top-level entry point — usually a function in `engine/projection.py` or `importers/`. Read the test file for that module; tests are concrete examples.
- **Why does the code look like this?** Check the commit history. Each commit is one focused change with a message describing the *why*.
- **What's the right way to add a new feature?** If it's a new rate type, follow `PostFixedCDIPlusSpread`'s footprint (commit `fb1c37c`). If it's a new product type, look at how LCD was added with its 365-day minimum-term rule. Patterns repeat; find the most similar existing thing and follow its shape.

If a test is hard to write, the *code* is probably wrong, not the test.
