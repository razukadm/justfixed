"""Tests for the BTG loader: parsed rows -> persisted Investments.

These tests verify the layer-3 loader: takes a Path to a BTG statement,
calls layers 1 and 2 internally, then reconciles issuers and persists
investments idempotently.

Fixture file: tests/importers/fixtures/synthetic_btg_statement.xlsx
Two sub-sections:
  0. LCI  ASSOCIACAO DE POUPANCA E EMPRESTIMO POUPEX  89% CDI   NONE
       emissao == aquisicao == 2025-09-29
  1. LCA  BANCO DO BRASIL                             115% CDI  NONE
       emissao 2024-01-10, aquisicao 2024-03-15 (secondary-market purchase)

The LCA row has a deliberate emissao/aquisicao gap so that
test_issue_date_on_loaded_investment can prove the loader reads
issue_date from emissao_date_text rather than defaulting it to
purchase_date (aquisicao).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from justfixed.domain.investment import InvestmentSource
from justfixed.domain.issuer import Issuer, IssuerKind, UNVERIFIED_CONGLOMERATE_PREFIX
from justfixed.domain.product import CouponFrequency
from justfixed.importers.btg_loader import (
    LoadResult,
    _resolve_issuer,
    load_btg_statement,
)
from justfixed.persistence.database import Base, make_engine, make_session_factory
from justfixed.persistence.repositories import (
    CurationMemoryRepository,
    InvestmentRepository,
    IssuerRepository,
)


FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "synthetic_btg_statement.xlsx"
)


# ---------- Fixtures ----------


@pytest.fixture
def factory():
    """Fresh in-memory SQLite database per test, with schema created."""
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield make_session_factory(engine)
    engine.dispose()


@pytest.fixture
def issuer_repo(factory):
    return IssuerRepository(factory)


@pytest.fixture
def investment_repo(factory):
    return InvestmentRepository(factory)


@pytest.fixture
def curation_repo(factory):
    return CurationMemoryRepository(factory)


# ---------- Fixture sanity ----------


class TestFixtureExists:
    def test_fixture_file_present(self) -> None:
        assert FIXTURE_PATH.exists(), (
            f"Fixture missing: {FIXTURE_PATH}. "
            "Run tests/importers/fixtures/create_synthetic_btg_statement.py "
            "to regenerate it."
        )


# ---------- Core load behavior ----------


class TestLoadBtgStatement:
    def test_loads_two_rows_into_empty_database(
        self, factory, issuer_repo, investment_repo
    ) -> None:
        result = load_btg_statement(FIXTURE_PATH, factory)

        assert result == LoadResult(
            inserted=2,
            skipped=0,
            issuers_created=2,
            issuers_reused=0,
        )
        assert len(investment_repo.list_all()) == 2
        assert len(issuer_repo.list_all()) == 2

    def test_re_importing_same_file_is_idempotent(
        self, factory, issuer_repo, investment_repo
    ) -> None:
        load_btg_statement(FIXTURE_PATH, factory)

        result = load_btg_statement(FIXTURE_PATH, factory)

        assert result == LoadResult(
            inserted=0,
            skipped=2,
            issuers_created=0,
            issuers_reused=2,
        )
        assert len(investment_repo.list_all()) == 2
        assert len(issuer_repo.list_all()) == 2


# ---------- Issuer handling ----------


class TestIssuerCreation:
    def test_poupex_classified_as_savings_loan_association(
        self, factory, issuer_repo
    ) -> None:
        load_btg_statement(FIXTURE_PATH, factory)

        poupex = issuer_repo.find_by_normalized_name(
            "ASSOCIACAO DE POUPANCA E EMPRESTIMO POUPEX"
        )
        assert poupex is not None
        assert poupex.kind == IssuerKind.SAVINGS_LOAN_ASSOCIATION
        assert poupex.name == "ASSOCIACAO DE POUPANCA E EMPRESTIMO POUPEX"

    def test_creates_issuers_with_unverified_conglomerate(
        self, factory, issuer_repo
    ) -> None:
        # Both fixture issuers are new and uncurated; both should get
        # the [unverified] prefix on conglomerate.
        load_btg_statement(FIXTURE_PATH, factory)

        all_issuers = issuer_repo.list_all()
        assert len(all_issuers) == 2
        for issuer in all_issuers:
            assert issuer.conglomerate.startswith(UNVERIFIED_CONGLOMERATE_PREFIX), (
                f"Issuer {issuer.name!r} has conglomerate "
                f"{issuer.conglomerate!r}, expected to start with "
                f"{UNVERIFIED_CONGLOMERATE_PREFIX!r}"
            )

    def test_reuses_existing_issuer_when_already_present(
        self, factory, issuer_repo, investment_repo
    ) -> None:
        # Pre-seed BANCO DO BRASIL. The loader must reuse it rather than
        # create a duplicate, and must not overwrite its record.
        existing = Issuer.create(
            name="Banco do Brasil",
            conglomerate="Banco do Brasil S.A. (manually curated)",
            kind=IssuerKind.COMMERCIAL_BANK,
        )
        issuer_repo.save(existing)

        result = load_btg_statement(FIXTURE_PATH, factory)

        assert result.issuers_created == 1  # POUPEX only
        assert result.issuers_reused == 1   # BANCO DO BRASIL

        reloaded = issuer_repo.find_by_normalized_name("Banco do Brasil")
        assert reloaded is not None
        assert reloaded.id == existing.id
        assert reloaded.conglomerate == "Banco do Brasil S.A. (manually curated)"

    def test_normalizes_issuer_name_for_lookup(
        self, factory, issuer_repo
    ) -> None:
        # Pre-seed with lowercase "banco do brasil". Normalization should
        # match the fixture's "BANCO DO BRASIL" without creating a duplicate.
        existing = Issuer.create(
            name="banco do brasil",
            conglomerate="lowercase test",
            kind=IssuerKind.COMMERCIAL_BANK,
        )
        issuer_repo.save(existing)

        load_btg_statement(FIXTURE_PATH, factory)

        all_issuers = issuer_repo.list_all()
        bb_matches = [
            i for i in all_issuers
            if Issuer.normalize_name(i.name) == "BANCO DO BRASIL"
        ]
        assert len(bb_matches) == 1
        assert bb_matches[0].id == existing.id


# ---------- Issuer-kind classification ----------


class TestIssuerKindClassification:
    def test_poupex_resolves_as_savings_loan_association(
        self, issuer_repo, curation_repo
    ) -> None:
        issuer, was_created = _resolve_issuer(
            "ASSOCIACAO DE POUPANCA E EMPRESTIMO POUPEX",
            issuer_repo,
            curation_repo,
        )
        assert was_created is True
        assert issuer.kind == IssuerKind.SAVINGS_LOAN_ASSOCIATION

    def test_unknown_issuer_defaults_to_commercial_bank(
        self, issuer_repo, curation_repo
    ) -> None:
        issuer, was_created = _resolve_issuer("Banco Foo BTG", issuer_repo, curation_repo)
        assert was_created is True
        assert issuer.kind == IssuerKind.COMMERCIAL_BANK


# ---------- Curation memory integration ----------


class TestCurationMemoryIntegration:
    def test_curated_conglomerate_applied_on_create(
        self, issuer_repo, curation_repo
    ) -> None:
        curation_repo.set("BANCO DO BRASIL", "BB Participações S.A.")

        issuer, was_created = _resolve_issuer(
            "BANCO DO BRASIL", issuer_repo, curation_repo
        )

        assert was_created is True
        assert issuer.conglomerate == "BB Participações S.A."

    def test_find_branch_ignores_curation(
        self, issuer_repo, curation_repo
    ) -> None:
        existing = Issuer.create(
            name="BANCO DO BRASIL",
            conglomerate="Original Conglomerate",
            kind=IssuerKind.COMMERCIAL_BANK,
        )
        issuer_repo.save(existing)
        curation_repo.set("BANCO DO BRASIL", "Curated Conglomerate")

        issuer, was_created = _resolve_issuer(
            "BANCO DO BRASIL", issuer_repo, curation_repo
        )

        assert was_created is False
        assert issuer.id == existing.id
        assert issuer.conglomerate == "Original Conglomerate"

    def test_fallback_to_unverified_when_no_curation(
        self, issuer_repo, curation_repo
    ) -> None:
        issuer, was_created = _resolve_issuer(
            "Banco Foo BTG", issuer_repo, curation_repo
        )

        assert was_created is True
        assert issuer.conglomerate == f"{UNVERIFIED_CONGLOMERATE_PREFIX}Banco Foo BTG"


# ---------- Investment field coverage ----------


class TestInvestmentFields:
    def test_loaded_investments_have_btg_import_source(
        self, factory, investment_repo
    ) -> None:
        load_btg_statement(FIXTURE_PATH, factory)
        all_investments = investment_repo.list_all()
        assert all_investments
        assert all(inv.source == InvestmentSource.BTG_IMPORT for inv in all_investments)

    def test_issue_date_on_loaded_investment(
        self, factory, investment_repo
    ) -> None:
        # The LCA fixture row has emissao (2024-01-10) != aquisicao (2024-03-15),
        # so this test genuinely proves the loader reads issue_date from
        # emissao_date_text and does NOT default it to purchase_date (aquisicao).
        load_btg_statement(FIXTURE_PATH, factory)

        all_investments = investment_repo.list_all()
        poupex_inv = next(
            inv for inv in all_investments
            if inv.issuer.name == "ASSOCIACAO DE POUPANCA E EMPRESTIMO POUPEX"
        )
        assert poupex_inv.issue_date == date(2025, 9, 29)
        assert poupex_inv.coupon_frequency == CouponFrequency.NONE

        bb_inv = next(
            inv for inv in all_investments
            if inv.issuer.name == "BANCO DO BRASIL"
        )
        assert bb_inv.issue_date == date(2024, 1, 10)
        assert bb_inv.purchase_date == date(2024, 3, 15)
        assert bb_inv.issue_date != bb_inv.purchase_date
