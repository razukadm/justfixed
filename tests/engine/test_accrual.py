"""Tests for the accrual engine."""

from __future__ import annotations

from decimal import Decimal

import pytest

from justfixed.domain.money import Money
from justfixed.domain.rates import PostFixedCDI, PostFixedIPCA, Prefixed
from justfixed.engine.accrual import accrue


# Tolerance for floating-point-style comparisons. We work in Decimal
# but exponentiation introduces small precision artifacts; 1 cent on
# R$ 10000 (i.e. 0.0001) is plenty tight for our purposes.
TOLERANCE = Decimal("0.01")


def assert_close(actual: Money, expected: Money, tolerance: Decimal = TOLERANCE) -> None:
    """Assert two Money values are equal to within `tolerance`."""
    diff = abs(actual.amount - expected.amount)
    assert diff <= tolerance, (
        f"{actual.to_display()} != {expected.to_display()} "
        f"(diff {diff} > tolerance {tolerance})"
    )


# ---------- Prefixed ----------


class TestPrefixedAccrual:
    def test_one_full_year_at_twelve_percent(self) -> None:
        # 252 business days = exactly 1 year of basis math.
        # 10000 × (1.12)^(252/252) = 10000 × 1.12 = 11200.
        result = accrue(
            Money.from_reais("10000"),
            Prefixed.from_percent("12"),
            252,
        )
        assert_close(result, Money.from_reais("11200"))

    def test_zero_business_days_returns_principal(self) -> None:
        result = accrue(
            Money.from_reais("10000"),
            Prefixed.from_percent("12"),
            0,
        )
        assert result == Money.from_reais("10000")

    def test_half_year_at_ten_percent(self) -> None:
        # 126 business days = 0.5 year. (1.10)^0.5 ≈ 1.04881.
        # 10000 × 1.04881 ≈ 10488.09.
        result = accrue(
            Money.from_reais("10000"),
            Prefixed.from_percent("10"),
            126,
        )
        assert_close(result, Money.from_reais("10488.09"))

    def test_two_years_at_eight_percent(self) -> None:
        # 504 business days = 2 years. (1.08)^2 = 1.1664.
        # 10000 × 1.1664 = 11664.
        result = accrue(
            Money.from_reais("10000"),
            Prefixed.from_percent("8"),
            504,
        )
        assert_close(result, Money.from_reais("11664"))

    def test_zero_rate_preserves_principal(self) -> None:
        # Edge: a 0% rate (rare but possible).
        result = accrue(
            Money.from_reais("10000"),
            Prefixed(Decimal("0")),
            252,
        )
        assert_close(result, Money.from_reais("10000"))

    def test_negative_business_days_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            accrue(
                Money.from_reais("10000"),
                Prefixed.from_percent("12"),
                -1,
            )


# ---------- PostFixedCDI ----------


class TestPostFixedCDIAccrual:
    def test_one_year_at_100_percent_of_cdi(self) -> None:
        # 100% of CDI, with CDI assumed 12%. Effective rate: 12%.
        # 252 business days: 10000 × 1.12 = 11200.
        result = accrue(
            Money.from_reais("10000"),
            PostFixedCDI.from_percent("100"),
            252,
            assumed_cdi=Decimal("0.12"),
        )
        assert_close(result, Money.from_reais("11200"))

    def test_one_year_at_110_percent_of_cdi(self) -> None:
        # 110% of CDI, CDI = 12%. Effective rate: 13.2%.
        # 10000 × 1.132 = 11320.
        result = accrue(
            Money.from_reais("10000"),
            PostFixedCDI.from_percent("110"),
            252,
            assumed_cdi=Decimal("0.12"),
        )
        assert_close(result, Money.from_reais("11320"))

    def test_one_year_at_85_percent_of_cdi(self) -> None:
        # 85% of CDI, CDI = 12%. Effective rate: 10.2%.
        # Common for LCI/LCA where the lower yield is offset by tax exemption.
        result = accrue(
            Money.from_reais("10000"),
            PostFixedCDI.from_percent("85"),
            252,
            assumed_cdi=Decimal("0.12"),
        )
        assert_close(result, Money.from_reais("11020"))

    def test_missing_assumed_cdi_raises(self) -> None:
        with pytest.raises(ValueError, match="assumed_cdi"):
            accrue(
                Money.from_reais("10000"),
                PostFixedCDI.from_percent("100"),
                252,
                # assumed_cdi not provided
            )


# ---------- PostFixedIPCA ----------


