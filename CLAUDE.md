# CLAUDE.md

Notes for any Claude session (Claude Code or claude.ai) working on this repo.
Read this before starting work. The full architecture lives in `docs/ARCHITECTURE.md`;
this file is the working-style and conventions summary.

## What this project is

JustFixed is a Windows desktop portfolio tracker for Brazilian fixed-income investments
(CDB, LCI, LCA, LCD, LC, Tesouro Direto). Offline-first, single-user. Engine,
persistence, exports, and the XP importer are complete; the UI (PySide6) is through
B24 (read-only viewer, conglomerate curation, filter dropdowns, totals strip,
Conglomerates accordion tab) plus B9a (live curve fetch, seed DB loader, dev view tab).
The README covers the user-facing intent; ARCHITECTURE.md covers the internal shape.

## Architectural shape

Strict layer ordering, no upward dependencies:

- `domain/` — pure value/entity types (Money, Rate, Issuer, Investment). No I/O.
- `persistence/` — SQLAlchemy models, mappers, repositories, alembic migrations.
- `engine/` — calendar, accrual, tax, projection, fgc. Pure functions over domain types.
- `importers/` — three layers: parser (xlsx → strings), mapper (strings → typed),
  loader (typed → persisted).
- `exports/` — calendar.py: iCalendar (.ics) export. Depends on domain + engine, not persistence.
- `ui/` — PySide6 single-window app. Milestones A′, B′, B24, and B9a shipped (read-only viewer, conglomerate curation, Conglomerates accordion tab, dev view with curve/seed status). See docs/UI_DESIGN.md.

Each layer's tests live in `tests/<layer>/` mirroring `src/justfixed/<layer>/`.

## Hard conventions

- **All money is `Decimal`, never `float`.** Financial precision is non-negotiable.
- **All rates are typed.** One of `Prefixed`, `PostFixedCDI`, `PostFixedCDIPlusSpread`,
  `PostFixedIPCA`. No raw numbers in rate-shaped slots.
- **Domain types validate in `__post_init__`.** Corrupt data fails to load with a
  clear `ValueError`. The domain is the gatekeeper for invariants.
- **Tests are the spec.** If behavior changes, the test changes first. Currently
  622 tests, ~4 second runtime, no skips. Tests pass on every commit.
- **Hand-compute financial test expected values.** Show all decimals; don't approximate.
  Approximation has been a real source of bugs.
- **Repositories are the only public access to persistence.** Engine, UI, and importers
  depend on repository classes, not SQLAlchemy directly.

## Loader-specific decisions (Layer 3)

These are the most counter-intuitive design choices in the codebase. Read before
touching `src/justfixed/importers/xp_loader.py` or anything that calls it.

### Issuer matching uses normalized name

`Issuer.normalize_name(s)` is the canonical form: strip whitespace, collapse internal
whitespace, uppercase. Punctuation and accents are preserved (`"S/A"` ≠ `"SA"`,
`"Itaú"` ≠ `"Itau"`). Stored on `IssuerRow.normalized_name` with a unique index.
The database, not the application, enforces "no two issuers share a normalized name."

### Treasury routing

Parsed `issuer_name == "Tesouro Nacional"` resolves via `Issuer.treasury()` (canonical
factory with the right CNPJ and `IssuerKind.TREASURY`), not as a generic commercial bank.

### `[unverified]` conglomerate convention

New commercial-bank issuers from the loader are created with
`conglomerate=f"[unverified] {name}"`. The loader doesn't know which brands roll up
into which holdings (Itaú/Unibanco, BTG/Pan, etc.) — that's a curation problem the
FGC concentration check (engine/fgc.py) surfaces. The persistence foundation for
curation is now live (B′): `CurationMemoryRepository` stores curated values, and the
loader auto-applies them on the create branch. The curation UI is shipped; the table shows verified and [unverified]-prefixed
conglomerate names with inline editing on the conglomerate column.
The prefix signals "human review needed."
The constant `UNVERIFIED_CONGLOMERATE_PREFIX` lives in `domain/issuer.py` and is consumed
by both the loader (writing) and the FGC engine (reading).

### Natural-key idempotency, no DB constraint

Re-importing the same statement does not duplicate investments. The natural key is
`(issuer_id, product, principal, purchase_date, maturity_date)`. The loader checks
`InvestmentRepository.find_by_natural_key(...)` before insert.

There is **no unique constraint** on this tuple in the database. A user can legitimately
hold two identical positions through separate orders; only the importer enforces
deduplication, not the schema. Manual UI entry (Phase 2) is free to create natural-key
duplicates.

## The "audit when it crashes" rule

The domain enforces product/coupon-frequency rules (e.g., LCI is bullet-only). These
rules can be over-strict relative to the real Brazilian market. **Don't preemptively
audit them.** When real broker data crashes the loader because a rule rejected a
legitimate combination, fix that one rule with a focused test and commit, and move on.
The crash is the signal; absence of crash means the rule is currently fine.

(Already discovered: LCAs do allow monthly coupons in real issuances; the rule was
relaxed. LCI is still bullet-only and stays that way until a real LCI-with-coupons
crashes the loader.)

## Loader and parser hardcoded knowledge

Two small hardcoded sets live in the importers, each recognizing things the
importer needs to know about specific Brazilian financial entities or document
structures. A third mechanism (curation memory) is database-backed, not hardcoded:

- **Curation memory** (`CurationMemoryRepository`, table `curation_memory`): maps
  normalized issuer names to curated conglomerate strings. The loader consults this
  on the **create branch only** — if a curated entry exists for the normalized name,
  the new issuer is created with that conglomerate instead of `[unverified] {name}`.
  Existing issuers are never overwritten; the find branch ignores curation memory
  entirely. Entries are populated by the B′ curation UI (shipped) and the seed
  loader's first-run import (B9a Phase 3, shipped). The repository is also writable
  directly, which is how tests seed curation memory.
