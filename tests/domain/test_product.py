"""Tests for product taxonomy — ProductRule and CouponFrequency."""

from __future__ import annotations

from datetime import date

import pytest

from justfixed.domain.investment import Investment
from justfixed.domain.issuer import Issuer, IssuerKind
from justfixed.domain.money import Money
from justfixed.domain.product import CouponFrequency, ProductType
from justfixed.domain.rates import PostFixedCDI


# ---------- Helpers ----------

def _issuer(kind: IssuerKind) -> Issuer:
    return Issuer.create("Test Institution", "Test Institution", kind)

def _lci(kind: IssuerKind) -> Investment:
    return Investment.create(
        product=ProductType.LCI,
        issuer=_issuer(kind),
        principal=Money.from_reais("10000"),
        rate=PostFixedCDI.from_percent("90"),
        purchase_date=date(2024, 1, 15),
        maturity_date=date(2026, 1, 15),
    )

def _lca(kind: IssuerKind) -> Investment:
    return Investment.create(
        product=ProductType.LCA,
        issuer=_issuer(kind),
        principal=Money.from_reais("10000"),
        rate=PostFixedCDI.from_percent("90"),
        purchase_date=date(2024, 1, 15),
        maturity_date=date(2026, 1, 15),
    )


# ---------- CouponFrequency display ----------

class TestCouponFrequencyToDisplay:
    def test_none_returns_portuguese(self) -> None:
        assert CouponFrequency.NONE.to_display() == "Nenhum"

    def test_monthly_returns_portuguese(self) -> None:
        assert CouponFrequency.MONTHLY.to_display() == "Mensal"

    def test_semi_annual_returns_portuguese(self) -> None:
        assert CouponFrequency.SEMI_ANNUAL.to_display() == "Semestral"


# ---------- LCI allowed issuer kinds ----------

# Seven kinds newly permitted beyond the original COMMERCIAL_BANK.
_LCI_NEW_KINDS = [
    IssuerKind.MULTIPLE_BANK,
    IssuerKind.CAIXA_ECONOMICA,
    IssuerKind.CREDIT_FINANCE_INVESTMENT_COMPANY,
    IssuerKind.REAL_ESTATE_CREDIT_COMPANY,
    IssuerKind.MORTGAGE_COMPANY,
    IssuerKind.SAVINGS_LOAN_ASSOCIATION,
    IssuerKind.COOP,
]


class TestLCIIssuerKinds:
    @pytest.mark.parametrize("kind", _LCI_NEW_KINDS)
    def test_lci_accepts_newly_permitted_kind(self, kind: IssuerKind) -> None:
        inv = _lci(kind)
        assert inv.product == ProductType.LCI

    @pytest.mark.parametrize("kind", [
        IssuerKind.TREASURY,
        IssuerKind.OTHERS,
        IssuerKind.DEVELOPMENT_BANK,
        IssuerKind.INVESTMENT_BANK,
    ])
    def test_lci_rejects_excluded_kind(self, kind: IssuerKind) -> None:
        with pytest.raises(ValueError, match="LCI requires issuer kind"):
            _lci(kind)


# ---------- LCA allowed issuer kinds ----------

# Seven kinds newly permitted beyond the original COMMERCIAL_BANK + DEVELOPMENT_BANK baseline.
_LCA_NEW_KINDS = [
    IssuerKind.MULTIPLE_BANK,
    IssuerKind.CAIXA_ECONOMICA,
    IssuerKind.CREDIT_FINANCE_INVESTMENT_COMPANY,
    IssuerKind.REAL_ESTATE_CREDIT_COMPANY,
    IssuerKind.MORTGAGE_COMPANY,
    IssuerKind.SAVINGS_LOAN_ASSOCIATION,
    IssuerKind.COOP,
]


class TestLCAIssuerKinds:
    @pytest.mark.parametrize("kind", _LCA_NEW_KINDS)
    def test_lca_accepts_newly_permitted_kind(self, kind: IssuerKind) -> None:
        inv = _lca(kind)
        assert inv.product == ProductType.LCA

    @pytest.mark.parametrize("kind", [
        IssuerKind.TREASURY,
        IssuerKind.OTHERS,
        IssuerKind.INVESTMENT_BANK,
    ])
    def test_lca_rejects_excluded_kind(self, kind: IssuerKind) -> None:
        with pytest.raises(ValueError, match="LCA requires issuer kind"):
            _lca(kind)
