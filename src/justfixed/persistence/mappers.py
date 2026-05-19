"""Mappers: pure functions converting between domain objects and ORM rows.

This module is the ONLY place that knows how to translate the rich
domain types (Investment, Issuer, Rate, Money) to and from the flat
row-shaped types in models.py.

Design rules:
- Mappers are pure functions: no side effects, no I/O, no globals.
- Domain types do not know about row types (one-way dependency).
- Loading a row reconstructs the domain object via its normal
  constructor, which means all domain invariants are re-checked.
  Corrupt rows fail to load with a clear ValueError.
"""

from __future__ import annotations

from decimal import Decimal

from justfixed.domain.investment import Investment, InvestmentSource
from justfixed.domain.issuer import Issuer, IssuerKind
from justfixed.domain.money import Money
from justfixed.domain.product import CouponFrequency, ProductType
from justfixed.domain.rates import (
    PostFixedCDI,
    PostFixedCDIPlusSpread,
    PostFixedIPCA,
    Prefixed,
    Rate,
)
from justfixed.persistence.models import InvestmentRow, IssuerRow


# ---------- Issuer ----------


def issuer_to_row(issuer: Issuer) -> IssuerRow:
    """Convert a domain Issuer to an ORM IssuerRow ready for insert/update."""
    return IssuerRow(
        id=issuer.id,
        name=issuer.name,
        normalized_name=Issuer.normalize_name(issuer.name),
        conglomerate=issuer.conglomerate,
        kind=issuer.kind.value,
        tax_id=issuer.tax_id,
    )


def issuer_from_row(row: IssuerRow) -> Issuer:
    """Reconstruct a domain Issuer from a loaded IssuerRow.

    All Issuer invariants are re-checked via __post_init__.
    Raises ValueError if the row is corrupt.
    """
    return Issuer(
        id=row.id,
        name=row.name,
        conglomerate=row.conglomerate,
        kind=IssuerKind(row.kind),
        tax_id=row.tax_id,
    )


# ---------- Rate (helper, used by Investment mappers) ----------


# Discriminator strings stored in InvestmentRow.rate_kind. Keeping them
# as constants here avoids typos creeping in across the two mapping
# directions.
_RATE_KIND_PREFIXED = "prefixed"
_RATE_KIND_POST_FIXED_CDI = "post_fixed_cdi"
_RATE_KIND_POST_FIXED_IPCA = "post_fixed_ipca"
_RATE_KIND_POST_FIXED_CDI_PLUS_SPREAD = "post_fixed_cdi_plus_spread"


def _rate_to_columns(rate: Rate) -> tuple[str, Decimal]:
    """Split a Rate into its (kind, value) columnar form for the database."""
    match rate:
        case Prefixed(annual_rate=v):
            return _RATE_KIND_PREFIXED, v
        case PostFixedCDI(cdi_percentage=v):
            return _RATE_KIND_POST_FIXED_CDI, v
        case PostFixedIPCA(spread=v):
            return _RATE_KIND_POST_FIXED_IPCA, v
        case PostFixedCDIPlusSpread(spread=v):
            return _RATE_KIND_POST_FIXED_CDI_PLUS_SPREAD, v
        case _:
            raise ValueError(f"Unknown Rate subclass: {type(rate).__name__}")


def _rate_from_columns(kind: str, value: Decimal) -> Rate:
    """Reconstruct a Rate subclass from its (kind, value) columnar form."""
    match kind:
        case "prefixed":
            return Prefixed(value)
        case "post_fixed_cdi":
            return PostFixedCDI(value)
        case "post_fixed_ipca":
            return PostFixedIPCA(value)
        case "post_fixed_cdi_plus_spread":
            return PostFixedCDIPlusSpread(value)
        case _:
            raise ValueError(f"Unknown rate_kind in row: {kind!r}")


# ---------- Investment ----------


def investment_to_row(inv: Investment) -> InvestmentRow:
    """Convert a domain Investment to an ORM InvestmentRow ready for insert/update.

    Note: issue_date is guaranteed non-None on a constructed Investment,
    because Investment.__post_init__ sets it from purchase_date if needed.
    """
    rate_kind, rate_value = _rate_to_columns(inv.rate)
    assert inv.issue_date is not None  # for type checkers
    return InvestmentRow(
        id=inv.id,
        product=inv.product.value,
        issuer_id=inv.issuer.id,
        principal_amount=inv.principal.amount,
        principal_currency=inv.principal.currency,
        rate_kind=rate_kind,
        rate_value=rate_value,
        purchase_date=inv.purchase_date,
        maturity_date=inv.maturity_date,
        issue_date=inv.issue_date,
        coupon_frequency=inv.coupon_frequency.value,
        description=inv.description,
        source=inv.source.value,
    )


def investment_from_row(row: InvestmentRow, issuer: Issuer) -> Investment:
    """Reconstruct a domain Investment from a loaded InvestmentRow.

    The issuer must be supplied by the caller (typically the repository
    fetches it via the row's relationship, then passes it here). This
    keeps the mapper a pure function — no database access from inside it.
    """
    if issuer.id != row.issuer_id:
        raise ValueError(
            f"Issuer mismatch: row references issuer {row.issuer_id}, "
            f"but caller passed issuer {issuer.id}."
        )
    return Investment(
        id=row.id,
        product=ProductType(row.product),
        issuer=issuer,
        principal=Money(row.principal_amount, row.principal_currency),
        rate=_rate_from_columns(row.rate_kind, row.rate_value),
        purchase_date=row.purchase_date,
        maturity_date=row.maturity_date,
        issue_date=row.issue_date,
        coupon_frequency=CouponFrequency(row.coupon_frequency),
        description=row.description,
        source=InvestmentSource(row.source),
    )