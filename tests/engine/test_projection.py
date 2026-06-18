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
from justfixed.engine.calendar import add_business_days
from justfixed.engine.curve import Curve, CurveVertex
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


# ---------- ipca_curve threading ----------


class TestIpcaCurveProjection:
    """project() ipca_curve parameter: market-implied breakeven in place of flat assumed."""

    _PURCHASE = date(2026, 1, 2)

    def _ipca_bullet(self, purchase: date, maturity: date, spread_pct: str = "5") -> Investment:
        return Investment.create(
            product=ProductType.CDB,
            issuer=Issuer.create("Banco Test", "Banco Test S.A.", IssuerKind.COMMERCIAL_BANK),
            principal=Money.from_reais("10000"),
            rate=PostFixedIPCA.from_percent(spread_pct),
            purchase_date=purchase,
            maturity_date=maturity,
        )

    def test_exact_gross_and_current_change_with_breakeven(self) -> None:
        # 252 biz days → exponent = 252/252 = 1 → exact Decimal arithmetic.
        # Baseline (assumed_ipca=0.04, spread=5%):
        #   effective = 0.04 + 0.05 + 0.04×0.05 = 0.0920
        #   gross = 10000 × 1.0920 = 10920.00
        # With ipca_curve breakeven=0.06 at maturity:
        #   effective = 0.06 + 0.05 + 0.06×0.05 = 0.1130
        #   gross = 10000 × 1.1130 = 11130.00
        purchase = self._PURCHASE
        maturity = add_business_days(purchase, 252)
        inv = self._ipca_bullet(purchase, maturity)

        result_flat = project(inv, as_of=maturity, assumed_ipca=Decimal("0.04"))
        assert result_flat.gross_at_maturity == Money.from_reais("10920")

        ipca_curve = Curve(
            anchor=purchase,
            vertices=(CurveVertex(business_days=252, rate=Decimal("0.06")),),
        )
        result_curve = project(inv, as_of=maturity, assumed_ipca=Decimal("0.04"), ipca_curve=ipca_curve)
        assert result_curve.gross_at_maturity == Money.from_reais("11130")
        assert result_curve.current_value == Money.from_reais("11130")
        assert result_curve.gross_at_maturity != result_flat.gross_at_maturity

    def test_two_bonds_pick_up_their_own_maturity_breakeven(self) -> None:
        # Short (252 biz): rate_at(maturity)=0.04 → effective=0.092 → gross=10920.00
        # Long (504 biz): rate_at(maturity)=0.08 → effective=0.134
        #   exponent=504/252=2 → gross=10000×1.134²=10000×1.285956=12859.56
        purchase = self._PURCHASE
        maturity_short = add_business_days(purchase, 252)
        maturity_long = add_business_days(purchase, 504)

        inv_short = self._ipca_bullet(purchase, maturity_short)
        inv_long = self._ipca_bullet(purchase, maturity_long)

        ipca_curve = Curve(
            anchor=purchase,
            vertices=(
                CurveVertex(business_days=252, rate=Decimal("0.04")),
                CurveVertex(business_days=504, rate=Decimal("0.08")),
            ),
        )

        proj_short = project(inv_short, as_of=maturity_long, assumed_ipca=Decimal("0.05"), ipca_curve=ipca_curve)
        proj_long = project(inv_long, as_of=maturity_long, assumed_ipca=Decimal("0.05"), ipca_curve=ipca_curve)

        assert proj_short.gross_at_maturity == Money.from_reais("10920")
        assert proj_long.gross_at_maturity == Money.from_reais("12859.56")
        assert proj_short.gross_at_maturity != proj_long.gross_at_maturity

    def test_fallback_when_ipca_curve_is_none(self) -> None:
        purchase = self._PURCHASE
        maturity = add_business_days(purchase, 252)
        inv = self._ipca_bullet(purchase, maturity)

        result_no_param = project(inv, as_of=maturity, assumed_ipca=Decimal("0.04"))
        result_explicit_none = project(inv, as_of=maturity, assumed_ipca=Decimal("0.04"), ipca_curve=None)
        assert result_explicit_none.gross_at_maturity == result_no_param.gross_at_maturity
        assert result_explicit_none.current_value == result_no_param.current_value

    def test_fallback_when_ipca_curve_has_empty_vertices(self) -> None:
        purchase = self._PURCHASE
        maturity = add_business_days(purchase, 252)
        inv = self._ipca_bullet(purchase, maturity)
        empty_curve = Curve(anchor=purchase, vertices=())

        result_flat = project(inv, as_of=maturity, assumed_ipca=Decimal("0.04"))
        result_empty = project(inv, as_of=maturity, assumed_ipca=Decimal("0.04"), ipca_curve=empty_curve)
        assert result_empty.gross_at_maturity == result_flat.gross_at_maturity

    def test_non_ipca_bond_unaffected_by_ipca_curve(self) -> None:
        purchase = self._PURCHASE
        maturity = add_business_days(purchase, 252)
        inv = Investment.create(
            product=ProductType.CDB,
            issuer=Issuer.create("Banco Test", "Banco Test S.A.", IssuerKind.COMMERCIAL_BANK),
            principal=Money.from_reais("10000"),
            rate=Prefixed.from_percent("12"),
            purchase_date=purchase,
            maturity_date=maturity,
        )
        ipca_curve = Curve(
            anchor=purchase,
            vertices=(CurveVertex(business_days=252, rate=Decimal("0.06")),),
        )
        result_no_curve = project(inv, as_of=maturity)
        result_with_curve = project(inv, as_of=maturity, assumed_ipca=Decimal("0.04"), ipca_curve=ipca_curve)
        assert result_with_curve.gross_at_maturity == result_no_curve.gross_at_maturity