"""Tests for the IR tax engine."""

from __future__ import annotations

from decimal import Decimal

import pytest

from justfixed.domain.money import Money
from justfixed.domain.product import TaxTreatment
from justfixed.engine.tax import compute_ir, regressive_rate_for


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