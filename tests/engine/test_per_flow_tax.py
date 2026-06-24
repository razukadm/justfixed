"""Per-flow IR withholding: trace-level tests (F-07).

Verifies that TaxTrace.per_flow is populated correctly by _compute_projection,
and that aggregate fields equal the sums across all per-flow entries.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from justfixed.domain.investment import Investment
from justfixed.domain.issuer import Issuer, IssuerKind
from justfixed.domain.money import Money
from justfixed.domain.product import CouponFrequency, ProductType
from justfixed.domain.rates import PostFixedCDI, Prefixed
from justfixed.engine.projection import project_traced
from justfixed.engine.trace import FlowTax


def _bank() -> Issuer:
    return Issuer.create("Banco PF", "Banco PF S.A.", IssuerKind.COMMERCIAL_BANK)


def _semi_annual_cdb() -> Investment:
    return Investment.create(
        product=ProductType.CDB,
        issuer=_bank(),
        principal=Money.from_reais("10000"),
        rate=Prefixed.from_percent("12"),
        purchase_date=date(2024, 1, 15),
        maturity_date=date(2026, 1, 15),
        coupon_frequency=CouponFrequency.SEMI_ANNUAL,
    )


def _bullet_cdb() -> Investment:
    return Investment.create(
        product=ProductType.CDB,
        issuer=_bank(),
        principal=Money.from_reais("10000"),
        rate=Prefixed.from_percent("12"),
        purchase_date=date(2024, 1, 15),
        maturity_date=date(2026, 1, 15),
    )


def _lci_exempt() -> Investment:
    return Investment.create(
        product=ProductType.LCI,
        issuer=_bank(),
        principal=Money.from_reais("10000"),
        rate=PostFixedCDI.from_percent("90"),
        purchase_date=date(2024, 1, 15),
        maturity_date=date(2026, 1, 15),
    )


class TestPerFlowTaxTrace:
    """TaxTrace.per_flow is populated with one FlowTax per cash flow."""

    def test_coupon_per_flow_length_matches_cash_flows(self) -> None:
        inv = _semi_annual_cdb()
        trace = project_traced(inv, as_of=date(2026, 1, 15))
        assert len(trace.tax.per_flow) == len(trace.cash_flows)

    def test_coupon_per_flow_length_is_four(self) -> None:
        # 2-year semi-annual → 3 COUPON + 1 COUPON_AND_PRINCIPAL = 4 flows
        inv = _semi_annual_cdb()
        trace = project_traced(inv, as_of=date(2026, 1, 15))
        assert len(trace.tax.per_flow) == 4

    def test_coupon_per_flow_entries_are_flow_tax(self) -> None:
        inv = _semi_annual_cdb()
        trace = project_traced(inv, as_of=date(2026, 1, 15))
        for entry in trace.tax.per_flow:
            assert isinstance(entry, FlowTax)

    def test_coupon_holding_days_are_purchase_to_pay_date(self) -> None:
        inv = _semi_annual_cdb()
        trace = project_traced(inv, as_of=date(2026, 1, 15))
        for ft, pf in zip(trace.cash_flows, trace.tax.per_flow):
            expected_days = (ft.pay_date - inv.purchase_date).days
            assert pf.holding_days == expected_days

    def test_coupon_pay_dates_match_cash_flow_pay_dates(self) -> None:
        inv = _semi_annual_cdb()
        trace = project_traced(inv, as_of=date(2026, 1, 15))
        for ft, pf in zip(trace.cash_flows, trace.tax.per_flow):
            assert pf.pay_date == ft.pay_date

    def test_coupon_per_flow_tax_sums_to_aggregate(self) -> None:
        inv = _semi_annual_cdb()
        trace = project_traced(inv, as_of=date(2026, 1, 15))
        total = Money.zero("BRL")
        for pf in trace.tax.per_flow:
            total = total + pf.tax_amount
        assert total == trace.tax.tax_amount

    def test_coupon_earlier_flows_have_higher_brackets_than_final(self) -> None:
        # Early coupons (< 181 days or < 361 days) use higher rates than the
        # final flow (~730 days at 15%). This is the behavioural difference vs
        # the old single-bracket path.
        inv = _semi_annual_cdb()
        trace = project_traced(inv, as_of=date(2026, 1, 15))
        final_rate = trace.tax.per_flow[-1].bracket_rate
        first_rate = trace.tax.per_flow[0].bracket_rate
        assert first_rate > final_rate

    def test_coupon_aggregate_bracket_rate_is_effective_blended(self) -> None:
        # Blended rate != any single-bracket rate for a multi-flow instrument.
        inv = _semi_annual_cdb()
        trace = project_traced(inv, as_of=date(2026, 1, 15))
        # Each per-flow bracket is one of {0.225, 0.20, 0.175, 0.15}; the
        # blended rate falls somewhere in range.
        assert Decimal("0.15") < trace.tax.bracket_rate < Decimal("0.225")

    def test_bullet_per_flow_length_is_one(self) -> None:
        inv = _bullet_cdb()
        trace = project_traced(inv, as_of=date(2026, 1, 15))
        assert len(trace.tax.per_flow) == 1

    def test_bullet_per_flow_aggregate_matches_compute_ir(self) -> None:
        # For a bullet, the single-flow per_flow path must reproduce today's
        # single-bracket result exactly (the KEY INVARIANT at the projection level).
        from justfixed.engine.tax import compute_ir
        from justfixed.domain.product import rules_for

        inv = _bullet_cdb()
        trace = project_traced(inv, as_of=date(2026, 1, 15))
        holding_days = (inv.maturity_date - inv.purchase_date).days
        rule = rules_for(inv.product)
        expected = compute_ir(
            principal=inv.principal,
            gross=trace.gross_at_maturity,
            treatment=rule.tax_treatment,
            holding_days=holding_days,
        )
        # tax_amount and net must match exactly; bracket_rate is the exact bracket
        assert trace.tax.tax_amount == expected.tax_amount
        assert trace.net_at_maturity == expected.net
        assert trace.tax.bracket_rate == expected.tax_rate

    def test_exempt_per_flow_all_zero_tax(self) -> None:
        inv = _lci_exempt()
        trace = project_traced(inv, as_of=date(2026, 1, 15), assumed_cdi=Decimal("0.12"))
        assert trace.tax.tax_amount == Money.zero("BRL")
        # LCI is bullet; per_flow has one entry with zero tax
        assert len(trace.tax.per_flow) == 1
        assert trace.tax.per_flow[0].tax_amount == Money.zero("BRL")
        assert trace.tax.per_flow[0].bracket_rate == Decimal("0")

    def test_coupon_net_plus_tax_equals_gross(self) -> None:
        inv = _semi_annual_cdb()
        trace = project_traced(inv, as_of=date(2026, 1, 15))
        assert trace.net_at_maturity + trace.tax.tax_amount == trace.gross_at_maturity
