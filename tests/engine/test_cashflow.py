"""Tests for the cash flow scheduling engine."""

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
from justfixed.engine.cashflow import (
    CashFlowKind,
    coupon_dates,
    schedule,
)
from justfixed.engine.curve import Curve, CurveVertex


# ---------- Fixtures ----------


def commercial_bank() -> Issuer:
    return Issuer.create(
        "Banco Inter", "Banco Inter S.A.", IssuerKind.COMMERCIAL_BANK
    )


def make_bullet_cdb(
    purchase: date = date(2024, 1, 15),
    maturity: date = date(2026, 1, 15),
    principal: str = "10000",
    rate_percent: str = "12",
) -> Investment:
    return Investment.create(
        product=ProductType.CDB,
        issuer=commercial_bank(),
        principal=Money.from_reais(principal),
        rate=Prefixed.from_percent(rate_percent),
        purchase_date=purchase,
        maturity_date=maturity,
    )


def make_semi_annual_tesouro(
    purchase: date = date(2024, 1, 15),
    maturity: date = date(2030, 1, 15),
) -> Investment:
    return Investment.create(
        product=ProductType.TESOURO_PREFIXADO,
        issuer=Issuer.treasury(),
        principal=Money.from_reais("10000"),
        rate=Prefixed.from_percent("11"),
        purchase_date=purchase,
        maturity_date=maturity,
        coupon_frequency=CouponFrequency.SEMI_ANNUAL,
    )


def make_monthly_cdb() -> Investment:
    return Investment.create(
        product=ProductType.CDB,
        issuer=commercial_bank(),
        principal=Money.from_reais("10000"),
        rate=Prefixed.from_percent("12"),
        purchase_date=date(2024, 1, 15),
        maturity_date=date(2024, 7, 15),  # 6 months
        coupon_frequency=CouponFrequency.MONTHLY,
    )


# ---------- coupon_dates ----------


class TestCouponDatesBullet:
    def test_bullet_has_no_coupon_dates(self) -> None:
        assert coupon_dates(make_bullet_cdb()) == []


class TestCouponDatesSemiAnnual:
    def test_six_year_bond_has_eleven_coupon_dates(self) -> None:
        # Maturity 2030-01-15, purchased 2024-01-15.
        # Coupons every 6 months, walking back from maturity:
        # 2029-07-15, 2029-01-15, 2028-07-15, 2028-01-15,
        # 2027-07-15, 2027-01-15, 2026-07-15, 2026-01-15,
        # 2025-07-15, 2025-01-15, 2024-07-15.
        # That's 11 dates (the maturity itself is not included).
        inv = make_semi_annual_tesouro()
        dates = coupon_dates(inv)
        assert len(dates) == 11

    def test_dates_are_chronological(self) -> None:
        inv = make_semi_annual_tesouro()
        dates = coupon_dates(inv)
        assert dates == sorted(dates)

    def test_first_coupon_six_months_after_purchase(self) -> None:
        # First coupon date should be roughly 2024-07-15 (or the next
        # business day if that's not one).
        inv = make_semi_annual_tesouro()
        dates = coupon_dates(inv)
        # July 15, 2024 was a Monday — a business day.
        assert dates[0] == date(2024, 7, 15)

    def test_last_coupon_strictly_before_maturity(self) -> None:
        inv = make_semi_annual_tesouro()
        dates = coupon_dates(inv)
        assert dates[-1] < inv.maturity_date

    def test_all_dates_strictly_between_purchase_and_maturity(self) -> None:
        inv = make_semi_annual_tesouro()
        dates = coupon_dates(inv)
        for d in dates:
            assert inv.purchase_date < d < inv.maturity_date


