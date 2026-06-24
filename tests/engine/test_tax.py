"""Tests for the IR tax engine."""

from __future__ import annotations

from decimal import Decimal

import pytest

from justfixed.domain.money import Money
from justfixed.domain.product import TaxTreatment
from justfixed.engine.tax import FlowTaxResult, compute_ir, compute_ir_schedule, regressive_rate_for


# ---------- regressive_rate_for ----------


class TestRegressiveBrackets:
    """The 4 brackets must apply at the correct boundaries."""

    def test_day_zero_uses_first_bracket(self) -> None:
        assert regressive_rate_for(0) == Decimal("0.225")

    def test_day_180_uses_first_bracket(self) -> None:
        # Boundary: <= 180 days is still 22.5%.
        assert regressive_rate_for(180) == Decimal("0.225")

    def test_day_181_uses_second_bracket(self) -> None:
        assert regressive_rate_for(181) == Decimal("0.20")

    def test_day_360_uses_second_bracket(self) -> None:
        assert regressive_rate_for(360) == Decimal("0.20")

    def test_day_361_uses_third_bracket(self) -> None:
        assert regressive_rate_for(361) == Decimal("0.175")

    def test_day_720_uses_third_bracket(self) -> None:
        assert regressive_rate_for(720) == Decimal("0.175")

    def test_day_721_uses_fourth_bracket(self) -> None:
        assert regressive_rate_for(721) == Decimal("0.15")

    def test_far_future_uses_fourth_bracket(self) -> None:
        assert regressive_rate_for(10_000) == Decimal("0.15")

    def test_negative_days_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            regressive_rate_for(-1)


# ---------- compute_ir: regressive tax ----------


class TestComputeIRRegressive:
    """compute_ir on IR_REGRESSIVE products."""

    def test_one_year_at_15_percent_bracket(self) -> None:
        # 730 days holding -> 15% bracket.
        # Principal 10000, gross 11200, gain 1200.
        # Tax = 0.15 × 1200 = 180. Net = 11200 - 180 = 11020.
        result = compute_ir(
            principal=Money.from_reais("10000"),
            gross=Money.from_reais("11200"),
            treatment=TaxTreatment.IR_REGRESSIVE,
            holding_days=730,
        )
        assert result.tax_rate == Decimal("0.15")
        assert result.gain == Money.from_reais("1200")
        assert result.tax_amount == Money.from_reais("180")
        assert result.net == Money.from_reais("11020")

    def test_short_term_22_5_percent_bracket(self) -> None:
        # 90 days holding -> 22.5% bracket.
        # Gain 500, tax = 112.50, net = principal + 500 - 112.50.
        result = compute_ir(
            principal=Money.from_reais("10000"),
            gross=Money.from_reais("10500"),
            treatment=TaxTreatment.IR_REGRESSIVE,
            holding_days=90,
        )
        assert result.tax_rate == Decimal("0.225")
        assert result.tax_amount == Money.from_reais("112.50")
        assert result.net == Money.from_reais("10387.50")

    def test_tax_is_on_gain_not_principal(self) -> None:
        """The most important invariant: tax is computed on (gross - principal)."""
        result = compute_ir(
            principal=Money.from_reais("10000"),
            gross=Money.from_reais("11000"),
            treatment=TaxTreatment.IR_REGRESSIVE,
            holding_days=1000,
        )
        # Gain = 1000. Tax = 15% × 1000 = 150. NOT 15% of 11000.
        assert result.tax_amount == Money.from_reais("150")
        assert result.net == Money.from_reais("10850")

    def test_zero_gain_zero_tax(self) -> None:
        # Edge: principal == gross. No gain, no tax.
        result = compute_ir(
            principal=Money.from_reais("10000"),
            gross=Money.from_reais("10000"),
            treatment=TaxTreatment.IR_REGRESSIVE,
            holding_days=200,
        )
        assert result.gain == Money.zero()
        assert result.tax_amount == Money.zero()
        assert result.net == Money.from_reais("10000")

    def test_negative_gain_no_tax(self) -> None:
        # MtM scenario where the position is currently underwater.
        # No tax on losses.
        result = compute_ir(
            principal=Money.from_reais("10000"),
            gross=Money.from_reais("9500"),
            treatment=TaxTreatment.IR_REGRESSIVE,
            holding_days=200,
        )
        assert result.tax_rate == Decimal("0")
        assert result.tax_amount == Money.zero()
        assert result.net == Money.from_reais("9500")


