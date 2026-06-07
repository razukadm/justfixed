# JustFixed Architecture

This document is the map for an engineer joining the project. It explains *how* the codebase is organized, *why* it's organized that way, and *where* to look when adding a feature or fixing a bug.

## Audience

You are an engineer who knows Python, has used SQLAlchemy and pytest, and has a basic grasp of fixed-income investing. You don't need to know Brazilian financial markets in depth — this doc explains the relevant idiosyncrasies as they come up.

## Status

| Layer | Status | Test count |
|---|---|---|
| Domain | Complete | 207 |
| Persistence | Complete | 100 |
| Engine | Complete | 194 |
| Importers | Complete — XP, BTG, and BB pipelines all three layers done | 274 |
| UI (PySide6) | A′, A′-plus, B′, B′ companion, B24, B9a, B27, C′, B34, B41, B44, B22, and Curve Inspector complete | 489 |
| Exports (calendar / ICS) | Complete | 11 |
| Tools (admin scripts) | Complete | 71 |
| Build info | Complete | 3 |

1349 tests pass in ~16 seconds. If any test fails on a fresh checkout, treat that as the first bug to fix.

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

Banks, treasuries, development banks. Has a `kind` — one of the twelve `IssuerKind` values (bank subtypes, Caixa Econômica, finance/credit companies, cooperatives, treasury, and others) — which gates two things:

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

The aggregate root. An `Investment` knows its product, issuer, principal, rate, dates, coupon frequency. Validates six invariants in `__post_init__`:

1. Principal is positive
2. `maturity > issue_date` and `maturity > purchase_date`
3. `purchase_date >= issue_date` (secondary-market case: purchase later than issue)
4. The issuer's `kind` is valid for this product type
5. The coupon frequency is allowed for this product
6. The full security term meets product minimums (LCD)

Identity is by UUID, not field-based equality — a property of the entity enforced via `__eq__`/`__hash__`, not a `__post_init__` check.

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

A third row class, `CurationMemoryRow`, maps normalized issuer names to curated conglomerate strings (table `curation_memory`). The primary key is the normalized name, enforcing at most one curated entry per issuer. The separate table is deliberate: curation is a research artifact (which Brazilian banks roll up to which conglomerates) that should survive Clear DB, so it lives apart from `IssuerRow`.

### `mappers.py`

Pure functions converting between domain types and ORM rows. **Mappers do no I/O** — they're testable without a database. The repository layer is what actually opens sessions.

`investment_from_row(row, issuer)` re-runs domain validation when reconstructing — meaning a corrupt database row fails to load with a clear error rather than producing a half-broken Investment. This is paranoid, in a good way.

### `repositories.py`

`IssuerRepository` and `InvestmentRepository`. Methods use `session.merge()` for upserts, open short-lived sessions per operation, and order results predictably (issuers by name, investments by maturity).

`InvestmentRepository.save()` requires the issuer to already exist (FK constraint). The "always save the issuer first" workflow is enforced by the database, not by trust.

`CurationMemoryRepository` exposes `get`, `set`, `list_all`, and `delete` against the curation memory table. The same session-handling pattern applies: one short-lived session per method call, `session.merge()` for upserts (so re-curating an existing entry preserves `created_at` while advancing `updated_at`). It is consumed by all three loaders (XP, BTG, BB) on the issuer-create path, and written by the shipped conglomerate-curation UI (B′) and the seed loader's first-run import (B9a Phase 3).

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

There is a **second migration mechanism** alongside Alembic: `persistence/migrations.py`, a PRAGMA `user_version` runner (`run_migrations(engine)`). It applies ordered, idempotent steps on startup — currently `_migrate_0_to_1`, which adds the `custodian` column and backfills it from import provenance (B42). Alembic is the dev-time, autogenerated schema history (its versions stop at the `source` column); the `user_version` runner is the runtime path that brings an existing user database up to date on launch. New runtime steps append a `(target_version, migrate_fn)` tuple and must be idempotent under re-run.

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

