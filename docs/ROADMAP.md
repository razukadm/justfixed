# JustFixed Roadmap

This document describes what's planned next, what's been deferred, and what
open questions are blocking future decisions. It is a living document —
update it when scope changes, when decisions get made, or when new
deferred work surfaces during implementation.

For what's *currently built*, see `docs/ARCHITECTURE.md`. This file is
about what isn't built yet.

This is `v0.1` of the roadmap, compiled by scanning three project chats
(initial mentorship through engine/persistence; XP loader layer 3 through
FGC concentration; calendar export). It captures everything that was
explicitly deferred or discussed-but-not-decided. It does not pretend to
be a comprehensive product plan — items will be added, reordered, and
removed as the project evolves.

---

## Part 1 — Forward plan

What comes next, in rough order. Estimates are sessions of the slow,
careful pace this project uses (2–4 hours each).

### 1. UI — PySide6

**Status:** Milestones A′, A′-plus, B′, B′ companion, B24, B9a, B27,
C′, B34, B41, B44, B22, B37, Curve Inspector, and B19 (partial — delete +
conglomerate/custodian management) complete. See `docs/UI_DESIGN.md`
and `docs/ARCHITECTURE.md` for what shipped.

**C′ — projection detail view — COMPLETE.**
Manual-entry form (C′ commits 1–6, commit `08a2ead`), per-investment
delete (B34, commit `a0e333e`), and projection detail view (B44,
2026-05-28) have all shipped. B44 delivered the Projection Panel in
`InvestmentDetailPanel`: accrual breakdown, IR tax rate and amount, and
net-at-maturity. C′ is complete.

Coupon frequency display (deferred from B27, 2026-05-19) — SHIPPED. The
`InvestmentDetailPanel` "Coupon" row shows the frequency via
`CouponFrequency.to_display()` (Nenhum / Mensal / Semestral), editable for
manual investments and read-only for imported ones; it landed with the
detail-panel field rows (C′ era). The Investments tab stays at its column
limit, so the value lives in the detail panel only. The note's five-way
wishlist (Trimestral / Anual) was aspirational — the domain models three
frequencies (NONE / MONTHLY / SEMI_ANNUAL); adding quarterly/annual is a
domain change under the audit-when-it-crashes rule, not a display task.

### 2. Windows installer

**Status:** Shipped. Commits `3152f63`–`b2e1ed9` (May 2026). See
`docs/BUILD.md` for build and packaging details.

### 3. BTG importer — SHIPPED

All three layers shipped (2026-05-20). Commit range: btg.py (parser) through
`282bd73` (UI rewire). Detection layer (`detection.py`) added alongside the
loader: `Broker` enum, `detect_broker` (sheet-name fingerprints), `load_statement`
dispatcher. UI rewired to a single broker-agnostic "Import Statement" button.
See the session-status section below for full details.

### 3a. BB importer — SHIPPED

All three layers shipped (2026-05-23). Commits `2544a43` (Layer 1 parser),
`251c120` (Layer 2 mapper), `45e4f58` (Layer 3 loader + detection wiring).
Layer 1 (`bb.py`) reads a fixed-width plain-text BB/SISBB terminal dump
(`.txt`), not XLSX. Layer 2 infers rate type from TAXA magnitude via
`_RATE_BANDS`. Layer 3 skips matured positions (saldo == zero) before
persisting. The `Broker.BB` enum member and dispatch case were added to
`detection.py`. This is the third broker importer — the stated trigger for
cashing in B32 and B33.

### 3b. Curve Inspector — SHIPPED

Three read-only yield-curve windows shipped (2026-05-23). Commits `58d4259`
(Part 1, static), `bbd728e` (provenance callout), `b98bd10` (chart/table
hover-sync), `1017af1` (date-based x-axis and 2-column table). Accessible
from the View menu — one window each for CDI, PRE, and IPCA curves.
`ui/curve_inspector.py`; wired from `MainWindow._open_curve_inspector`.

### 4. Model guarantee funds (FGC / FGCoop) as first-class entities

**Scheduled after:** BTG importer completes.