- **Development-bank set** (xp_loader.py `_DEVELOPMENT_BANK_NAMES`): issuers in this
  set get `IssuerKind.DEVELOPMENT_BANK` instead of the `COMMERCIAL_BANK` default.
- **Section-terminator set** (xp.py `_RENDA_FIXA_TERMINATORS`): row text matching
  these strings ends the Renda Fixa reading loop, preventing the parser from reading
  into subsequent non-fixed-income sections.

Entries are added per the audit-when-it-crashes rule: a real XP statement crashes
the importer, one entry is added with a focused test, ship.

## Working style preferences

- **Slow and step-by-step.** One file at a time, one focused change per paste.
- **Verify each edit landed.** After any non-trivial paste, check the file with
  `Get-Content <path> -Tail 5` (in PowerShell) or equivalent. Indentation errors on
  multi-line pastes have been a real source of grief.
- **Run pytest after every change.** The full suite runs in ~2 seconds; there's no
  excuse to skip it.
- **One commit per focused change with passing tests.** Commit messages describe what
  changed, not vague "updates" or "fixes." If two unrelated things land, two commits.
- **Slow down on financial test expected values.** Compute by hand, show all decimals,
  don't approximate.
- **Talk through design before writing code on anything substantive.** A 5-minute
  conversation about "what is this method's contract?" prevents 30 minutes of
  refactoring later. claude.ai is good for this; Claude Code is good for executing
  the plan once made.

**Doc-update timing.** Feature-specific docs (the doc most directly
describing this feature's surface — e.g. `BUILD.md` for the installer,
`FGC_DESIGN.md` for FGC work) get updated per pass, as part of the same
commit that lands the implementation pass they describe. Cross-cutting
docs (`ARCHITECTURE.md`, `ROADMAP.md`, `CLAUDE.md`, `UI_DESIGN.md`) get
swept once at the end of a feature in a dedicated commit.

The cross-cutting sweep draws on the already-current feature-specific
docs, not on memory of what shipped. This is what protects against the
"claimed it but didn't" sweep-at-the-end failure mode.

## Things that have caused trouble

- **Indentation on multi-line paste.** VS Code "Render Whitespace" should be on.
- **PowerShell command concatenation.** Don't run two unrelated commands on one line —
  output mixes and diagnosis gets confusing.
- **PATH changes don't propagate to the current shell.** Always open a new terminal.
- **Line-ending warnings (`LF will be replaced by CRLF`).** Cosmetic, ignore. Windows
  checkout, Unix line endings in repo, git is doing the right thing.
- **The architecture doc and README can drift from reality.** Test counts, layer
  status, available functions. When making substantial changes, sweep the docs
  in the same PR or as the immediate-next commit.
- **Personal data in the repo.** Real `PosicaoDetalhada.xlsx` files belong outside
  the working tree (e.g., `~/Documents/JustFixed/`). Only `synthetic_xp_statement.xlsx`
  goes in `tests/importers/fixtures/`. The `.gitignore` enforces this.

## Pointers

- Full architecture: `docs/ARCHITECTURE.md`
- User-facing summary: `docs/README.md` (also serves as the project's GitHub README)
- Build and packaging: `docs/BUILD.md`
- Test fixtures: `tests/importers/fixtures/synthetic_xp_statement.xlsx`
- Real broker data (your machine only, not tracked):
  `C:\Users\carlo\Documents\JustFixed\PosicaoDetalhada.xlsx`

## Team & working agreement

Four participants work on this project:
- **claude.ai** — project manager: design discussion, task decomposition,
  drafting Claude Code prompts, reviewing returned work, authorizing commits.
- **Claude Design** — visual work: mockups, prototypes, UI flows. Hands
  designs to Claude Code for implementation or back to claude.ai for discussion.
- **Claude Code** — implementation in this repository.
- **The user** — decisions, authorization, and routine local checks.

**Turn structure.** When a claude.ai turn produces work for others, it is
written project-manager style: discrete, labelled blocks, one owner per
block — never merged into a single block. Standard block labels:
- `Claude Code — task`: the verbatim prompt to paste into Claude Code.
- `Claude Design — task`: when visual/design work is needed.
- `Your turn — PowerShell`: commands for the user to run in their own
  terminal, given in PowerShell syntax.
- `Back to claude.ai — review`: what the user pastes back into claude.ai
  for evaluation, fixing, and authorization.

The seam between "Claude Code's job is done" and "returned to claude.ai
for review" must be unmistakable.

**Prefer PowerShell for cheap checks.** Routine inspection — git status,
git log, git show --stat, file listings, reading a short file — the user
runs directly in PowerShell rather than spending a Claude Code turn on it.
claude.ai states explicitly which steps are the user's PowerShell turn and
which need Claude Code. Claude Code is reserved for actual code changes and
substantive work. Note: "PowerShell" refers to the user's local terminal;
Claude Code uses its own tool environment for its own tasks.

**Review gate.** Claude Code stops before committing. Diffs are read before
approval. Importer and real-data work is gated on smoke tests against real
files, not only synthetic fixtures. The block structure makes this gate
clearer — it does not replace it.

The JustFixed project's claude.ai instructions mirror this section; if the
working agreement changes, revise both together.

**UI design workflow.** UI design work for JustFixed routes through the Claude Design tool — mockups, prototypes, and UI flows are produced there before implementation. Claude Code implements from reviewed designs; it does not originate visual work.