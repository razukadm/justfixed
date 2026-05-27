"""FGC back-solve engine.

Computes the maximum principal for a new Prefixed investment with a given
issuer that keeps FGC exposure at or below the cap at every sample date in
the holding window.

Phase 1 limitation: only Prefixed rates are supported. Post-fixed rate
types raise NotImplementedError (Phase 1.5 extension).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_DOWN
from typing import Sequence

from justfixed.domain.investment import Investment
from justfixed.domain.issuer import IssuerKind
from justfixed.domain.product import ProductType
from justfixed.domain.rates import Prefixed, Rate
from justfixed.engine.calendar import business_days_between, BUSINESS_DAYS_PER_YEAR
from justfixed.engine.projection import project

FGC_CAP: Decimal = Decimal("250000.00")

_CENT = Decimal("0.01")
_ONE = Decimal("1")
_252 = Decimal(BUSINESS_DAYS_PER_YEAR)


@dataclass(frozen=True)
class BackSolveResult:
    """Result of an FGC back-solve computation."""

    max_principal: Decimal        # Maximum safe principal, rounded DOWN to nearest cent
    projected_at_maturity: Decimal  # Mock's gross value at maturity using max_principal
    peak_utilization: Decimal     # Fraction of cap consumed at the binding sample date
    peak_date: date               # Sample date that produced the tightest P bound
    effective_rate_aa: Decimal    # Annual rate fraction (= rate.annual_rate for Prefixed)


def max_principal_under_fgc(
    issuer_name: str,
    product: ProductType,
    rate: Rate,
    purchase_date: date,
    maturity_date: date,
    existing_holdings: Sequence[Investment],
    assumed_cdi: Decimal,
    assumed_ipca: Decimal,
    cap: Decimal = FGC_CAP,
) -> BackSolveResult:
    """Compute the maximum principal that keeps issuer FGC exposure <= cap.

    At each sample date d in [purchase_date, maturity_date], the constraint is:
        existing_total(d) + P * growth(d) <= cap
    where growth(d) = (1 + rate.annual_rate)^(bdays(purchase_date, d) / 252).

    The binding sample date is where (cap - existing_total(d)) / growth(d) is
    minimised. Between consecutive sample dates, existing_total is constant and
    growth is monotonically increasing, so the binding moment is always at one
    of the boundary endpoints — evaluating at sample dates is sufficient.

    Args:
        issuer_name: Name of the issuer for the proposed investment.
        product: Product type (passed for future use; unused in Phase 1 math).
        rate: Rate for the proposed investment. Must be Prefixed.
        purchase_date: Start date of the proposed investment.
        maturity_date: End date of the proposed investment.
        existing_holdings: All portfolio holdings. Non-overlapping, non-matching
            issuer, and Treasury holdings are filtered out internally.
        assumed_cdi: Annualized CDI fraction for projecting post-fixed holdings.
        assumed_ipca: Annualized IPCA fraction. Required even when no existing
            holdings use IPCA, for API consistency with fgc_concentration_report.
        cap: FGC cap per issuer. Defaults to R$ 250,000.

    Returns:
        BackSolveResult with max_principal rounded DOWN to the nearest cent.

    Raises:
        NotImplementedError: If rate is not Prefixed.
    """
    if not isinstance(rate, Prefixed):
        raise NotImplementedError(
            f"Back-solve is only implemented for Prefixed rates; got {type(rate).__name__}"
        )

    r = rate.annual_rate

    # Filter to same-issuer, non-Treasury, window-overlapping holdings.
    relevant = [
        inv for inv in existing_holdings
        if inv.issuer.name == issuer_name
        and inv.issuer.kind != IssuerKind.TREASURY
        and inv.purchase_date < maturity_date
        and inv.maturity_date > purchase_date
    ]

    # Sample dates: sorted union of all boundary dates in [purchase_date, maturity_date].
    boundary_dates: set[date] = {purchase_date, maturity_date}
    for inv in relevant:
        if purchase_date <= inv.purchase_date <= maturity_date:
            boundary_dates.add(inv.purchase_date)
        if purchase_date <= inv.maturity_date <= maturity_date:
            boundary_dates.add(inv.maturity_date)
    sample_dates = sorted(boundary_dates)

    # Evaluate P <= (cap - existing_total(d)) / growth(d) at each sample date.
    min_bound: Decimal | None = None
    min_bound_date: date = purchase_date
    min_bound_existing: Decimal = Decimal("0")

    for d in sample_dates:
        bdays = business_days_between(purchase_date, d)
        growth = (_ONE + r) ** (Decimal(bdays) / _252)

        existing_total = Decimal("0")
        for inv in relevant:
            if inv.purchase_date <= d <= inv.maturity_date:
                val = project(
                    inv, as_of=d,
                    assumed_cdi=assumed_cdi,
                    assumed_ipca=assumed_ipca,
                ).current_value.amount
                existing_total += val

        bound = (cap - existing_total) / growth
        if min_bound is None or bound < min_bound:
            min_bound = bound
            min_bound_date = d
            min_bound_existing = existing_total

    assert min_bound is not None  # sample_dates always has >= 2 entries

    max_principal = max(Decimal("0"), min_bound).quantize(_CENT, rounding=ROUND_DOWN)

    # Projected gross value of mock at its maturity.
    total_bdays = business_days_between(purchase_date, maturity_date)
    growth_at_maturity = (_ONE + r) ** (Decimal(total_bdays) / _252)
    projected_at_maturity = (max_principal * growth_at_maturity).quantize(
        _CENT, rounding=ROUND_DOWN
    )

    # Peak utilization at the binding date.
    peak_bdays = business_days_between(purchase_date, min_bound_date)
    growth_at_peak = (_ONE + r) ** (Decimal(peak_bdays) / _252)
    peak_utilized = min_bound_existing + max_principal * growth_at_peak
    peak_utilization = (peak_utilized / cap).quantize(
        Decimal("0.0001"), rounding=ROUND_DOWN
    )

    return BackSolveResult(
        max_principal=max_principal,
        projected_at_maturity=projected_at_maturity,
        peak_utilization=peak_utilization,
        peak_date=min_bound_date,
        effective_rate_aa=r,
    )
