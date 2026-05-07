# JustFixed

A desktop portfolio tracker for Brazilian fixed-income investments (CDB, LCI, LCA, LCD, LC, Tesouro Direto). Offline-first, Windows-targeted, single-user.

**Status:** in development. Engine and persistence layers complete; importer 2/3 done; UI not started. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for what's built and what isn't.

## What it does

Given a portfolio of Brazilian fixed-income positions, JustFixed answers:

- *What is each position worth today?* (252-business-day accrual from purchase date)
- *What will it pay at maturity, gross and net of IR tax?*
- *When are the next coupon payments?* (for juros mensais / juros semestrais bonds)
- *How exposed are you to a single FGC conglomerate?* (planned, not built)

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

You should see ~395 tests passing in under 3 seconds. If anything fails, the architecture doc covers common environment issues.

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

To import an XP statement (parsing layers only — DB persistence not yet built):

```python
from pathlib import Path
from justfixed.importers.xp import read_renda_fixa_rows
from justfixed.importers.xp_mapper import parse_row

rows = read_renda_fixa_rows(Path("PosicaoDetalhada.xlsx"))
for r in rows:
    parsed = parse_row(r)
    print(f"{parsed.product.value:15} {parsed.issuer_name:30} {parsed.principal}")
```

## Project structure

```
src/justfixed/
  domain/         # Money, Rate, Issuer, Investment — pure value/entity types
  persistence/    # SQLAlchemy models, migrations, repositories
  engine/         # Calendar, accrual, tax, cash flows, projection
  importers/      # XP statement parser
tests/            # 395 tests; mirrors src/ structure
alembic/          # Database migrations
docs/             # ARCHITECTURE.md and other design notes
```

## Contributing

Read [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) first. Key conventions:

- All money is `Decimal`, never `float`
- All rates are typed (one of four `Rate` subclasses)
- Domain types validate their invariants in `__post_init__` — corrupt data fails to load
- Tests are the spec; if behavior changes, the test changes first
- Every commit is one focused change with passing tests

## License

To be determined.
