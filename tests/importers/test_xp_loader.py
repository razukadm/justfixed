"""Tests for the XP loader: parsed rows → persisted Investments.

These tests verify the layer-3 loader: takes a Path to an XP statement,
calls layers 1 and 2 internally, then reconciles issuers and persists
investments idempotently.

Fixture file: tests/importers/fixtures/synthetic_xp_statement.xlsx
The same 6-row file used by test_xp_parser.py. Contents (in order):
  0. LCI    CEF              PostFixedCDI           NONE
  1. CDB    BMG              PostFixedCDIPlusSpread NONE
  2. LCA    SICREDI          Prefixed               NONE
  3. CDB    PINE             Prefixed               MONTHLY
  4. TES_IPCA Tesouro Nac.   PostFixedIPCA          NONE
  5. LCI    BANCO INTER      PostFixedIPCA          NONE
"""

from __future__ import annotations

from pathlib import Path

import pytest

from justfixed.domain.issuer import Issuer, IssuerKind
from justfixed.domain.product import CouponFrequency
from justfixed.domain.rates import (
    PostFixedCDI,
    PostFixedCDIPlusSpread,
    PostFixedIPCA,
    Prefixed,
)
from justfixed.importers.xp_loader import (
    UNVERIFIED_CONGLOMERATE_PREFIX,
    LoadResult,
    load_xp_statement,
)
from justfixed.persistence.database import Base, make_engine, make_session_factory
from justfixed.persistence.repositories import (
    InvestmentRepository,
    IssuerRepository,
)


FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "synthetic_xp_statement.xlsx"
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


# ---------- Fixture sanity ----------


class TestFixtureExists:
    """If this test fails, no other test in the file can pass."""

    def test_fixture_file_present(self) -> None:
        assert FIXTURE_PATH.exists(), (
            f"Fixture missing: {FIXTURE_PATH}. "
            "Did you copy synthetic_xp_statement.xlsx into "
            "tests/importers/fixtures/?"
        )


# ---------- Core load behavior ----------


class TestLoadXpStatement:
    def test_loads_all_six_rows_into_empty_database(
        self, factory, issuer_repo, investment_repo
    ) -> None:
        result = load_xp_statement(FIXTURE_PATH, factory)

        assert result == LoadResult(
            inserted=6,
            skipped=0,
            issuers_created=6,
            issuers_reused=0,
        )
        assert len(investment_repo.list_all()) == 6
        assert len(issuer_repo.list_all()) == 6

    def test_re_importing_same_file_is_idempotent(
        self, factory, issuer_repo, investment_repo
    ) -> None:
        # First import: everything is new.
        load_xp_statement(FIXTURE_PATH, factory)

        # Second import: nothing should be added.
        result = load_xp_statement(FIXTURE_PATH, factory)

        assert result == LoadResult(
            inserted=0,
            skipped=6,
            issuers_created=0,
            issuers_reused=6,
        )
        assert len(investment_repo.list_all()) == 6
        assert len(issuer_repo.list_all()) == 6


# ---------- Issuer handling ----------


