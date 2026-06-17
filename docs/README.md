# JustFixed

A desktop portfolio tracker for Brazilian fixed-income investments (CDB, LCI, LCA, LCD, LC, Tesouro Direto). Offline-first, Windows-targeted, single-user.

**Status:** in development. Engine, persistence, the XP/BTG/BB importers, exports, and the PySide6 desktop UI are all functional. See [`ARCHITECTURE.md`](ARCHITECTURE.md) for what's built and what isn't.

## What it does

Given a portfolio of Brazilian fixed-income positions, JustFixed answers:

- *What is each position worth today?* (252-business-day accrual from purchase date)
- *What will it pay at maturity, gross and net of IR tax?*
- *When are the next coupon payments?* (for juros mensais / juros semestrais bonds)
- *How exposed are you to a single FGC conglomerate?* (R$250k per-conglomerate limit with UNDER/APPROACHING/OVER status)
- *What is the maximum I can invest while staying under the FGC limit?* (back-solve to the R$250k ceiling, accounting for all same-conglomerate holdings across the holding window)
- *When do my positions mature, and how much will I receive?* Export a .ics calendar file to drag into Google Calendar or Apple Calendar.

It does **not** mark positions to market — accrual only. Phase 2 will add DI-curve MtM.

## Why it exists

Brazilian retail brokerages produce statements that show *current values* but not *projected outcomes*. Investors who hold to maturity want to know "what will I actually receive on this date." JustFixed answers that, accurately, with the right tax treatment per product type and the right holiday-aware business-day math.

## Quick start (development)

Prerequisites: Windows 11, Python 3.13, Git.

```powershell
git clone https://github.com/razukadm/justfixed.git
cd justfixed

# Set up venv
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install
pip install -e .[dev]

# Initialize the database
alembic upgrade head

# Run tests
pytest tests/ -v
```

You should see 1406 tests passing in about 16 seconds. If anything fails, the architecture doc covers common environment issues.

## Using what's built

The engine is fully functional — you can compute projections from Python without any UI. Example:

```python
from datetime import date
from decimal import Decimal
from justfixed.domain.investment import Investment
from justfixed.domain.issuer import Issuer, IssuerKind
from justfixed.domain.money import Money
from justfixed.domain.product import ProductType
from justfixed.domain.rates import PostFixedCDI
from justfixed.engine.projection import project

issuer = Issuer.create("Banco Inter", "Banco Inter S.A.", IssuerKind.COMMERCIAL_BANK)
inv = Investment.create(
    product=ProductType.CDB,
    issuer=issuer,
    principal=Money.from_reais("50000"),
    rate=PostFixedCDI.from_percent("110"),
    purchase_date=date(2025, 1, 15),
    maturity_date=date(2027, 1, 15),
)

result = project(inv, as_of=date(2026, 5, 6), assumed_cdi=Decimal("0.12"))

print(f"Today's value:    {result.current_value.to_display()}")
print(f"Gross at maturity: {result.gross_at_maturity.to_display()}")
print(f"IR tax:            {result.tax_amount.to_display()}")
print(f"Net at maturity:   {result.net_at_maturity.to_display()}")
```

To import an XP statement into the database (BTG and BB have analogous loaders; `load_statement` auto-detects the broker):

```python
from pathlib import Path
from justfixed.persistence.database import (
    Base, default_database_url, make_engine, make_session_factory,
)
from justfixed.importers.xp_loader import load_xp_statement

engine = make_engine(default_database_url())
Base.metadata.create_all(engine)  # First-time setup; alembic upgrade head also works
factory = make_session_factory(engine)

result = load_xp_statement(Path("PosicaoDetalhada.xlsx"), factory)
print(f"Inserted: {result.inserted}, skipped: {result.skipped}")
print(f"Issuers created: {result.issuers_created}, reused: {result.issuers_reused}")
```

Re-running the same file is safe: investments matching the natural key `(issuer, product, principal, purchase_date, maturity_date)` are skipped, not duplicated.

To export upcoming maturities as a calendar file:

```python
from datetime import date
from decimal import Decimal
from pathlib import Path
from justfixed.exports.calendar import export_maturity_calendar

# investments: list of Investment objects, e.g. from InvestmentRepository.all()
ics_bytes = export_maturity_calendar(
    investments,
    as_of=date.today(),
    assumed_cdi=Decimal("0.12"),  # your assumed CDI for the year
)
Path("vencimentos.ics").write_bytes(ics_bytes)
# Drag vencimentos.ics into Google Calendar, Apple Calendar, Outlook, etc.
```

Each event shows the post-IR net amount — what your bank account will actually
receive, not a pre-tax gross.

**Limitation:** re-importing an updated .ics file will refresh existing events but
will not remove events for investments you've since sold or deleted. Calendar apps
only update events present in the file; they don't delete events whose UIDs are
absent. Remove stale events manually if needed. A calendar subscription URL that
your app can poll automatically is out of scope for v1.

## Project structure

```
src/justfixed/
  domain/         # Money, Rate, Issuer, Investment — pure value/entity types
  persistence/    # SQLAlchemy models, migrations, repositories
  engine/         # Calendar, accrual, tax, cash flows, projection, FGC analysis
  importers/      # XP / BTG / BB statement parsers + DB loaders
  exports/        # iCalendar (.ics) export
tests/            # 1406 tests; mirrors src/ structure
alembic/          # Database migrations
docs/             # ARCHITECTURE.md and other design notes
```

## Contributing

Read [`ARCHITECTURE.md`](ARCHITECTURE.md) first. Key conventions:

- All money is `Decimal`, never `float`
- All rates are typed (one of four `Rate` subclasses)
- Domain types validate their invariants in `__post_init__` — corrupt data fails to load
- Tests are the spec; if behavior changes, the test changes first
- Every commit is one focused change with passing tests

## License

To be determined.
