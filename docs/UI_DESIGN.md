# UI Design — Milestone A′ (Minimal Usable)

This document describes the first JustFixed UI milestone. It is the spec
that the next Claude Code session(s) should consume to build the UI.

It does *not* prescribe specific widget classes, signal/slot wiring, or
PySide6 API calls. Those are decisions to make at build time, against
current PySide6 docs (the framework moves faster than this project's
training-time knowledge of it).

For what's already built, see `ARCHITECTURE.md`. For what's deferred
beyond this milestone, see `ROADMAP.md`.

---

## Scope

### What this milestone is

**One main window.** The user can:

1. Import an XP statement (file picker → loader runs → table refreshes).
2. View their investments in a read-only table, with per-row FGC status.
3. Re-project all values as of today and see the table update.
4. Export their maturity calendar to an `.ics` file.

That's the entire user-visible surface for this milestone. Everything
else is deferred — see "Out of scope" below.

### Why this scope

Every existing backend capability is reachable from this UI: the loader
(`importers/xp_loader.py`), the projection engine (`engine/projection.py`),
the FGC engine (`engine/fgc.py`), and the calendar export
(`exports/calendar.py`). Nothing built so far is unreachable, and nothing
unbuilt is required.

The user can complete a real loop: load → see → export. Whether they
*do* anything more is a B′ question, not an A′ question.

### Estimate

~2-3 sessions. The risk that drives the upper end is PySide6
unfamiliarity, not scope.

### Out of scope (deferred)

The following are *not* in this milestone. They will be revisited in
follow-on milestones (B′, C′, or later as roadmap items):

- **Manual-entry form** for investments not in an XP statement.
  Deferred to C′.
- **Per-investment projection detail view** (accrual breakdown, IR tax,
  net at maturity). Deferred to B′ or C′.
- **Conglomerate curation UX** — editing `[unverified]` conglomerate
  values, merging issuers into shared groups. Deferred to B′. The
  data model decision that supports curation is recorded in this
  document (see "Conglomerate model" below) so B′ doesn't have to
  relitigate it.
- **Multi-window navigation.** A′ is one window.
- **Settings, preferences, persistence of UI state** (window size, last
  file path, column widths). Use defaults; don't store anything.
- **FGC concentration warnings beyond the per-row badge** — no
  banner, no summary header, no "you're over the limit" modal. The
  badge tells the truth; richer surfaces wait for B′.

---

## Window layout

One top-level window. Three vertical regions, top to bottom.

### Top region — Import

Contains the import controls.