class TestIssuerCreation:
    def test_creates_treasury_issuer_via_factory(
        self, factory, issuer_repo
    ) -> None:
        # The treasury must be created via Issuer.treasury(), not as a
        # generic commercial bank. This is verified by checking kind,
        # canonical conglomerate (no [unverified] prefix), and CNPJ.
        load_xp_statement(FIXTURE_PATH, factory)

        treasury = issuer_repo.find_by_normalized_name("Tesouro Nacional")
        assert treasury is not None
        assert treasury.kind == IssuerKind.TREASURY
        assert treasury.name == "Tesouro Nacional"
        assert treasury.conglomerate == "Tesouro Nacional"
        # CNPJ from the Issuer.treasury() factory.
        assert treasury.tax_id == "00394460000141"

    def test_creates_commercial_bank_issuers_with_unverified_conglomerate(
        self, factory, issuer_repo
    ) -> None:
        # Every non-treasury issuer should be COMMERCIAL_BANK with the
        # [unverified] prefix on conglomerate, signaling that no human
        # has reviewed the conglomerate grouping yet.
        load_xp_statement(FIXTURE_PATH, factory)

        all_issuers = issuer_repo.list_all()
        commercial = [i for i in all_issuers if i.kind == IssuerKind.COMMERCIAL_BANK]
        assert len(commercial) == 5  # Five non-treasury issuers in fixture

        for issuer in commercial:
            assert issuer.conglomerate.startswith(
                UNVERIFIED_CONGLOMERATE_PREFIX
            ), (
                f"Issuer {issuer.name!r} has conglomerate "
                f"{issuer.conglomerate!r}, expected to start with "
                f"{UNVERIFIED_CONGLOMERATE_PREFIX!r}"
            )

    def test_reuses_existing_issuer_when_already_present(
        self, factory, issuer_repo, investment_repo
    ) -> None:
        # Pre-seed the DB with an issuer matching one of the fixture's
        # rows (BANCO INTER, row 5). The loader should reuse it rather
        # than create a duplicate. The pre-existing issuer's record
        # (including its custom conglomerate string) must not be
        # overwritten — issuer reconciliation is read-only on existing rows.
        existing = Issuer.create(
            name="Banco Inter",  # Mixed case; will normalize to BANCO INTER
            conglomerate="Banco Inter (manually curated)",
            kind=IssuerKind.COMMERCIAL_BANK,
            tax_id="00416968000101",
        )
        issuer_repo.save(existing)

        result = load_xp_statement(FIXTURE_PATH, factory)

        assert result.issuers_created == 5  # 5 new (everyone except Banco Inter)
        assert result.issuers_reused == 1   # 1 reused (Banco Inter)

        # The existing issuer's record is untouched.
        reloaded = issuer_repo.find_by_normalized_name("Banco Inter")
        assert reloaded is not None
        assert reloaded.id == existing.id
        assert reloaded.conglomerate == "Banco Inter (manually curated)"

    def test_normalizes_issuer_name_for_lookup(
        self, factory, issuer_repo, investment_repo
    ) -> None:
        # The fixture's row 5 has issuer_name "BANCO INTER" (uppercase).
        # If we pre-seed with "banco inter" (lowercase), normalization
        # should still match — proving the loader uses normalized lookup
        # rather than direct string equality.
        existing = Issuer.create(
            name="banco inter",
            conglomerate="lowercase test",
            kind=IssuerKind.COMMERCIAL_BANK,
            tax_id="00416968000101",
        )
        issuer_repo.save(existing)

        load_xp_statement(FIXTURE_PATH, factory)

        # Only one issuer should exist with this normalized name.
        all_issuers = issuer_repo.list_all()
        inter_matches = [
            i for i in all_issuers
            if Issuer.normalize_name(i.name) == "BANCO INTER"
        ]
        assert len(inter_matches) == 1
        assert inter_matches[0].id == existing.id


# ---------- Investment field coverage ----------


class TestInvestmentFields:
    def test_loads_all_four_rate_types(
        self, factory, investment_repo
    ) -> None:
        # The fixture is constructed so that every rate type appears at
        # least once. After load, each Rate subclass should be present
        # among the saved investments. This catches any mapper or rate-
        # dispatch regression that drops a rate type silently.
        load_xp_statement(FIXTURE_PATH, factory)

        all_investments = investment_repo.list_all()
        rate_types = {type(inv.rate) for inv in all_investments}

        assert Prefixed in rate_types
        assert PostFixedCDI in rate_types
        assert PostFixedCDIPlusSpread in rate_types
        assert PostFixedIPCA in rate_types

    def test_loads_monthly_coupon_investment_correctly(
        self, factory, investment_repo
    ) -> None:
        # The fixture's row 3 (CDB PINE) is the only MONTHLY coupon
        # position. After load, exactly one investment should have
        # MONTHLY coupon frequency, and reloading it via repository
        # should preserve that value.
        load_xp_statement(FIXTURE_PATH, factory)

        all_investments = investment_repo.list_all()
        monthly = [
            inv for inv in all_investments
            if inv.coupon_frequency == CouponFrequency.MONTHLY
        ]

        assert len(monthly) == 1
        assert monthly[0].issuer.name == "PINE"