**Why:** Coverage amount, global ceiling, and per-conglomerate
aggregation are properties of a *fund*, not of `IssuerKind`. FGC and
FGCoop currently both cover R$250k per institution, but the amounts
can diverge, and global limits (FGC's R$1M/4yr) must aggregate FGC
and FGCoop exposure **separately** — an investor's FGC-institution
total and cooperative total are independent ceiling computations.

The current `is_deposit_guaranteed` bool is a deliberate interim: true
and sufficient for the per-institution R$250k check, but it cannot
express divergent limits or separate global-ceiling buckets.

**Scope:**
- A `GuaranteeFund` concept (FGC, FGCOOP) owning per-institution limit
  and global ceiling.
- An `IssuerKind → fund` mapping.
- FGC-engine refactor: query the fund's per-institution limit instead
  of the hardcoded R$250k.

**Verification note:** The FGCoop global-ceiling rule could **not** be
confirmed from a primary source — `fgcoop.coop.br/cobertura-ordinaria`
is a JS-rendered app and secondary sources conflict on whether FGCoop
has a R$1M global cap matching FGC's. Whoever builds this milestone
must verify the FGCoop regulation directly before encoding a global
ceiling value.

### 5. Phase 2 — post-MVP

After the MVP UI and installer ship, the broader Phase 2 work begins.
See Part 2 (Backlog) for individual items. Phase 2 is not one feature;
it's a collection of independent enhancements that can be picked up in
any order based on real usage signals.

---

## Part 2 — Backlog (deferred features)

Things explicitly chosen *not* to build, with the reasoning preserved.
Grouped by feature area. Items here are *not* a commitment to build —
they're a record of what was considered and deferred, so future-you
doesn't lose the context.

### B1. Calendar export — orphan event cleanup (v2)

**Source:** `docs/CALENDAR_EXPORT_DESIGN.md`, "Future enhancements"
section.

**Why deferred:** v1 is correct in the common case (re-export updates
events). v2 fixes the edge case (orphan events for removed
investments). Doing v2 now requires a new persistence concern
(last-export state tracking) that doesn't exist yet.

**What v2 needs:**
1. Track per-export state: persist which investment UIDs were exported
   and when.
2. On each export, diff current investments against the last export's
   UIDs.
3. For each UID present-then-absent, emit a VEVENT with
   `STATUS:CANCELLED` and `METHOD:CANCEL`.

**Trigger to revisit:** When the user accumulates real ghost events
in their calendar from sold/removed investments and finds it annoying.
Until then, the README documents the limitation and tells the user
to remove stale events manually.

### B2. Calendar export — coupon events

**Source:** `docs/CALENDAR_EXPORT_DESIGN.md`, "Future enhancements"
section.

**Why deferred:** v1 emits one event per investment, at maturity.
LCI/LCA/CDB with juros mensais or juros semestrais also pay periodic
coupons. v2 could emit additional VEVENTs for each coupon date. The
projection engine already exposes coupon dates and amounts via
`engine/cashflow.py`.

**Trigger to revisit:** When a user with coupon-paying bonds asks for
calendar coverage of those payments.

### B3. Calendar export — bank-of-custody field

**Status:** SHIPPED 2026-05-30, commit `2bb755f`. Custodian appears as a
"Custodiante:" line in each VEVENT DESCRIPTION, omitted when null. See
`docs/CALENDAR_EXPORT_DESIGN.md` (B3 marked shipped there).

**Source:** `docs/CALENDAR_EXPORT_DESIGN.md`, "Future enhancements"
section.

**Why deferred:** Brazilian fixed income has separate issuer (the
entity paying back) and custodian (the brokerage holding the
certificate). The domain doesn't currently model custodian.

**Implemented by:** B42 (custodian field) → B3 (calendar export wiring).

### B4. Calendar export — subscription URL / auto-refresh

**Source:** `docs/CALENDAR_EXPORT_DESIGN.md`, "Out of scope".

**Why deferred:** Would require a server. JustFixed is offline-first
and single-user; running a server contradicts the architecture.

**Trigger to revisit:** Probably never, given the project's
offline-first commitment. If JustFixed ever became a multi-user
hosted product, this would be a natural addition.

### B5. FGC — R$ 1,000,000 / 4-year aggregate cap

**Source:** `docs/FGC_DESIGN.md`, "Out of scope".

**Why deferred:** The R$ 1M cap depends on actual past FGC payouts,
not current holdings. For a user with no prior claims, it doesn't
activate. Computing it would require modeling claim events, which
is event-driven rather than holdings-driven.

**Trigger to revisit:** If a user has experienced an FGC payout and
needs to know their remaining 4-year window.

### B6. FGC — multiple CPFs / joint accounts

**Source:** `docs/FGC_DESIGN.md`, "Out of scope".

**Why deferred:** Phase 1 assumes one user owns all positions. The
FGC engine's data structures were designed not to bake in single-CPF
assumptions in places that would be hard to extract later, but no
multi-CPF code exists.

**Trigger to revisit:** When a user wants to track joint accounts
or multiple family members' portfolios in one JustFixed instance.

### B7. SQLCipher encryption

**Source:** Initial mentorship chat. Deferred from Week 1.

**Why deferred:** SQLCipher Python bindings on Windows are notoriously
fiddly. Phase 1 uses plain SQLite. The architecture doc and product
vision both mention encryption as the long-term intent.

**Trigger to revisit:** Before any beta release to non-developer
users. Plain SQLite is fine for single-developer use; encryption is
necessary if other people are going to install JustFixed and trust
it with real financial data.

### B8. Multi-broker importers (BTG, Itaú, Nu, Inter)

**Source:** Phase 2 list in `ARCHITECTURE.md` and original mentorship
chat.

**Why deferred:** XP is the user's primary broker. Other brokers
have their own statement formats. Each new importer is its own 2–3
session piece of work (parser → mapper → loader, mirroring the XP
pipeline).

**Trigger to revisit:** When the user starts using a second broker,
or when a beta user from a different broker asks.

**Architectural note:** The three-layer importer pattern
(parser/mapper/loader) generalizes. XP (XLSX), BTG (XLSX), and BB
(fixed-width .txt) are all complete. The third importer (BB) has
shipped — the stated trigger for extracting shared utilities (B32, B33)
has now fired. Those items are no longer parked — both shipped 2026-05-29
(commits `4ba3f5b`, `a958e68`).

### B9. DI-curve mark-to-market — SPLIT

**Split:** This entry was split into B9a (engine: curve fetch and
accrual integration) and B9b (UI: MtM display). See those entries
for current status.

### B9a. DI curve: fetch and use for accrual — SHIPPED

**Shipped:** May 2026. Curve infrastructure complete: engine integration,
HTTP fetcher with disk cache, seed DB first-run loader, admin script for
publishing curves from ANBIMA + B3, and dev view with curve/seed status
plus B30 manual override.

**Commit range:** `6d4fd20` (Phase 1, curve engine) through `ca1efbd`
(Phase 5a, dev view). Five phases plus admin script and ancillary work.

**Data repo:** `github.com/razukadm/justfixed-data` is the public source
of curves and seed data. Admin updates manually via `tools/publish_curves.py`.

**Architectural notes:**
- The `_effective_annual_rate` seam in `engine/accrual.py` was preserved
  as scalar-rate; curve lookup happens at higher-level callers in
  `cashflow.py` and `projection.py` (Option A integration, per-period rate
  per Option 5b).
- `Curve` is a frozen dataclass with business-day vertices, linear
  interpolation, flat extension beyond bounds.
- Three curves are fetched (CDI, PRE, IPCA real). CDI is wired into projection
  directly; IPCA-linked holdings use a breakeven inflation curve derived from
  the PRE and IPCA-real curves (see B45). PRE is also retained for future
  mark-to-market work (B9b).
- Seed DB schema is flat (no ConglomerateRow); first-run loader inserts
  IssuerRow records only.

### B9b. DI curve: mark-to-market display

**Source:** Split from original B9 in May 2026. The display half.

**What it is:** Use the curve (from B9a) to compute mark-to-market
values for each investment — "what could I sell this for today,
based on current market rates." Display somewhere in the UI.

**Why deferred:** Two reasons.
1. Q3 (projection screen design) is unresolved — the right place for
   an MtM view depends on whether per-investment detail views exist
   (which is C′'s scope).
2. For retail Brazilian fixed-income (CDB/LCI/LCA) which can't be
   sold on a secondary market, MtM is informational only. The user
   value of a column they can't act on is unclear without seeing how
   C′ shapes the per-investment view.

**Trigger to revisit:** After C′ (per-investment detail view) ships.
At that point Q3 gets answered in context, and B9b can be designed as
"add MtM to the detail view C′ built."

**Architectural note:** B9a built the *curve* engine, but the
mark-to-market *computation* does not exist — `projection.py`,
`cashflow.py`, and `tax.py` all flag MtM as not-implemented (current_value
is accrual-only). So B9b is NOT UI-only as earlier stated; it needs a new
engine discounting function first.

**Verdict (2026-06-09, investigation):** Deferred, low value-per-hour for
this portfolio. Three findings: (1) the "replace current_value with MtM"
option is RULED OUT on correctness grounds — FGC concentration (`fgc.py`)
and back-solve (`back_solve.py`) both consume `current_value`; MtM-as-FGC-input
would understate exposure, since FGC pays out on contracted balance, not a
hypothetical resale price. (2) For CDI-linked instruments MtM ≈ accrual
(no rate divergence to capture); it only diverges for prefixed / IPCA+ /
Tesouro. (3) Most holdings (CDB/LCI/LCA) have no secondary market, so the
"sell today" price is informational only. If ever built, the only safe shape
is an additive display-only `market_value` field, leaving `current_value`
(and its FGC/back-solve consumers) untouched. Pivoted to B10 instead.

### B10. Multi-source current value (broker / user-edited / computed)

**Shipped (2026-06, Slices 1 + 2 — two of three sources):**
- **Slice 1 (broker-reported)** — commit f81b997. Carries the broker's
  present value (XP "Posição a mercado" / BTG "saldo bruto") from importer
  layer 1 through mapper → domain (`Investment.broker_reported_value`) →
  persistence (`broker_value_amount`/`_currency`, migration 1→2) →
  detail-panel display with a "(broker)" marker.
- **Slice 2 (user-edited)** — commit 1082886. Adds
  `Investment.user_edited_value` (separate field, coexists with broker),
  editable via the detail-panel "Current value" field even on imported
  investments; empty clears the override. Persistence
  `user_value_amount`/`_currency`, migration 2→3. Displayed with an
  "(edited)" marker. Selection precedence is **user-edited → broker-reported
  → computed**.
- Both stored values are display-only: FGC concentration and back-solve
  continue to consume the computed `current_value` (a user/broker figure must
  not change the FGC verdict, which keys on contracted balance).
- **Slice 3 (historical-computed) — DEFERRED.** The original B10 scope (fetch
  real CDI/IPCA history to replace the `_ASSUMED_*` constants) was deferred by
  decision: Slices 1+2 deliver the two *authoritative* sources for every
  holding, while Slice 3 only improves the *estimate* shown when neither
  exists, and it carries the external-API dependency plus the eight-site
  constant refactor. External verification done: **BCB SGS** chosen for both
  CDI (series 12) and IPCA (series 433) — one simple client, same `{data,
  valor}` JSON shape, no auth — rather than the heavier IBGE SIDRA the
  original plan named. Endpoints still need a live primary-source check before
  coding. Revisit when the computed fallback proves to show often enough to be
  worth the work.

The sections below describe the original three-source plan; they remain
accurate for the deferred Slice 3.

**Source:** Phase 2 list in `ARCHITECTURE.md`; reframed 2026-05-21 after two scoping investigations.

**What it is:** Give each investment a current value drawn from up to three sources, showing the freshest available one with a visible provenance indicator (colour or symbol marking which source the displayed value came from). The three sources:

- **User-edited** — a current value the user types in manually.
- **Broker-reported** — the broker's own present value from an imported statement (XP "Posição a mercado" / BTG "saldo bruto").
- **Historical-computed** — a value computed by the engine from real historical CDI/IPCA data. This is the original B10 scope: fetch historical CDI (Banco Central) and IPCA (IBGE) series and use them instead of the hardcoded `_ASSUMED_CDI` / `_ASSUMED_IPCA` constants in `ui/main.py`.

**Selection rule:** Show the freshest available source. When not all three exist, choose among those present. Priority order — user → broker → historical — is the primary tie-break and overrides naive recency: the historical-computed value recalculates on every projection, so by raw timestamp it would always appear "newest"; the priority order prevents a computed estimate from silently overriding a user edit or a recent broker statement. Recency is a secondary signal within that ordering. The exact freshness-comparison rule across source types is an open detail to pin at implementation.

**Why this reframing:** The original B10 ("fetch real index data") is now only one of the three sources, not the whole feature. The accrual math does not change — the engine already computes correctly; what changes is where the rate input comes from, and now also that two non-computed sources can supersede it.

**Investigation findings (2026-05-21):**

- The broker's present value is already parsed at importer layer 1 (`XPRow.market_value`, `BTGRow.saldo_bruto_text`) but is dropped at layer 2 — the mappers deliberately keep `principal` as acquisition cost and discard current-value fields. It never reaches the domain model or database.
- The `Investment` domain model has no field for a broker-reported or user-edited current value; the engine computes current/projected values independently at projection time.
- Touch points to carry a non-computed current value through: a new field in `ParsedXPRow` / `ParsedBTGRow` (layer 2), a field in `Investment` (domain), a persistence-schema migration, and UI display logic. Layer-1 structs already hold the data.

**Dependencies / sequencing:** C′ (per-investment detail view) has shipped, so the staging blocker is cleared — the detail view is the natural home for a multi-source value display with provenance. B9b (MtM display) was investigated and deferred (see its verdict above), so B10 no longer overlaps an active item. The historical-computed source (a Banco Central / IBGE fetcher with disk cache) should mirror the existing curve fetcher from B9a; those endpoints (Banco Central SGS, IBGE SIDRA) must be verified live against a primary source before that source is coded.

**Until B10 lands:** `_ASSUMED_CDI` and `_ASSUMED_IPCA` in `src/justfixed/ui/main.py` remain hardcoded module-level constants. They drift between Copom decisions (CDI; ~45-day cycle) and IBGE releases (IPCA; monthly). Verify both at any rebuild and update if material. Comment headers in `ui/main.py` carry source attribution (Banco Central for Selic→CDI, IBGE for IPCA acumulado 12 meses).

**Trigger to revisit:** After C′ ships. At that point the detail view exists, B9b can be designed in context, and B10's multi-source display has a home.

### B11. Database backup/restore

**Source:** Phase 2 list in `ARCHITECTURE.md`.

**Why deferred:** Single-user offline app; the SQLite file is the
backup. Manual file copy works for a developer; not for a non-technical
user.

**Trigger to revisit:** Before beta release. A non-developer user
needs a "back up your data" button somewhere in the UI.

### B12. FGC engine — per-investment timeline view — CLOSED

**Closed:** Superseded by B24 (the conglomerate consolidated report).
The per-investment timeline view's purpose — showing per-investment
exposure data within a conglomerate — is delivered by B24's detail rows.
B12's architectural note ("engine work is already done; this is purely
a UI addition") remains accurate: the underlying `ConglomerateExposure`
data structure was deliberately designed to return per-investment data,
and that's what B24's detail rows read from. No separate B12
implementation needed.

### B13. Curated issuer-to-conglomerate lookup table — CLOSED

**Closed:** Superseded by B20. The pre-seeded curation approach
replaces the loader-side hardcoded mapping. The original B13 proposal
(loader consults a hardcoded dict and emits non-`[unverified]`
issuers directly) was correct before curation memory existed; once
B′ introduces curation memory, seeding that table is the cleaner
mechanism. The user-facing outcome (new users get most issuers
already curated from day one) is preserved; the mechanism shifts to
the post-B′ design.

### B14. CNPJ / tax_id population for parser-emitted issuers

**Source:** XP loader chat, "decisions worth thinking about" section.

**Why deferred:** The loader currently creates new commercial-bank
issuers with `tax_id=""`. FGC concentration is technically keyed on
CNPJ, not name. Four options were discussed:
- (a) Curated lookup table
- (b) User fills it in via UI
- (c) Lookup from a Brazilian registry API at first import
- (d) Accept it stays empty; FGC uses normalized name as proxy

None unblocked yet. (a) is probably easiest to bootstrap.

**Parked (2026-06-09):** Specifically blocked on *data availability* — there
is no CNPJ data source on hand to populate the curated table (a), and the
registry-API route (c) is a larger lift. Until a CNPJ source exists, the app
stays on (d): FGC uses normalized conglomerate name as proxy. This is the
real blocker, narrower than the original "before high-stakes FGC use" trigger.

**Trigger to revisit:** Before FGC concentration is used for
high-stakes decisions (e.g., before any beta release where a user
might genuinely rely on the warnings).

### B15. Sector / non-FGC concentration metrics

**Source:** `docs/FGC_DESIGN.md`, "Out of scope".

**Why deferred:** FGC is the most consequential concentration metric
for Brazilian fixed-income. Sector concentration (e.g., "too much in
private credit") and other portfolio-level risk metrics weren't
identified as needs.

**Trigger to revisit:** If a user starts asking portfolio-construction
questions JustFixed can't answer.

### B16. Investigate parser LCD-iteration inconsistency — CLOSED

**Closed:** Not reproduced. Both wide (parser + mapper) and narrow
(parser only) diagnostics run against the current `PosicaoDetalhada.xlsx`
return the same single LCD record (`LCD BDMG - JUN/2029`). The original
report of an inconsistency is not reproducible. Each Claude Code session
is amnesiac about prior sessions, so the exact original diagnostic code
and its output cannot be recovered. We can verify behavior against
current code only, not behavior against prior code. B16 closes as not
reproduced.

### B17. Calendar export respects Hide matured filter — CLOSED

**Closed:** Resolved. Calendar export now passes the visible-investments
list (filtered by the Hide matured toggle) to `export_maturity_calendar`.
When the toggle is on (default), matured investments are excluded from
the `.ics` file. When off, all investments are exported. Single source
of truth via `_visible_investments()`, shared with the table and Project
flow.

### B18. Clear DB removes issuers, losing any in-DB curation

**Source:** A′-plus. The Clear Database action deletes all investments
and their issuers. If the user had manually curated any conglomerate
strings (in B′), those edits are lost on Clear DB + reimport.

**Why deferred:** Clear DB is a developer-only action (gated by
`JUSTFIXED_DEV`). Curation (B′) isn't built yet.

**Trigger to revisit:** When B′ ships and Clear DB becomes a real
user-facing workflow. At that point, consider a "delete investments
only, preserve issuers" alternative, or surface the side effect in
user guidance.

### B19. Issuer edit/delete UI (partial — delete + conglomerate/custodian management SHIPPED)

**Source:** `docs/UI_DESIGN.md` § "Deferred from A′ — milestone plan",
and the B′ design conversation (this chat).

**SHIPPED (2026-06-17, commits `86212f6` / `e3f5b52` / `9f0e73c` / `9e0d55c`):**
The **Manage Reference Data** dialog (View ▸ Manage Reference Data,
`ui/manage_reference_data.py`, `ManageReferenceDataDialog`) ships three tabs:

- **Issuers tab:** delete orphan issuers (FK-guarded; button disabled with
  tooltip when investments still reference the issuer). Curation-memory is
  preserved on delete, matching the broader curation-preserve stance.
- **Conglomerates tab:** rename a conglomerate (with merge-on-collision
  confirmation), or dissolve it (reverts all members to `[unverified] <name>`
  and clears their curation-memory entries). Backed by
  `IssuerRepository.rename_conglomerate` / `dissolve_conglomerate` (bulk,
  with curation-memory sync).
- **Custodians tab:** rename a custodian across all its investments (with
  merge-on-collision confirmation), or clear it (sets custodian to NULL).
  Backed by `InvestmentRepository.rename_custodian` / `clear_custodian`.

The main window's `refresh_table()` is called on dialog close. A
projection-cache re-pair (`dataclasses.replace` re-points cached
`ProjectionResult` objects to freshly-read investments) ensures conglomerate
label changes are reflected without a manual re-projection.

**What it needs (remaining open work):**
1. Edit issuer name — must migrate the curation-memory row if the
   natural key changes (open question: key on CNPJ root instead of
   name to avoid this; see B14). *(Still deferred.)*
2. ~~Delete issuer~~ — shipped above.
3. ~~Decision: preserve curation-memory on delete~~ — resolved: preserve,
   per the curation-preserve stance. Shipped above.

**Why the remaining rename is still deferred:** An issuer name change
alters the normalized-name natural key. The loader uses that key for
deduplication and curation-memory lookup; a rename without migrating the
key can silently recreate a "new" issuer on next import.

**Trigger to revisit:** When the user encounters a real misspelling they
want to correct.

**Architectural note:** Coupled with B14 (CNPJ/tax_id population).
If issuers become keyed on a stable CNPJ root rather than name, the
name-edit case stops needing curation-memory migration entirely.
Resolving B14 first would simplify the remaining B19 work.

### B20. Pre-seeded issuer/conglomerate table — CLOSED

**Closed:** Absorbed into B9a. The "pre-seeded" concept is delivered
via the GitHub data repo's `seed/issuers.json` file, loaded on first
app launch when the database is empty. The schema and population are
designed as part of B9a Phase 3. No separate B20 implementation.

### B21. Auto-project after state changes

**Source:** B′-companion design conversation. Deferred from Stage C
discussion.

**Why deferred:** Today, projections require an explicit "Project as
of today" click. After import, Clear DB, Hide-matured toggle, or
filter change, the cache is invalidated and the user has to click
Project again to refresh the Current/Projected columns and FGC
badges.

Auto-projecting on these events would shift the mental model from
"projections are explicit, expensive, run-when-needed" to
"projections are always current, run automatically." Both models
are valid; the explicit one is friendlier for users making rapid
state changes (e.g., toggling filters) who don't want each toggle
to trigger a fresh background projection.

**Trigger to revisit:** When the explicit-project model proves
annoying enough in practice that the user wants automatic
projection. Or before a beta release to non-developer users, where
"why are my values blank — oh, I have to click Project" is a
predictable confusion point.

**What it needs:**
1. Decision on scope — auto-project after which events? Import is
   the obvious one. Hide-matured toggle and filter changes are
   real questions: filter changes don't change *what* would be
   projected (the underlying investments are unchanged), only what
   the user is *currently viewing*. Toggling Hide-matured doesn't
   change the cached projections either, but it changes which are
   visible. The right answer might be "auto-project on data
   changes (import, Clear DB) but not on display changes (filter,
   Hide-matured)."
2. Status bar UX for chained background workers — import + project
   running back-to-back means the status bar must communicate both
   phases ("Importing..." → "Projecting..." → "Ready").
3. Possibly a setting toggle for users who prefer the explicit
   model.

**Architectural note:** The Project flow already runs in a
background worker (`_ProjectWorker`), so chaining is mechanically
trivial. The hard part is the UX decisions in #1 and #2 above.

### B22. Visual differentiation for matured investments — SHIPPED

**Shipped:** 2026-05-27, commits `e4d10b1` (`_is_matured` predicate),
`ed7d4b3` (Hide matured checkbox in filter row), `980db97` (PAID cell
substitution + row demote), `163af07` (totals exclusion, pill split).

**What shipped:** When Hide matured is OFF, matured rows appear with
"PAID" substituted in Current and Projected cells, whole-row text
demoted to `COLORS.INK_3`, and the FGC badge greyed out. Totals always
exclude matured rows regardless of toggle. Row-count pill shows
`N active · M matured` when at least one matured row is visible. See
`docs/UI_DESIGN.md` — "Matured investments — PAID treatment (B22)"
for the full design record.

### B23. Replace placeholder icon

**Source:** Pass 3a (installer work). The current `assets/icon.ico` is a
programmatically generated dark teal square with white "JF" lettering,
produced by `tools/generate_placeholder_icon.py`. Functional but not a
real design.

**Why deferred:** Real icon design is a different kind of work
(graphic design, not coding). Placeholder is fine for the beta where
testers are trusted and expect rough edges.

**Trigger to revisit:** Before any non-beta release. Or earlier if a
designer's time becomes available.

**Architectural note:** The icon path is referenced from `justfixed.spec`
(EXE icon) and Pass 4's Inno Setup script (installer icon + Start Menu
shortcut). Replacing the file at `assets/icon.ico` propagates everywhere
automatically; no spec changes needed.

### B24. Conglomerate consolidated report (tab)

**Status:** Shipped. Commits `30d6a00`–`3859f73` (May 2026).

Conglomerates tab added as first tab (default landing). Accordion layout:
one section per conglomerate, collapsed by default, click to expand.
Summary row shows total principal, current value, projected value, next
maturity, and FGC status badge. Detail rows (one per investment) add
per-row Projected Balance (sequential drawdown, maturity-ascending) and
per-row FGC badge. All values gross. Tesouro section shows "N/A" for FGC.
Projection cache shared with the Investments tab; a single "Project as of
today" button populates both tabs.

### B25. Sticky conglomerate summary-row header

When a conglomerate section is expanded and the user scrolls down through
many detail rows, the section's summary row scrolls off the top. A sticky
header (section header stays pinned while its detail rows are visible)
would improve readability for large sections.

**Deferred:** Qt's `QScrollArea` has no native CSS `position: sticky`
equivalent. Implementing it requires either a custom `QAbstractScrollArea`
subclass with manual header repositioning on scroll events, or a two-panel
layout (fixed header, scrollable body). Both approaches add significant
complexity. Defer until real user feedback confirms this is a pain point.

### B27. Investments tab: Type and Rate columns

**Shipped:** 2026-05-19, commit 32a433d ("B27: Type and Rate columns on Investments tab"). Two columns added to the Investments tab between Product and Principal: "Type" (Pré / Pós / Pós+ / IPCA+, via `_format_type`) and "Taxa" (configured rate, with effective annualized rate in parentheses for post-fixed types via `_format_rate`; Prefixed shows the single rate without a redundant parenthetical). Effective rate uses the CDI curve when available, `_ASSUMED_CDI`/`_ASSUMED_IPCA` fallback otherwise. Changes in `src/justfixed/ui/main.py`; tests in `tests/ui/test_main_window.py`.

### B28. XLSX export for Investments and Conglomerates tabs — SHIPPED

**Shipped:** 2026-06 in two slices. Slice 1 (pure module + tests): the
`exports/xlsx.py` module with `export_investments_xlsx` and
`export_conglomerates_xlsx`, both pure functions returning bytes, mirroring
`exports/calendar.py` (depend on domain + engine only). Slice 2 (UI wiring,
commit `745bc4e`): two File-menu actions ("Export investments to Excel…",
"Export conglomerates to Excel…") via the QFileDialog save flow.

**Source:** User request 2026-05-17.

**As built:**
- Format: XLSX. Money cells are written as numeric reais (not the formatted
  display string) so the file is analysable in Excel/LibreOffice.
- Investments export: one row per `visible_investments()` (filter dropdowns +
  Hide matured already applied), columns Issuer / Conglomerate / Custodian / Product /
  Type / Rate / Principal / Maturity / Current / Projected / FGC. (Custodian is export-only — it is not shown on the Investments table, which is at its column-density limit; the export is deliberately a superset. Unset custodian exports as a blank cell.) Current and
  Projected are blank when no projection has run. The FGC column reports the
  per-conglomerate `ExposureStatus` from the same `_fgc_status_by_id()` map
  the table uses (Treasury → "not_fgc"), so the file cannot disagree with the
  on-screen badge — a regression test pins this (three same-conglomerate
  R$100k holdings export "over" on every row, not "under").
- Conglomerates export: one summary row per `ConglomerateSection` (detail
  rows are not exported), rebuilt from `projection_cache` the same way the
  accordion is.
- Placement: File menu (not per-tab buttons — the Investments tab is at its
  column-density limit and the File menu already holds tab-spanning actions).
- Enablement: investments export whenever investments exist; conglomerates
  export only once a projection has run.
- Filename: `justfixed-investments-{YYYY-MM-DD}.xlsx` /
  `justfixed-conglomerates-{YYYY-MM-DD}.xlsx`; user can override in the save
  dialog.

**Follow-up resolved (2026-06-16, commit 2ad8bf9):** the Investments export's
Type column now emits the table's pt-BR labels ("Pré"/"Pós"/"Pós+"/"IPCA+")
via a shared `rate_type_label()` in `domain/rates.py`. Both the table
(`_format_type` delegates to it) and the export call it, so the two cannot
diverge. The Rate column deliberately still emits only the configured rate via
`to_display()` and does NOT add the effective-annualized parenthetical the
table shows — that figure is assumption-derived (`_ASSUMED_IPCA`, CDI curve /
fallback), and baking a drifting estimate into a saved spreadsheet was judged
undesirable (option a). `_format_rate` was therefore not extracted; only the
type label moved to the shared location. Full Rate parity / `_format_rate`
extraction remains available if ever wanted, and still pairs with B37 (i18n).

### B29. Dev view: XLSX curve export — SHIPPED

**Source:** User request 2026-05-17. Paired with B28 but distinct in
scope: this is diagnostic / validation tooling, not user-facing.

**Shipped:** 2026-06-17, commits `23c54ac` (export_curves_xlsx in
exports/xlsx.py) and `8961d3f` (dev-tab button). One sheet per curve
(CDI/PRE/IPCA), Business Days / Rate columns, active in-memory curves; a
missing curve writes a (no curve loaded) marker sheet.

**Note:** The "currently active curves" display (CDI/PRE/IPCA status:
source, anchor date, vertex count, fetch timestamp) was delivered as
part of B9a Phase 5a (commit `ca1efbd`). What remains here is the
XLSX export button only.

**What it is:** Dev view gains an "Export curve data as XLSX" button.
The exported file has one sheet per curve (CDI, PRE, IPCA), each
containing the vertices (business_days, rate) in tabular form. Purpose:
external validation — the user or admin can verify the app's projections
are using the intended curve.

**Pinned decisions:**
- Visible only when `JUSTFIXED_DEV` env var is set (consistent with
  existing dev view pattern).
- Exports the *active in-memory* curve (what's actually driving
  projection), not the on-disk cache. If those differ, the active one
  is what matters for verification.
- Format: XLSX. One sheet per curve.

**Effort:** ~1 calibrated session. Dev view scaffolding and openpyxl
(via B28) are already in place.

### B30. Dev view: load curve from file — CLOSED

**Closed:** Absorbed into B9a Phase 5a. Shipped in commit `ca1efbd`.

### B31. Dev view: edit assumed CDI and IPCA constants — SHIPPED

**Status:** SHIPPED 2026-06-16. Two commits: `fdbfa5d` (projection assumptions
made a single MainWindow-owned source, threaded to projection, calculator, and
export) and `9975be9` (Dev-tab editor: Apply & re-project / Reset). Session-only
by decision — values reset on restart; persistence not implemented (changing the
permanent default is a one-line constant edit).

**Source:** User request 2026-05-19 during B27 discussion.

**What it is:** Dev view tab gains editable fields for `_ASSUMED_CDI` and
`_ASSUMED_IPCA` constants. These are the fallback values used when the
curve is unavailable (curve fetch failed AND no cache) or for rate types
not yet curve-wired (PostFixedIPCA always; PostFixedCDI/PostFixedCDIPlusSpread
when curve unavailable).

The Dev tab shows the current values as editable fields. Saving the new
values updates the runtime constants and re-projects. Optionally persists
to disk for next session.

**Pinned decisions (tentative, refine at implementation):**
- Visible only when `JUSTFIXED_DEV` env var is set.
- Two editable fields with current values pre-filled.
- "Apply" button triggers re-projection with new constants.
- Persistence across sessions: TBD at implementation (probably JSON sidecar
  in `~/.justfixed/` mirroring the curve cache pattern).
- Validation: rates must be in (0, 0.30) range, same as the admin script's
  validation.

**Why deferred:** Convenience feature, not blocking. The current hardcoded
constants are adequate for typical use. This entry surfaces the capability
as a low-priority improvement.

**Effort:** ~1-2 calibrated sessions, riding on B9a Phase 5a's dev view
scaffolding.

**Trigger to revisit:** Any time. Independent of other roadmap items.

### B32. Extract shared Brazilian-number parsing into a common importer utility — SHIPPED

**Shipped:** 2026-05-29, commit `4ba3f5b`.

**What shipped:** `_PERCENT_RE` and `_parse_brazilian_percent_to_fraction` moved
verbatim from `xp_mapper.py` into a new shared module
`src/justfixed/importers/_parsing_utils.py`. `btg_mapper`'s cross-sibling
private import now points there; direct unit tests added in
`tests/importers/test_parsing_utils.py`. BB was confirmed out of scope —
`bb_mapper` parses a bare decimal (no `%`) via its own `_parse_taxa_magnitude`
and was not folded in.

**Source:** btg_mapper.py layer-2 review, 2026-05-20.

**Why deferred:** `btg_mapper.py` currently imports
`_parse_brazilian_percent_to_fraction` from `xp_mapper` — a
private (underscore-prefixed) symbol — creating a cross-module
coupling on another module's internals. The percent format is identical
between XP and BTG (comma-decimal, e.g. "89,00%"), so sharing is
correct; only the coupling point is wrong. Extracting to a shared
module (e.g. `importers/_parsing_utils.py`) would let both mappers
draw from a clean internal API. Deferred because two importers don't
yet justify the extraction; the private import is a known smell, not a
breaking problem.

**Trigger to revisit:** ~~When a third broker importer is added~~ — the
BB importer (commits `2544a43`, `251c120`, `45e4f58`) is the third broker.
The trigger has fired; this item is ready to pick up. The secondary
trigger (xp_mapper internals change and break the import) also still applies.

### B33. Unified issuer-kind classifier across broker importers — SHIPPED

**Shipped:** 2026-05-29, commit `a958e68`.

**What shipped:** Two halves. (1) `LoadResult` relocated from `xp_loader` to a
new shared `src/justfixed/importers/loader_types.py`; all four import sites
repointed (`xp_loader`, `btg_loader`, `bb_loader`, `detection`). (2) The two
non-conflicting per-loader classification tables (`xp_loader._DEVELOPMENT_BANK_NAMES`
and `btg_loader._ISSUER_KIND_CATALOG`) merged losslessly into a new shared
`src/justfixed/importers/_kind_catalog.py` with a `classify_issuer_kind` helper
that defaults to `COMMERCIAL_BANK`; both loaders repointed. Direct tests in
`tests/importers/test_kind_catalog.py`. BB does not use a catalog (it hardcodes
`COMMERCIAL_BANK` for its single known issuer), so the classifier unification was
XP+BTG only; BB participates solely via the relocated `LoadResult`. The
"broader scope note" below — that `LoadResult` should move to a common module —
is now satisfied.

**Source:** btg_loader.py layer-3 review, 2026-05-20.

**Why deferred:** Issuer-kind classification is duplicated across
importers: `xp_loader._DEVELOPMENT_BANK_NAMES` (frozenset of
development-bank exceptions, defaulting to COMMERCIAL_BANK) and
`btg_loader._ISSUER_KIND_CATALOG` (dict mapping normalized names to
IssuerKind, also defaulting to COMMERCIAL_BANK). The two structures
differ in shape because they grew independently — XP only needed a
development-bank exception list; BTG needed a broader kind map from the
start. A shared `importers/_kind_catalog.py` (or equivalent) would give
all loaders a single name→IssuerKind lookup with one source of truth.

**Trigger to revisit:** ~~When a third broker importer is added~~ — the
BB importer is the third broker; the trigger has fired. This item is ready
to pick up. The secondary trigger (catalog drift between importers) also
still applies. See B32 as a sibling importer-coupling item.

**Broader scope note:** The same coupling smell applies to `LoadResult`:
it is defined in `xp_loader.py` and imported by `btg_loader.py` — a
shared loader type living in one importer's module. When the classifier
work happens, `LoadResult` (and any other cross-importer types) should
move to a common module (e.g. `importers/loader_types.py`) so no loader
depends on a sibling loader's internals.

### B34. Delete investment — SHIPPED

**Shipped:** 2026-05-22, commit `a0e333e`. Detail-panel delete button
(`InvestmentDetailPanel._on_delete_clicked`), confirmed via `QMessageBox`,
calls `InvestmentRepository.delete`. `MainWindow._on_investment_deleted`
removes the entry from the projection cache and refreshes both tabs.

**What shipped:** delete applies to all investments regardless of source
(imported or manually created). No source branch, no tombstone, no orphan-issuer
cleanup — the issuer is left in place when its last investment is deleted.

**Known limitation:** re-importing a statement that contained a deleted
imported investment resurrects it, because the importer's natural-key
find-or-create (`find_by_natural_key`) has no "deleted" record to consult.
This is accepted behaviour, not a planned fix.

### B35. Run the curve daily-routine inside JustFixed (dev mode)

**Source:** Session 2026-05-21, after the publish_curves.py pymupdf speedup.

**What it is:** Move the curve-update routine from a standalone PowerShell/tools/ workflow into the app itself, under JUSTFIXED_DEV. The admin uploads the B3 BDI PDF and ANBIMA ETTJ CSV through a dev-view file picker; the app runs the existing publish_curves.py parse logic and writes latest.json into the local justfixed-data clone. The admin still reviews and git pushes manually.

**Why deferred:** Convenience/automation layer on top of B9a (shipped) and the now-fast importer. Not blocking — the PowerShell routine works and is documented in docs/DEV_ROUTINE.md.

**Design note — the deliberate stopping point:** The git push publishes latest.json to all users on next launch; that review-then-push gate exists by design and must stay human. Automate the upload-and-parse; do not automate the publish. Related: B29 and B31 (dev-view curve capabilities — build coherently with this), and B39 (a further automation increment on the fetch side).

**Trigger to revisit:** When the manual PowerShell routine becomes frequent enough to be a chore.

### B36. Review and correct error messages

**Source:** Session 2026-05-21.

**What it is:** An audit pass over user-facing error and warning messages across the app — accuracy, clarity, consistency, actionability. Correct the ones that are wrong, vague, or stale.

**Why deferred:** Quality/polish pass, not a feature. Best done as one focused sweep rather than ad hoc.

**Trigger to revisit:** Before beta release to non-developer users, where unclear errors become real support burden. Pairs naturally with B37 (i18n) — reviewing message text and translating it touch the same strings.

**As-built (2026-06-09, commit 26d3410):** The user-facing UI tier shipped —
dialog titles/bodies and status text in `ui/main.py` (split the shared
"Export failed" title by cause; stripped `{text!r}` repr leak from the two
rate-input validators; made the startup database-error dialog actionable).
Deliberately OUT of scope: the ~87 exception messages in
domain/engine/importers/persistence, which are test-pinned behaviour
contracts (each reword would need lockstep `match=` test edits) and are
developer-facing with low user value. B36's high-value tier is therefore
done; the exception-text tier is deferred, not abandoned, and pairs with B37.

**Exception-text tier closed by inspection (2026-06-11):** Audited all ~50
distinct `raise` sites across domain/engine/importers/persistence. Verdict: no
rewrite needed — the messages are already well-written. Most name the field,
show the offending value, and many give a fix example (e.g. money.py "Use
Decimal or string instead, e.g. Money.from_reais('100.50')"; accrual.py
"requires assumed_cdi parameter (e.g. Decimal('0.12') for 12% annual CDI)";
detection.py names the expected fingerprints and file types). The terse
"Unknown X: {...}" exhaustion guards fire only on programmer error, never user
input, so terseness is correct. The `{text!r}` repr in importer parse errors
(xp_mapper / btg_mapper / _parsing_utils) was considered for stripping to match
the UI tier, but kept: unlike a short UI field value, `text` here is a
spreadsheet cell, and the repr makes whitespace/encoding visible, which aids
debugging real broker files. B36 is therefore COMPLETE — UI tier reworded
(26d3410), exception tier verified adequate by audit. Any future polish belongs
to B37 (i18n), which will revisit these strings for translation regardless.

### B37. Translate the app to Brazilian Portuguese (i18n)

**Source:** Session 2026-05-21.

**Shipped:** 2026-06-20, slices S1 `3afc1e7` through S9b-tail `17f4142` (14 slices). Implemented as a lightweight in-repo string catalog: `src/justfixed/ui/strings.py` defines a frozen `Strings` dataclass exposed as the `STR` singleton — a single pt-BR locale with no runtime toggle and no Qt `tr()`/`.ts` plumbing (deliberate; the entire user base is Brazilian). Every user-facing UI string routes through `STR`: menus and tabs, the Investments and Conglomerates tabs, the Calculator, Manage Reference Data, the Curve Inspector, all `QMessageBox` dialogs and status-bar messages, the add-investment panel and its field errors, and the provenance callout. Domain display values (`Money.to_display`, `rate_type_label`, product names, dates) were already pt-BR and left untouched. The XLSX export (S8) was localized with module-local constants instead of importing `STR`, preserving the exports→UI dependency direction. Deliberately left in English: the `JUSTFIXED_DEV`-gated Dev tab and the `"JustFixed"` app-name window titles. Suite at 1517.

**Original scoping (historical, pre-implementation):**

**What it is:** Localize the UI to pt-BR.

### B38. UI design-review pass

**Source:** Session 2026-05-21.

**What it is:** A holistic review of the UI as a whole — distinct from the specific, already-scoped UI features (B19, B22, B25, B27, B28). Step back, evaluate the current interface against real usage, and produce a prioritized list of improvements. The specific improvements identified then either become their own roadmap entries or feed the existing ones.

**Why deferred:** The existing UI backlog items are all specific features; no entry currently covers an open-ended "evaluate and improve the UI overall" pass. This is that pass.

**Scope note:** To stay actionable rather than becoming a permanent "make it nicer" item, this is a bounded design-review with a definable output (the prioritized improvement list), not open-ended polishing. UI design work for this project routes through the Claude Design tool — see CLAUDE.md.

**Trigger to revisit:** Before beta release, or when accumulated UI friction makes a deliberate review worthwhile.

### B39. InfoMoney endpoint investigation for automated curve fetch

**Source:** Session 2026-05-21 (deferred during the publish_curves.py speedup work).

**What it is:** The B3 BDI PDF and ANBIMA CSV are downloaded manually each day. InfoMoney's juros-futuros-di tool serves the DI curve from a backend JSON endpoint (the page's "Baixar arquivo" button). Investigate whether that endpoint is stable and usable as an automated CDI-curve source, replacing the manual BDI download.

**Why deferred:** The pymupdf speedup fixed the parse cost; the manual fetch remains. This is the next increment. Not done because it needs a browser network-tab investigation to isolate the endpoint, and a decision on intraday-quotes vs. B3 official settlement rates.

**Caveat to capture:** InfoMoney rates are intraday quotes, not B3 official ajuste settlement rates — a different measurement, not a drop-in equivalent. Decide which the curve file should hold before adopting. Pairs with B35 (the in-app routine).

**Trigger to revisit:** When the manual daily fetch becomes a chore, or B3 changes the BDI layout and breaks the current parser.

### B40. Real-PDF regression fixture for publish_curves.py — SHIPPED

**Shipped:** 2026-05-29, commit `c1a49c1`.

**What shipped:** A real captured-pymupdf fixture
(`tests/tools/fixtures/bdi_di1_page_words.py`) holding the complete 47-row
DI1 table from the 2026-05-28 BDI page (937 word-tuples, genuine
`get_text("words")` output). A `TestParseB3RealBdi` regression class in
`tests/tools/test_publish_curves.py` pins the extracted vertex count to 47
— so a table-truncation regression fails the test even though the
pre-existing synthetic fixture would still pass. The synthetic
`_REAL_DI1_PAGE_WORDS` test was kept intact alongside it.

**Source:** Session 2026-05-21, after the pymupdf swap.

**What it is:** tests/tools/test_publish_curves.py uses synthetic word-tuple fixtures (_REAL_DI1_PAGE_WORDS) — realistic irregular spacing, but hand-built, not captured from a real BDI. Capture one real BDI page's actual get_text("words") output as a committed fixture so the suite would catch a genuine pymupdf-output-shape regression.

**Why deferred:** Minor hardening. The synthetic fixture already exercises irregular spacing; this strengthens the guarantee. The pymupdf round's near-misses (zero rows extracted, then an off-by-one) slipped past green unit tests because the fixtures were synthetic — that is the case for doing it.

**Trigger to revisit:** If publish_curves.py parsing breaks again, or before relying heavily on the curve pipeline.

**Real-data format note (for future ANBIMA parser work):** Two real-data
gotchas surfaced during the `publish_curves.py` fixes that shipped alongside
B40. (1) ANBIMA writes the Vertices column with a Brazilian thousands
separator for counts ≥ 1000 (e.g. `1.008`), so the business-day field must
have `.` stripped before `int()`. (2) Blank value cells in the ANBIMA CSV
raise `decimal.InvalidOperation` (not `ValueError`), so value parsing must
gate on a non-empty cell rather than relying on a `ValueError` except-clause.

### B41. Calculator tab — mock an investment, project, FGC headroom — SHIPPED

**Shipped:** 2026-05-28, commits `5b2d0d8` (phase 1: back-solve engine,
Prefixed), `bca0834` (phase 1.5: back-solve all four rate types),
`4713559` (phase 2.1: tab shell + form), `ae75797` (phase 2.2:
Enter-value mode), `48cb989` (phase 2.3a: Solve mode), `5f93747`
(phase 2.3b: drawdown preview), `45edbe4` (phase 2.4a: active_mock
state), `5edc924` (phase 2.4b-i: splice into Conglomerates report),
`65e50d3` (phase 2.4b-ii: mock-row visual treatment cross-tab). Polish
followup: `a36b6f3` (Drawdown preview — Projected Balance header,
peak/mock colors → red/green, MOCK badge right of issuer, fix
duplicate peak rows on shared-maturity dates).

**What shipped:** A Calculator tab that models a hypothetical
investment without saving it to the portfolio. Enter-value mode
projects the entered principal and shows maturity value, FGC
utilization, status pill, effective net rate, and tenor. Solve mode
calls `engine/back_solve.py` to compute the maximum principal that
keeps the conglomerate's FGC exposure at or below R$ 250k across the
entire holding window — with a drawdown preview showing how the mock
interacts with overlapping same-issuer holdings at peak. Both modes
splice the mock into the Conglomerates tab's expanded detail view
(amber highlight, MOCK badge) while leaving the Investments tab, FGC
totals, and projection cache unaffected. Session-only: the mock is
cleared on Reset or app close. See `docs/UI_DESIGN.md` —
"Calculator tab (B41)" for the full design record.

**Post-ship fix (2026-06-16, commit `e7eeafa`):** the mock splice was silently
dead in production. `_CalculatorTab` reached MainWindow via `self.parent()`, but
`QTabWidget.addTab` reparents the tab to the tab widget's internal
`QStackedWidget`, so the `hasattr`-guarded `set_active_mock` / `clear_active_mock`
/ `statusBar` calls never fired — the mock never spliced into the Conglomerates
detail view and calculator status messages never showed. Surfaced during B31.
Fixed by routing all three through the stored `self._main_window` reference
(captured at construction, before `addTab`); regression test reparents via
`addTab` before asserting dispatch reaches the owner.

---

### B41a. Promote mock to real investment

**Source:** B41 design Decisions doc, open-questions list.

**What it is:** An action on the Calculator's result card that takes
the currently-modeled mock and creates it as a real Investment via
the Add-investment flow, pre-populated from the mock's form values.

**Why deferred:** B41 phase 2 was already a substantial shipment. The
promote action depends on `_AddInvestmentPanel` being pre-fillable
from external state — its own wiring task. Deferred to avoid scope
creep.

**Trigger to revisit:** When a user requests it, or when comparing
multiple mocks surfaces the need to commit one of them.

**What it needs:** A "Promote to real investment" button on the
Calculator result card; a pre-fill API on `_AddInvestmentPanel`;
opening the Add panel with those values pre-set.

---

### B41b. Calculator Solve-Tesouro hardening

**Source:** B41 phase 2.4a (the Treasury guard added in
`_run_solve_calculation`, commit `45edbe4`).

**What it is:** The Calculator's "Solve disabled for Treasury" rule is
enforced by `setEnabled(False)` on the Solve radio button.
Programmatic state changes (tests, future automation) can bypass the
disable and reach the solve path with a Treasury issuer. The current
code guards this with a silent skip; the harder enforcement would be
a validation gate with a clear error if Solve mode is attempted for a
Treasury issuer.

**Why deferred:** The silent skip is correct for all reachable user
paths. The harder enforcement is belt-and-suspenders code that does
not change user-visible behavior.

**Trigger to revisit:** If the Treasury-Solve path is ever reached by
a real bug, or if the Calculator form is opened to issuer types the
radio-disable can't catch (e.g. an issuer that toggles between
Treasury and non-Treasury after Solve was already selected).

