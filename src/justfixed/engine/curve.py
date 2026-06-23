"""Yield curve data structure for CDI-based accrual projection.

A Curve is a dated snapshot of implied annualized rates at discrete
business-day vertices. The engine uses it to look up the expected CDI
rate at any future date via linear interpolation.

Design notes:
- Vertices are business-day-from-anchor counts, matching the engine's
  252-business-day convention and ANBIMA's ETTJ vertex format.
- Interpolation is linear between vertices; flat extension beyond both ends.
- Pre-anchor and at-anchor target dates return the first vertex's rate
  by design — the curve does not model historical rates.
- An empty Curve (no vertices) raises ValueError on rate_at(); callers
  are responsible for checking curve.vertices before calling.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from justfixed.engine.calendar import business_days_between


@dataclass(frozen=True, slots=True)
class CurveVertex:
    """One point on a yield curve.

    business_days: business days from the curve's anchor date.
    rate: annualized rate as a decimal fraction (e.g. Decimal("0.144") = 14.4%).
    """

    business_days: int
    rate: Decimal


@dataclass(frozen=True)
class Curve:
    """A yield curve snapshot: an anchor date plus discrete rate vertices.

    anchor: the "as of" date for this curve (when it was published / built).
    vertices: rate vertices sorted by business_days ascending. The constructor
        validates the sort order; callers must not rely on re-sorting.
    """

    anchor: date
    vertices: tuple[CurveVertex, ...]

    def __post_init__(self) -> None:
        for i in range(len(self.vertices) - 1):
            if self.vertices[i].business_days >= self.vertices[i + 1].business_days:
                raise ValueError(
                    "Curve vertices must be sorted by business_days ascending; "
                    f"vertex {i} ({self.vertices[i].business_days}bd) >= "
                    f"vertex {i + 1} ({self.vertices[i + 1].business_days}bd)."
                )

    def rate_at(self, target_date: date) -> Decimal:
        """Return the interpolated annualized rate for target_date.

        Flat extension: dates at or before the first vertex return the first
        vertex's rate. Dates at or beyond the last vertex return the last
        vertex's rate. Linear interpolation between vertices otherwise.

        Pre-anchor and at-anchor target dates also return the first vertex's
        rate by design: business_days_between clamps to 0 when end <= start,
        so they fall into the flat-extension branch. The curve does not model
        historical rates; pre-anchor lookups get the earliest known vertex.

        Raises:
            ValueError: if the curve has no vertices.
        """
        if not self.vertices:
            raise ValueError("Curve has no vertices; use assumed_cdi fallback instead.")

        days = business_days_between(self.anchor, target_date)

        if days <= self.vertices[0].business_days:
            return self.vertices[0].rate

        if days >= self.vertices[-1].business_days:
            return self.vertices[-1].rate

        for lo, hi in zip(self.vertices, self.vertices[1:]):
            if lo.business_days <= days <= hi.business_days:
                t = Decimal(days - lo.business_days) / Decimal(hi.business_days - lo.business_days)
                return lo.rate + t * (hi.rate - lo.rate)

        # Unreachable: flat-extension guards ensure days is strictly inside
        # [first.business_days, last.business_days] at this point.
        raise AssertionError("rate_at: no bracketing vertices found (should be unreachable).")


def curve_content_hash(curve: Curve) -> str:
    """Return a deterministic SHA-256 hex digest identifying this curve's content.

    Canonical form: anchor ISO date, then each vertex as "bd:rate", joined with "|".
    The rate is rendered via str(Decimal) — exact, no float conversion.
    """
    parts = [curve.anchor.isoformat()]
    for v in curve.vertices:
        parts.append(f"{v.business_days}:{str(v.rate)}")
    canonical = "|".join(parts)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