class TestPostFixedIPCAAccrual:
    def test_one_year_ipca_plus_spread(self) -> None:
        # IPCA + 5%, with IPCA = 4%.
        # Effective rate: 0.04 + 0.05 + 0.04*0.05 = 0.092 (9.2%).
        # 10000 × 1.092 = 10920.
        result = accrue(
            Money.from_reais("10000"),
            PostFixedIPCA.from_percent("5"),
            252,
            assumed_ipca=Decimal("0.04"),
        )
        assert_close(result, Money.from_reais("10920"))

    def test_zero_spread_pure_inflation(self) -> None:
        # IPCA + 0% means the bond just tracks inflation.
        # 10000 × 1.04 = 10400.
        result = accrue(
            Money.from_reais("10000"),
            PostFixedIPCA.from_percent("0"),
            252,
            assumed_ipca=Decimal("0.04"),
        )
        assert_close(result, Money.from_reais("10400"))

    def test_zero_ipca_just_spread(self) -> None:
        # In a no-inflation world, IPCA + 5% behaves like Prefixed 5%.
        # 10000 × 1.05 = 10500.
        result = accrue(
            Money.from_reais("10000"),
            PostFixedIPCA.from_percent("5"),
            252,
            assumed_ipca=Decimal("0"),
        )
        assert_close(result, Money.from_reais("10500"))

    def test_missing_assumed_ipca_raises(self) -> None:
        with pytest.raises(ValueError, match="assumed_ipca"):
            accrue(
                Money.from_reais("10000"),
                PostFixedIPCA.from_percent("5"),
                252,
            )


# ---------- Currency preservation ----------


class TestCurrencyPreserved:
    def test_brl_in_brl_out(self) -> None:
        result = accrue(
            Money.from_reais("10000", currency="BRL"),
            Prefixed.from_percent("10"),
            252,
        )
        assert result.currency == "BRL"

    def test_usd_in_usd_out(self) -> None:
        # We don't actively support USD investments, but the engine
        # is currency-agnostic: rate math is the same.
        result = accrue(
            Money.from_reais("10000", currency="USD"),
            Prefixed.from_percent("10"),
            252,
        )
        assert result.currency == "USD"


# ---------- Realistic Brazilian portfolio scenarios ----------


class TestRealisticScenarios:
    """End-to-end accrual scenarios across a 1-year holding period (252 du)."""

    def test_typical_cdb(self) -> None:
        # A typical retail CDB at 110% of CDI, 1 year, CDI = 12%.
        result = accrue(
            Money.from_reais("50000"),
            PostFixedCDI.from_percent("110"),
            252,
            assumed_cdi=Decimal("0.12"),
        )
        # 50000 × 1.132 = 56600.
        assert_close(result, Money.from_reais("56600"))

    def test_typical_lci(self) -> None:
        # A typical LCI at 90% of CDI, 1 year, CDI = 12%.
        # Lower headline rate but tax-exempt — net yield often beats CDB.
        result = accrue(
            Money.from_reais("50000"),
            PostFixedCDI.from_percent("90"),
            252,
            assumed_cdi=Decimal("0.12"),
        )
        # 50000 × 1.108 = 55400.
        assert_close(result, Money.from_reais("55400"))

    def test_typical_tesouro_ipca_2035(self) -> None:
        # A long-dated Tesouro IPCA+ at IPCA + 5.75%, with IPCA = 4.5%.
        # 252 business days only (1-year snapshot).
        # Effective: 0.045 + 0.0575 + 0.045*0.0575 = 0.1051 (10.51%).
        result = accrue(
            Money.from_reais("100000"),
            PostFixedIPCA.from_percent("5.75"),
            252,
            assumed_ipca=Decimal("0.045"),
        )
        # 100000 × 1.10509 = 110508.75.
        assert_close(result, Money.from_reais("110508.75"))


# ---------- Multi-period composition ----------


class TestComposition:
    """Accruing over a long period should equal the same rate over sub-periods."""

    def test_full_year_equals_two_half_years(self) -> None:
        """Compounding consistency: f(1 year) == f(half) ∘ f(half)."""
        principal = Money.from_reais("10000")
        rate = Prefixed.from_percent("12")

        full = accrue(principal, rate, 252)

        # Two halves of 126 business days each.
        half1 = accrue(principal, rate, 126)
        composed = accrue(half1, rate, 126)

        # Should match within tolerance.
        assert_close(full, composed, tolerance=Decimal("0.01"))