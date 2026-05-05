"""Accrual engine: rate × time → final amount.

The 252-business-day basis is universal in Brazilian fixed income:

    Final = Principal × (1 + i)^(Du / 252)

This module implements that formula for each Rate subclass:
- Prefixed: i = annual_rate (known up front)
- PostFixedCDI: i = cdi_percentage × assumed_cdi (CDI is post-fixed)
- PostFixedIPCA: i ≈ assumed_ipca + spread + cross-term (Fisher form)

For post-fixed kinds, the engine accepts an assumed annualized rate as
input. Phase 2 will replace assumptions with real index history; the
formula stays identical.

Design notes:
- All Decimal math; no floats anywhere.
- accrue() dispatches on Rate type via match. Adding a fourth Rate kind
  requires updating this match statement (the type checker will flag
  the missing branch).
- Returns Money, preserving currency from the input.
"""

from __future__ import annotations

from decimal import Decimal

from justfixed.domain.money import Money
from justfixed.domain.rates import (
    PostFixedCDI,
    PostFixedIPCA,
    Prefixed,
    Rate,
)
from justfixed.engine.calendar import BUSINESS_DAYS_PER_YEAR


def _power(base: Decimal, exponent: Decimal) -> Decimal:
    """Decimal-safe exponentiation using ** operator.

    Decimal supports `**` directly. For non-integer exponents (which we
    always have via Du/252), this falls back to natural-log/exp under
    the hood, which is fine for our precision needs.
    """
    return base ** exponent


def accrue(
    principal: Money,
    rate: Rate,
    business_days: int,
    *,
    assumed_cdi: Decimal | None = None,
    assumed_ipca: Decimal | None = None,
) -> Money:
    """Apply `rate` to `principal` over `business_days` business days.

    Args:
        principal: Starting amount (Money).
        rate: One of Prefixed | PostFixedCDI | PostFixedIPCA.
        business_days: Du, count of business days in the period.
        assumed_cdi: Annual CDI rate as a decimal fraction (e.g.
            Decimal("0.12") for 12%). Required for PostFixedCDI rates,
            ignored otherwise.
        assumed_ipca: Annual IPCA rate as a decimal fraction. Required
            for PostFixedIPCA rates, ignored otherwise.

    Returns:
        The accrued amount as Money in the same currency as principal.

    Raises:
        ValueError: If business_days is negative, or a required assumed
            rate is missing for a post-fixed rate.
    """
    if business_days < 0:
        raise ValueError(f"business_days must be non-negative; got {business_days}")
    if business_days == 0:
        return principal

    effective_annual_rate = _effective_annual_rate(
        rate, assumed_cdi=assumed_cdi, assumed_ipca=assumed_ipca
    )

    exponent = Decimal(business_days) / Decimal(BUSINESS_DAYS_PER_YEAR)
    factor = _power(Decimal("1") + effective_annual_rate, exponent)
    return principal * factor


def _effective_annual_rate(
    rate: Rate,
    *,
    assumed_cdi: Decimal | None,
    assumed_ipca: Decimal | None,
) -> Decimal:
    """Compute the effective annual rate (decimal fraction) for any Rate.

    This collapses the differences between rate kinds: after this, all
    accrual is just `(1 + r)^(Du/252)` regardless of the original kind.
    """
    match rate:
        case Prefixed(annual_rate=r):
            return r

        case PostFixedCDI(cdi_percentage=p):
            if assumed_cdi is None:
                raise ValueError(
                    "PostFixedCDI rate requires assumed_cdi parameter "
                    "(e.g. Decimal('0.12') for 12% annual CDI)."
                )
            return p * assumed_cdi

        case PostFixedIPCA(spread=s):
            if assumed_ipca is None:
                raise ValueError(
                    "PostFixedIPCA rate requires assumed_ipca parameter "
                    "(e.g. Decimal('0.045') for 4.5% annual IPCA)."
                )
            # Fisher form: (1 + ipca)(1 + spread) - 1 = ipca + spread + ipca*spread
            return assumed_ipca + s + (assumed_ipca * s)

        case _:
            raise ValueError(f"Unknown Rate type: {type(rate).__name__}")