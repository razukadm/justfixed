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

**Status:** Milestone A′ complete (commit `ad05ad4`). See
`docs/UI_DESIGN.md` for what shipped and what's deferred.

**A′ — shipped.** One-window read-only app: import XP statement,
investment table with per-row FGC badges, project as of today,
export maturity calendar to .ics.

**A′-plus — shipped** (commits `27541bb`, `6d26697`, `28becc8`,
`0099c02`, `897e66e`, `f975aad`, `1582ee5`). Three UI additions:
Clear DB button (dev-flag gated), Projected Value column (net at
maturity), Hide matured toggle. Plus four loader/domain/parser
fixes surfaced during testing (BDMG issuer kind, LCA-from-dev-bank
rule, ProductRule generalization, parser section terminators).
See `docs/UI_DESIGN.md` § "Deferred from A′" for specs.

**B′ — curation (~2-3 sessions).** Inline conglomerate editing
with autocomplete. Model: string editing only, no verified flag.
Autocomplete filtered to verified-only. Immediate FGC refresh on
every edit. See `docs/UI_DESIGN.md` § "Deferred from A′" for
specs.

**B′ companion — filter and totals (~1-2 sessions).** Filter by
issuer/conglomerate, totals panel. Depends on B′ being shipped
(filtering by conglomerate is much less useful while
`[unverified]` rows pollute the namespace).

**C′ — manual entry and detail view (~3-4 sessions, deferred).**
Manual-entry form for non-XP investments, per-investment detail
view with accrual breakdown and IR tax.

**Risks worth keeping in mind for B′:**
- PySide6 changes between minor versions. Verify against current
  docs at build time, not from training-time memory.
- UI bugs are visual; the feedback loop stays "run the app, look
  at it." Don't try to instrument GUI verification through
  background-launch tricks.
- API names in the backend (LoadResult fields, ProjectionResult
  shape, etc.) need to be confirmed by reading source before code
  is written that depends on them.

### 2. Windows installer

**Status:** Not started. ~1–2 sessions.

PyInstaller to bundle the app into an executable, Inno Setup to create
a Windows installer. End state: a `.exe` installer the user (or a beta
tester) can double-click to install JustFixed without touching Python.

**Dependencies:**
- UI must be built (no installer for a backend-only library).
- Decision on whether SQLCipher encryption is included (see Backlog
  item B7 — currently deferred, plain SQLite is in use).

### 3. Phase 2 — post-MVP

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

**Source:** `docs/CALENDAR_EXPORT_DESIGN.md`, "Future enhancements"
section.

**Why deferred:** Brazilian fixed income has separate issuer (the
entity paying back) and custodian (the brokerage holding the
certificate). The domain doesn't currently model custodian.

**Trigger to revisit:** When the domain gains a custodian field
(itself blocked on a use case requiring it).

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
(parser/mapper/loader) generalizes. A second broker importer would
follow XP's footprint. If a third importer is ever built, that's the
moment to consider whether common parser/mapper utilities should be
extracted — not before.

### B9. DI-curve mark-to-market

**Source:** Phase 2 list in `ARCHITECTURE.md`. Long-standing
commitment from the original vision doc.

**Why deferred:** Real mark-to-market for Tesouro Prefixado mid-life
requires discounting future cash flows by the current DI curve from
B3. Phase 1's accrual-only valuation is honest but not market-true.

**Trigger to revisit:** When the user wants to know "what could I
sell this for today" rather than "what has it accrued to today."

**Note:** This decision has UI consequences (see Open Question Q3).
If MtM lands, the projection screen needs either two view modes or
a per-investment toggle.

### B10. Real index data fetching (B3 for CDI history, IBGE for IPCA)

**Source:** Phase 2 list in `ARCHITECTURE.md`.

**Why deferred:** PostFixedCDI and PostFixedIPCA accrual currently
takes assumed annualized rates as parameters. The math is correct;
the input is a user-supplied assumption. Real history would replace
the assumption with computed values.

**Trigger to revisit:** When the user wants to see "what this
investment is *actually* worth right now" rather than "what it would
be worth if CDI averaged X%."

**Architectural note:** The accrual formulas don't change when real
data arrives — the engine already does the math correctly. What
changes is *where the rate input comes from*. The seam already exists.

**Until B10 lands:** both `_ASSUMED_CDI` and `_ASSUMED_IPCA` in
`src/justfixed/ui/main.py` are hardcoded module-level constants.
They drift between Copom decisions (CDI; ~45-day cycle) and IBGE
releases (IPCA; monthly). Verify both at any rebuild and update if
material. Comment headers in `ui/main.py` carry source attribution
(Banco Central for Selic→CDI, IBGE for IPCA acumulado 12 meses)
to guide the verification.

### B11. Database backup/restore

**Source:** Phase 2 list in `ARCHITECTURE.md`.

**Why deferred:** Single-user offline app; the SQLite file is the
backup. Manual file copy works for a developer; not for a non-technical
user.

**Trigger to revisit:** Before beta release. A non-developer user
needs a "back up your data" button somewhere in the UI.

### B12. FGC engine — per-investment timeline view

**Source:** `docs/FGC_DESIGN.md`. The engine already returns
per-investment exposure data inside each `ConglomerateExposure`,
deliberately, so this UI can be built without engine changes.

**Why deferred:** Phase 1's report summarizes by conglomerate. The
timeline view would render per-investment: when each investment in a
conglomerate matures, what the running exposure looks like as each
pays out.

**Trigger to revisit:** When the FGC concentration UI is being
designed and the user wants to see "how does my exposure to this
conglomerate decay over time?"

**Architectural note:** Engine work is already done. This is purely
a UI/visualization addition.

### B13. Curated issuer-to-conglomerate lookup table

**Source:** XP loader chat, "decisions worth thinking about" section.

**Why deferred:** The `[unverified]` convention defers the curation
work to whenever the user reviews FGC concentration. A pre-curated
lookup table would let the loader produce correct conglomerates from
day one, but requires hand-maintenance that grows over time.

**Approach if revisited:** Hardcoded mapping in the loader (or a
separate config file): `"BMG"` → `"Banco BMG"`, `"CEF"` → `"Caixa
Econômica Federal"`, `"Itaú"` and `"Unibanco"` → `"Itaú Unibanco
Holding"`, etc. New issuers not in the table fall back to the
`[unverified]` convention.

**Trigger to revisit:** If the curation workflow (Open Question Q1)
becomes painful enough that the user wants the loader to handle the
common cases automatically.

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

### B17. Calendar export should respect Hide matured filter

**Source:** A′-plus testing. The calendar export currently includes all
investments, including matured ones, regardless of the Hide matured
toggle state. Pre-existing behavior since A′.

**Why deferred:** May be intentional — a maturity calendar is about
events that happened, not just future events. Worth a deliberate design
pass before assuming it's a bug.

**Trigger to revisit:** When a user finds stale matured events in their
exported calendar and asks for them to be excluded.

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

**Question:** When DI-curve MtM is added (B9 above), how does the
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

### Q5. Doc-update timing

**Surfaced in:** XP loader chat, "decisions worth thinking about".

**Question:** Do `ARCHITECTURE.md` and `CLAUDE.md` get updated
*during* feature work (small commit per layer change) or *after*
(a sweep at the end)?

**Why it matters:** The end-of-feature sweep was the source of one
"claimed it but didn't" mistake during loader work. Per-step doc
updates scale better but slow each session.

**Blocks:** Nothing concrete. It's a process decision worth making
explicit before the next feature, so we don't keep oscillating.

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