# ---------- compute_ir: exempt tax ----------


class TestComputeIRExempt:
    """LCI, LCA, LCD: zero IR for individuals."""

    def test_exempt_treatment_zero_tax(self) -> None:
        result = compute_ir(
            principal=Money.from_reais("10000"),
            gross=Money.from_reais("11000"),
            treatment=TaxTreatment.IR_EXEMPT,
            holding_days=365,
        )
        assert result.tax_rate == Decimal("0")
        assert result.tax_amount == Money.zero()
        assert result.net == Money.from_reais("11000")
        assert result.gain == Money.from_reais("1000")  # gain still computed

    def test_exempt_short_term_still_zero(self) -> None:
        # Exempt is exempt regardless of holding period.
        result = compute_ir(
            principal=Money.from_reais("10000"),
            gross=Money.from_reais("10300"),
            treatment=TaxTreatment.IR_EXEMPT,
            holding_days=30,
        )
        assert result.tax_amount == Money.zero()


# ---------- Currency safety ----------


class TestCurrencySafety:
    def test_currency_mismatch_rejected(self) -> None:
        with pytest.raises(ValueError, match="Currency mismatch"):
            compute_ir(
                principal=Money.from_reais("10000", currency="BRL"),
                gross=Money.from_reais("11000", currency="USD"),
                treatment=TaxTreatment.IR_REGRESSIVE,
                holding_days=365,
            )

    def test_result_preserves_currency(self) -> None:
        result = compute_ir(
            principal=Money.from_reais("10000", currency="BRL"),
            gross=Money.from_reais("11000", currency="BRL"),
            treatment=TaxTreatment.IR_REGRESSIVE,
            holding_days=365,
        )
        assert result.net.currency == "BRL"
        assert result.tax_amount.currency == "BRL"


# ---------- Realistic scenarios ----------


class TestRealisticScenarios:
    """Concrete cases mirroring real Brazilian portfolios."""

    def test_two_year_cdb_bracket_change(self) -> None:
        # 2-year CDB at 110% CDI (CDI=12%) → ~13.2% effective.
        # Principal 50000, gross ≈ 64080, gain ≈ 14080.
        # 730 days → 15% bracket. Tax ≈ 2112. Net ≈ 61968.
        result = compute_ir(
            principal=Money.from_reais("50000"),
            gross=Money.from_reais("64080"),
            treatment=TaxTreatment.IR_REGRESSIVE,
            holding_days=730,
        )
        assert result.tax_rate == Decimal("0.15")
        assert result.tax_amount == Money.from_reais("2112")
        assert result.net == Money.from_reais("61968")

    def test_short_term_cdb_high_tax_bracket(self) -> None:
        # 4-month CDB held to maturity. Falls in 22.5% bracket.
        # 50000 → 51500 (a 3% gain over 120 days).
        # Tax = 0.225 × 1500 = 337.50. Net = 51162.50.
        result = compute_ir(
            principal=Money.from_reais("50000"),
            gross=Money.from_reais("51500"),
            treatment=TaxTreatment.IR_REGRESSIVE,
            holding_days=120,
        )
        assert result.tax_rate == Decimal("0.225")
        assert result.tax_amount == Money.from_reais("337.50")

    def test_lci_short_or_long_term_no_tax(self) -> None:
        """LCI is exempt regardless of holding period — the key advantage."""
        # Same gain, different holding periods.
        for days in [30, 365, 1000]:
            result = compute_ir(
                principal=Money.from_reais("10000"),
                gross=Money.from_reais("11000"),
                treatment=TaxTreatment.IR_EXEMPT,
                holding_days=days,
            )
            assert result.tax_amount == Money.zero()
            assert result.net == Money.from_reais("11000")


# ---------- Result structure ----------


