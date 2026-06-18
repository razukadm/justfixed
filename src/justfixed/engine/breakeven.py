"""Breakeven inflation curve derived from PRE and IPCA-real yield curves.

The market-implied breakeven inflation rate at each maturity is the Fisher
identity:
    breakeven = (1 + nominal) / (1 + real) - 1

where nominal is the PRE (prefixed/nominal) rate and real is the IPCA-real
rate at the same business-day count from the shared anchor date.
"""

from __future__ import annotations

from decimal import Decimal

from justfixed.engine.curve import Curve, CurveVertex


def _rate_at_bd(curve: Curve, days: int) -> Decimal:
    """Return the curve rate at an integer business-day offset.

    Mirrors Curve.rate_at exactly but operates on a raw bd count rather
    than a date, avoiding the date round-trip that Curve.rate_at requires.
    Flat extension at both ends; linear interpolation between vertices.
    Caller guarantees curve.vertices is non-empty.
    """
    vertices = curve.vertices

    if days <= vertices[0].business_days:
        return vertices[0].rate

    if days >= vertices[-1].business_days:
        return vertices[-1].rate

    for lo, hi in zip(vertices, vertices[1:]):
        if lo.business_days <= days <= hi.business_days:
            t = Decimal(days - lo.business_days) / Decimal(hi.business_days - lo.business_days)
            return lo.rate + t * (hi.rate - lo.rate)

    raise AssertionError("_rate_at_bd: no bracketing vertices found (should be unreachable).")


def breakeven_inflation_curve(
    pre: Curve | None,
    ipca_real: Curve | None,
) -> Curve | None:
    """Derive a breakeven inflation curve from PRE and IPCA-real curves.

    Returns None when either input curve is absent, either has no vertices,
    or the anchors do not match (mixing curves from different publish dates
    produces invalid breakeven rates). The caller falls back to a flat
    assumed-IPCA constant in the None case.
    """
    if pre is None or ipca_real is None:
        return None

    if not pre.vertices or not ipca_real.vertices:
        return None

    if pre.anchor != ipca_real.anchor:
        return None

    anchor = pre.anchor

    all_bds = sorted(
        {v.business_days for v in pre.vertices}
        | {v.business_days for v in ipca_real.vertices}
    )

    vertices = tuple(
        CurveVertex(
            business_days=bd,
            rate=(
                (Decimal(1) + _rate_at_bd(pre, bd))
                / (Decimal(1) + _rate_at_bd(ipca_real, bd))
                - Decimal(1)
            ),
        )
        for bd in all_bds
    )

    return Curve(anchor=anchor, vertices=vertices)
