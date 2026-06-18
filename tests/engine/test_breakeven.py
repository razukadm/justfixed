"""Tests for engine/breakeven.py — breakeven inflation curve derivation.

Written TDD-first: tests exist before the module. All tests fail with
ImportError until engine/breakeven.py is implemented.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from justfixed.engine.breakeven import breakeven_inflation_curve
from justfixed.engine.curve import Curve, CurveVertex


_ANCHOR = date(2026, 5, 15)
_ANCHOR_OTHER = date(2026, 5, 16)


def _v(bd: int, rate: str) -> CurveVertex:
    return CurveVertex(business_days=bd, rate=Decimal(rate))


def _curve(*vertices: CurveVertex) -> Curve:
    return Curve(anchor=_ANCHOR, vertices=vertices)


# ── Basic Fisher calculation ──────────────────────────────────────────────────

class TestBasicFisher:
    def test_exact_fisher_value(self) -> None:
        # nominal=0.14, real=0.075
        # (1.14 / 1.075) - 1 = 0.060465116279069767441860465
        pre = _curve(_v(252, "0.14"))
        ipca = _curve(_v(252, "0.075"))
        result = breakeven_inflation_curve(pre, ipca)
        assert result is not None
        assert len(result.vertices) == 1
        assert result.vertices[0].rate == Decimal("0.060465116279069767441860465")

    def test_plausibility_band(self) -> None:
        # Realistic Brazil rates; a nominal/real swap would give < 0 or > 0.14
        pre = _curve(_v(252, "0.14"))
        ipca = _curve(_v(252, "0.075"))
        result = breakeven_inflation_curve(pre, ipca)
        assert result is not None
        rate = result.vertices[0].rate
        assert Decimal("0.03") <= rate <= Decimal("0.08")


# ── Union grid ────────────────────────────────────────────────────────────────

class TestUnionGrid:
    def test_sorted_dedup_union(self) -> None:
        # pre: {63, 252, 756}, ipca: {126, 252} → sorted dedup union {63, 126, 252, 756}
        pre = Curve(anchor=_ANCHOR, vertices=(
            _v(63, "0.12"), _v(252, "0.13"), _v(756, "0.14"),
        ))
        ipca = Curve(anchor=_ANCHOR, vertices=(
            _v(126, "0.05"), _v(252, "0.06"),
        ))
        result = breakeven_inflation_curve(pre, ipca)
        assert result is not None
        assert [v.business_days for v in result.vertices] == [63, 126, 252, 756]

    def test_shared_bd_appears_once(self) -> None:
        # bd=252 is present in both inputs → exactly one vertex at 252 in result
        pre = _curve(_v(252, "0.14"))
        ipca = _curve(_v(252, "0.075"))
        result = breakeven_inflation_curve(pre, ipca)
        assert result is not None
        bds = [v.business_days for v in result.vertices]
        assert bds.count(252) == 1


# ── Flat extension ────────────────────────────────────────────────────────────

class TestFlatExtension:
    def test_beyond_last_vertex_uses_flat_extension(self) -> None:
        # pre: {63→0.12, 252→0.14}, ipca: {63→0.06} only
        # At union bd=252, ipca flat-extends at its last vertex (0.06)
        pre = Curve(anchor=_ANCHOR, vertices=(_v(63, "0.12"), _v(252, "0.14")))
        ipca = _curve(_v(63, "0.06"))
        result = breakeven_inflation_curve(pre, ipca)
        assert result is not None
        bds = [v.business_days for v in result.vertices]
        assert 252 in bds
        v252 = next(v for v in result.vertices if v.business_days == 252)
        # pre=0.14 (exact vertex); ipca flat-extends at 0.06
        expected = (Decimal("1") + Decimal("0.14")) / (Decimal("1") + Decimal("0.06")) - Decimal("1")
        assert v252.rate == expected


# ── None and empty-vertices guards ────────────────────────────────────────────

class TestNoneAndEmpty:
    def test_pre_none_returns_none(self) -> None:
        ipca = _curve(_v(252, "0.075"))
        assert breakeven_inflation_curve(None, ipca) is None

    def test_ipca_real_none_returns_none(self) -> None:
        pre = _curve(_v(252, "0.14"))
        assert breakeven_inflation_curve(pre, None) is None

    def test_both_none_returns_none(self) -> None:
        assert breakeven_inflation_curve(None, None) is None

    def test_pre_empty_vertices_returns_none(self) -> None:
        pre = Curve(anchor=_ANCHOR, vertices=())
        ipca = _curve(_v(252, "0.075"))
        assert breakeven_inflation_curve(pre, ipca) is None

    def test_ipca_real_empty_vertices_returns_none(self) -> None:
        pre = _curve(_v(252, "0.14"))
        ipca = Curve(anchor=_ANCHOR, vertices=())
        assert breakeven_inflation_curve(pre, ipca) is None


# ── Anchor mismatch guard ─────────────────────────────────────────────────────

class TestAnchorMismatch:
    def test_different_anchors_returns_none(self) -> None:
        pre = _curve(_v(252, "0.14"))
        ipca = Curve(anchor=_ANCHOR_OTHER, vertices=(_v(252, "0.075"),))
        assert breakeven_inflation_curve(pre, ipca) is None

    def test_matching_anchors_does_not_return_none(self) -> None:
        pre = _curve(_v(252, "0.14"))
        ipca = _curve(_v(252, "0.075"))
        assert breakeven_inflation_curve(pre, ipca) is not None


# ── Result validity ───────────────────────────────────────────────────────────

class TestResultValidity:
    def test_anchor_preserved(self) -> None:
        pre = _curve(_v(252, "0.14"))
        ipca = _curve(_v(252, "0.075"))
        result = breakeven_inflation_curve(pre, ipca)
        assert result is not None
        assert result.anchor == _ANCHOR

    def test_result_is_valid_curve(self) -> None:
        # Curve.__post_init__ enforces strictly ascending bds;
        # constructing without ValueError proves no duplicates.
        pre = Curve(anchor=_ANCHOR, vertices=(_v(63, "0.12"), _v(252, "0.14")))
        ipca = Curve(anchor=_ANCHOR, vertices=(_v(63, "0.06"), _v(252, "0.075")))
        result = breakeven_inflation_curve(pre, ipca)
        assert result is not None
        assert isinstance(result, Curve)