---

### B42. Custodian (bank of custody) as a first-class field

**Status:** SHIPPED 2026-05-30. Four commits:
`28c9973` (domain field) → `adc22d1` (persistence: column, mappers,
user_version migration runner + provenance backfill) → `1ddf5aa`
(importer wiring) → `f0a7c68` (UI: filter dropdown, detail panel,
manual entry).

**Resolved decisions** (the three "open decisions" below were settled
at implementation):
1. Free-form string with autocomplete — no `Custodian` entity (followed
   the Q1 issuer/conglomerate precedent).
2. Backfill from import provenance: imported rows backfilled from
   `source` (xp_import→"XP", btg_import→"BTG Pactual", bb_import→
   "Banco do Brasil"); manual rows left NULL. No "Unknown" sentinel —
   NULL renders "—" in the detail panel and "(unset)" in the filter.
3. No new table column (B27 density limit) — custodian appears in the
   filter dropdown and detail panel only.

The "Open decisions" section below is retained as the historical record.

**Source:** Session 2026-05-23. This is the use case that B3 ("Calendar
export — bank-of-custody field") was deferred waiting for — B3's trigger
was "when the domain gains a custodian field (itself blocked on a use
case requiring it)." That use case is now here.

**What it is:** Record, for every investment, which institution holds
custody of the certificate — distinct from the issuer. Brazilian fixed
income separates the issuer (the entity that pays the principal back)
from the custodian (the brokerage holding the position). Today JustFixed
models only the issuer.

