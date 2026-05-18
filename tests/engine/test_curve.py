"""Tests for engine/curve.py — Curve data structure and CDI accrual integration."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from justfixed.domain.investment import Investment
from justfixed.domain.issuer import Issuer, IssuerKind
from justfixed.domain.money import Money
from justfixed.domain.product import CouponFrequency, ProductType
from justfixed.domain.rates import PostFixedCDI
from justfixed.engine.calendar import add_business_days
from justfixed.engine.curve import Curve, CurveVertex
from justfixed.engine.projection import project


ANCHOR = date(2026, 5, 15)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _bank() -> Issuer:
    return Issuer.create("Banco Test", "Banco Test S.A.", IssuerKind.COMMERCIAL_BANK)


def _cdi_bullet(
    principal: str = "10000",
    cdi_pct: str = "100",
    purchase: date = ANCHOR,
    maturity: date = date(2027, 5, 15),
) -> Investment:
    return Investment.create(
        product=ProductType.CDB,
        issuer=_bank(),
        principal=Money.from_reais(principal),
        rate=PostFixedCDI.from_percent(cdi_pct),
        purchase_date=purchase,
        maturity_date=maturity,
    )


def _cdi_monthly(
    principal: str = "10000",
    cdi_pct: str = "100",
    purchase: date = ANCHOR,
    maturity: date = date(2027, 5, 15),
) -> Investment:
    return Investment.create(
        product=ProductType.CDB,
        issuer=_bank(),
        principal=Money.from_reais(principal),
        rate=PostFixedCDI.from_percent(cdi_pct),
        purchase_date=purchase,
        maturity_date=maturity,
        coupon_frequency=CouponFrequency.MONTHLY,
    )


def _flat_curve(rate_str: str = "0.144") -> Curve:
    r = Decimal(rate_str)
    return Curve(
        anchor=ANCHOR,
        vertices=(
            CurveVertex(business_days=30,  rate=r),
            CurveVertex(business_days=126, rate=r),
            CurveVertex(business_days=252, rate=r),
            CurveVertex(business_days=504, rate=r),
        ),
    )


def _two_vertex_curve() -> Curve:
    return Curve(
        anchor=ANCHOR,
        vertices=(
            CurveVertex(business_days=100, rate=Decimal("0.12")),
            CurveVertex(business_days=200, rate=Decimal("0.16")),
        ),
    )


# ── Construction ──────────────────────────────────────────────────────────────

class TestCurveConstruction:
    def test_single_vertex(self) -> None:
        c = Curve(
            anchor=ANCHOR,
            vertices=(CurveVertex(business_days=252, rate=Decimal("0.144")),),
        )
        assert len(c.vertices) == 1
        assert c.vertices[0].business_days == 252

    def test_multiple_vertices_sorted(self) -> None:
        c = Curve(
            anchor=ANCHOR,
            vertices=(
                CurveVertex(business_days=126, rate=Decimal("0.12")),
                CurveVertex(business_days=252, rate=Decimal("0.14")),
                CurveVertex(business_days=504, rate=Decimal("0.16")),
            ),
        )
        assert len(c.vertices) == 3

    def test_empty_vertices_valid_to_construct(self) -> None:
        c = Curve(anchor=ANCHOR, vertices=())
        assert c.vertices == ()

    def test_unsorted_vertices_raises(self) -> None:
        with pytest.raises(ValueError, match="sorted"):
            Curve(
                anchor=ANCHOR,
                vertices=(
                    CurveVertex(business_days=252, rate=Decimal("0.14")),
                    CurveVertex(business_days=126, rate=Decimal("0.12")),
                ),
            )

    def test_duplicate_business_days_raises(self) -> None:
        with pytest.raises(ValueError, match="sorted"):
            Curve(
                anchor=ANCHOR,
                vertices=(
                    CurveVertex(business_days=126, rate=Decimal("0.12")),
                    CurveVertex(business_days=126, rate=Decimal("0.14")),
                ),
            )


# ── rate_at ───────────────────────────────────────────────────────────────────

class TestCurveRateAt:
    def test_exact_first_vertex(self) -> None:
        curve = _two_vertex_curve()
        target = add_business_days(ANCHOR, 100)
        assert curve.rate_at(target) == Decimal("0.12")

    def test_exact_last_vertex(self) -> None:
        curve = _two_vertex_curve()
        target = add_business_days(ANCHOR, 200)
        assert curve.rate_at(target) == Decimal("0.16")

    def test_interpolation_at_midpoint(self) -> None:
        curve = _two_vertex_curve()
        # 150bd is the midpoint of [100, 200].
        # t = (150-100)/(200-100) = 0.5 exactly.
        # rate = 0.12 + 0.5 * (0.16 - 0.12) = 0.14 exactly.
        target = add_business_days(ANCHOR, 150)
        assert curve.rate_at(target) == Decimal("0.14")

    def test_before_first_vertex_holds_flat(self) -> None:
        curve = _two_vertex_curve()
        target = add_business_days(ANCHOR, 50)   # 50bd < first vertex at 100bd
        assert curve.rate_at(target) == Decimal("0.12")

    def test_after_last_vertex_holds_flat(self) -> None:
        curve = _two_vertex_curve()
        target = add_business_days(ANCHOR, 300)  # 300bd > last vertex at 200bd
        assert curve.rate_at(target) == Decimal("0.16")

    def test_rate_at_anchor(self) -> None:
        # anchor itself → 0 business days → before first vertex (100bd) → flat extension.
        curve = _two_vertex_curve()
        assert curve.rate_at(ANCHOR) == Decimal("0.12")

    def test_empty_curve_raises(self) -> None:
        curve = Curve(anchor=ANCHOR, vertices=())
        with pytest.raises(ValueError, match="no vertices"):
            curve.rate_at(ANCHOR)


# ── Flat-curve regression (architectural promise) ────────────────────────────

class TestFlatCurveEquivalentToSingleRate:
    """Flat curve must produce bit-identical results to the single-rate path.

    Any drift here means curve-mode and flat-mode are diverging silently.
    Assertions are exact (==), not assert_close — tolerance would mask the
    problem.
    """

    def test_flat_curve_bullet_cdi(self) -> None:
        rate = Decimal("0.144")
        flat_curve = _flat_curve("0.144")
        inv = _cdi_bullet()

        result_curve = project(inv, as_of=ANCHOR, cdi_curve=flat_curve)
        result_flat  = project(inv, as_of=ANCHOR, assumed_cdi=rate)

        assert result_curve.gross_at_maturity == result_flat.gross_at_maturity
        assert result_curve.net_at_maturity   == result_flat.net_at_maturity
        assert result_curve.current_value     == result_flat.current_value

    def test_flat_curve_monthly_coupon_cdi(self) -> None:
        rate = Decimal("0.144")
        flat_curve = _flat_curve("0.144")
        inv = _cdi_monthly()

        result_curve = project(inv, as_of=ANCHOR, cdi_curve=flat_curve)
        result_flat  = project(inv, as_of=ANCHOR, assumed_cdi=rate)

        assert result_curve.gross_at_maturity == result_flat.gross_at_maturity
        assert result_curve.net_at_maturity   == result_flat.net_at_maturity
        assert result_curve.current_value     == result_flat.current_value


# ── Non-flat curve ────────────────────────────────────────────────────────────

class TestNonFlatCurve:
    def test_rising_curve_differs_from_midpoint_flat(self) -> None:
        # Rising curve: ~12% at 126bd, 16% at 252bd.
        rising = Curve(
            anchor=ANCHOR,
            vertices=(
                CurveVertex(business_days=126, rate=Decimal("0.12")),
                CurveVertex(business_days=252, rate=Decimal("0.16")),
            ),
        )
        # Maturity at exactly 252 business days → curve looks up the 252bd vertex → 16%.
        maturity = add_business_days(ANCHOR, 252)
        inv = _cdi_bullet(maturity=maturity)

        result_curve = project(inv, as_of=ANCHOR, cdi_curve=rising)
        # Flat at 14% (the midpoint) — curve result should differ.
        result_flat = project(inv, as_of=ANCHOR, assumed_cdi=Decimal("0.14"))

        assert result_curve.gross_at_maturity != result_flat.gross_at_maturity