class TestCouponDatesMonthly:
    def test_six_month_monthly_cdb_has_five_coupons(self) -> None:
        # Purchased 2024-01-15, matures 2024-07-15. Monthly coupons.
        # Walking back: 2024-06-15, 2024-05-15, 2024-04-15,
        # 2024-03-15, 2024-02-15. Five dates.
        inv = make_monthly_cdb()
        dates = coupon_dates(inv)
        assert len(dates) == 5

    def test_business_day_rolling(self) -> None:
        # Choose an investment whose monthly coupon would naturally fall
        # on a weekend/holiday and verify it rolls forward.
        # Purchase 2024-01-15, maturity 2024-07-15 monthly.
        # Coupon at "2024-03-15" — was a Friday, business day, no roll.
        # Coupon at "2024-06-15" — was a Saturday, should roll to Mon Jun 17.
        inv = make_monthly_cdb()
        dates = coupon_dates(inv)
        # Find the date around mid-June.
        june_coupon = [d for d in dates if d.month == 6]
        assert len(june_coupon) == 1
        # June 15, 2024 was a Saturday → expect Monday June 17.
        assert june_coupon[0] == date(2024, 6, 17)


# ---------- schedule: bullet products ----------


class TestScheduleBullet:
    def test_one_year_bullet_single_cashflow_at_maturity(self) -> None:
        inv = make_bullet_cdb(
            purchase=date(2024, 1, 15),
            maturity=date(2025, 1, 15),
        )
        flows = schedule(inv)
        assert len(flows) == 1
        flow = flows[0]
        assert flow.date == date(2025, 1, 15)
        assert flow.kind == CashFlowKind.PRINCIPAL

    def test_bullet_amount_matches_accrual(self) -> None:
        # 10000 at Prefixed 12% over 253 business days.
        # 10000 × (1.12)^(253/252) = 11205.04 (verified empirically).
        inv = make_bullet_cdb(
            purchase=date(2024, 1, 15),
            maturity=date(2025, 1, 15),
        )
        flows = schedule(inv)
        # Within 5 cents — Decimal precision is exact, this absorbs
        # any future quantize-on-display differences.
        assert abs(flows[0].amount.amount - Decimal("11205.04")) < Decimal("0.05")


# ---------- schedule: coupon-paying products ----------


class TestScheduleSemiAnnual:
    def test_count_equals_coupons_plus_one(self) -> None:
        # 11 coupons + 1 final payment = 12 cash flows.
        inv = make_semi_annual_tesouro()
        flows = schedule(inv)
        assert len(flows) == 12

    def test_final_flow_is_combined(self) -> None:
        inv = make_semi_annual_tesouro()
        flows = schedule(inv)
        assert flows[-1].kind == CashFlowKind.COUPON_AND_PRINCIPAL
        assert flows[-1].date == inv.maturity_date

    def test_intermediate_flows_are_coupons(self) -> None:
        inv = make_semi_annual_tesouro()
        flows = schedule(inv)
        for flow in flows[:-1]:
            assert flow.kind == CashFlowKind.COUPON

    def test_dates_are_chronological(self) -> None:
        inv = make_semi_annual_tesouro()
        flows = schedule(inv)
        dates = [f.date for f in flows]
        assert dates == sorted(dates)

    def test_final_flow_includes_principal(self) -> None:
        # Final payment > a typical mid-life coupon (it includes principal).
        inv = make_semi_annual_tesouro()
        flows = schedule(inv)
        first_coupon = flows[0].amount
        final = flows[-1].amount
        assert final > first_coupon
        # Final should be roughly principal + a coupon.
        assert final > inv.principal


class TestScheduleMonthly:
    def test_six_flows_for_six_month_monthly_cdb(self) -> None:
        # 5 coupons + 1 final = 6 flows.
        inv = make_monthly_cdb()
        flows = schedule(inv)
        assert len(flows) == 6

    def test_final_flow_includes_principal(self) -> None:
        inv = make_monthly_cdb()
        flows = schedule(inv)
        assert flows[-1].kind == CashFlowKind.COUPON_AND_PRINCIPAL


# ---------- schedule: post-fixed rate parameter handling ----------


