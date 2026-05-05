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
from justfixed.engine.cashflow import (
    CashFlowKind,
    coupon_dates,
    schedule,
)


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