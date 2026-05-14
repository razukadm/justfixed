# CLAUDE.md

Notes for any Claude session (Claude Code or claude.ai) working on this repo.
Read this before starting work. The full architecture lives in `docs/ARCHITECTURE.md`;
this file is the working-style and conventions summary.

## What this project is

JustFixed is a Windows desktop portfolio tracker for Brazilian fixed-income investments
(CDB, LCI, LCA, LCD, LC, Tesouro Direto). Offline-first, single-user. Engine,
persistence, and exports are complete; the importer for XP statements is complete;
the UI (PySide6) is the next major piece. The README covers the user-facing intent; ARCHITECTURE.md
covers the internal shape.

## Architectural shape

Strict layer ordering, no upward dependencies:

- `domain/` — pure value/entity types (Money, Rate, Issuer, Investment). No I/O.
- `persistence/` — SQLAlchemy models, mappers, repositories, alembic migrations.
- `engine/` — calendar, accrual, tax, projection, fgc. Pure functions over domain types.
- `importers/` — three layers: parser (xlsx → strings), mapper (strings → typed),
  loader (typed → persisted).
- `exports/` — calendar.py: iCalendar (.ics) export. Depends on domain + engine, not persistence.
- `ui/` — PySide6 single-window app. Milestone A′ shipped (read-only). See docs/UI_DESIGN.md.

Each layer's tests live in `tests/<layer>/` mirroring `src/justfixed/<layer>/`.

## Hard conventions

- **All money is `Decimal`, never `float`.** Financial precision is non-negotiable.
- **All rates are typed.** One of `Prefixed`, `PostFixedCDI`, `PostFixedCDIPlusSpread`,
  `PostFixedIPCA`. No raw numbers in rate-shaped slots.
- **Domain types validate in `__post_init__`.** Corrupt data fails to load with a
  clear `ValueError`. The domain is the gatekeeper for invariants.
- **Tests are the spec.** If behavior changes, the test changes first. Currently
  462 tests, ~5 second runtime, no skips. Tests pass on every commit.
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
FGC concentration check (engine/fgc.py) surfaces and the future curation UI will resolve.
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

Three small hardcoded sets live in the importers, each recognizing things the
importer needs to know about specific Brazilian financial entities or document
structures:

- **Conglomerate-name lookup** (xp_loader.py): when the loader sees a known issuer
  name, it assigns the canonical conglomerate string instead of the `[unverified]`
  default.
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
- Test fixtures: `tests/importers/fixtures/synthetic_xp_statement.xlsx`
- Real broker data (your machine only, not tracked):
  `C:\Users\carlo\Documents\JustFixed\PosicaoDetalhada.xlsx`