The engine exposes two FGC report functions. `fgc_concentration_report(investments, as_of, assumed_cdi)` is the original API: takes raw investments, projects each internally, aggregates. `fgc_concentration_report_from_projections(projections)` takes already-computed `ProjectionResult` instances and aggregates without re-projecting. Both produce the same `FGCReport` and share their aggregation logic via the private helper `_build_report_from_projections`. The UI uses the second function from two call sites: `_ProjectWorker` (project once, FGC over results) and `refresh_table` (FGC over cached projections after a conglomerate edit). The first function remains for callers that don't have projections pre-computed.

### `back_solve.py`

Inverse projection for FGC-aware principal sizing. Single public function:

```python
max_principal_under_fgc(
    issuer, product, rate, purchase_date, maturity_date,
    existing_holdings, assumed_cdi, assumed_ipca,
) → BackSolveResult
```

At each sample date `d` (the mock's purchase and maturity dates, plus
every same-conglomerate existing holding's maturity that falls in the
holding window), evaluates the closed-form per-date bound
`(cap - existing_total(d)) / growth(d)` and takes the minimum across
all sample dates. The closed-form sweep is valid because between any
two consecutive sample dates `existing_total` is constant and the
mock's growth factor is monotonically increasing, so the binding
constraint within each segment always occurs at its later endpoint —
checking the finite set of sample dates is sufficient. Returns the
minimum bound as `max_principal`, together with the binding date and
peak utilization ratio. Supports all four rate types. Used exclusively
by the Calculator tab (B41) Solve mode; the UI is the only caller.

---

## Importers (`src/justfixed/importers/`)

The XP Investimentos, BTG Pactual, and Banco do Brasil pipelines are each split into three layers, all complete. A broker-detection layer (`importers/detection.py`) dispatches to the appropriate loader. Further multi-broker importers (Itaú, Nu) are Phase 2.

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

The loader first looks up by normalized name. If found, the existing issuer is returned untouched — its persisted conglomerate is never overwritten, even if curation memory holds a different value for that name. This is what allows manual conglomerate edits (when the curation UI lands) to survive re-import of the same statement.

If no existing issuer matches, the loader creates one. The create path branches two ways:

- **Treasury** (parsed name `"Tesouro Nacional"`): resolves via `Issuer.treasury()`, the canonical factory with the right CNPJ and `IssuerKind.TREASURY`. Treasury doesn't participate in conglomerate curation — its conglomerate is hardcoded — so curation memory is bypassed here.
- **Everything else**: the `IssuerKind` is decided by `classify_issuer_kind` (the shared `_kind_catalog` lookup — e.g. `BDMG` → `DEVELOPMENT_BANK`, POUPEX → `SAVINGS_LOAN_ASSOCIATION`, default `COMMERCIAL_BANK`). The conglomerate comes from curation memory if a curated entry exists; otherwise it falls back to the `[unverified]` prefix.

#### The `[unverified]` conglomerate convention

The loader has only one piece of issuer information: the parser-emitted name. It can't know whether `"BMG"` and `"PAN"` belong to the same conglomerate, or whether `"CEF"` is part of a holding company. So new commercial-bank issuers are created with `conglomerate=f"[unverified] {name}"` — a string convention that signals "this needs human review."

The FGC concentration check (`engine/fgc.py`) surfaces these for the user to merge into real conglomerates. Until that merge happens, the prefix is honest about what we don't know. When the user does merge (via the curation UI, milestone B′ — shipped), the merge writes to curation memory, and re-importing the same statement preserves the merge. This is a string convention, not a schema constraint, so future migration to a nullable conglomerate field is a one-line UPDATE.

The constant `UNVERIFIED_CONGLOMERATE_PREFIX` lives in `domain/issuer.py` and is imported by both the loader (writing) and the FGC engine (reading).

#### Investment idempotency

Re-importing the same statement does not duplicate investments. The natural key is the 5-tuple `(issuer_id, product, principal, purchase_date, maturity_date)`. Before insert, the loader queries `InvestmentRepository.find_by_natural_key(...)`; if a match exists, the row is skipped.

There is **no unique constraint** on this key in the database. A user can legitimately hold two identical positions through separate orders; the database doesn't reject this, it's the importer's idempotency contract that prevents accidental re-insertion. Other entry paths (manual UI entry in Phase 2) are free to create natural-key duplicates.