class TestTaxResult:
    """The TaxResult contains all the pieces a UI needs."""

    def test_all_fields_populated(self) -> None:
        result = compute_ir(
            principal=Money.from_reais("10000"),
            gross=Money.from_reais("11200"),
            treatment=TaxTreatment.IR_REGRESSIVE,
            holding_days=730,
        )
        assert result.gross == Money.from_reais("11200")
        assert result.gain == Money.from_reais("1200")
        assert result.tax_rate == Decimal("0.15")
        assert result.tax_amount == Money.from_reais("180")
        assert result.net == Money.from_reais("11020")

    def test_net_plus_tax_equals_gross(self) -> None:
        """Invariant: gross == net + tax_amount, always."""
        for days, gross_amount in [
            (90, "10500"),
            (300, "10800"),
            (500, "11500"),
            (1000, "13000"),
        ]:
            result = compute_ir(
                principal=Money.from_reais("10000"),
                gross=Money.from_reais(gross_amount),
                treatment=TaxTreatment.IR_REGRESSIVE,
                holding_days=days,
            )
            assert result.net + result.tax_amount == result.gross


# ---------- compute_ir_schedule ----------


class TestComputeIRSchedule:
    """Per-flow IR schedule: KEY INVARIANT and multi-flow correctness."""

    # KEY INVARIANT: single flow where interest == gain matches compute_ir exactly

    def test_single_flow_15_bracket_matches_compute_ir(self) -> None:
        # 730 days → 15%; gain=1200; tax=180; net=11020
        principal = Money.from_reais("10000")
        gross = Money.from_reais("11200")
        aggregate, per_flow = compute_ir_schedule(
            [(Money.from_reais("1200"), 730)],
            principal=principal,
            gross=gross,
            treatment=TaxTreatment.IR_REGRESSIVE,
        )
        expected = compute_ir(principal, gross, TaxTreatment.IR_REGRESSIVE, 730)
        assert aggregate.tax_amount == expected.tax_amount
        assert aggregate.tax_rate == expected.tax_rate
        assert aggregate.net == expected.net
        assert len(per_flow) == 1
        assert per_flow[0].bracket_rate == Decimal("0.15")
        assert per_flow[0].tax_amount == Money.from_reais("180")

    def test_single_flow_225_bracket_matches_compute_ir(self) -> None:
        # 90 days → 22.5%; gain=500; tax=112.50; net=10387.50
        principal = Money.from_reais("10000")
        gross = Money.from_reais("10500")
        aggregate, per_flow = compute_ir_schedule(
            [(Money.from_reais("500"), 90)],
            principal=principal,
            gross=gross,
            treatment=TaxTreatment.IR_REGRESSIVE,
        )
        expected = compute_ir(principal, gross, TaxTreatment.IR_REGRESSIVE, 90)
        assert aggregate.tax_amount == expected.tax_amount
        assert aggregate.net == expected.net

    def test_single_flow_175_bracket_matches_compute_ir(self) -> None:
        # 400 days → 17.5%; gain=1000; tax=175; net=10825
        principal = Money.from_reais("10000")
        gross = Money.from_reais("11000")
        aggregate, per_flow = compute_ir_schedule(
            [(Money.from_reais("1000"), 400)],
            principal=principal,
            gross=gross,
            treatment=TaxTreatment.IR_REGRESSIVE,
        )
        expected = compute_ir(principal, gross, TaxTreatment.IR_REGRESSIVE, 400)
        assert aggregate.tax_amount == expected.tax_amount
        assert aggregate.net == expected.net

    def test_single_flow_effective_rate_equals_bracket(self) -> None:
        # For one flow where interest == gain, effective_rate == bracket_rate exactly.
        # 730 days → 15%; gain=1000; tax=150; effective = 150/1000 = 0.15
        principal = Money.from_reais("10000")
        gross = Money.from_reais("11000")
        aggregate, _ = compute_ir_schedule(
            [(Money.from_reais("1000"), 730)],
            principal=principal,
            gross=gross,
            treatment=TaxTreatment.IR_REGRESSIVE,
        )
        assert aggregate.tax_rate == Decimal("0.15")

    def test_two_flow_coupon_hand_computed(self) -> None:
        # Hand-computed expected values:
        # Flow 1: interest=500, holding_days=90  → bracket 22.5% → tax = 500 × 0.225 = 112.50
        # Flow 2: interest=700, holding_days=500 → bracket 17.5% → tax = 700 × 0.175 = 122.50
        # total_tax = 235.00; net = 11200 - 235 = 10965.00
        # effective_rate = 235.00000000 / 1200.00000000
        principal = Money.from_reais("10000")
        gross = Money.from_reais("11200")
        aggregate, per_flow = compute_ir_schedule(
            [(Money.from_reais("500"), 90), (Money.from_reais("700"), 500)],
            principal=principal,
            gross=gross,
            treatment=TaxTreatment.IR_REGRESSIVE,
        )
        assert len(per_flow) == 2
        assert per_flow[0].bracket_rate == Decimal("0.225")
        assert per_flow[0].tax_amount == Money.from_reais("112.50")
        assert per_flow[1].bracket_rate == Decimal("0.175")
        assert per_flow[1].tax_amount == Money.from_reais("122.50")
        assert aggregate.tax_amount == Money.from_reais("235")
        assert aggregate.net == Money.from_reais("10965")
        expected_rate = Decimal("235.00000000") / Decimal("1200.00000000")
        assert aggregate.tax_rate == expected_rate

    def test_two_flow_net_plus_tax_equals_gross(self) -> None:
        # Invariant holds even for multi-flow.
        principal = Money.from_reais("10000")
        gross = Money.from_reais("11200")
        aggregate, _ = compute_ir_schedule(
            [(Money.from_reais("500"), 90), (Money.from_reais("700"), 500)],
            principal=principal,
            gross=gross,
            treatment=TaxTreatment.IR_REGRESSIVE,
        )
        assert aggregate.net + aggregate.tax_amount == aggregate.gross

    def test_exempt_all_flows_zero_tax(self) -> None:
        principal = Money.from_reais("10000")
        gross = Money.from_reais("11000")
        aggregate, per_flow = compute_ir_schedule(
            [(Money.from_reais("500"), 90), (Money.from_reais("500"), 365)],
            principal=principal,
            gross=gross,
            treatment=TaxTreatment.IR_EXEMPT,
        )
        assert aggregate.tax_amount == Money.zero()
        assert aggregate.net == gross
        assert aggregate.tax_rate == Decimal("0")
        assert len(per_flow) == 2
        for flow_result in per_flow:
            assert flow_result.bracket_rate == Decimal("0")
            assert flow_result.tax_amount == Money.zero()

    def test_negative_gain_zero_tax_empty_per_flow(self) -> None:
        principal = Money.from_reais("10000")
        gross = Money.from_reais("9500")
        aggregate, per_flow = compute_ir_schedule(
            [(Money.from_reais("500"), 90)],
            principal=principal,
            gross=gross,
            treatment=TaxTreatment.IR_REGRESSIVE,
        )
        assert aggregate.tax_amount == Money.zero()
        assert aggregate.net == gross
        assert aggregate.tax_rate == Decimal("0")
        assert per_flow == ()

    def test_currency_mismatch_principal_vs_gross_rejected(self) -> None:
        with pytest.raises(ValueError, match="Currency mismatch"):
            compute_ir_schedule(
                [(Money.from_reais("500", currency="BRL"), 90)],
                principal=Money.from_reais("10000", currency="BRL"),
                gross=Money.from_reais("10500", currency="USD"),
                treatment=TaxTreatment.IR_REGRESSIVE,
            )

    def test_currency_mismatch_flow_vs_gross_rejected(self) -> None:
        with pytest.raises(ValueError, match="Currency mismatch"):
            compute_ir_schedule(
                [(Money.from_reais("500", currency="USD"), 90)],
                principal=Money.from_reais("10000", currency="BRL"),
                gross=Money.from_reais("10500", currency="BRL"),
                treatment=TaxTreatment.IR_REGRESSIVE,
            )

    def test_flow_tax_result_is_frozen(self) -> None:
        r = FlowTaxResult(
            holding_days=90,
            bracket_rate=Decimal("0.225"),
            taxable_interest=Money.from_reais("500"),
            tax_amount=Money.from_reais("112.50"),
        )
        with pytest.raises(AttributeError):
            r.holding_days = 999  # type: ignore[misc]