"""Tests for the mappers — domain ↔ ORM row conversion."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from justfixed.domain.investment import Investment, InvestmentSource
from justfixed.domain.issuer import Issuer, IssuerKind
from justfixed.domain.money import Money
from justfixed.domain.product import CouponFrequency, ProductType
from justfixed.domain.rates import PostFixedCDI, PostFixedCDIPlusSpread, PostFixedIPCA, Prefixed
from justfixed.persistence.mappers import (
    investment_from_row,
    investment_to_row,
    issuer_from_row,
    issuer_to_row,
)
from justfixed.persistence.models import InvestmentRow, IssuerRow


# ---------- Helpers ----------


def commercial_bank() -> Issuer:
    return Issuer.create(
        "Banco Inter", "Banco Inter S.A.", IssuerKind.COMMERCIAL_BANK,
        tax_id="00416968000101",
    )


# ---------- Issuer mappers ----------


class TestIssuerToRow:
    def test_basic_fields_copied(self) -> None:
        issuer = commercial_bank()
        row = issuer_to_row(issuer)
        assert row.id == issuer.id
        assert row.name == "Banco Inter"
        assert row.conglomerate == "Banco Inter S.A."
        assert row.tax_id == "00416968000101"

    def test_kind_serialized_as_value_string(self) -> None:
        issuer = commercial_bank()
        row = issuer_to_row(issuer)
        assert row.kind == "commercial_bank"

    def test_treasury_kind(self) -> None:
        issuer = Issuer.treasury()
        row = issuer_to_row(issuer)
        assert row.kind == "treasury"

    def test_development_bank_kind(self) -> None:
        issuer = Issuer.create("BNDES", "BNDES", IssuerKind.DEVELOPMENT_BANK)
        row = issuer_to_row(issuer)
        assert row.kind == "development_bank"


class TestIssuerFromRow:
    def test_basic_round_trip(self) -> None:
        original = commercial_bank()
        row = issuer_to_row(original)
        restored = issuer_from_row(row)
        assert restored == original  # identity-based equality (same id)
        assert restored.name == original.name
        assert restored.conglomerate == original.conglomerate
        assert restored.kind == original.kind
        assert restored.tax_id == original.tax_id

    def test_unknown_kind_string_rejected(self) -> None:
        # Manually construct a row with bad data to simulate corruption.
        row = IssuerRow(
            id=uuid.uuid4(),
            name="Bad Bank",
            conglomerate="Bad",
            kind="not_a_real_kind",
            tax_id="",
        )
        with pytest.raises(ValueError):
            issuer_from_row(row)


# ---------- Rate column splitting ----------


class TestRateRoundTrip:
    """Each rate kind must round-trip through its (kind, value) form."""

    def _make_inv_with_rate(self, rate) -> Investment:
        return Investment.create(
            product=ProductType.CDB,
            issuer=commercial_bank(),
            principal=Money.from_reais("10000"),
            rate=rate,
            purchase_date=date(2024, 1, 15),
            maturity_date=date(2026, 1, 15),
        )

    def test_prefixed(self) -> None:
        original = Prefixed.from_percent("12.5")
        inv = self._make_inv_with_rate(original)
        row = investment_to_row(inv)
        assert row.rate_kind == "prefixed"
        assert row.rate_value == Decimal("0.125")
        # Now reconstruct.
        restored_inv = investment_from_row(row, inv.issuer)
        assert restored_inv.rate == original

    def test_post_fixed_cdi(self) -> None:
        original = PostFixedCDI.from_percent("112")
        inv = self._make_inv_with_rate(original)
        row = investment_to_row(inv)
        assert row.rate_kind == "post_fixed_cdi"
        assert row.rate_value == Decimal("1.12")
        restored_inv = investment_from_row(row, inv.issuer)
        assert restored_inv.rate == original

    def test_post_fixed_ipca(self) -> None:
        original = PostFixedIPCA.from_percent("5.5")
        inv = self._make_inv_with_rate(
            # IPCA-linked is most common for Tesouro IPCA, but the rate
            # type is independent of the product type at the domain level.
            original
        )
        row = investment_to_row(inv)
        assert row.rate_kind == "post_fixed_ipca"
        assert row.rate_value == Decimal("0.055")
        restored_inv = investment_from_row(row, inv.issuer)
        assert restored_inv.rate == original

    def test_post_fixed_cdi_plus_spread(self) -> None:
        original = PostFixedCDIPlusSpread.from_percent("2.05")
        inv = self._make_inv_with_rate(original)
        row = investment_to_row(inv)
        assert row.rate_kind == "post_fixed_cdi_plus_spread"
        assert row.rate_value == Decimal("0.0205")
        restored_inv = investment_from_row(row, inv.issuer)
        assert restored_inv.rate == original

# ---------- Investment mappers, full round-trip ----------


class TestInvestmentToRow:
    def test_basic_fields_copied(self) -> None:
        issuer = commercial_bank()
        inv = Investment.create(
            product=ProductType.CDB,
            issuer=issuer,
            principal=Money.from_reais("10000.50"),
            rate=PostFixedCDI.from_percent("110"),
            purchase_date=date(2024, 1, 15),
            maturity_date=date(2026, 1, 15),
            description="My first CDB",
        )
        row = investment_to_row(inv)

        assert row.id == inv.id
        assert row.product == "cdb"
        assert row.issuer_id == issuer.id
        assert row.principal_amount == Decimal("10000.50")
        assert row.principal_currency == "BRL"
        assert row.purchase_date == date(2024, 1, 15)
        assert row.maturity_date == date(2026, 1, 15)
        assert row.issue_date == date(2024, 1, 15)  # defaulted from purchase
        assert row.coupon_frequency == "none"
        assert row.description == "My first CDB"

    def test_secondary_market_issue_date_preserved(self) -> None:
        issuer = Issuer.create("BNDES", "BNDES", IssuerKind.DEVELOPMENT_BANK)
        inv = Investment.create(
            product=ProductType.LCD,
            issuer=issuer,
            principal=Money.from_reais("5000"),
            rate=PostFixedCDI.from_percent("100"),
            purchase_date=date(2026, 5, 4),
            maturity_date=date(2026, 10, 1),
            issue_date=date(2025, 10, 1),
        )
        row = investment_to_row(inv)
        assert row.issue_date == date(2025, 10, 1)
        assert row.purchase_date == date(2026, 5, 4)

    def test_coupon_frequency_serialized(self) -> None:
        inv = Investment.create(
            product=ProductType.CDB,
            issuer=commercial_bank(),
            principal=Money.from_reais("10000"),
            rate=Prefixed.from_percent("12"),
            purchase_date=date(2024, 1, 15),
            maturity_date=date(2026, 1, 15),
            coupon_frequency=CouponFrequency.SEMI_ANNUAL,
        )
        row = investment_to_row(inv)
        assert row.coupon_frequency == "semi_annual"


class TestInvestmentFromRow:
    def test_full_round_trip(self) -> None:
        issuer = commercial_bank()
        original = Investment.create(
            product=ProductType.CDB,
            issuer=issuer,
            principal=Money.from_reais("10000.50"),
            rate=PostFixedCDI.from_percent("110"),
            purchase_date=date(2024, 1, 15),
            maturity_date=date(2026, 1, 15),
            coupon_frequency=CouponFrequency.MONTHLY,
            description="Round trip",
        )
        row = investment_to_row(original)
        restored = investment_from_row(row, issuer)

        assert restored == original  # entity equality by id
        assert restored.product == original.product
        assert restored.principal == original.principal
        assert restored.rate == original.rate
        assert restored.purchase_date == original.purchase_date
        assert restored.maturity_date == original.maturity_date
        assert restored.issue_date == original.issue_date
        assert restored.coupon_frequency == original.coupon_frequency
        assert restored.description == original.description

    def test_secondary_market_round_trip(self) -> None:
        issuer = Issuer.create("BNDES", "BNDES", IssuerKind.DEVELOPMENT_BANK)
        original = Investment.create(
            product=ProductType.LCD,
            issuer=issuer,
            principal=Money.from_reais("5000"),
            rate=PostFixedCDI.from_percent("100"),
            purchase_date=date(2026, 5, 4),
            maturity_date=date(2026, 10, 1),
            issue_date=date(2025, 10, 1),
        )
        row = investment_to_row(original)
        restored = investment_from_row(row, issuer)
        assert restored.issue_date == date(2025, 10, 1)
        assert restored.holding_term_days == 150
        assert restored.security_term_days == 365
        assert restored.is_secondary_market is True

    def test_issuer_mismatch_rejected(self) -> None:
        issuer_a = commercial_bank()
        issuer_b = Issuer.create("Other", "Other", IssuerKind.COMMERCIAL_BANK)
        inv = Investment.create(
            product=ProductType.CDB,
            issuer=issuer_a,
            principal=Money.from_reais("10000"),
            rate=PostFixedCDI.from_percent("110"),
            purchase_date=date(2024, 1, 15),
            maturity_date=date(2026, 1, 15),
        )
        row = investment_to_row(inv)
        # Wrong issuer for this row.
        with pytest.raises(ValueError, match="Issuer mismatch"):
            investment_from_row(row, issuer_b)

    def test_unknown_rate_kind_rejected(self) -> None:
        # Simulate a corrupt row.
        issuer = commercial_bank()
        row = InvestmentRow(
            id=uuid.uuid4(),
            product="cdb",
            issuer_id=issuer.id,
            principal_amount=Decimal("10000"),
            principal_currency="BRL",
            rate_kind="not_a_real_kind",
            rate_value=Decimal("0.10"),
            purchase_date=date(2024, 1, 15),
            maturity_date=date(2026, 1, 15),
            issue_date=date(2024, 1, 15),
            coupon_frequency="none",
            description="",
            source="xp_import",
        )
        with pytest.raises(ValueError, match="Unknown rate_kind"):
            investment_from_row(row, issuer)

    def test_corrupt_row_fails_domain_validation(self) -> None:
        # Row data that violates a domain invariant (maturity before purchase).
        # The reconstructed Investment must fail at __post_init__.
        issuer = commercial_bank()
        row = InvestmentRow(
            id=uuid.uuid4(),
            product="cdb",
            issuer_id=issuer.id,
            principal_amount=Decimal("10000"),
            principal_currency="BRL",
            rate_kind="post_fixed_cdi",
            rate_value=Decimal("1.10"),
            purchase_date=date(2024, 6, 1),
            maturity_date=date(2024, 1, 15),  # BEFORE purchase!
            issue_date=date(2024, 1, 15),
            coupon_frequency="none",
            description="",
            source="xp_import",
        )
        with pytest.raises(ValueError):
            investment_from_row(row, issuer)

    def test_source_round_trips(self) -> None:
        issuer = commercial_bank()
        inv = Investment.create(
            product=ProductType.CDB,
            issuer=issuer,
            principal=Money.from_reais("10000"),
            rate=PostFixedCDI.from_percent("110"),
            purchase_date=date(2024, 1, 15),
            maturity_date=date(2026, 1, 15),
            source=InvestmentSource.MANUAL,
        )
        row = investment_to_row(inv)
        assert row.source == "manual"
        restored = investment_from_row(row, issuer)
        assert restored.source == InvestmentSource.MANUAL

    def test_custodian_set_round_trips(self) -> None:
        issuer = commercial_bank()
        inv = Investment.create(
            product=ProductType.CDB,
            issuer=issuer,
            principal=Money.from_reais("10000"),
            rate=PostFixedCDI.from_percent("110"),
            purchase_date=date(2024, 1, 15),
            maturity_date=date(2026, 1, 15),
            custodian="XP",
        )
        row = investment_to_row(inv)
        assert row.custodian == "XP"
        restored = investment_from_row(row, issuer)
        assert restored.custodian == "XP"

    def test_custodian_none_round_trips(self) -> None:
        issuer = commercial_bank()
        inv = Investment.create(
            product=ProductType.CDB,
            issuer=issuer,
            principal=Money.from_reais("10000"),
            rate=PostFixedCDI.from_percent("110"),
            purchase_date=date(2024, 1, 15),
            maturity_date=date(2026, 1, 15),
            custodian=None,
        )
        row = investment_to_row(inv)
        assert row.custodian is None
        restored = investment_from_row(row, issuer)
        assert restored.custodian is None

    def test_broker_reported_value_set_round_trips(self) -> None:
        issuer = commercial_bank()
        inv = Investment.create(
            product=ProductType.CDB,
            issuer=issuer,
            principal=Money.from_reais("10000"),
            rate=PostFixedCDI.from_percent("110"),
            purchase_date=date(2024, 1, 15),
            maturity_date=date(2026, 1, 15),
            broker_reported_value=Money.from_reais("10500"),
        )
        row = investment_to_row(inv)
        assert row.broker_value_amount == Decimal("10500")
        assert row.broker_value_currency == "BRL"
        restored = investment_from_row(row, issuer)
        assert restored.broker_reported_value == Money.from_reais("10500")

    def test_broker_reported_value_none_round_trips(self) -> None:
        issuer = commercial_bank()
        inv = Investment.create(
            product=ProductType.CDB,
            issuer=issuer,
            principal=Money.from_reais("10000"),
            rate=PostFixedCDI.from_percent("110"),
            purchase_date=date(2024, 1, 15),
            maturity_date=date(2026, 1, 15),
        )
        row = investment_to_row(inv)
        assert row.broker_value_amount is None
        assert row.broker_value_currency is None
        restored = investment_from_row(row, issuer)
        assert restored.broker_reported_value is None

    def test_user_edited_value_set_round_trips(self) -> None:
        issuer = commercial_bank()
        inv = Investment.create(
            product=ProductType.CDB,
            issuer=issuer,
            principal=Money.from_reais("10000"),
            rate=PostFixedCDI.from_percent("110"),
            purchase_date=date(2024, 1, 15),
            maturity_date=date(2026, 1, 15),
            user_edited_value=Money.from_reais("10600"),
        )
        row = investment_to_row(inv)
        assert row.user_value_amount == Decimal("10600")
        assert row.user_value_currency == "BRL"
        restored = investment_from_row(row, issuer)
        assert restored.user_edited_value == Money.from_reais("10600")

    def test_user_edited_value_none_round_trips(self) -> None:
        issuer = commercial_bank()
        inv = Investment.create(
            product=ProductType.CDB,
            issuer=issuer,
            principal=Money.from_reais("10000"),
            rate=PostFixedCDI.from_percent("110"),
            purchase_date=date(2024, 1, 15),
            maturity_date=date(2026, 1, 15),
        )
        row = investment_to_row(inv)
        assert row.user_value_amount is None
        assert row.user_value_currency is None
        restored = investment_from_row(row, issuer)
        assert restored.user_edited_value is None