#### Lessons from real-world data

The synthetic fixture (6 rows, all 4 rate types) is not enough. Running against a real `PosicaoDetalhada.xlsx` (~94 positions) immediately surfaced one over-strict rule: the domain rejected LCAs with monthly coupons, but real LCAs in the Brazilian market commonly pay monthly. The fix was a one-line domain change (`allowed_coupons=frozenset(CouponFrequency)` for LCA), discovered only because real data forced it. **Audit when crashes happen, not preemptively.** The rule for LCI is still NONE-only and stays that way until a real LCI-with-coupons crashes the loader.

Further examples from the A′-plus testing cycle (commits `0099c02`, `897e66e`, `f975aad`, `1582ee5`):

- **LCAs from development banks rejected by `ProductRule`.** The issuer-kind constraint was a single value; generalized to a frozenset so both commercial and development banks can issue LCA.
- **BDMG created as a commercial bank.** BDMG is a development bank; the loader gained an explicit issuer-kind lookup so known development banks get the right `IssuerKind` at creation time. (Originally `_DEVELOPMENT_BANK_NAMES` in `xp_loader`; merged into the shared `_kind_catalog` in B33.)
- **Parser read past the Renda Fixa section.** The XLSX has non-investment sections (Dividendos, Custódia Remunerada) after Renda Fixa. The parser gained a `_RENDA_FIXA_TERMINATORS` frozenset; hitting a terminator string breaks the reading loop.

### BB importer: `bb.py`, `bb_mapper.py`, `bb_loader.py`

Unlike XP and BTG (which parse XLSX files), BB's Layer 1 (`bb.py`) reads a fixed-width plain-text terminal dump (`.txt`) — specifically a BB/SISBB "RESUMO DAS APLICAÇÕES LCA" export. Columns are extracted by character-position slices, not cell references. The test fixture is `tests/importers/fixtures/synthetic_bb_statement.txt`.

Layer 2 (`bb_mapper.py`) infers rate type from the bare numeric magnitude of the TAXA field using a `_RATE_BANDS` lookup table, because BB omits the rate-type label that XP and BTG include explicitly. This is the principal mapping quirk in the BB pipeline; the same `PostFixedCDI` vs `PostFixedCDIPlusSpread` ~700bp distinction documented above applies here — the magnitude bands are calibrated to keep them correctly separated.

Layer 3 (`bb_loader.py`) skips matured positions (saldo == Money zero) before persisting. Matured BB rows carry past maturity dates that would fail domain invariants; filtering happens here rather than at the domain layer.

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

PySide6 single-window desktop application. Three tabs: **Conglomerates** (default landing, B24), **Investments**, and **Calculator** (B41). The Conglomerates tab shows an accordion layout — one collapsible section per conglomerate with summary totals, FGC status badge, and expandable detail rows (per-investment projected balance via sequential drawdown). The Investments tab imports an XP statement, displays investments in a table with per-row FGC concentration badges and an inline-editable Conglomerate column (B′ curation), and filters by conglomerate and issuer via dropdowns with a totals strip below the table (B′ companion). Both tabs share a projection cache populated by a single "Project as of today" button. The Calculator tab models a hypothetical investment — either by entering a principal (Enter-value mode) or by solving for the maximum principal that keeps FGC exposure at or below R$250k throughout the holding window (Solve mode, via `engine/back_solve.py`) — and splices the mock into the Conglomerates expanded view for context; the mock is session-only and never touches the portfolio. Background work (statement loading, projection) runs on `QThread` workers; a single `_set_busy` guard prevents overlapping operations. Empty state (no investments loaded) swaps the table for a centered prompt via `QStackedWidget`.

The module imports from `domain`, `persistence`, `engine.projection`, `engine.fgc`, `engine.conglomerate_report`, `exports.calendar`, `importers.detection` (which dispatches to the appropriate broker loader — XP, BTG, or BB), `importers.xp_loader` (for `LoadResult`), `importers.xp_mapper` (for `parse_brazilian_money`), and `ui.curve_inspector`. It introduces no new architectural layer between itself and those — direct calls, no service or presenter layer.