- A button labeled approximately **"Import XP statement…"**. Clicking it
  opens a native file-picker dialog (Qt's standard file dialog). The
  filter restricts to `.xlsx` files. The dialog's starting location is
  decided in "Open question Q4" below.
- A status text area immediately to the right of or below the button.
  Three states:
  - **Idle:** empty, or "Ready."
  - **Loading:** "Loading {filename}…" while `load_xp_statement` runs.
  - **After load:** a one-line summary of `LoadResult` —
    something like "Loaded 12 investments (3 new, 9 unchanged) from
    {filename}." Errors during load become a Qt error dialog (modal),
    not inline text.

The status area is informational only. It doesn't need to persist
across imports — the next import overwrites it.

### Middle region — Investment table

A read-only table showing one row per investment in the database.

**Columns** (left to right):

1. **Issuer** — `investment.issuer.name`.
2. **Conglomerate** — `investment.issuer.conglomerate`. Display the
   raw string, including any `[unverified]` prefix, in a visually
   subdued style when the prefix is present (gray italic, or a small
   "needs review" icon — pick one, don't do both). The user can read
   the prefix but not edit anything in this milestone.
3. **Product** — `investment.product.name` or similar short label.
4. **Principal** — formatted Money (`R$ 50,000.00`).
5. **Maturity** — `investment.maturity_date` as `YYYY-MM-DD` or
   localized format. Whatever's idiomatic in PySide6's locale handling
   for pt-BR; consistent across rows is what matters.
6. **Current value** — projected value as of "today" (see project
   button below). Empty until the user clicks Project. After projection,
   shows formatted Money.
7. **FGC status** — a small visual badge: green / yellow / red for
   under / approaching / over. Computed by `engine/fgc.py` per
   conglomerate; every investment in the same conglomerate shows the
   same badge color.

**Sorting:** Default sort by maturity date ascending (so soonest
maturities are at top — that's the order the user would naturally
want for "what should I think about next"). Clicking a column header
to re-sort is nice-to-have, not required for this milestone.

**Selection:** None. The table is read-only and rows are not actionable
in A′. (B′ adds row interactions for curation and detail view.)

**Empty state:** When the database is empty (fresh install, no statement
imported yet), the table area shows a single centered message:
"Import an XP statement to see your investments." When the database
has data, this message is hidden.

### Bottom region — Actions

Two buttons. Stacked or side-by-side, doesn't matter.

- **"Project as of today"** — recomputes current value and FGC status
  for every investment, using `date.today()` as `as_of`. Updates the
  current-value column and the FGC status badges. The button is enabled
  whenever the database has at least one investment.
- **"Export calendar…"** — opens a save-file dialog (default filename
  something like `justfixed-maturities.ics`). Calls
  `exports/calendar.py` with `as_of=date.today()` to generate the bytes,
  writes them to the chosen path. Shows a success or error dialog when
  done. Enabled whenever the database has at least one future-maturity
  investment.

A status bar at the very bottom (Qt's standard status bar) is fine for
brief transient messages — "Calendar exported to {path}", "Project
complete: 12 investments updated" — but isn't required if the buttons
themselves provide adequate feedback. Pick one approach and stay
consistent.

---

## Required interactions

### Import flow

1. User clicks "Import XP statement…".
2. File-picker opens. User selects a `.xlsx` file or cancels.
3. If cancelled, nothing happens.
4. If selected, the import button disables, status area shows "Loading
   {filename}…", and `load_xp_statement(path, session_factory)` runs.
   Run it on a background thread or via `QThread`/`QtConcurrent` —
   *do not block the UI thread*. (Even a small XP statement involves
   file I/O and database commits; blocking the UI gives the user a
   "frozen window" impression.)
5. On success: status area shows the LoadResult summary. The
   investment table refreshes to show all current investments
   (including ones that already existed before this import; the table
   reflects the database state, not the load delta).
6. On error: status area returns to idle, a modal error dialog shows
   the exception message. The table is not changed.
7. Import button re-enables.

### Project flow

1. User clicks "Project as of today".
2. The button disables briefly. The UI calls into the projection engine
   for each investment to compute current value, and into
   `engine/fgc.py` once with the full investment list to compute FGC
   status per conglomerate.
3. The "Current value" column populates. FGC status badges update.
4. Button re-enables.
5. The projection engine requires `assumed_cdi` for CDI-linked rates
   and `assumed_ipca` for IPCA-linked rates. Both come from hardcoded
   constants in the UI module (`_ASSUMED_CDI`, `_ASSUMED_IPCA`) with
   comments documenting the source values and the rebuild-time verify
   discipline. Making either user-editable is deferred to backlog
   B10 (real index data fetching). When future rate types are added
   to the projection engine — any new `PostFixed*` variant — they'll
   require their own assumed-rate constant on the same pattern.

### Calendar export flow

1. User clicks "Export calendar…".
2. Save-file dialog opens with default filename `justfixed-maturities.ics`.
3. User selects a path or cancels.
4. If cancelled, nothing happens.
5. If selected, generate bytes via `exports/calendar.py`, write to
   path. The export honors the Hide matured toggle: when the toggle
   is on (the default), matured investments are excluded from the
   `.ics` file using the same rule as the table view
   (`maturity_date > today`). When off, all investments are exported.
   Show a brief success dialog or status bar message including the
   chosen path.
6. On error (file system permission, disk full, etc.), show a modal
   error dialog with the exception message.

### Error handling, generally

- **Loader errors** (parse failure, unrecognized file format,
  database conflict): modal dialog, table unchanged.
- **Projection errors** (very unlikely — pure functions over validated
  domain): modal dialog, table unchanged.
- **Export errors** (file system): modal dialog.
- **Database errors at startup** (corrupt file, schema mismatch):
  modal dialog at app launch with enough information for the user
  (or developer) to diagnose. App may exit if it can't open the DB.

Error dialogs should show the exception's `str()` representation, not
a stack trace. Stack traces are for the developer console / log file,
not the user.

---

## FGC display details

This is small enough to spell out completely so Claude Code doesn't
guess.

The FGC engine's `fgc_concentration_report` returns an `FGCReport`
with one `ConglomerateExposure` per conglomerate. Each exposure has
`current_status` and `peak_status` (both `ExposureStatus`: under,
approaching, over).

For A′, the table badge reflects **current_status only**. Peak status
is more nuanced — it's a forward-looking conservative estimate — and
surfacing it cleanly requires more UI than a single badge. Defer the
peak-status surface to B′ (likely as a tooltip or a second badge).

Color mapping:

- `UNDER` → green badge or check icon.
- `APPROACHING` → yellow badge or warning icon.
- `OVER` → red badge or alert icon.

Treasury investments don't appear in the FGC report (the engine filters
them out). Their badge cell should show a neutral indicator — a dash,
or "N/A — Treasury", or similar. The point is the user sees "this
investment is outside the FGC system" rather than "this investment is
mysteriously empty."

Issuers with `[unverified]` conglomerate prefix: the badge is computed
from that issuer alone (since each `[unverified]` issuer is its own
"conglomerate of one" in the engine's grouping). The badge is correct
but possibly misleading if the user has multiple unverified issuers
that actually belong together. In A′ this is fine: the prefix in the
conglomerate column itself tells the user "this calculation may be
incomplete." Curation in B′ resolves it.

---

## Data flow

The UI reads from and writes to the database via the existing
repository layer in `persistence/`. It does *not* call the loader,
engine, or exports through new abstractions.

Specifically:

- **Reading investments for the table:** `InvestmentRepository.list_all()`
  (or whatever the existing accessor is — match what's there).
- **Loader trigger:** `load_xp_statement(path, session_factory)`.
- **Projection:** `engine/projection.project(investment, as_of, assumed_cdi, assumed_ipca)`
  per row. Both assumed-rate kwargs are required when the portfolio
  contains the corresponding rate types.
- **FGC:** Two call paths. Initial projection: `_ProjectWorker` calls `fgc_concentration_report_from_projections(results)` over its already-computed `ProjectionResult` list (projects once, no double-projection). Cache-aware refresh after conglomerate edits: `refresh_table` calls the same function over `projection_cache`. The original `fgc_concentration_report(investments, as_of, assumed_cdi, assumed_ipca)` remains the public API for callers without pre-computed projections.
- **Calendar export:** `exports/calendar.export(...)` (signature per
  `exports/calendar.py`).

The UI module(s) live in `src/justfixed/ui/`. The session factory
and any DB connection wiring stays where it currently is; the UI
imports and uses it.

**One architectural note:** the UI should not introduce a new layer
between itself and the existing modules. No "service layer," no
"presenter layer," no "view model." Direct calls into the existing
modules. If a method gets too gnarly, extract a helper *inside the
UI module*, not into a new architectural layer. The codebase is
small; over-architecting the UI now would cost more than it saves.

---

## Conglomerate model — decision recorded

This decision affects A′ minimally (A′ only displays the conglomerate
string) but matters for B′ (which adds curation). Recording it here
so B′ doesn't relitigate.

**`Issuer.conglomerate` remains a free-form string.** No
`Conglomerate` entity is introduced. The FGC engine groups by string
equality.

When B′ adds curation, it will be **inline string editing with
autocomplete** from existing conglomerate values in the DB. This
handles all curation operations:

- **Renaming** `[unverified] CEF` → `Caixa Econômica Federal`: edit
  the string.
- **Merging** Itaú and Unibanco: set both `conglomerate` strings to
  `"Itaú Unibanco Holding"`. Same string → same group → engine merges
  automatically.
- **Splitting:** edit one of the strings to something different.

No new entity, no migration, no separate Conglomerate table. The
string equality relation is sufficient because every curation
operation reduces to "make these strings equal" or "make these
strings different."

This forecloses the "Conglomerate as entity" design path. The
strongest argument against this decision is that an entity would
let us attach conglomerate-level metadata (CNPJ list, FGC
registration ID, etc.) cleanly. We're rejecting that argument
because (a) such metadata, where it matters, attaches to issuers
not conglomerates; (b) JustFixed isn't a banking-group registry;
(c) speculative modeling for unbuilt features creates migration
debt without paying for itself. If a future feature *does* genuinely
need conglomerate-level metadata, the migration from "string" to
"entity" is mechanical and well-understood.

---

## Open questions for the build session

These are small enough to decide at build time but worth flagging
so they're not forgotten:

### Q4 (from ROADMAP) — File-picker default location

What's the starting directory when the file picker opens?

**Recommendation:** Use Qt's `QStandardPaths.DownloadLocation` (the
user's default Downloads folder). XP's broker portal exports `.xlsx`
files there by default on Windows, so this matches the user's
muscle memory. Don't try to remember the last-used path between
sessions in A′ (would require persisting UI state, which we
deferred). A future milestone can add path memory if it's annoying.

### Assumed-rate parameters for projection

The projection engine accepts assumed-rate kwargs corresponding to
each `PostFixed*` rate variant the domain models. As of milestone
A′ that's two: `assumed_cdi` (CDI-linked rates) and `assumed_ipca`
(IPCA-linked rates). Both are required for portfolios containing
the corresponding investments; the engine raises a clear error if
they're missing.

The UI keeps both as hardcoded module-level constants in
`ui/main.py`:

- `_ASSUMED_CDI` — sourced from the most recent Banco Central Selic
  decision minus typical 0.10 p.p. CDI spread. Verify at every
  rebuild against the current Copom publication.
- `_ASSUMED_IPCA` — sourced from the most recent IBGE IPCA acumulado
  12 meses release. Verify at every rebuild against IBGE.

Each constant's source attribution lives in the comment header
above its definition. Making either user-editable is deferred to
backlog B10 (real index data fetching from B3 for CDI and IBGE for
IPCA).

**Lesson recorded from commit `6dc9b4f`:** This subsection originally
covered only `assumed_cdi`, scoping the question by the most
user-visible parameter. That framing missed `assumed_ipca` because
no UI surface specifically discusses IPCA — but the projection
engine's typed-rate dispatch does, and the first IPCA-linked
investment in a real portfolio crashed Project and Export.

When future rate types are added to the projection engine (any new
`PostFixed*` variant — e.g. a hypothetical `PostFixedSelic`), the
spec for any UI work that calls `project()` or
`fgc_concentration_report()` should enumerate **every** assumed-rate
kwarg the engine accepts, not just the most-common one. The
right framing is "what does every code path need," not "what does
the user see."

### Threading model

Loader runs file I/O and database commits. Projection runs many
small calculations across all investments. Both should run off the
UI thread for any portfolio of non-trivial size. PySide6 has
`QThread`, `QThreadPool`, `QtConcurrent`, and `Future`-style options.
The build session should pick whichever pattern is most idiomatic in
current PySide6 docs and stay consistent. This is a verify-against-current-docs
moment — don't pick a pattern from older Qt 5 / PyQt5 examples.

### Locale / formatting

Money formatting (R$ XX.XXX,XX with comma decimal) and date
formatting (DD/MM/YYYY) are pt-BR conventions. PySide6 has locale
support via `QLocale`. The build session should use it consistently
rather than hand-formatting strings. Test on a non-pt-BR system to
make sure it still renders sensibly.

---

## Deferred from A′ — milestone plan

A′ shipped as a read-only viewer. Real usage (May 2026) surfaced
gaps that split into three follow-on milestones, each shippable
independently. Decisions captured here so the next build session
has a concrete spec.

### Tight scope (next session)

Shipped (commits `27541bb`, `6d26697`, `28becc8`).

Three small additions that make A′ more usable for ongoing
testing without expanding the data model.

**Clear DB button.** A menu item under File → "Clear Database…"
that empties all investments from the DB. Confirmation dialog
shows the actual count ("Clear all 12 investments from the
database? This cannot be undone."). Gated by environment variable:
`if os.environ.get("JUSTFIXED_DEV"): show the menu item`.
Invisible to non-developer users by default; available on-demand
for testing by running with `JUSTFIXED_DEV=1`.

**Projected Value column.** New column in the investment table
showing `ProjectionResult.net_at_maturity` (post-IR-tax value at
maturity). Position: after "Current value", before "FGC".
Formatted as Money via existing `to_display()`. Populated by the
Project flow alongside Current value.

**Hide matured toggle.** A button or menu item that toggles
visibility of investments where `maturity_date <= today`.
Maturity-day investments are considered already-paid by the
issuer; they hide together with strictly-past-maturity ones.
When hidden:
- Rows do not appear in the table.
- Hidden investments are excluded from all totals (when those
  exist) and from the FGC concentration calculation.
- The toggle state does not persist between app launches (default:
  hidden, since the testing pattern is "look at current
  portfolio").

**Known minor follow-ups (deferred).** One inconsistency
deliberately left for a future polish pass:

- The Project button stays enabled when the Hide matured filter would
  leave zero visible investments. Clicking produces a "Projected 0
  investments" status message, which is the user-recoverable signal.
  Deliberate: buttons reflect DB state, the filter reflects view
  state.

### Curation — milestone B′ (shipped)

**Shipped** (commits `a60ba63`, `8938820`, `a65ff19`, `578a186`, `68cb88a`, `d7435c9`, `cb5255d`, `7052f2f`, `29c8513`, `95eaa6f`, `3a4857f`). Inline conglomerate editing. Model: **string editing only, no
verified flag.** The `[unverified]` prefix is the verification
state — its presence or absence in the conglomerate string is the
truth. To verify a row, the user edits the string and removes the
prefix (or types a completely new value, which has no prefix).

**Interaction.**
1. User clicks a conglomerate cell. Cell becomes editable.
2. As they type, autocomplete shows the union of (a) verified
   conglomerate strings currently in use on any issuer in the DB,
   and (b) all entries in curation memory. Strings are deduplicated
   case-insensitively; canonical case comes from curation memory
   when present, otherwise from the in-use spelling. `[unverified] `-prefixed
   strings are never shown. User can pick from the dropdown or
   type a brand-new string (strict autocomplete with new-value
   fallback).
3. On Enter or focus-loss, the new value is saved to
   `issuer.conglomerate`. The row's visual marker updates: if the
   new string has no `[unverified] ` prefix, the row is no longer
   gray-italic.
4. FGC re-computation runs immediately on every save. Badges
   refresh to reflect new conglomerate groupings.

**Autocomplete rationale.** Two failure modes to suppress. First,
showing `[unverified] `-prefixed strings would let the user merge
into another unverified entry and propagate the prefix — so
unverified strings are excluded. Second, sourcing only from
currently-in-use strings would mean a brand-new issuer can't see
a previously-curated spelling, leading to duplicates like `"itau"`
vs. `"Itaú"` when the same conglomerate is curated at different
times — so curation memory is also included. Curation memory is
also what makes pre-seeded conglomerates (future B20) show up in
the dropdown on day one, before any issuer currently carries them.

**FGC refresh rationale.** Immediate refresh on every edit
prioritizes discoverability. Implementation: the UI controller
caches the last `ProjectionResults`; on conglomerate save, FGC
re-aggregates over the cached results (a pure function over
investments and the projection cache), bypassing re-projection.
The cache is invalidated on projection-affecting events: new
projection completion, Hide matured toggle, new import, Clear DB,
investment add/edit/delete (when those exist), assumed-CDI change
(when user-configurable). Conglomerate edits are *not* in that list
— they don't affect projections, only aggregation. If projection
over a real portfolio measures under ~50ms, the cache may be
dropped and full re-run used instead; the choice is a measurement
decision, not a design one.

### Filter and totals — milestone B′ companion

**Shipped** (commits `c987286`, `253a7c8`, `d08daa2`, `6afff76`,
`684d44b`, `361f0a6`, `18ba8e0`, `0b88913`, `33173d6`).
Filter dropdowns and totals strip.

**Filter.** Two `QComboBox` dropdowns above the table — one for
issuer name, one for conglomerate name. Each lists the distinct
values currently in the database plus an "All" sentinel that
clears that filter. The two dropdowns combine with AND: selecting
"Bank A" and "Group X" shows only investments where both match.
The hidden-matured toggle combines with the dropdowns (also AND).

**Totals strip.** A row of labels below the table showing aggregate
values across the currently-visible (post-filter) investments:
- Total principal.
- Total current value ("—" until Project has run, or if the
  projection cache is partial).
- Total projected value at maturity — gross (pre-IR), to align
  with FGC exposure semantics.
- Row count, shown as "N of M" when a filter is active.
The strip updates on every filter change and after every Project
run. FGC badges do not appear in the strip (they're
per-conglomerate, not aggregate).

### Matured investments — PAID treatment (B22)

**Shipped** (commits `e4d10b1`, `ed7d4b3`, `980db97`, `163af07`).

**Toggle affordance.** The Hide matured control now lives in both the
View menu (existing) and as a `QCheckBox` labeled "Hide matured" at the
right end of the Investments filter row. Both controls are wired to the
same handler and stay in sync via `blockSignals()`. Default: checked
(ON). The toggle state does not persist between app launches.

**When Hide matured is ON (default):** Behavior is identical to before
B22. Rows where `maturity_date <= today` are excluded from the table,
from all totals, and from FGC concentration.

**When Hide matured is OFF — PAID treatment:** Matured rows reappear in
the table but are visually demoted to signal that the money has been
paid out and is no longer an outstanding holding:

- **Current and Projected cells:** show the literal string `PAID`
  instead of a money value. Font: Consolas at `FONTS.MONO_SIZE`.
  Meaning: PAID is a *value substitution*, not a strikethrough.
  Strikethrough reads "this number is wrong"; PAID reads "this number no
  longer exists." They communicate different things.

- **Whole-row text:** all cells (Issuer through FGC) are set to
  `COLORS.INK_3` (`#888888`), visually demoting the row relative to
  active rows.

- **FGC badge:** the badge text is unchanged (it retains whatever status
  it carried) but its foreground colour is overridden to `COLORS.INK_3`,
  greying it out to signal that FGC coverage no longer applies.

**Totals exclusion is unconditional.** The Principal / Current /
Projected totals strip always excludes matured rows regardless of the
Hide matured toggle. When the toggle is OFF, `_update_totals` splits
visible rows into active and matured before calling `compute_totals`;
only active rows are passed to the sum. This ensures totals always
reflect outstanding holdings.

**Row count pill:** When at least one matured row is visible (toggle
OFF), the pill reads `N active · M matured`. When no matured rows are
visible (toggle ON, or portfolio contains none), the pill reads `N` or
`N of M` (the existing filter-active format).

**Implementation note — table cells and QSS.** The B43 `setProperty(
"role", ...)` + QSS pattern applies to `QWidget` subclasses
(`QPushButton`, `QLabel`, etc.). `QTableWidgetItem` is a `QObject` but
*not* a `QWidget`; QSS property selectors do not fire for table items.
The PAID treatment therefore uses imperative `setForeground()` on each
`QTableWidgetItem`. Future table-level styling work should use
`QStyledItemDelegate` or `Qt.ItemDataRole.ForegroundRole` rather than
reaching for QSS selectors.

### Calculator tab — FGC back-solve (B41)

**Shipped** 2026-05-28. Phases 1–2.4b, commits `5b2d0d8`–`65e50d3`.

The Calculator tab surfaces `engine/back_solve.py` via two modes:

**Enter-value mode.** User enters a principal amount; the tab projects
the investment to maturity and shows: principal, projected value at
maturity, FGC utilization (gross / cap), status pill, effective net
rate (derived from `net_at_maturity / principal` annualized rather than
from rate parameters directly, so the figure stays consistent with the
Projected column), and tenor days. FGC status thresholds match
`engine/fgc.py` (`ExposureStatus`).

**Solve mode.** User omits the principal; the tab calls
`back_solve.max_principal_under_fgc(...)` and shows the maximum
principal that keeps FGC exposure at or below R$ 250k at every sample
date. The result card mirrors Enter-value (max principal, gross
projected, peak utilization, status, gross effective rate, tenor).
Disabled for Treasury issuers — they are not FGC-covered.

**Drawdown preview (Solve mode only).** Below the result card, a
"Drawdown preview" panel shows the sequence of maturities for
same-issuer, non-Treasury, window-overlapping holdings alongside the
hypothetical mock investment. Rows are sorted by maturity date.
The mock row is rendered with `[rowKind="mock"]` (amber background,
sketch-orange left border, `badge="mock"` label) to distinguish it
from existing holdings. The row at `result.peak_date` is the
cap-binds row: `[rowKind="peak"]` (faint amber), `▶` indicator, and
the balance cell shows `R$ 250.000,00 · cap binds`. The balance
column shows the right-to-left cumulative gross exposure for existing
rows only; the mock row shows its own `projected_at_maturity`.

**QSS properties introduced:** `QWidget[rowKind="mock"]`,
`QWidget[rowKind="peak"]`, `QLabel[badge="mock"]`,
`QLabel[indicator="peak"]`. Theme tokens: `MOCK_ROW_BG`,
`MOCK_ROW_EDGE`, `MOCK_INK`, `PEAK_ROW_BG`, `PEAK_INDICATOR`.

**Cross-tab mock rendering (B41 phase 2.4b).** Both Calculate modes
set `MainWindow.active_mock`; Reset clears it via `clear_active_mock`.
On every Conglomerates rebuild (`_refresh_conglomerates`) the mock's
projection is spliced into the report, and the mock's conglomerate
section auto-expands so the row is immediately visible. The mock row
renders with `rowKind="mock"` (amber background, sketch-orange left
border) and a MOCK badge (`badge="mock"`) prepended to the issuer cell. The Investments tab,
FGC totals, and `projection_cache` are unaffected — the mock is
visible in the Conglomerates tab only. Tesouro mocks appear in (or
create) the "Tesouro Nacional" section with NOT_FGC status on every
row, because `build_conglomerate_report_from_projections` groups by
conglomerate without filtering Treasury investments.

### Projection detail — InvestmentDetailPanel (B44)

**Shipped** 2026-05-28. Single commit. Closes C′.

The `InvestmentDetailPanel` now includes a "Projection" Panel widget
below the investment-fields scroll area. It shows five rows drawn from
`ProjectionResult`:

1. **Current value** — `projection.current_value` (accrual to as_of)
2. **Gross at maturity** — `projection.gross_at_maturity`
3. **Gain** — `tax_breakdown.gain`
4. **IR tax** — rate formatted via `_format_brazilian_percent(rate × 100)`
   combined with `tax_breakdown.tax_amount`, e.g. `"22,50% — R$ 1.125,00"`
5. **Net at maturity** — `projection.net_at_maturity`

All money values use `Money.to_display()` in mono font. The Panel's meta
line reads `"as of dd/MM/yyyy"` from `projection.as_of`.

**Placeholder state.** When `MainWindow.projection_cache` is `None` or
contains no entry for the selected investment's id, the Panel shows a
centered "No projection yet. Click 'Project as of today' to compute."
label (`role="emptyState"`). The placeholder switches to the live rows
automatically as soon as a matching projection appears.

**Real-time refresh.** `InvestmentDetailPanel.refresh_projection()` is
called from three places: `show_investment()` (on every selection
change), `clear()` (resets to placeholder), and
`MainWindow._on_project_done()` (immediately after the projection
worker finishes, updating the panel if it has a current investment).

**Visual sibling.** The five-row layout mirrors the Calculator result
card (B41 phase 2.2) — same Panel widget, same `_row()` pattern, same
mono font for money values.

## What this document is not

This is a scope and structure spec. It is intentionally silent on:

- Specific widget classes (`QTableView` vs `QTableWidget`, model/view
  vs item-based, etc.). Claude Code picks at build time against
  current PySide6 docs.
- Visual styling beyond the broad strokes (badge colors). No CSS, no
  QSS, no specific font sizes. The first build should look minimally
  reasonable; visual polish is its own pass.
- Test discipline for UI code. UI tests in PySide6 are possible
  (`pytest-qt`) but the cost/benefit is different from backend tests.
  The build session should decide whether to write any UI tests for
  A′; the project's overall test discipline still applies to any
  non-UI code touched.
- File organization within `src/justfixed/ui/`. One module or several
  is a build-time call. Match whatever feels natural for the size of
  what's being built.

The point of recording the *what* and *why* here, but not the *how*,
is that the *how* will inevitably need to bend to current PySide6
realities, and we want to discover those at build time, not pre-commit
to guesses.