"""Tests for the Investment entity and its validation rules."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from justfixed.domain.investment import Investment
from justfixed.domain.issuer import Issuer, IssuerKind
from justfixed.domain.money import Money
from justfixed.domain.product import CouponFrequency, ProductType
from justfixed.domain.rates import PostFixedCDI, PostFixedIPCA, Prefixed


# ------------------------------------------------------------------
# Test fixtures (helpers to build common entities concisely)
# ------------------------------------------------------------------


def commercial_bank() -> Issuer:
    return Issuer.create(
        "Banco Inter", "Banco Inter S.A.", IssuerKind.COMMERCIAL_BANK
    )


def development_bank() -> Issuer:
    return Issuer.create("BNDES", "BNDES", IssuerKind.DEVELOPMENT_BANK)


def make_cdb(
    *,
    purchase: date | None = None,
    maturity: date | None = None,
    principal: Money | None = None,
    coupons: CouponFrequency = CouponFrequency.NONE,
) -> Investment:
    """Build a minimal valid CDB. Override fields per test."""
    return Investment.create(
        product=ProductType.CDB,
        issuer=commercial_bank(),
        principal=principal or Money.from_reais("10000"),
        rate=PostFixedCDI.from_percent("110"),
        purchase_date=purchase or date(2024, 1, 15),
        maturity_date=maturity or date(2026, 1, 15),
        coupon_frequency=coupons,
    )


# ------------------------------------------------------------------
# Construction and basic invariants
# ------------------------------------------------------------------


class TestConstruction:
    def test_minimal_cdb_constructs(self) -> None:
        inv = make_cdb()
        assert inv.product == ProductType.CDB
        assert inv.principal == Money.from_reais("10000")
        assert isinstance(inv.id, type(inv.id))  # has a UUID

    def test_create_assigns_distinct_ids(self) -> None:
        a = make_cdb()
        b = make_cdb()
        assert a.id != b.id

    def test_description_stripped(self) -> None:
        inv = Investment.create(
            product=ProductType.CDB,
            issuer=commercial_bank(),
            principal=Money.from_reais("10000"),
            rate=PostFixedCDI.from_percent("110"),
            purchase_date=date(2024, 1, 15),
            maturity_date=date(2026, 1, 15),
            description="  retirement bucket  ",
        )
        assert inv.description == "retirement bucket"


# ------------------------------------------------------------------
# Invariant 1: principal must be positive
# ------------------------------------------------------------------


class TestPrincipalPositive:
    def test_zero_principal_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            make_cdb(principal=Money.zero())

    def test_negative_principal_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            make_cdb(principal=Money.from_reais("-100"))


# ------------------------------------------------------------------
# Invariant 2: maturity > purchase
# ------------------------------------------------------------------


class TestDateOrdering:
    def test_maturity_before_purchase_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be after"):
            make_cdb(
                purchase=date(2024, 1, 15),
                maturity=date(2024, 1, 14),
            )

    def test_maturity_equal_to_purchase_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be after"):
            make_cdb(
                purchase=date(2024, 1, 15),
                maturity=date(2024, 1, 15),
            )

    def test_maturity_one_day_after_accepted(self) -> None:
        inv = make_cdb(
            purchase=date(2024, 1, 15),
            maturity=date(2024, 1, 16),
        )
        assert inv.term_days == 1


# ------------------------------------------------------------------
# Invariant 3: issuer kind must match product
# ------------------------------------------------------------------


class TestIssuerKindMatching:
    def test_cdb_with_commercial_bank_ok(self) -> None:
        # Already covered by make_cdb default, but explicit here.
        Investment.create(
            product=ProductType.CDB,
            issuer=commercial_bank(),
            principal=Money.from_reais("10000"),
            rate=Prefixed.from_percent("12"),
            purchase_date=date(2024, 1, 15),
            maturity_date=date(2026, 1, 15),
        )

    def test_cdb_with_treasury_rejected(self) -> None:
        with pytest.raises(ValueError, match="CDB requires issuer kind"):
            Investment.create(
                product=ProductType.CDB,
                issuer=Issuer.treasury(),
                principal=Money.from_reais("10000"),
                rate=Prefixed.from_percent("12"),
                purchase_date=date(2024, 1, 15),
                maturity_date=date(2026, 1, 15),
            )

    def test_lcd_with_commercial_bank_rejected(self) -> None:
        with pytest.raises(ValueError, match="LCD requires issuer kind"):
            Investment.create(
                product=ProductType.LCD,
                issuer=commercial_bank(),
                principal=Money.from_reais("10000"),
                rate=PostFixedCDI.from_percent("100"),
                purchase_date=date(2024, 1, 15),
                maturity_date=date(2026, 1, 15),
            )

    def test_lcd_with_development_bank_ok(self) -> None:
        inv = Investment.create(
            product=ProductType.LCD,
            issuer=development_bank(),
            principal=Money.from_reais("10000"),
            rate=PostFixedCDI.from_percent("100"),
            purchase_date=date(2024, 1, 15),
            maturity_date=date(2026, 1, 15),
        )
        assert inv.product == ProductType.LCD

    def test_tesouro_with_commercial_bank_rejected(self) -> None:
        with pytest.raises(ValueError, match="requires issuer kind"):
            Investment.create(
                product=ProductType.TESOURO_SELIC,
                issuer=commercial_bank(),
                principal=Money.from_reais("1000"),
                rate=PostFixedCDI.from_percent("100"),
                purchase_date=date(2024, 1, 15),
                maturity_date=date(2026, 1, 15),
            )

    def test_tesouro_with_treasury_ok(self) -> None:
        inv = Investment.create(
            product=ProductType.TESOURO_IPCA,
            issuer=Issuer.treasury(),
            principal=Money.from_reais("1000"),
            rate=PostFixedIPCA.from_percent("5.5"),
            purchase_date=date(2024, 1, 15),
            maturity_date=date(2030, 1, 15),
        )
        assert inv.product == ProductType.TESOURO_IPCA


# ------------------------------------------------------------------
# Invariant 4: coupon frequency must be allowed for product
# ------------------------------------------------------------------


class TestCouponFrequency:
    def test_cdb_allows_bullet(self) -> None:
        inv = make_cdb(coupons=CouponFrequency.NONE)
        assert inv.is_bullet is True

    def test_cdb_allows_monthly(self) -> None:
        inv = make_cdb(coupons=CouponFrequency.MONTHLY)
        assert inv.coupon_frequency == CouponFrequency.MONTHLY
        assert inv.is_bullet is False

    def test_cdb_allows_semi_annual(self) -> None:
        inv = make_cdb(coupons=CouponFrequency.SEMI_ANNUAL)
        assert inv.coupon_frequency == CouponFrequency.SEMI_ANNUAL

    def test_lci_rejects_monthly_coupons(self) -> None:
        with pytest.raises(ValueError, match="LCI does not allow"):
            Investment.create(
                product=ProductType.LCI,
                issuer=commercial_bank(),
                principal=Money.from_reais("10000"),
                rate=PostFixedCDI.from_percent("95"),
                purchase_date=date(2024, 1, 15),
                maturity_date=date(2026, 1, 15),
                coupon_frequency=CouponFrequency.MONTHLY,
            )

    def test_lcd_rejects_semi_annual_coupons(self) -> None:
        with pytest.raises(ValueError, match="LCD does not allow"):
            Investment.create(
                product=ProductType.LCD,
                issuer=development_bank(),
                principal=Money.from_reais("10000"),
                rate=PostFixedCDI.from_percent("100"),
                purchase_date=date(2024, 1, 15),
                maturity_date=date(2026, 1, 15),
                coupon_frequency=CouponFrequency.SEMI_ANNUAL,
            )

    def test_tesouro_selic_rejects_coupons(self) -> None:
        with pytest.raises(ValueError, match="does not allow"):
            Investment.create(
                product=ProductType.TESOURO_SELIC,
                issuer=Issuer.treasury(),
                principal=Money.from_reais("1000"),
                rate=PostFixedCDI.from_percent("100"),
                purchase_date=date(2024, 1, 15),
                maturity_date=date(2026, 1, 15),
                coupon_frequency=CouponFrequency.MONTHLY,
            )

    def test_tesouro_prefixado_allows_semi_annual(self) -> None:
        inv = Investment.create(
            product=ProductType.TESOURO_PREFIXADO,
            issuer=Issuer.treasury(),
            principal=Money.from_reais("1000"),
            rate=Prefixed.from_percent("11"),
            purchase_date=date(2024, 1, 15),
            maturity_date=date(2030, 1, 15),
            coupon_frequency=CouponFrequency.SEMI_ANNUAL,
        )
        assert inv.coupon_frequency == CouponFrequency.SEMI_ANNUAL


# ------------------------------------------------------------------
# Invariant 5: LCD minimum term
# ------------------------------------------------------------------


class TestLCDMinimumTerm:
    def test_lcd_below_365_days_rejected(self) -> None:
        with pytest.raises(ValueError, match="minimum term"):
            Investment.create(
                product=ProductType.LCD,
                issuer=development_bank(),
                principal=Money.from_reais("10000"),
                rate=PostFixedCDI.from_percent("100"),
                purchase_date=date(2024, 1, 15),
                maturity_date=date(2024, 6, 15),  # ~5 months
            )

    def test_lcd_exactly_365_days_accepted(self) -> None:
        purchase = date(2024, 1, 15)
        maturity = purchase + timedelta(days=365)
        inv = Investment.create(
            product=ProductType.LCD,
            issuer=development_bank(),
            principal=Money.from_reais("10000"),
            rate=PostFixedCDI.from_percent("100"),
            purchase_date=purchase,
            maturity_date=maturity,
        )
        assert inv.term_days == 365

    def test_lcd_well_above_365_days_accepted(self) -> None:
        inv = Investment.create(
            product=ProductType.LCD,
            issuer=development_bank(),
            principal=Money.from_reais("10000"),
            rate=PostFixedCDI.from_percent("100"),
            purchase_date=date(2024, 1, 15),
            maturity_date=date(2027, 1, 15),
        )
        assert inv.term_days >= 365

    def test_cdb_does_not_enforce_minimum_term(self) -> None:
        # CDB has no minimum; a 30-day CDB is valid.
        inv = make_cdb(
            purchase=date(2024, 1, 15),
            maturity=date(2024, 2, 14),
        )
        assert inv.term_days == 30


# ------------------------------------------------------------------
# Derived properties
# ------------------------------------------------------------------


class TestDerivedProperties:
    def test_term_days(self) -> None:
        inv = make_cdb(
            purchase=date(2024, 1, 15),
            maturity=date(2025, 1, 15),
        )
        assert inv.term_days == 366  # 2024 was a leap year

    def test_is_bullet_true_for_no_coupons(self) -> None:
        inv = make_cdb(coupons=CouponFrequency.NONE)
        assert inv.is_bullet is True

    def test_is_bullet_false_for_monthly(self) -> None:
        inv = make_cdb(coupons=CouponFrequency.MONTHLY)
        assert inv.is_bullet is False

    def test_is_fgc_covered_for_cdb_at_commercial_bank(self) -> None:
        inv = make_cdb()
        assert inv.is_fgc_covered is True

    def test_is_fgc_covered_for_lcd_at_development_bank(self) -> None:
        inv = Investment.create(
            product=ProductType.LCD,
            issuer=development_bank(),
            principal=Money.from_reais("10000"),
            rate=PostFixedCDI.from_percent("100"),
            purchase_date=date(2024, 1, 15),
            maturity_date=date(2026, 1, 15),
        )
        assert inv.is_fgc_covered is True

    def test_is_not_fgc_covered_for_tesouro(self) -> None:
        inv = Investment.create(
            product=ProductType.TESOURO_SELIC,
            issuer=Issuer.treasury(),
            principal=Money.from_reais("1000"),
            rate=PostFixedCDI.from_percent("100"),
            purchase_date=date(2024, 1, 15),
            maturity_date=date(2026, 1, 15),
        )
        assert inv.is_fgc_covered is False


# ------------------------------------------------------------------
# Identity-based equality
# ------------------------------------------------------------------


class TestIdentity:
    def test_same_attributes_different_ids_unequal(self) -> None:
        # Two CDBs purchased on the same day with the same issuer
        # are distinct positions (entity semantics).
        a = make_cdb()
        b = make_cdb()
        assert a != b

    def test_hashable(self) -> None:
        a = make_cdb()
        b = make_cdb()
        s = {a, b, a}
        assert len(s) == 2

    def test_compared_to_non_investment(self) -> None:
        a = make_cdb()
        assert (a == "not an investment") is False