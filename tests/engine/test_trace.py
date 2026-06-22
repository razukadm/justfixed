"""Tests for the audit calculation-trace data model (Audit-readiness Slice 1).

Nine test classes, one per audit category:
  1. TestDataclassImmutability
  2. TestRateResolutionPerKind
  3. TestResolveRateSource
  4. TestAccrualFactorAndStep
  5. TestProjectTracedVsProject
  6. TestCurrentValueAccrualFidelity
  7. TestFlowTraceFidelityPerKind
  8. TestTenorDivergence
  9. TestConventionAndProvenance

ZERO edits to any existing test module.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from justfixed.domain.investment import Investment
from justfixed.domain.issuer import Issuer, IssuerKind
from justfixed.domain.money import Money
from justfixed.domain.product import CouponFrequency, ProductType, TaxTreatment
from justfixed.domain.rates import (
    PostFixedCDI,
    PostFixedCDIPlusSpread,
    PostFixedIPCA,
    Prefixed,
)
from justfixed.engine.accrual import _accrue_step, _accrual_factor, _resolve_rate
from justfixed.engine.cashflow import CashFlowKind
from justfixed.engine.curve import Curve, CurveVertex
from justfixed.engine.projection import project, project_traced
from justfixed.engine.trace import (
    AccrualStep,
    Assumptions,
    CurveProvenance,
    FlowTrace,
    ProjectionTrace,
    RateResolution,
    TaxTrace,
)


# ---------- Module-level constants ----------

PURCHASE = date(2024, 1, 15)
MATURITY_1Y = date(2025, 1, 15)
MATURITY_2Y = date(2026, 1, 15)
MATURITY_3Y = date(2027, 1, 15)
MIDPOINT_1Y = date(2024, 7, 15)
MIDPOINT_2Y = date(2025, 1, 15)

CDI_ASSUMED = Decimal("0.12")
IPCA_ASSUMED = Decimal("0.04")

ANCHOR = date(2024, 1, 15)
CDI_CURVE = Curve(
    anchor=ANCHOR,
    vertices=(CurveVertex(business_days=252, rate=Decimal("0.14")),),
)
IPCA_CURVE = Curve(
    anchor=ANCHOR,
    vertices=(CurveVertex(business_days=756, rate=Decimal("0.05")),),
)


# ---------- Investment factories ----------


def _bank() -> Issuer:
    return Issuer.create("Banco Trace", "Banco Trace S.A.", IssuerKind.COMMERCIAL_BANK)


def _prefixed_bullet() -> Investment:
    return Investment.create(
        product=ProductType.CDB,
        issuer=_bank(),
        principal=Money.from_reais("10000"),
        rate=Prefixed.from_percent("12"),
        purchase_date=PURCHASE,
        maturity_date=MATURITY_2Y,
    )


def _cdi_bullet_assumed() -> Investment:
    return Investment.create(
        product=ProductType.CDB,
        issuer=_bank(),
        principal=Money.from_reais("10000"),
        rate=PostFixedCDI.from_percent("110"),
        purchase_date=PURCHASE,
        maturity_date=MATURITY_2Y,
    )


def _cdi_plus_spread_bullet() -> Investment:
    return Investment.create(
        product=ProductType.CDB,
        issuer=_bank(),
        principal=Money.from_reais("10000"),
        rate=PostFixedCDIPlusSpread.from_percent("2"),
        purchase_date=PURCHASE,
        maturity_date=MATURITY_2Y,
    )


def _ipca_bullet() -> Investment:
    return Investment.create(
        product=ProductType.CDB,
        issuer=_bank(),
        principal=Money.from_reais("10000"),
        rate=PostFixedIPCA.from_percent("5"),
        purchase_date=PURCHASE,
        maturity_date=MATURITY_3Y,
    )


def _lci_exempt() -> Investment:
    return Investment.create(
        product=ProductType.LCI,
        issuer=_bank(),
        principal=Money.from_reais("10000"),
        rate=PostFixedCDI.from_percent("90"),
        purchase_date=PURCHASE,
        maturity_date=MATURITY_1Y,
    )


def _prefixed_semi_annual() -> Investment:
    return Investment.create(
        product=ProductType.CDB,
        issuer=_bank(),
        principal=Money.from_reais("10000"),
        rate=Prefixed.from_percent("12"),
        purchase_date=PURCHASE,
        maturity_date=MATURITY_2Y,
        coupon_frequency=CouponFrequency.SEMI_ANNUAL,
    )


def _cdi_semi_annual_curve() -> Investment:
    return Investment.create(
        product=ProductType.CDB,
        issuer=_bank(),
        principal=Money.from_reais("10000"),
        rate=PostFixedCDI.from_percent("100"),
        purchase_date=PURCHASE,
        maturity_date=MATURITY_2Y,
        coupon_frequency=CouponFrequency.SEMI_ANNUAL,
    )


def _ipca_semi_annual_curve() -> Investment:
    return Investment.create(
        product=ProductType.CDB,
        issuer=_bank(),
        principal=Money.from_reais("10000"),
        rate=PostFixedIPCA.from_percent("5"),
        purchase_date=PURCHASE,
        maturity_date=MATURITY_2Y,
        coupon_frequency=CouponFrequency.SEMI_ANNUAL,
    )


# ---------- Minimal-construction helpers ----------


def _minimal_rate_resolution() -> RateResolution:
    return RateResolution(
        rate_kind="Prefixed",
        effective_annual_rate=Decimal("0.12"),
        source="fixed",
        resolved_index_rate=None,
        index_multiplier_or_spread=None,
        curve_anchor=None,
        curve_tenor_date=None,
    )


def _minimal_accrual_step() -> AccrualStep:
    rr = _minimal_rate_resolution()
    principal = Money.from_reais("10000")
    factor = (Decimal("1") + Decimal("0.12")) ** (Decimal(252) / Decimal(252))
    return AccrualStep(
        from_date=PURCHASE,
        to_date=MATURITY_1Y,
        business_days=252,
        rate=rr,
        factor=factor,
        opening_balance=principal,
        closing_balance=principal * factor,
    )


# ---------- Tests ----------


class TestDataclassImmutability:
    """All 7 trace dataclasses are frozen (slots=True, frozen=True)."""

    def test_rate_resolution_is_frozen(self) -> None:
        rr = _minimal_rate_resolution()
        with pytest.raises(AttributeError):
            rr.source = "mutated"  # type: ignore[misc]

    def test_accrual_step_is_frozen(self) -> None:
        step = _minimal_accrual_step()
        with pytest.raises(AttributeError):
            step.business_days = 999  # type: ignore[misc]

    def test_flow_trace_is_frozen(self) -> None:
        step = _minimal_accrual_step()
        coupon = Money.from_reais("600")
        ft = FlowTrace(
            pay_date=MATURITY_1Y,
            kind=CashFlowKind.COUPON,
            amount=coupon,
            interest_component=coupon,
            principal_component=Money.zero("BRL"),
            accrual=(step,),
        )
        with pytest.raises(AttributeError):
            ft.pay_date = date(2099, 1, 1)  # type: ignore[misc]

    def test_tax_trace_is_frozen(self) -> None:
        tt = TaxTrace(
            treatment=TaxTreatment.IR_REGRESSIVE,
            holding_calendar_days=365,
            bracket_rate=Decimal("0.175"),
            taxable_gain=Money.from_reais("1200"),
            tax_amount=Money.from_reais("210"),
            iof_modeled=False,
        )
        with pytest.raises(AttributeError):
            tt.bracket_rate = Decimal("0")  # type: ignore[misc]

    def test_assumptions_is_frozen(self) -> None:
        a = Assumptions(assumed_cdi=CDI_ASSUMED, assumed_ipca=None)
        with pytest.raises(AttributeError):
            a.assumed_cdi = Decimal("0")  # type: ignore[misc]

    def test_curve_provenance_is_frozen(self) -> None:
        cp = CurveProvenance(source=None, anchor=None)
        with pytest.raises(AttributeError):
            cp.source = "mutated"  # type: ignore[misc]

    def test_projection_trace_is_frozen(self) -> None:
        trace = project_traced(_prefixed_bullet(), as_of=MIDPOINT_2Y)
        with pytest.raises(AttributeError):
            trace.convention = "mutated"  # type: ignore[misc]


class TestRateResolutionPerKind:
    """_resolve_rate produces correct RateResolution fields for each Rate subclass."""

    def test_prefixed_source_and_fields(self) -> None:
        rr = _resolve_rate(
            Prefixed.from_percent("12"),
            lookup_date=MIDPOINT_2Y,
            assumed_cdi=None,
            assumed_ipca=None,
            cdi_curve=None,
            ipca_curve=None,
        )
        assert rr.rate_kind == "Prefixed"
        assert rr.effective_annual_rate == Decimal("0.12")
        assert rr.source == "fixed"
        assert rr.resolved_index_rate is None
        assert rr.index_multiplier_or_spread is None
        assert rr.curve_anchor is None
        assert rr.curve_tenor_date is None

    def test_prefixed_effective_rate_exact(self) -> None:
        rr = _resolve_rate(
            Prefixed.from_percent("7.5"),
            lookup_date=MIDPOINT_2Y,
            assumed_cdi=None,
            assumed_ipca=None,
            cdi_curve=None,
            ipca_curve=None,
        )
        assert rr.effective_annual_rate == Decimal("0.075")

    def test_cdi_assumed_fallback_effective_rate_exact(self) -> None:
        # By hand: effective = 1.10 × 0.12 = 0.1320
        rr = _resolve_rate(
            PostFixedCDI.from_percent("110"),
            lookup_date=MIDPOINT_2Y,
            assumed_cdi=CDI_ASSUMED,
            assumed_ipca=None,
            cdi_curve=None,
            ipca_curve=None,
        )
        assert rr.rate_kind == "PostFixedCDI"
        assert rr.source == "assumed_fallback"
        assert rr.resolved_index_rate == CDI_ASSUMED
        assert rr.index_multiplier_or_spread == Decimal("1.10")
        assert rr.effective_annual_rate == Decimal("1.10") * CDI_ASSUMED

    def test_ipca_assumed_fallback_fisher_exact(self) -> None:
        # By hand: (1 + 0.04)(1 + 0.05) − 1 = 1.0920 − 1 = 0.0920
        rr = _resolve_rate(
            PostFixedIPCA.from_percent("5"),
            lookup_date=MATURITY_3Y,
            assumed_cdi=None,
            assumed_ipca=IPCA_ASSUMED,
            cdi_curve=None,
            ipca_curve=None,
        )
        expected = (
            (Decimal("1") + IPCA_ASSUMED) * (Decimal("1") + Decimal("0.05")) - Decimal("1")
        )
        assert rr.effective_annual_rate == expected
        assert rr.index_multiplier_or_spread == Decimal("0.05")
        assert rr.resolved_index_rate == IPCA_ASSUMED

    def test_cdi_plus_spread_assumed_fallback_fisher_exact(self) -> None:
        # By hand: (1 + 0.12)(1 + 0.02) − 1 = 1.1424 − 1 = 0.1424
        rr = _resolve_rate(
            PostFixedCDIPlusSpread.from_percent("2"),
            lookup_date=MIDPOINT_2Y,
            assumed_cdi=CDI_ASSUMED,
            assumed_ipca=None,
            cdi_curve=None,
            ipca_curve=None,
        )
        expected = (
            (Decimal("1") + CDI_ASSUMED) * (Decimal("1") + Decimal("0.02")) - Decimal("1")
        )
        assert rr.effective_annual_rate == expected
        assert rr.index_multiplier_or_spread == Decimal("0.02")
        assert rr.resolved_index_rate == CDI_ASSUMED


class TestResolveRateSource:
    """Curve vs assumed_fallback selection, and ValueError for missing index."""

    def test_cdi_curve_preferred_over_assumed(self) -> None:
        # CDI_CURVE has rate 0.14 at 252 bds; assumed is 0.12 — curve wins
        rr = _resolve_rate(
            PostFixedCDI.from_percent("100"),
            lookup_date=MATURITY_2Y,
            assumed_cdi=CDI_ASSUMED,
            assumed_ipca=None,
            cdi_curve=CDI_CURVE,
            ipca_curve=None,
        )
        assert rr.source == "curve"
        assert rr.resolved_index_rate == CDI_CURVE.rate_at(MATURITY_2Y)
        assert rr.curve_anchor == CDI_CURVE.anchor
        assert rr.curve_tenor_date == MATURITY_2Y

    def test_cdi_assumed_fallback_when_no_curve(self) -> None:
        rr = _resolve_rate(
            PostFixedCDI.from_percent("100"),
            lookup_date=MATURITY_2Y,
            assumed_cdi=CDI_ASSUMED,
            assumed_ipca=None,
            cdi_curve=None,
            ipca_curve=None,
        )
        assert rr.source == "assumed_fallback"
        assert rr.resolved_index_rate == CDI_ASSUMED
        assert rr.curve_anchor is None
        assert rr.curve_tenor_date is None

    def test_assumed_fallback_when_empty_curve(self) -> None:
        empty = Curve(anchor=ANCHOR, vertices=())
        rr = _resolve_rate(
            PostFixedCDI.from_percent("100"),
            lookup_date=MATURITY_2Y,
            assumed_cdi=CDI_ASSUMED,
            assumed_ipca=None,
            cdi_curve=empty,
            ipca_curve=None,
        )
        assert rr.source == "assumed_fallback"

    def test_ipca_curve_preferred_over_assumed(self) -> None:
        rr = _resolve_rate(
            PostFixedIPCA.from_percent("5"),
            lookup_date=MATURITY_2Y,
            assumed_cdi=None,
            assumed_ipca=IPCA_ASSUMED,
            cdi_curve=None,
            ipca_curve=IPCA_CURVE,
        )
        assert rr.source == "curve"
        assert rr.resolved_index_rate == IPCA_CURVE.rate_at(MATURITY_2Y)
        assert rr.curve_anchor == IPCA_CURVE.anchor

    def test_value_error_cdi_no_rate_available(self) -> None:
        with pytest.raises(ValueError, match="assumed_cdi"):
            _resolve_rate(
                PostFixedCDI.from_percent("100"),
                lookup_date=MATURITY_2Y,
                assumed_cdi=None,
                assumed_ipca=None,
                cdi_curve=None,
                ipca_curve=None,
            )

    def test_value_error_ipca_no_rate_available(self) -> None:
        with pytest.raises(ValueError, match="assumed_ipca"):
            _resolve_rate(
                PostFixedIPCA.from_percent("5"),
                lookup_date=MATURITY_3Y,
                assumed_cdi=None,
                assumed_ipca=None,
                cdi_curve=None,
                ipca_curve=None,
            )

    def test_prefixed_needs_no_assumed_rate(self) -> None:
        rr = _resolve_rate(
            Prefixed.from_percent("12"),
            lookup_date=MATURITY_2Y,
            assumed_cdi=None,
            assumed_ipca=None,
            cdi_curve=None,
            ipca_curve=None,
        )
        assert rr.source == "fixed"


class TestAccrualFactorAndStep:
    """_accrual_factor and _accrue_step match the formula exactly."""

    def test_factor_zero_bdays_is_one(self) -> None:
        assert _accrual_factor(Decimal("0.12"), 0) == Decimal("1")

    def test_factor_formula_exact(self) -> None:
        # 126 bd at 12%: same Decimal arithmetic as the function
        r = Decimal("0.12")
        du = 126
        expected = (Decimal("1") + r) ** (Decimal(du) / Decimal(252))
        assert _accrual_factor(r, du) == expected

    def test_factor_full_year_prefixed(self) -> None:
        # 252 bd at 12%: (1.12)^(252/252) — same expression
        r = Decimal("0.12")
        expected = (Decimal("1") + r) ** (Decimal(252) / Decimal(252))
        assert _accrual_factor(r, 252) == expected

    def test_accrue_step_factor_exact(self) -> None:
        rr = _resolve_rate(
            Prefixed.from_percent("12"),
            lookup_date=MATURITY_2Y,
            assumed_cdi=None, assumed_ipca=None,
            cdi_curve=None, ipca_curve=None,
        )
        step = _accrue_step(
            Money.from_reais("10000"), rr,
            from_date=PURCHASE, to_date=MATURITY_2Y, business_days=504,
        )
        expected_factor = (Decimal("1") + Decimal("0.12")) ** (Decimal(504) / Decimal(252))
        assert step.factor == expected_factor

    def test_accrue_step_closing_balance_exact(self) -> None:
        rr = _resolve_rate(
            Prefixed.from_percent("12"),
            lookup_date=MATURITY_2Y,
            assumed_cdi=None, assumed_ipca=None,
            cdi_curve=None, ipca_curve=None,
        )
        principal = Money.from_reais("10000")
        step = _accrue_step(
            principal, rr,
            from_date=PURCHASE, to_date=MATURITY_2Y, business_days=504,
        )
        assert step.closing_balance == principal * step.factor

    def test_accrue_step_metadata(self) -> None:
        rr = _minimal_rate_resolution()
        principal = Money.from_reais("5000")
        step = _accrue_step(
            principal, rr,
            from_date=PURCHASE, to_date=MATURITY_1Y, business_days=252,
        )
        assert step.from_date == PURCHASE
        assert step.to_date == MATURITY_1Y
        assert step.business_days == 252
        assert step.rate is rr
        assert step.opening_balance == principal

    def test_accrue_step_zero_bdays_closing_equals_opening(self) -> None:
        rr = _minimal_rate_resolution()
        principal = Money.from_reais("10000")
        step = _accrue_step(
            principal, rr,
            from_date=PURCHASE, to_date=PURCHASE, business_days=0,
        )
        assert step.factor == Decimal("1")
        assert step.closing_balance == principal


class TestProjectTracedVsProject:
    """project_traced output must be bit-identical to project on all result fields."""

    def _assert_parity(self, inv: Investment, **kwargs) -> None:
        result = project(inv, **kwargs)
        trace = project_traced(inv, **kwargs)

        assert trace.current_value == result.current_value
        assert trace.gross_at_maturity == result.gross_at_maturity
        assert trace.net_at_maturity == result.net_at_maturity
        assert len(trace.cash_flows) == len(result.cash_flows)
        assert tuple(ft.amount for ft in trace.cash_flows) == tuple(
            cf.amount for cf in result.cash_flows
        )
        assert tuple(ft.pay_date for ft in trace.cash_flows) == tuple(
            cf.date for cf in result.cash_flows
        )
        assert tuple(ft.kind for ft in trace.cash_flows) == tuple(
            cf.kind for cf in result.cash_flows
        )
        assert trace.tax.bracket_rate == result.tax_breakdown.tax_rate
        assert trace.tax.tax_amount == result.tax_breakdown.tax_amount
        assert trace.tax.taxable_gain == result.tax_breakdown.gain
        assert trace.tax.iof_modeled is False

    def test_prefixed_bullet_midpoint(self) -> None:
        self._assert_parity(_prefixed_bullet(), as_of=MIDPOINT_2Y)

    def test_cdi_bullet_assumed_at_maturity(self) -> None:
        self._assert_parity(
            _cdi_bullet_assumed(), as_of=MATURITY_2Y, assumed_cdi=CDI_ASSUMED
        )

    def test_cdi_bullet_with_curve_midpoint(self) -> None:
        self._assert_parity(
            _cdi_bullet_assumed(), as_of=MIDPOINT_2Y,
            assumed_cdi=CDI_ASSUMED, cdi_curve=CDI_CURVE,
        )

    def test_ipca_bullet_assumed(self) -> None:
        self._assert_parity(_ipca_bullet(), as_of=MIDPOINT_2Y, assumed_ipca=IPCA_ASSUMED)

    def test_cdi_plus_spread_bullet(self) -> None:
        self._assert_parity(
            _cdi_plus_spread_bullet(), as_of=MIDPOINT_2Y, assumed_cdi=CDI_ASSUMED
        )

    def test_lci_ir_exempt(self) -> None:
        self._assert_parity(_lci_exempt(), as_of=MIDPOINT_1Y, assumed_cdi=CDI_ASSUMED)

    def test_prefixed_semi_annual(self) -> None:
        self._assert_parity(_prefixed_semi_annual(), as_of=MIDPOINT_2Y)


class TestCurrentValueAccrualFidelity:
    """current_value_accrual has correct structure and arithmetic."""

    def test_at_purchase_date_no_accrual(self) -> None:
        inv = _prefixed_bullet()
        trace = project_traced(inv, as_of=PURCHASE)
        assert trace.current_value_accrual == ()
        assert trace.current_value == inv.principal

    def test_before_purchase_no_accrual(self) -> None:
        inv = _prefixed_bullet()
        trace = project_traced(inv, as_of=date(2023, 1, 1))
        assert trace.current_value_accrual == ()
        assert trace.current_value == inv.principal

    def test_after_maturity_step_capped_at_maturity(self) -> None:
        inv = _prefixed_bullet()
        trace = project_traced(inv, as_of=date(2030, 1, 1))
        assert len(trace.current_value_accrual) == 1
        step = trace.current_value_accrual[0]
        assert step.to_date == inv.maturity_date
        assert trace.current_value == step.closing_balance

    def test_normal_midpoint_one_step(self) -> None:
        inv = _prefixed_bullet()
        trace = project_traced(inv, as_of=MIDPOINT_2Y)
        assert len(trace.current_value_accrual) == 1
        step = trace.current_value_accrual[0]
        assert step.from_date == inv.purchase_date
        assert step.to_date == MIDPOINT_2Y
        assert trace.current_value == step.closing_balance

    def test_cv_step_factor_exact(self) -> None:
        # factor == (1+r)^(Du/252) — same Decimal arithmetic as _accrual_factor
        inv = _prefixed_bullet()
        trace = project_traced(inv, as_of=MIDPOINT_2Y)
        step = trace.current_value_accrual[0]
        expected = (Decimal("1") + Decimal("0.12")) ** (
            Decimal(step.business_days) / Decimal(252)
        )
        assert step.factor == expected

    def test_cv_step_closing_balance_exact(self) -> None:
        inv = _prefixed_bullet()
        trace = project_traced(inv, as_of=MIDPOINT_2Y)
        step = trace.current_value_accrual[0]
        assert step.closing_balance == inv.principal * step.factor


class TestFlowTraceFidelityPerKind:
    """Per-flow: kind, components, single accrual step, exact arithmetic."""

    def test_bullet_has_one_principal_flow(self) -> None:
        trace = project_traced(_prefixed_bullet(), as_of=MIDPOINT_2Y)
        assert len(trace.cash_flows) == 1
        assert trace.cash_flows[0].kind == CashFlowKind.PRINCIPAL

    def test_principal_flow_components_sum_to_amount(self) -> None:
        inv = _prefixed_bullet()
        trace = project_traced(inv, as_of=MIDPOINT_2Y)
        ft = trace.cash_flows[0]
        assert ft.principal_component == inv.principal
        assert ft.interest_component + ft.principal_component == ft.amount

    def test_semi_annual_has_coupon_and_coupon_and_principal_flows(self) -> None:
        trace = project_traced(_prefixed_semi_annual(), as_of=MIDPOINT_2Y)
        kinds = [ft.kind for ft in trace.cash_flows]
        assert CashFlowKind.COUPON in kinds
        assert CashFlowKind.COUPON_AND_PRINCIPAL in kinds
        assert kinds[-1] == CashFlowKind.COUPON_AND_PRINCIPAL

    def test_coupon_flow_principal_component_is_zero(self) -> None:
        trace = project_traced(_prefixed_semi_annual(), as_of=MIDPOINT_2Y)
        for ft in trace.cash_flows:
            if ft.kind == CashFlowKind.COUPON:
                assert ft.principal_component == Money.zero("BRL")
                assert ft.interest_component == ft.amount

    def test_coupon_and_principal_flow_components(self) -> None:
        inv = _prefixed_semi_annual()
        trace = project_traced(inv, as_of=MIDPOINT_2Y)
        final = trace.cash_flows[-1]
        assert final.kind == CashFlowKind.COUPON_AND_PRINCIPAL
        assert final.principal_component == inv.principal
        assert final.interest_component + final.principal_component == final.amount

    def test_each_flow_has_exactly_one_accrual_step(self) -> None:
        for trace in [
            project_traced(_prefixed_bullet(), as_of=MIDPOINT_2Y),
            project_traced(_prefixed_semi_annual(), as_of=MIDPOINT_2Y),
        ]:
            for ft in trace.cash_flows:
                assert len(ft.accrual) == 1

    def test_flow_accrual_step_opening_is_principal(self) -> None:
        inv = _prefixed_semi_annual()
        trace = project_traced(inv, as_of=MIDPOINT_2Y)
        for ft in trace.cash_flows:
            assert ft.accrual[0].opening_balance == inv.principal

    def test_flow_step_factor_exact(self) -> None:
        # Every accrual step: factor == (1+r)^(Du/252) — same Decimal arithmetic
        inv = _prefixed_semi_annual()
        trace = project_traced(inv, as_of=MIDPOINT_2Y)
        for ft in trace.cash_flows:
            step = ft.accrual[0]
            expected = (Decimal("1") + step.rate.effective_annual_rate) ** (
                Decimal(step.business_days) / Decimal(252)
            )
            assert step.factor == expected

    def test_flow_step_closing_balance_exact(self) -> None:
        inv = _prefixed_semi_annual()
        trace = project_traced(inv, as_of=MIDPOINT_2Y)
        for ft in trace.cash_flows:
            step = ft.accrual[0]
            assert step.closing_balance == inv.principal * step.factor

    def test_flow_pay_dates_match_project_schedule(self) -> None:
        inv = _prefixed_semi_annual()
        result = project(inv, as_of=MIDPOINT_2Y)
        trace = project_traced(inv, as_of=MIDPOINT_2Y)
        assert tuple(ft.pay_date for ft in trace.cash_flows) == tuple(
            cf.date for cf in result.cash_flows
        )


class TestTenorDivergence:
    """CDI and IPCA use different lookup dates for curve resolution."""

    def test_prefixed_all_curve_tenor_dates_are_none(self) -> None:
        trace = project_traced(_prefixed_semi_annual(), as_of=MIDPOINT_2Y)
        for ft in trace.cash_flows:
            assert ft.accrual[0].rate.curve_tenor_date is None
        if trace.current_value_accrual:
            assert trace.current_value_accrual[0].rate.curve_tenor_date is None

    def test_cdi_coupon_tenor_equals_pay_date(self) -> None:
        inv = _cdi_semi_annual_curve()
        trace = project_traced(
            inv, as_of=MIDPOINT_2Y,
            assumed_cdi=CDI_ASSUMED, cdi_curve=CDI_CURVE,
        )
        for ft in trace.cash_flows:
            if ft.kind == CashFlowKind.COUPON:
                assert ft.accrual[0].rate.curve_tenor_date == ft.pay_date

    def test_cdi_final_flow_tenor_equals_maturity(self) -> None:
        inv = _cdi_semi_annual_curve()
        trace = project_traced(
            inv, as_of=MIDPOINT_2Y,
            assumed_cdi=CDI_ASSUMED, cdi_curve=CDI_CURVE,
        )
        final = trace.cash_flows[-1]
        assert final.kind == CashFlowKind.COUPON_AND_PRINCIPAL
        assert final.accrual[0].rate.curve_tenor_date == inv.maturity_date

    def test_cdi_cv_tenor_equals_min_as_of_maturity(self) -> None:
        inv = _cdi_semi_annual_curve()
        as_of = MIDPOINT_2Y
        trace = project_traced(
            inv, as_of=as_of,
            assumed_cdi=CDI_ASSUMED, cdi_curve=CDI_CURVE,
        )
        assert trace.current_value_accrual
        cv_step = trace.current_value_accrual[0]
        assert cv_step.rate.curve_tenor_date == min(as_of, inv.maturity_date)

    def test_ipca_all_flow_tenors_equal_maturity(self) -> None:
        inv = _ipca_semi_annual_curve()
        trace = project_traced(
            inv, as_of=MIDPOINT_2Y,
            assumed_ipca=IPCA_ASSUMED, ipca_curve=IPCA_CURVE,
        )
        for ft in trace.cash_flows:
            assert ft.accrual[0].rate.curve_tenor_date == inv.maturity_date

    def test_ipca_cv_tenor_equals_maturity(self) -> None:
        inv = _ipca_semi_annual_curve()
        trace = project_traced(
            inv, as_of=MIDPOINT_2Y,
            assumed_ipca=IPCA_ASSUMED, ipca_curve=IPCA_CURVE,
        )
        assert trace.current_value_accrual
        assert trace.current_value_accrual[0].rate.curve_tenor_date == inv.maturity_date


class TestConventionAndProvenance:
    """convention string, Assumptions, CurveProvenance, and TaxTrace.iof_modeled."""

    def test_convention_string(self) -> None:
        trace = project_traced(_prefixed_bullet(), as_of=MIDPOINT_2Y)
        assert trace.convention == "252 bd/yr; B3/ANBIMA holidays"

    def test_assumptions_cdi_only(self) -> None:
        trace = project_traced(_cdi_bullet_assumed(), as_of=MIDPOINT_2Y, assumed_cdi=CDI_ASSUMED)
        assert trace.assumptions.assumed_cdi == CDI_ASSUMED
        assert trace.assumptions.assumed_ipca is None

    def test_assumptions_ipca_only(self) -> None:
        trace = project_traced(_ipca_bullet(), as_of=MIDPOINT_2Y, assumed_ipca=IPCA_ASSUMED)
        assert trace.assumptions.assumed_cdi is None
        assert trace.assumptions.assumed_ipca == IPCA_ASSUMED

    def test_assumptions_both_none_for_prefixed(self) -> None:
        trace = project_traced(_prefixed_bullet(), as_of=MIDPOINT_2Y)
        assert trace.assumptions.assumed_cdi is None
        assert trace.assumptions.assumed_ipca is None

    def test_curve_provenance_anchor_none_when_no_curve(self) -> None:
        trace = project_traced(_cdi_bullet_assumed(), as_of=MIDPOINT_2Y, assumed_cdi=CDI_ASSUMED)
        assert trace.curve_provenance.anchor is None
        assert trace.curve_provenance.source is None
        assert trace.curve_provenance.curve_ref is None

    def test_curve_provenance_anchor_set_from_cdi_curve(self) -> None:
        trace = project_traced(
            _cdi_bullet_assumed(), as_of=MIDPOINT_2Y,
            assumed_cdi=CDI_ASSUMED, cdi_curve=CDI_CURVE,
        )
        assert trace.curve_provenance.anchor == CDI_CURVE.anchor

    def test_curve_provenance_anchor_set_from_ipca_curve(self) -> None:
        trace = project_traced(
            _ipca_bullet(), as_of=MIDPOINT_2Y,
            assumed_ipca=IPCA_ASSUMED, ipca_curve=IPCA_CURVE,
        )
        assert trace.curve_provenance.anchor == IPCA_CURVE.anchor

    def test_curve_provenance_anchor_none_for_prefixed(self) -> None:
        trace = project_traced(_prefixed_bullet(), as_of=MIDPOINT_2Y)
        assert trace.curve_provenance.anchor is None

    def test_tax_trace_iof_modeled_always_false(self) -> None:
        for trace in [
            project_traced(_prefixed_bullet(), as_of=MIDPOINT_2Y),
            project_traced(_cdi_bullet_assumed(), as_of=MIDPOINT_2Y, assumed_cdi=CDI_ASSUMED),
            project_traced(_lci_exempt(), as_of=MIDPOINT_1Y, assumed_cdi=CDI_ASSUMED),
        ]:
            assert trace.tax.iof_modeled is False

    def test_tax_trace_holding_days(self) -> None:
        inv = _prefixed_bullet()
        trace = project_traced(inv, as_of=MIDPOINT_2Y)
        expected_days = (inv.maturity_date - inv.purchase_date).days
        assert trace.tax.holding_calendar_days == expected_days
