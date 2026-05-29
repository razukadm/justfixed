"""FGC back-solve engine.

Computes the maximum principal for a new investment with a given issuer
that keeps FGC exposure at or below the cap at every sample date in the
holding window.

Supported rate types: Prefixed, PostFixedCDI, PostFixedCDIPlusSpread,
PostFixedIPCA.  Growth for the mock investment is computed via the
projection engine so the back-solve uses the same rate math as the rest
of the codebase.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_DOWN
from typing import Sequence

from justfixed.domain.investment import Investment
from justfixed.domain.issuer import Issuer, IssuerKind
from justfixed.domain.money import Money
from justfixed.domain.product import ProductType
from justfixed.domain.rates import (
    PostFixedCDI,
    PostFixedCDIPlusSpread,
    PostFixedIPCA,
    Prefixed,
    Rate,
)
from justfixed.engine.projection import project

FGC_CAP: Decimal = Decimal("250000.00")

_CENT = Decimal("0.01")


@dataclass(frozen=True)
class BackSolveResult:
    """Result of an FGC back-solve computation."""

    max_principal: Decimal          # Maximum safe principal, rounded DOWN to nearest cent
    projected_at_maturity: Decimal  # Mock's gross value at maturity using max_principal
    peak_utilization: Decimal       # Fraction of cap consumed at the binding sample date
    peak_date: date                  # Sample date that produced the tightest P bound
    effective_rate_aa: Decimal      # Rate's primary parameter (annual_rate, cdi_percentage,
                                    # or spread, depending on Rate type)


def _mock_growth_factor(
    rate: Rate,
    product: ProductType,
    issuer_name: str,
    purchase_date: date,
    as_of: date,
    maturity_date: date,
    assumed_cdi: Decimal,
    assumed_ipca: Decimal,
) -> Decimal:
    """Growth factor for a mock investment between purchase_date and as_of.

    Constructs a unit-principal synthetic Investment with the given
    rate / product / dates, projects it at as_of using the assumed-rate
    constants, and returns the resulting current_value as a Decimal.
    This reuses engine.projection.project() so the back-solve's mock
    growth uses the same rate math as the rest of the codebase.

    At as_of == purchase_date, project() returns the principal unchanged,
    so the return value is exactly Decimal("1.00000000") — a growth of 1.

    The synthetic Issuer is COMMERCIAL_BANK; the kind is irrelevant to
    project()'s rate math.
    """
    synth_issuer = Issuer.create(issuer_name, issuer_name, IssuerKind.COMMERCIAL_BANK)
    synth_inv = Investment.create(
        product=product,
        issuer=synth_issuer,
        principal=Money.from_reais("1"),
        rate=rate,
        purchase_date=purchase_date,
        maturity_date=maturity_date,
    )
    return project(
        synth_inv, as_of=as_of,
        assumed_cdi=assumed_cdi,
        assumed_ipca=assumed_ipca,
    ).current_value.amount


def _effective_rate(rate: Rate) -> Decimal:
    """Primary rate parameter for BackSolveResult.effective_rate_aa."""
    if isinstance(rate, Prefixed):
        return rate.annual_rate
    if isinstance(rate, PostFixedCDI):
        return rate.cdi_percentage
    if isinstance(rate, (PostFixedIPCA, PostFixedCDIPlusSpread)):
        return rate.spread
    raise TypeError(f"Unsupported rate type: {type(rate).__name__}")


def max_principal_under_fgc(
    issuer: Issuer,
    product: ProductType,
    rate: Rate,
    purchase_date: date,
    maturity_date: date,
    existing_holdings: Sequence[Investment],
    assumed_cdi: Decimal,
    assumed_ipca: Decimal,
    cap: Decimal = FGC_CAP,
) -> BackSolveResult:
    """Compute the maximum principal that keeps conglomerate FGC exposure <= cap.

    At each sample date d in [purchase_date, maturity_date], the constraint is:
        existing_total(d) + P * growth(d) <= cap
    where growth(d) is the current_value of a unit-principal synthetic
    investment with the given rate, projected at d via project().

    The binding sample date is where (cap - existing_total(d)) / growth(d) is
    minimised. Between consecutive sample dates, existing_total is constant and
    growth is monotonically increasing, so the binding moment is always at one
    of the boundary endpoints — evaluating at sample dates is sufficient.

    Args:
        issuer: The proposed investment's Issuer (.name, .conglomerate, .kind
            are all read). existing_holdings are filtered by conglomerate so
            all same-conglomerate exposure counts toward the cap.
        product: Product type for the proposed investment.
        rate: Rate for the proposed investment. Any of the four supported types.
        purchase_date: Start date of the proposed investment.
        maturity_date: End date of the proposed investment.
        existing_holdings: All portfolio holdings. Non-overlapping, non-matching
            conglomerate, and Treasury holdings are filtered out internally.
        assumed_cdi: Annualized CDI fraction for projecting mock and post-fixed
            existing holdings.
        assumed_ipca: Annualized IPCA fraction for projecting mock and IPCA
            existing holdings.
        cap: FGC cap per conglomerate. Defaults to R$ 250,000.

    Returns:
        BackSolveResult with max_principal rounded DOWN to the nearest cent.
    """
    # Filter to same-conglomerate, non-Treasury, window-overlapping holdings.
    relevant = [
        inv for inv in existing_holdings
        if inv.issuer.conglomerate == issuer.conglomerate
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
        growth = _mock_growth_factor(
            rate, product, issuer.name, purchase_date, d, maturity_date,
            assumed_cdi, assumed_ipca,
        )

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
    growth_at_maturity = _mock_growth_factor(
        rate, product, issuer.name, purchase_date, maturity_date, maturity_date,
        assumed_cdi, assumed_ipca,
    )
    projected_at_maturity = (max_principal * growth_at_maturity).quantize(
        _CENT, rounding=ROUND_DOWN
    )

    # Peak utilization at the binding date.
    growth_at_peak = _mock_growth_factor(
        rate, product, issuer.name, purchase_date, min_bound_date, maturity_date,
        assumed_cdi, assumed_ipca,
    )
    peak_utilized = min_bound_existing + max_principal * growth_at_peak
    peak_utilization = (peak_utilized / cap).quantize(
        Decimal("0.0001"), rounding=ROUND_DOWN
    )

    return BackSolveResult(
        max_principal=max_principal,
        projected_at_maturity=projected_at_maturity,
        peak_utilization=peak_utilization,
        peak_date=min_bound_date,
        effective_rate_aa=_effective_rate(rate),
    )