**Scope:**
- A custodian field on the `Investment` domain model (or a `Custodian`
  entity if a custodian needs its own attributes — open decision below).
- Persistence-schema migration with a backfill default for existing rows.
- Importers set custodian from the detected broker: an XP statement
  imports with custodian "XP", a BTG statement with "BTG", a BB
  statement with "Banco do Brasil". The broker is already detected at
  import (`detection.py`, `Broker` enum) — this routes that known value
  into the new field instead of discarding it.
- Manual-entry form (`_AddInvestmentPanel`): the user picks a custodian
  from a list of existing custodians, or adds a new one.
- A "Custodian" filter dropdown on the Investments tab, alongside the
  existing filters.
- Custodian shown in the investment detail panel.

**Open decisions (resolve before implementation):**
1. Free-form string vs. a `Custodian` entity. The issuer/conglomerate
   precedent (Q1) chose a free-form string with autocomplete over a
   dedicated entity. Custodian has fewer attributes than a conglomerate,
   so the same call likely applies — but decide explicitly.
2. Migration backfill default for existing investments. Candidates:
   a literal "Unknown", or backfilling from import provenance where the
   originating broker is recoverable. Imported rows may be backfillable;
   manually-entered rows are not.
3. Whether the Investments tab can absorb another column or whether
   custodian is detail-panel-only. B27's note already flags the
   Investments tab at its visual-density limit; the filter dropdown
   may be the only tab-level surface, with the value shown in detail.

