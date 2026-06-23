"""Tests for trace-wiring slice: CurveProvenance.curve_ref / RateResolution.curve_ref.

Covers:
1. Hash determinism  — same curve input → same 64-char SHA-256 hex output
2. Hash sensitivity  — mutate one vertex rate → different hash
3. RateResolution.curve_ref (CDI)  — PostFixedCDI + cdi_curve → hash matches
4. CurveProvenance.curve_ref (CDI) — project_traced + cdi_curve → provenance.curve_ref matches
5. Pure fixed, no hash            — Prefixed → curve_ref is None everywhere
6. Source plumbing                — curve_source kwarg flows into provenance.source
7. IPCA parity                    — PostFixedIPCA + ipca_curve → hash matches
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from justfixed.domain.investment import Investment
from justfixed.domain.issuer import Issuer, IssuerKind
from justfixed.domain.money import Money
from justfixed.domain.product import ProductType
from justfixed.domain.rates import PostFixedCDI, PostFixedCDIPlusSpread, PostFixedIPCA, Prefixed
from justfixed.engine.accrual import _resolve_rate
from justfixed.engine.curve import Curve, CurveVertex, curve_content_hash
from justfixed.engine.projection import project_traced


# ── Shared fixtures ─────────────────────────────────────────────────────────────

ANCHOR = date(2024, 1, 15)
PURCHASE = date(2024, 1, 15)
MATURITY = date(2026, 1, 15)

CDI_CURVE = Curve(
    anchor=ANCHOR,
    vertices=(CurveVertex(business_days=252, rate=Decimal("0.14")),),
)
IPCA_CURVE = Curve(
    anchor=ANCHOR,
    vertices=(CurveVertex(business_days=756, rate=Decimal("0.05")),),
)


def _bank() -> Issuer:
    return Issuer.create("Banco Wire", "Banco Wire S.A.", IssuerKind.COMMERCIAL_BANK)


def _cdi_inv() -> Investment:
    return Investment.create(
        product=ProductType.CDB,
        issuer=_bank(),
        principal=Money.from_reais("10000"),
        rate=PostFixedCDI.from_percent("110"),
        purchase_date=PURCHASE,
        maturity_date=MATURITY,
    )


def _prefixed_inv() -> Investment:
    return Investment.create(
        product=ProductType.CDB,
        issuer=_bank(),
        principal=Money.from_reais("10000"),
        rate=Prefixed.from_percent("12"),
        purchase_date=PURCHASE,
        maturity_date=MATURITY,
    )


def _ipca_inv() -> Investment:
    return Investment.create(
        product=ProductType.CDB,
        issuer=_bank(),
        principal=Money.from_reais("10000"),
        rate=PostFixedIPCA.from_percent("5"),
        purchase_date=PURCHASE,
        maturity_date=MATURITY,
    )


def _cdi_plus_spread_inv() -> Investment:
    return Investment.create(
        product=ProductType.CDB,
        issuer=_bank(),
        principal=Money.from_reais("10000"),
        rate=PostFixedCDIPlusSpread.from_percent("2"),
        purchase_date=PURCHASE,
        maturity_date=MATURITY,
    )


# ── 1. Hash determinism ─────────────────────────────────────────────────────────

class TestHashDeterminism:
    def test_same_curve_same_hash(self) -> None:
        h1 = curve_content_hash(CDI_CURVE)
        h2 = curve_content_hash(CDI_CURVE)
        assert h1 == h2

    def test_hash_is_64_hex_chars(self) -> None:
        h = curve_content_hash(CDI_CURVE)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_equal_curves_equal_hash(self) -> None:
        curve_a = Curve(anchor=ANCHOR, vertices=(CurveVertex(252, Decimal("0.14")),))
        curve_b = Curve(anchor=ANCHOR, vertices=(CurveVertex(252, Decimal("0.14")),))
        assert curve_content_hash(curve_a) == curve_content_hash(curve_b)


# ── 2. Hash sensitivity ─────────────────────────────────────────────────────────

class TestHashSensitivity:
    def test_different_rate_different_hash(self) -> None:
        curve_a = Curve(anchor=ANCHOR, vertices=(CurveVertex(252, Decimal("0.14")),))
        curve_b = Curve(anchor=ANCHOR, vertices=(CurveVertex(252, Decimal("0.15")),))
        assert curve_content_hash(curve_a) != curve_content_hash(curve_b)

    def test_different_anchor_different_hash(self) -> None:
        curve_a = Curve(
            anchor=date(2024, 1, 15),
            vertices=(CurveVertex(252, Decimal("0.14")),),
        )
        curve_b = Curve(
            anchor=date(2024, 1, 16),
            vertices=(CurveVertex(252, Decimal("0.14")),),
        )
        assert curve_content_hash(curve_a) != curve_content_hash(curve_b)

    def test_different_business_days_different_hash(self) -> None:
        curve_a = Curve(anchor=ANCHOR, vertices=(CurveVertex(252, Decimal("0.14")),))
        curve_b = Curve(anchor=ANCHOR, vertices=(CurveVertex(504, Decimal("0.14")),))
        assert curve_content_hash(curve_a) != curve_content_hash(curve_b)

    def test_cdi_and_ipca_hashes_differ(self) -> None:
        assert curve_content_hash(CDI_CURVE) != curve_content_hash(IPCA_CURVE)


# ── 3. RateResolution.curve_ref (CDI) ───────────────────────────────────────────

class TestRateResolutionCurveRef:
    def test_cdi_curve_sets_curve_ref(self) -> None:
        resolution = _resolve_rate(
            PostFixedCDI.from_percent("110"),
            lookup_date=MATURITY,
            assumed_cdi=None,
            assumed_ipca=None,
            cdi_curve=CDI_CURVE,
            ipca_curve=None,
        )
        assert resolution.curve_ref == curve_content_hash(CDI_CURVE)

    def test_cdi_assumed_fallback_curve_ref_is_none(self) -> None:
        resolution = _resolve_rate(
            PostFixedCDI.from_percent("110"),
            lookup_date=MATURITY,
            assumed_cdi=Decimal("0.12"),
            assumed_ipca=None,
            cdi_curve=None,
            ipca_curve=None,
        )
        assert resolution.curve_ref is None

    def test_cdi_plus_spread_curve_ref(self) -> None:
        resolution = _resolve_rate(
            PostFixedCDIPlusSpread.from_percent("2"),
            lookup_date=MATURITY,
            assumed_cdi=None,
            assumed_ipca=None,
            cdi_curve=CDI_CURVE,
            ipca_curve=None,
        )
        assert resolution.curve_ref == curve_content_hash(CDI_CURVE)

    def test_ipca_curve_sets_curve_ref(self) -> None:
        resolution = _resolve_rate(
            PostFixedIPCA.from_percent("5"),
            lookup_date=MATURITY,
            assumed_cdi=None,
            assumed_ipca=None,
            cdi_curve=None,
            ipca_curve=IPCA_CURVE,
        )
        assert resolution.curve_ref == curve_content_hash(IPCA_CURVE)

    def test_prefixed_curve_ref_is_none(self) -> None:
        resolution = _resolve_rate(
            Prefixed.from_percent("12"),
            lookup_date=MATURITY,
            assumed_cdi=None,
            assumed_ipca=None,
            cdi_curve=CDI_CURVE,
            ipca_curve=None,
        )
        assert resolution.curve_ref is None


# ── 4. CurveProvenance.curve_ref (CDI via project_traced) ───────────────────────

class TestCurveProvenanceCurveRef:
    def test_cdi_curve_provenance_ref_matches_hash(self) -> None:
        trace = project_traced(
            _cdi_inv(),
            as_of=MATURITY,
            cdi_curve=CDI_CURVE,
        )
        assert trace.curve_provenance.curve_ref == curve_content_hash(CDI_CURVE)

    def test_no_curve_provenance_ref_is_none(self) -> None:
        trace = project_traced(
            _cdi_inv(),
            as_of=MATURITY,
            assumed_cdi=Decimal("0.12"),
        )
        assert trace.curve_provenance.curve_ref is None


# ── 5. Pure fixed — no hash ──────────────────────────────────────────────────────

class TestPureFixedNoHash:
    def test_prefixed_provenance_ref_is_none(self) -> None:
        trace = project_traced(
            _prefixed_inv(),
            as_of=MATURITY,
        )
        assert trace.curve_provenance.curve_ref is None

    def test_prefixed_provenance_anchor_is_none(self) -> None:
        trace = project_traced(
            _prefixed_inv(),
            as_of=MATURITY,
        )
        assert trace.curve_provenance.anchor is None


# ── 6. Source plumbing ──────────────────────────────────────────────────────────

class TestSourcePlumbing:
    def test_curve_source_flows_into_provenance(self) -> None:
        trace = project_traced(
            _cdi_inv(),
            as_of=MATURITY,
            cdi_curve=CDI_CURVE,
            curve_source="test-origin",
        )
        assert trace.curve_provenance.source == "test-origin"

    def test_curve_source_none_by_default(self) -> None:
        trace = project_traced(
            _cdi_inv(),
            as_of=MATURITY,
            cdi_curve=CDI_CURVE,
        )
        assert trace.curve_provenance.source is None


# ── 7. IPCA parity ──────────────────────────────────────────────────────────────

class TestIPCAParity:
    def test_ipca_curve_provenance_ref_matches_hash(self) -> None:
        trace = project_traced(
            _ipca_inv(),
            as_of=MATURITY,
            ipca_curve=IPCA_CURVE,
        )
        assert trace.curve_provenance.curve_ref == curve_content_hash(IPCA_CURVE)

    def test_ipca_provenance_ref_distinct_from_cdi_hash(self) -> None:
        trace = project_traced(
            _ipca_inv(),
            as_of=MATURITY,
            ipca_curve=IPCA_CURVE,
        )
        assert trace.curve_provenance.curve_ref != curve_content_hash(CDI_CURVE)