class TestScheduleWithPostFixedRates:
    def test_post_fixed_cdi_uses_assumed_cdi(self) -> None:
        inv = Investment.create(
            product=ProductType.CDB,
            issuer=commercial_bank(),
            principal=Money.from_reais("10000"),
            rate=PostFixedCDI.from_percent("110"),
            purchase_date=date(2024, 1, 15),
            maturity_date=date(2025, 1, 15),
        )
        flows = schedule(inv, assumed_cdi=Decimal("0.12"))
        assert len(flows) == 1
        # 110% of 12% = 13.2% effective. Over 253 du (one bizday more
        # than a 252-du year), 10000 × (1.132)^(253/252) = 11325.57.
        assert abs(flows[0].amount.amount - Decimal("11325.57")) < Decimal("0.05")

    def test_post_fixed_ipca_uses_assumed_ipca(self) -> None:
        inv = Investment.create(
            product=ProductType.TESOURO_IPCA,
            issuer=Issuer.treasury(),
            principal=Money.from_reais("10000"),
            rate=PostFixedIPCA.from_percent("5.5"),
            purchase_date=date(2024, 1, 15),
            maturity_date=date(2025, 1, 15),
        )
        flows = schedule(inv, assumed_ipca=Decimal("0.04"))
        assert len(flows) == 1
        # Fisher: 0.04 + 0.055 + 0.04*0.055 ≈ 0.0972. ~10972.
        assert abs(flows[0].amount.amount - Decimal("10972")) < Decimal("10")

    def test_missing_assumption_raises(self) -> None:
        inv = Investment.create(
            product=ProductType.CDB,
            issuer=commercial_bank(),
            principal=Money.from_reais("10000"),
            rate=PostFixedCDI.from_percent("110"),
            purchase_date=date(2024, 1, 15),
            maturity_date=date(2025, 1, 15),
        )
        with pytest.raises(ValueError, match="assumed_cdi"):
            schedule(inv)


# ---------- Realistic scenario: Tesouro Prefixado 2030 ----------


class TestRealisticScenarios:
    def test_tesouro_prefixado_2030_with_coupons(self) -> None:
        # 6-year Tesouro Prefixado with juros semestrais at 11% per year.
        # Purchased 2024-01-15, matures 2030-01-15.
        # 11 coupons + final payment.
        inv = make_semi_annual_tesouro()
        flows = schedule(inv)

        # Total cash returned = 11 coupons + final (which includes principal).
        total = sum(
            (f.amount for f in flows),
            start=Money.zero(),
        )
        # Sanity: total should be MORE than principal (we earned interest)
        # and LESS than what a bullet would pay (because coupons stop
        # compounding once paid out).
        bullet = make_bullet_cdb(
            purchase=date(2024, 1, 15),
            maturity=date(2030, 1, 15),
            principal="10000",
            rate_percent="11",
        )
        bullet_flows = schedule(bullet)
        bullet_total = bullet_flows[0].amount

        assert inv.principal < total < bullet_total


# ---------- ipca_curve threading ----------


