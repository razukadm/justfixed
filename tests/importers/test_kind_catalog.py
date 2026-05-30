"""Direct unit tests for _kind_catalog.classify_issuer_kind (B33).

The catalog merges xp_loader's _DEVELOPMENT_BANK_NAMES (BDMG) and
btg_loader's _ISSUER_KIND_CATALOG (POUPEX) into a single shared lookup.
"""
from __future__ import annotations

from justfixed.domain.issuer import IssuerKind
from justfixed.importers._kind_catalog import classify_issuer_kind


class TestClassifyIssuerKind:
    def test_bdmg_is_development_bank(self) -> None:
        assert classify_issuer_kind("BDMG") == IssuerKind.DEVELOPMENT_BANK

    def test_poupex_is_savings_loan_association(self) -> None:
        # Full normalized name — normalize_name does not shorten
        assert (
            classify_issuer_kind("ASSOCIACAO DE POUPANCA E EMPRESTIMO POUPEX")
            == IssuerKind.SAVINGS_LOAN_ASSOCIATION
        )

    def test_unknown_name_defaults_to_commercial_bank(self) -> None:
        assert classify_issuer_kind("BANCO INTER") == IssuerKind.COMMERCIAL_BANK

    def test_empty_string_defaults_to_commercial_bank(self) -> None:
        assert classify_issuer_kind("") == IssuerKind.COMMERCIAL_BANK

    def test_case_sensitivity(self) -> None:
        # Keys are normalized (uppercase); lowercase must not match
        assert classify_issuer_kind("bdmg") == IssuerKind.COMMERCIAL_BANK