CDI curve is fetched from `razukadm/justfixed-data` on launch (`engine/fetcher.py`); cached at `~/.justfixed/curve_cache.json`. The projection path uses the live curve when available; `_ASSUMED_CDI` is the offline fallback. (B9a shipped May 2026.)

Three read-only Curve Inspector windows (`ui/curve_inspector.py`) are accessible from the View menu — one each for CDI, PRE, and IPCA curves. Each window shows a date-based chart (yield vs. date) and a two-column vertex table; chart and table hover in sync. `MainWindow._open_curve_inspector(series)` creates the window on demand, passing the in-memory curve and fetch result. (Shipped May 2026, commits `58d4259`–`1017af1`.)

B34 per-investment delete shipped via `InvestmentDetailPanel._on_delete_clicked`: confirms via `QMessageBox`, calls `InvestmentRepository.delete`, then emits `investment_deleted`. `MainWindow._on_investment_deleted` removes the entry from the projection cache and refreshes both tabs. Delete applies to all investments regardless of source; no tombstone exists, so re-importing a statement resurrects any deleted imported investment. Orphan issuers are left in place. (Commit `a0e333e`.)

The `ui/` package also contains a styling-infrastructure layer. `theme.py` defines `COLORS` and `FONTS` as frozen dataclasses — the single source of truth for all palette and typography tokens across the app. `qss.py` generates the global stylesheet via `make_stylesheet()`, applied once to the `QApplication` before the main window opens; all role/property selectors (`role="toolbar"`, `objectName="investmentsTable"`, etc.) map to rules here. The `widgets/` subpackage extracts two reusable widget classes: `Panel` (titled bordered content frame) and `ProvenanceCallout` (curve provenance callout), shared between `main.py` and `curve_inspector.py`.

UI tests live in `tests/ui/` and use a "real method, MagicMock self" pattern: actual `MainWindow` or `ConglomerateEditDelegate` methods are called with a `MagicMock(spec=...)` stand-in for `self`, avoiding Qt window instantiation entirely. Layout and interaction verification remains a human "build, run, look at it" loop.

See `docs/UI_DESIGN.md` for the design rationale and milestone specs (A′, B′, and C′ all shipped).

---

## Test discipline

**1349 tests, ~16 second runtime, no skips.** The test suite is the spec; if behavior changes, the test changes first.

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

1. **GuaranteeFund milestone** — model FGC and FGCoop as first-class entities
   with per-institution limits and (for FGCoop) a global ceiling, so exposure
   calculations can track the two funds separately. Requires regulatory
   verification of the FGCoop global-ceiling rule before encoding.

2. **B41a — Promote mock to real investment** — action on the Calculator result
   card that creates the mock as a real Investment via the Add-investment flow,
   pre-populated from the form. Deferred from B41; depends on `_AddInvestmentPanel`
   accepting external pre-fill.

3. **B41b — Calculator Solve-Tesouro hardening** — add a validation gate for the
   Solve-with-Treasury path that is currently reachable programmatically but
   silently skipped. Deferred from B41; belt-and-suspenders, no user-visible
   behavior change today.

Phase 2 (post-MVP):
- DI-curve mark-to-market
- Real index data fetching (B3 for CDI history, IBGE for IPCA)
- Multi-broker importers (Itaú, Nu) — XP, BTG, and BB are complete
- Backup/restore for the SQLite database

---

## When you get stuck

The codebase is small enough to grep through. Three useful starting points:

- **What does feature X do?** Find its top-level entry point — usually a function in `engine/projection.py` or `importers/`. Read the test file for that module; tests are concrete examples.
- **Why does the code look like this?** Check the commit history. Each commit is one focused change with a message describing the *why*.
- **What's the right way to add a new feature?** If it's a new rate type, follow `PostFixedCDIPlusSpread`'s footprint (commit `fb1c37c`). If it's a new product type, look at how LCD was added with its 365-day minimum-term rule. Patterns repeat; find the most similar existing thing and follow its shape.

If a test is hard to write, the *code* is probably wrong, not the test.