class TestIpcaCurveSchedule:
    """schedule() ipca_curve: all accrual uses rate_at(maturity), not rate_at(coupon_date)."""

    _PURCHASE = date(2026, 1, 2)

    def _semi_annual_ipca_cdb(self, purchase: date, maturity: date) -> Investment:
        return Investment.create(
            product=ProductType.CDB,
            issuer=commercial_bank(),
            principal=Money.from_reais("10000"),
            rate=PostFixedIPCA.from_percent("5"),
            purchase_date=purchase,
            maturity_date=maturity,
            coupon_frequency=CouponFrequency.SEMI_ANNUAL,
        )

    def test_coupon_uses_maturity_rate_not_coupon_date_rate(self) -> None:
        # Bond: ~1.5-year CDB IPCA+ semi-annual, 378 biz days to maturity.
        # Breakeven curve:
        #   bd < 252 → flat at 0.02 (all coupon dates fall here)
        #   bd = 378 → 0.06 (maturity, flat-extension to the right)
        # Correct: ALL accrue calls use rate_at(maturity)=0.06.
        # Wrong: coupon dates would give 0.02; final period gives 0.06 by coincidence.
        # Test: flows match schedule(flat_assumed=0.06), NOT schedule(flat_assumed=0.02).
        purchase = self._PURCHASE
        maturity = add_business_days(purchase, 378)
        inv = self._semi_annual_ipca_cdb(purchase, maturity)

        ipca_curve = Curve(
            anchor=purchase,
            vertices=(
                CurveVertex(business_days=252, rate=Decimal("0.02")),
                CurveVertex(business_days=378, rate=Decimal("0.06")),
            ),
        )

        first_coupon_date = coupon_dates(inv)[0]
        rate_at_maturity = ipca_curve.rate_at(inv.maturity_date)
        rate_at_first_coupon = ipca_curve.rate_at(first_coupon_date)

        # Verify test setup: the two rates must differ for the test to be meaningful.
        assert rate_at_maturity != rate_at_first_coupon

        flows_actual = schedule(inv, assumed_ipca=Decimal("0.04"), ipca_curve=ipca_curve)
        # Reference: flat assumed = maturity breakeven (what every flow should use)
        flows_maturity_rate = schedule(inv, assumed_ipca=rate_at_maturity)
        # Counter-reference: flat assumed = coupon-date breakeven (wrong path)
        flows_coupon_rate = schedule(inv, assumed_ipca=rate_at_first_coupon)

        # Every cash flow matches the maturity-rate reference.
        assert len(flows_actual) == len(flows_maturity_rate)
        for fa, fm in zip(flows_actual, flows_maturity_rate):
            assert fa.amount == fm.amount, (
                f"{fa.kind}: {fa.amount} != {fm.amount} (expected maturity rate)"
            )

        # First intermediate coupon must differ from what the coupon-date rate would give.
        # This proves the implementation uses rate_at(maturity), not rate_at(coupon_date).
        intermediate = [(fa, fc) for fa, fc in zip(flows_actual, flows_coupon_rate)
                        if fa.kind == CashFlowKind.COUPON]
        assert len(intermediate) > 0, "Test requires at least one intermediate coupon"
        first_actual, first_coupon_wrong = intermediate[0]
        assert first_actual.amount != first_coupon_wrong.amount

    def test_bullet_ipca_curve_exact_value(self) -> None:
        # Bullet, 252 biz days, spread=5%, breakeven at maturity=0.06.
        # effective=0.113, gross=10000×1.1130=11130.00 (exact, exponent=1).
        purchase = self._PURCHASE
        maturity = add_business_days(purchase, 252)
        inv = Investment.create(
            product=ProductType.CDB,
            issuer=commercial_bank(),
            principal=Money.from_reais("10000"),
            rate=PostFixedIPCA.from_percent("5"),
            purchase_date=purchase,
            maturity_date=maturity,
        )
        ipca_curve = Curve(
            anchor=purchase,
            vertices=(CurveVertex(business_days=252, rate=Decimal("0.06")),),
        )
        flows = schedule(inv, assumed_ipca=Decimal("0.04"), ipca_curve=ipca_curve)
        assert len(flows) == 1
        assert flows[0].amount == Money.from_reais("11130")

    def test_fallback_when_ipca_curve_is_none(self) -> None:
        purchase = self._PURCHASE
        maturity = add_business_days(purchase, 252)
        inv = Investment.create(
            product=ProductType.CDB,
            issuer=commercial_bank(),
            principal=Money.from_reais("10000"),
            rate=PostFixedIPCA.from_percent("5"),
            purchase_date=purchase,
            maturity_date=maturity,
        )
        flows_no_param = schedule(inv, assumed_ipca=Decimal("0.04"))
        flows_none = schedule(inv, assumed_ipca=Decimal("0.04"), ipca_curve=None)
        assert flows_none[0].amount == flows_no_param[0].amount

    def test_fallback_when_ipca_curve_empty_vertices(self) -> None:
        purchase = self._PURCHASE
        maturity = add_business_days(purchase, 252)
        inv = Investment.create(
            product=ProductType.CDB,
            issuer=commercial_bank(),
            principal=Money.from_reais("10000"),
            rate=PostFixedIPCA.from_percent("5"),
            purchase_date=purchase,
            maturity_date=maturity,
        )
        empty_curve = Curve(anchor=purchase, vertices=())
        flows_flat = schedule(inv, assumed_ipca=Decimal("0.04"))
        flows_empty = schedule(inv, assumed_ipca=Decimal("0.04"), ipca_curve=empty_curve)
        assert flows_empty[0].amount == flows_flat[0].amount