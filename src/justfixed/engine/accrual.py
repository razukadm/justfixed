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

from datetime import date
from decimal import Decimal

from justfixed.domain.money import Money
from justfixed.domain.rates import (
    PostFixedCDI,
    PostFixedCDIPlusSpread,
    PostFixedIPCA,
    Prefixed,
    Rate,
)
from justfixed.engine.calendar import BUSINESS_DAYS_PER_YEAR
from justfixed.engine.curve import Curve
from justfixed.engine.trace import AccrualStep, RateResolution


def _power(base: Decimal, exponent: Decimal) -> Decimal:
    """Decimal-safe exponentiation using ** operator.

    Decimal supports `**` directly. For non-integer exponents (which we
    always have via Du/252), this falls back to natural-log/exp under
    the hood, which is fine for our precision needs.
    """
    return base ** exponent


def _accrual_factor(effective_rate: Decimal, business_days: int) -> Decimal:
    """Raw compound-interest factor: (1 + r)^(Du/252), full precision, not quantized."""
    exponent = Decimal(business_days) / Decimal(BUSINESS_DAYS_PER_YEAR)
    return _power(Decimal("1") + effective_rate, exponent)


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

    factor = _accrual_factor(effective_annual_rate, business_days)
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
        
        case PostFixedCDIPlusSpread(spread=s):
            if assumed_cdi is None:
                raise ValueError(
                    "PostFixedCDIPlusSpread rate requires assumed_cdi parameter "
                    "(e.g. Decimal('0.12') for 12% annual CDI)."
                )
            # Fisher form: (1 + cdi)(1 + spread) - 1 = cdi + spread + cdi*spread
            return assumed_cdi + s + (assumed_cdi * s)

        case _:
            raise ValueError(f"Unknown Rate type: {type(rate).__name__}")


def _resolve_rate(
    rate: Rate,
    *,
    lookup_date: date,
    assumed_cdi: Decimal | None,
    assumed_ipca: Decimal | None,
    cdi_curve: Curve | None,
    ipca_curve: Curve | None,
) -> RateResolution:
    """Resolve a Rate to a RateResolution with full provenance.

    Mirrors the index-resolution logic in accrue()/projection.py but
    records where the index rate came from (curve vs assumed_fallback).
    lookup_date is used for curve lookups; ignored for Prefixed.
    """
    rate_kind = type(rate).__name__

    match rate:
        case Prefixed(annual_rate=r):
            return RateResolution(
                rate_kind=rate_kind,
                effective_annual_rate=r,
                source="fixed",
                resolved_index_rate=None,
                index_multiplier_or_spread=None,
                curve_anchor=None,
                curve_tenor_date=None,
            )

        case PostFixedCDI(cdi_percentage=p):
            if cdi_curve is not None and cdi_curve.vertices:
                resolved = cdi_curve.rate_at(lookup_date)
                source = "curve"
                anchor = cdi_curve.anchor
                tenor_date: date | None = lookup_date
            else:
                resolved = assumed_cdi
                source = "assumed_fallback"
                anchor = None
                tenor_date = None
            if resolved is None:
                raise ValueError(
                    "PostFixedCDI rate requires assumed_cdi parameter "
                    "(e.g. Decimal('0.12') for 12% annual CDI)."
                )
            return RateResolution(
                rate_kind=rate_kind,
                effective_annual_rate=_effective_annual_rate(
                    rate, assumed_cdi=resolved, assumed_ipca=None
                ),
                source=source,
                resolved_index_rate=resolved,
                index_multiplier_or_spread=p,
                curve_anchor=anchor,
                curve_tenor_date=tenor_date,
            )

        case PostFixedIPCA(spread=s):
            if ipca_curve is not None and ipca_curve.vertices:
                resolved = ipca_curve.rate_at(lookup_date)
                source = "curve"
                anchor = ipca_curve.anchor
                tenor_date = lookup_date
            else:
                resolved = assumed_ipca
                source = "assumed_fallback"
                anchor = None
                tenor_date = None
            if resolved is None:
                raise ValueError(
                    "PostFixedIPCA rate requires assumed_ipca parameter "
                    "(e.g. Decimal('0.045') for 4.5% annual IPCA)."
                )
            return RateResolution(
                rate_kind=rate_kind,
                effective_annual_rate=_effective_annual_rate(
                    rate, assumed_cdi=None, assumed_ipca=resolved
                ),
                source=source,
                resolved_index_rate=resolved,
                index_multiplier_or_spread=s,
                curve_anchor=anchor,
                curve_tenor_date=tenor_date,
            )

        case PostFixedCDIPlusSpread(spread=s):
            if cdi_curve is not None and cdi_curve.vertices:
                resolved = cdi_curve.rate_at(lookup_date)
                source = "curve"
                anchor = cdi_curve.anchor
                tenor_date = lookup_date
            else:
                resolved = assumed_cdi
                source = "assumed_fallback"
                anchor = None
                tenor_date = None
            if resolved is None:
                raise ValueError(
                    "PostFixedCDIPlusSpread rate requires assumed_cdi parameter "
                    "(e.g. Decimal('0.12') for 12% annual CDI)."
                )
            return RateResolution(
                rate_kind=rate_kind,
                effective_annual_rate=_effective_annual_rate(
                    rate, assumed_cdi=resolved, assumed_ipca=None
                ),
                source=source,
                resolved_index_rate=resolved,
                index_multiplier_or_spread=s,
                curve_anchor=anchor,
                curve_tenor_date=tenor_date,
            )

        case _:
            raise ValueError(f"Unknown Rate type: {type(rate).__name__}")


def _accrue_step(
    opening_balance: Money,
    rate_resolution: RateResolution,
    *,
    from_date: date,
    to_date: date,
    business_days: int,
) -> AccrualStep:
    """Build one AccrualStep from a resolved rate and a time period."""
    factor = _accrual_factor(rate_resolution.effective_annual_rate, business_days)
    closing_balance = opening_balance * factor
    return AccrualStep(
        from_date=from_date,
        to_date=to_date,
        business_days=business_days,
        rate=rate_resolution,
        factor=factor,
        opening_balance=opening_balance,
        closing_balance=closing_balance,
    )