**Dependencies:** Unblocks B3 (calendar export can carry the custodian
once the domain has it). Crosses every layer (domain → persistence →
importers → UI), so it is a multi-session piece, not a quick add.

**Trigger to revisit:** Now — the use case is active. Sequence as its
own milestone when picked up.

---

### B43. UI theme consolidation — tokens, global QSS, shared widgets

**Source:** Session 2026-05-23 handoff document ("propagating the
curve-inspector look to the rest of JustFixed").

**Infrastructure shipped (steps 1, 2, 5):** `theme.py` (frozen
`COLORS`/`FONTS` dataclasses), `qss.py` (global stylesheet via
`make_stylesheet()`, applied once on the `QApplication`), and the
`widgets/` subpackage (`Panel`, `ProvenanceCallout`) are all on disk
and in use. The 2026-05-30 visual pass (commits through `6af1063`)
was built on this infrastructure: role/property QSS selectors,
`SELECTION_BG` and other new tokens, the `investmentsTable` and
`totalsStrip` objectName rules, tab and form-input chrome.

**Remaining scope — RESOLVED (2026-06-11):**
3. ~~Inline `setStyleSheet` audit~~ DONE (commit 8e6d2cc). Audited all
   10 calls in `main.py`. Migrated 5: three field labels to
   `role="fieldLabel"` (unified to the canonical #666666 per a design
   decision) and two field-row hints to a new `role="hint"` selector.
   The other 5 stay inline by design (the global app stylesheet; dev-tab
   single-use chrome and the QPlainTextEdit code block per qss.py's
   documented CODE_BLOCK_BG convention) and now carry a clarifying comment.
6. ~~Remove redundant dev-tab curve summaries~~ CLOSED, no action. The
   summaries (`_dev_cdi_label` / `_pre` / `_ipca` via `_summary()`) show
   curve-load provenance — fetch source, anchor, vertex count, fetch time,
   first/last vertex rates — which the Curve Inspector does NOT surface.
   They are not redundant; the "now-redundant" premise was incorrect.

With these resolved, B43 is COMPLETE: infrastructure (steps 1, 2, 5),
the visual pass (step 4), the inline-style audit (step 3), and the
dev-summary question (step 6) are all closed.

**Scope reference (original):**
1. ~~`theme.py` — tokens~~ SHIPPED
2. ~~`qss.py` — global stylesheet~~ SHIPPED
3. Refactor remaining inline `setStyleSheet` calls in `main.py`.
4. ~~Mono-numeric convention~~ SHIPPED (visual pass, commit 2).
5. ~~Extract `ProvenanceCallout` and `Panel`~~ SHIPPED (`widgets/`).
6. Remove redundant dev-tab curve summaries.

**Relationship to B38:** B38 is the open-ended UI design-review pass.
B43 infrastructure is complete; open items are cleanup/polish.

---

### B44. C′ projection detail view — accrual breakdown, IR tax, net-at-maturity — SHIPPED

**Shipped:** 2026-05-28. Single commit: "B44: projection detail section
in InvestmentDetailPanel; closes C′".

**What shipped:** Projection Panel added to `InvestmentDetailPanel`,
below the investment-fields scroll area. Five rows: current value,
gross at maturity, gain, IR tax (rate + amount), net at maturity.
Placeholder ("No projection yet…") when no cache entry exists for
the selected investment; real-time refresh via
`refresh_projection()` called from `show_investment`, `clear`, and
`MainWindow._on_project_done`. Closes C′. See `docs/UI_DESIGN.md` —
"Projection detail (B44)" for the full design record.

---

### B45. IPCA-linked projection via market breakeven inflation — SHIPPED

**Shipped:** 2026-06-17, commits `3d4e107` (breakeven_inflation_curve in
engine/breakeven.py), `2911292` (threaded through project/cashflow),
`5f5efd1` (forwarded through fgc_concentration_report), `78fea37` (UI: derive
in MainWindow, wire portfolio + Calculator).

**What it is:** PostFixedIPCA holdings previously projected off a single flat
assumed-inflation constant (_ASSUMED_IPCA, 4.14%) for every maturity. They now
use market-implied breakeven inflation, per maturity: breakeven = (1+nominal)/
(1+real)-1 from the PRE and IPCA-real curves, evaluated at each holding's
maturity tenor.

**Deliberate convention (do not "fix"):** the breakeven is evaluated at
rate_at(maturity) at EVERY accrual site, including coupon flows — unlike CDI,
which uses each flow's own date (bullet→maturity, coupon→coupon_date). This is
intentional: breakeven is a term inflation expectation for the whole
instrument, so all of a bond's flows use the maturity-tenor breakeven. A code
comment marks this at the coupon site; do not harmonize it with CDI.

**Fallback:** breakeven_inflation_curve returns None when PRE or IPCA-real is
absent/empty or their anchors differ (mixing publish dates is invalid); in
that case projection falls back to the flat assumed constant. The derived
curve is cached on MainWindow (self._breakeven_curve), re-derived on each fetch.

**Also closed:** the Calculator now passes both cdi_curve and the breakeven
curve into its project() and fgc_concentration_report() calls — it previously
passed no curve at all (flat for both CDI and IPCA).

---

## Part 3 — Open questions

Decisions that surfaced as "we should figure this out before X"
but haven't been answered. Different from backlog items: these are
*blocking* future work, not features to build.

### Q1. Conglomerate curation UX — Resolved

`Issuer.conglomerate` remains a free-form string; no `Conglomerate`
entity. B′ curation is inline string editing with autocomplete from
existing DB values. See `docs/UI_DESIGN.md`, "Conglomerate model —
decision recorded."

### Q2. UI scope (Option A/B/C) — Resolved

Milestone A′ (~2–3 sessions): one window, import + read-only table
with FGC badges + project + calendar export. Manual entry, detail
view, and curation deferred to B′/C′. See `docs/UI_DESIGN.md`.

### Q3. DI-curve MtM and projection screen design

**Surfaced in:** XP loader chat, "decisions worth thinking about".

**Question:** When DI-curve MtM is added (B9b above), how does the
projection screen present "today's value" — accrual-based,
market-based, or both?

**Why it matters:** Decision affects the projection screen's layout
*now*. Building it for accrual-only and retrofitting market-based
later means a UI rework. Building it for both modes from the start
means more work upfront with placeholder content for the unimplemented
mode.

**Blocks:** UI work on the projection display, if Option B or C is
chosen for Q2.

### Q4. File-picker default location

**Surfaced in:** XP loader chat, "decisions worth thinking about".

**Question:** When the UI's "import statement" button opens a file
picker, what's the default location?
- `~/Documents/JustFixed/`?
- The last-used path (remembered between sessions)?
- The default Downloads folder?

**Why it matters:** Small UX decision but worth making once rather
than improvising five times across different file pickers.

**Blocks:** UI work on the import flow.

### Q5. Doc-update timing — Resolved

Feature-specific docs updated per pass; cross-cutting docs swept at
end of feature in a dedicated commit. See `CLAUDE.md`, "Doc-update
timing."

---

## Maintenance notes

- When a backlog item gets built, move it from Part 2 to a
  "Recently shipped" section here briefly, then delete in the next
  roadmap update once the docs reflect it.
- When an open question gets answered, move it to a decision log
  (or just delete it once the resulting work has started — the
  context lives in the design doc that the work produced).
- This file is in scope for the same "docs match reality" discipline
  as `ARCHITECTURE.md` and `CLAUDE.md`. If the test count changes,
  it doesn't matter here. If a feature is built or a question is
  answered, that matters.
- New deferred items should land here as they surface, not in the
  conversation transcripts they came from.

---

## Source chats (for traceability)

This roadmap was compiled from:

1. **Software development project mentorship** — initial setup through
   domain/persistence/engine layers. Source of the original 7-week
   plan, the `ics` library choice (later replaced), the SQLCipher
   deferral, and the Phase 2 list (DI-curve MtM, real index data,
   multi-broker importers, backup/restore).

2. **Building XP loader layer 3 with issuer reconciliation** —
   importer Layer 3 implementation, the `[unverified]` conglomerate
   convention, the FGC concentration design, and the calendar export
   design. Source of most "decisions worth thinking about" items now
   in Open Questions.

3. **Calendar export feature build** (this chat) — calendar export
   implementation. Source of the orphan event cleanup deferral
   (B1) and the v2 design sketch.

---

## Session status — 2026-05-20

### BTG importer — SHIPPED

Shipped end to end: a BTG statement imports from file picker through to
investments in the table, broker auto-detected.

Layers delivered:
- `btg.py` (parser), `btg_mapper.py` (mapper), `btg_loader.py` (loader)
- `detection.py`: `Broker` enum, `detect_broker` (sheet-name fingerprints),
  `load_statement` dispatcher
- UI rewire: single "Import Statement" button; `_on_import_done` unpacks a
  `(Broker, LoadResult)` tuple and shows per-broker `QMessageBox.information`

Final commit of the feature: `282bd73`. The feature spans from the BTG
parser commit through `282bd73`.

Verified against the real statement file and by manual UI click-test (BTG
import, XP import, unrecognized-file error). Nothing pending on BTG itself.

### C′ milestone — shipped through commit 6

Investment detail-panel editing and the manual-entry form. All defined
commits landed: 1 (`74b18b6`) through 6 (`08a2ead`, 2026-05-21). Delivered:
side panel scaffolding and row selection, field-by-field view mode,
per-field editing via `_EditableField` (double-click to edit,
`dataclasses.replace` save), rate editing, and `_AddInvestmentPanel` for
manually entering non-XP investments.

"Commits 7–8" were referenced in the original C′ plan but had no defined
content — no design note, no `UI_DESIGN.md` section, no concrete scope.
They are not remaining work.

Two real gaps persist in this area, better tracked as their own items than
as unfinished C′: (a) the detail panel does not yet show the computed
accrual breakdown, IR tax, or net-at-maturity that `ARCHITECTURE.md`'s C′
description calls for — the main feature gap; (b) per-investment delete is
not wired into the detail panel UI — already tracked as B34.

### Next broker importer — touchpoints

~~When a third broker is added~~ — the BB importer (commits `2544a43`,
`251c120`, `45e4f58`) is now the third. Touchpoints were exactly as predicted:
1. `Broker.BB` enum member in `detection.py`
2. A fingerprint case in `detect_broker` (BB is `.txt`; routed by extension,
   then confirmed by a header line containing both `"SISBB"` and `"Banco do Brasil"`)
3. A dispatch case in `load_statement`

The UI did not change. The third-importer trigger for B32 and B33 has fired.

### Open items (pointers)

The GuaranteeFund milestone (Part 1 §4, "Model guarantee funds
(FGC / FGCoop) as first-class entities") remains open. B32 (shared
Brazilian-number parsing) and B33 (unified issuer-kind classifier) were
un-parked here when the third-importer trigger fired with BB, and shipped
2026-05-29 (commits `4ba3f5b` and `a958e68`).

---

## Session status — 2026-05-23

### BB importer — SHIPPED

All three layers shipped. Commits `2544a43` (Layer 1), `251c120` (Layer 2),
`45e4f58` (Layer 3 + detection). Parser reads fixed-width `.txt`, not XLSX.
Mapper infers rate type from TAXA magnitude (`_RATE_BANDS`). Loader skips
matured positions (saldo == zero). Verified against the synthetic fixture
(`synthetic_bb_statement.txt`). Third-importer trigger for B32 and B33 has fired.

### Curve Inspector — SHIPPED

Three read-only yield-curve windows shipped. Commits `58d4259` (Part 1,
static), `bbd728e` (provenance callout restructure), `b98bd10` (chart/table
hover-sync, chart-hover crash fix), `1017af1` (date-based x-axis, 2-column
table, hover-match fix at ms scale). Accessible from the View menu — CDI,
PRE, IPCA. `ui/curve_inspector.py` wired from `MainWindow._open_curve_inspector`.

### B34 — per-investment delete — SHIPPED

Commit `a0e333e`. Detail-panel delete button, `QMessageBox` confirm,
`InvestmentRepository.delete`, projection cache cleared. Applies to all
investments; no tombstone. Re-importing resurrects a deleted imported
investment (known, accepted).

### B22 — PAID visual treatment for matured investments — SHIPPED

Commits `e4d10b1`–`163af07` (2026-05-27). Hide matured checkbox added
to filter row. When toggle is OFF: Current/Projected show "PAID", whole
row demoted to `INK_3`, FGC badge greyed. Totals always exclude matured
rows. Pill shows `N active · M matured` when matured rows are visible.

### Open items

B41 (Calculator tab) and B44 (C′ projection detail view) both shipped
2026-05-28; C′ is now complete. B41a (promote mock to real investment)
and B41b (Solve-Tesouro hardening) are deferred items spun off from
B41. B32 and B33 shipped 2026-05-29 (commits `4ba3f5b`, `a958e68`); the
GuaranteeFund milestone remains open.