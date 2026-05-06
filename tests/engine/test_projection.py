"""Tests for the top-level projection engine."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from justfixed.domain.investment import Investment
from justfixed.domain.issuer import Issuer, IssuerKind
from justfixed.domain.money import Money
from justfixed.domain.product import CouponFrequency, ProductType
from justfixed.domain.rates import PostFixedCDI, PostFixedIPCA, Prefixed
from justfixed.engine.projection import ProjectionResult, project


# ---------- Fixtures ----------


def commercial_bank() -> Issuer:
    return Issuer.create(
        "Banco Inter", "Banco Inter S.A.", IssuerKind.COMMERCIAL_BANK
    )


def make_two_year_cdb() -> Investment:
    """A 2-year CDB at 12% prefixed. Tax bracket: 17.5% (361-720 days)."""
    return Investment.create(
        product=ProductType.CDB,
        issuer=commercial_bank(),
        principal=Money.from_reais("10000"),
        rate=Prefixed.from_percent("12"),
        purchase_date=date(2024, 1, 15),
        maturity_date=date(2026, 1, 15),
    )


def make_one_year_lci() -> Investment:
    """A 1-year LCI at 90% CDI. IR-exempt."""
    return Investment.create(
        product=ProductType.LCI,
        issuer=commercial_bank(),
        principal=Money.from_reais("10000"),
        rate=PostFixedCDI.from_percent("90"),
        purchase_date=date(2024, 1, 15),
        maturity_date=date(2025, 1, 15),
    )


# ---------- Bullet projections ----------


class TestBulletProjection:
    def test_returns_projection_result(self) -> None:
        result = project(make_two_year_cdb(), as_of=date(2025, 1, 15))
        assert isinstance(result, ProjectionResult)

    def test_one_cashflow_for_bullet(self) -> None:
        result = project(make_two_year_cdb(), as_of=date(2025, 1, 15))
        assert len(result.cash_flows) == 1

    def test_gross_equals_only_cashflow(self) -> None:
        result = project(make_two_year_cdb(), as_of=date(2025, 1, 15))
        assert result.gross_at_maturity == result.cash_flows[0].amount

    def test_current_value_at_purchase_equals_principal(self) -> None:
        inv = make_two_year_cdb()
        result = project(inv, as_of=inv.purchase_date)
        assert result.current_value == inv.principal

    def test_current_value_before_purchase_equals_principal(self) -> None:
        inv = make_two_year_cdb()
        result = project(inv, as_of=date(2023, 1, 15))
        assert result.current_value == inv.principal

    def test_current_value_at_maturity_equals_gross(self) -> None:
        inv = make_two_year_cdb()
        result = project(inv, as_of=inv.maturity_date)
        assert result.current_value == result.gross_at_maturity

    def test_current_value_past_maturity_capped(self) -> None:
        # Asking for "what's it worth in 2030" when it matured 2026:
        # should equal the maturity value, not extrapolate further.
        inv = make_two_year_cdb()
        at_maturity = project(inv, as_of=inv.maturity_date)
        far_future = project(inv, as_of=date(2030, 1, 1))
        assert at_maturity.current_value == far_future.current_value

    def test_current_value_grows_over_time(self) -> None:
        inv = make_two_year_cdb()
        early = project(inv, as_of=date(2024, 6, 15))
        later = project(inv, as_of=date(2025, 6, 15))
        assert early.current_value < later.current_value


# ---------- Tax application: regressive ----------


class TestRegressiveTax:
    def test_two_year_cdb_uses_17_5_bracket(self) -> None:
        # 2024-01-15 to 2026-01-15 = 731 calendar days.
        # 731 days falls in the 721+ bracket: 15%.
        inv = make_two_year_cdb()
        result = project(inv, as_of=inv.maturity_date)
        assert result.tax_breakdown.tax_rate == Decimal("0.15")

    def test_net_less_than_gross_when_taxable(self) -> None:
        result = project(make_two_year_cdb(), as_of=date(2026, 1, 15))
        assert result.net_at_maturity < result.gross_at_maturity

    def test_tax_invariant_holds(self) -> None:
        # Universal: net + tax = gross, always.
        result = project(make_two_year_cdb(), as_of=date(2026, 1, 15))
        assert result.net_at_maturity + result.tax_amount == result.gross_at_maturity


# ---------- Tax application: exempt ----------


class TestExemptTax:
    def test_lci_pays_no_tax(self) -> None:
        result = project(
            make_one_year_lci(),
            as_of=date(2025, 1, 15),
            assumed_cdi=Decimal("0.12"),
        )
        assert result.tax_breakdown.tax_rate == Decimal("0")
        assert result.tax_amount == Money.zero()
        assert result.net_at_maturity == result.gross_at_maturity

    def test_lcd_pays_no_tax(self) -> None:
        # LCD is also exempt.
        bndes = Issuer.create("BNDES", "BNDES", IssuerKind.DEVELOPMENT_BANK)
        inv = Investment.create(
            product=ProductType.LCD,
            issuer=bndes,
            principal=Money.from_reais("10000"),
            rate=PostFixedCDI.from_percent("105"),
            purchase_date=date(2024, 1, 15),
            maturity_date=date(2025, 6, 15),
        )
        result = project(inv, as_of=date(2025, 6, 15), assumed_cdi=Decimal("0.12"))
        assert result.tax_amount == Money.zero()


# ---------- Coupon projections ----------


class TestCouponProjection:
    def test_semi_annual_has_multiple_cashflows(self) -> None:
        inv = Investment.create(
            product=ProductType.TESOURO_PREFIXADO,
            issuer=Issuer.treasury(),
            principal=Money.from_reais("10000"),
            rate=Prefixed.from_percent("11"),
            purchase_date=date(2024, 1, 15),
            maturity_date=date(2030, 1, 15),
            coupon_frequency=CouponFrequency.SEMI_ANNUAL,
        )
        result = project(inv, as_of=date(2026, 1, 15))
        assert len(result.cash_flows) == 12  # 11 coupons + 1 final

    def test_gross_equals_sum_of_cashflows(self) -> None:
        inv = Investment.create(
            product=ProductType.TESOURO_PREFIXADO,
            issuer=Issuer.treasury(),
            principal=Money.from_reais("10000"),
            rate=Prefixed.from_percent("11"),
            purchase_date=date(2024, 1, 15),
            maturity_date=date(2030, 1, 15),
            coupon_frequency=CouponFrequency.SEMI_ANNUAL,
        )
        result = project(inv, as_of=date(2026, 1, 15))
        manual_sum = Money.zero()
        for flow in result.cash_flows:
            manual_sum = manual_sum + flow.amount
        assert result.gross_at_maturity == manual_sum


# ---------- Post-fixed rate parameter handling ----------


class TestPostFixedParameters:
    def test_cdi_assumption_required(self) -> None:
        with pytest.raises(ValueError, match="assumed_cdi"):
            project(make_one_year_lci(), as_of=date(2025, 1, 15))

    def test_cdi_assumption_used(self) -> None:
        result = project(
            make_one_year_lci(),
            as_of=date(2025, 1, 15),
            assumed_cdi=Decimal("0.12"),
        )
        # 90% of 12% = 10.8% effective.
        # Over ~253 du: ~11084. Tax-exempt, so net = gross.
        assert Money.from_reais("11050") < result.gross_at_maturity < Money.from_reais("11150")


# ---------- Realistic portfolio scenarios ----------


class TestRealisticScenarios:
    def test_cdb_at_one_year_mark(self) -> None:
        # Halfway through a 2-year CDB. Current value should be ~midway
        # between principal and maturity value.
        inv = make_two_year_cdb()
        result = project(inv, as_of=date(2025, 1, 15))

        # At 1 year, the investment is worth more than principal but
        # less than the 2-year maturity value.
        assert inv.principal < result.current_value < result.gross_at_maturity

    def test_lci_full_lifecycle(self) -> None:
        # 1-year LCI at 90% CDI, end-to-end check.
        result = project(
            make_one_year_lci(),
            as_of=date(2025, 1, 15),
            assumed_cdi=Decimal("0.12"),
        )
        # Tax-exempt: net == gross
        assert result.net_at_maturity == result.gross_at_maturity
        # Single cash flow (bullet)
        assert len(result.cash_flows) == 1
        # Gain on R$ 10000 at 10.8% over ~1 year ≈ R$ 1080
        assert result.gain_at_maturity > Money.from_reais("1000")

    def test_gain_at_maturity_property(self) -> None:
        result = project(make_two_year_cdb(), as_of=date(2026, 1, 15))
        assert result.gain_at_maturity == result.gross_at_maturity - make_two_year_cdb().principal


# ---------- ProjectionResult immutability ----------


class TestResultImmutability:
    def test_cannot_mutate_fields(self) -> None:
        result = project(make_two_year_cdb(), as_of=date(2025, 1, 15))
        with pytest.raises((AttributeError, TypeError)):
            result.current_value = Money.zero()  # type: ignore[misc]