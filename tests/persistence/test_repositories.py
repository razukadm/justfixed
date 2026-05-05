"""Tests for the repository layer — end-to-end domain ↔ database."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from justfixed.domain.investment import Investment
from justfixed.domain.issuer import Issuer, IssuerKind
from justfixed.domain.money import Money
from justfixed.domain.product import CouponFrequency, ProductType
from justfixed.domain.rates import PostFixedCDI, PostFixedIPCA, Prefixed
from justfixed.persistence.database import (
    Base,
    make_engine,
    make_session_factory,
)
from justfixed.persistence.repositories import (
    InvestmentRepository,
    IssuerRepository,
)


# ---------- Fixtures ----------


@pytest.fixture
def factory():
    """Fresh in-memory SQLite database per test, with schema created."""
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    yield factory
    engine.dispose()


@pytest.fixture
def issuer_repo(factory):
    return IssuerRepository(factory)


@pytest.fixture
def investment_repo(factory):
    return InvestmentRepository(factory)


def make_issuer(name: str = "Banco Inter") -> Issuer:
    return Issuer.create(
        name=name,
        conglomerate=name + " S.A.",
        kind=IssuerKind.COMMERCIAL_BANK,
        tax_id="00416968000101",
    )


def make_investment(issuer: Issuer, **overrides) -> Investment:
    defaults: dict = {
        "product": ProductType.CDB,
        "issuer": issuer,
        "principal": Money.from_reais("10000"),
        "rate": PostFixedCDI.from_percent("110"),
        "purchase_date": date(2024, 1, 15),
        "maturity_date": date(2026, 1, 15),
    }
    defaults.update(overrides)
    return Investment.create(**defaults)


# ---------- IssuerRepository ----------


class TestIssuerSave:
    def test_save_then_find(self, issuer_repo) -> None:
        issuer = make_issuer()
        issuer_repo.save(issuer)

        loaded = issuer_repo.find_by_id(issuer.id)
        assert loaded is not None
        assert loaded == issuer  # same id
        assert loaded.name == "Banco Inter"
        assert loaded.kind == IssuerKind.COMMERCIAL_BANK

    def test_save_is_upsert(self, issuer_repo) -> None:
        issuer = make_issuer()
        issuer_repo.save(issuer)

        # Mutate and save again. find_by_id should reflect the new name.
        issuer.name = "Banco Inter Renamed"
        issuer_repo.save(issuer)

        loaded = issuer_repo.find_by_id(issuer.id)
        assert loaded is not None
        assert loaded.name == "Banco Inter Renamed"

    def test_find_by_id_returns_none_for_missing(self, issuer_repo) -> None:
        result = issuer_repo.find_by_id(uuid.uuid4())
        assert result is None


class TestIssuerListAll:
    def test_empty_database_returns_empty_list(self, issuer_repo) -> None:
        assert issuer_repo.list_all() == []

    def test_lists_all_saved_issuers(self, issuer_repo) -> None:
        a = make_issuer("Banco Alpha")
        b = make_issuer("Banco Beta")
        issuer_repo.save(a)
        issuer_repo.save(b)

        all_issuers = issuer_repo.list_all()
        ids = {i.id for i in all_issuers}
        assert ids == {a.id, b.id}

    def test_results_ordered_by_name(self, issuer_repo) -> None:
        z = make_issuer("Zebra Bank")
        a = make_issuer("Alpha Bank")
        m = make_issuer("Middle Bank")
        for i in [z, a, m]:
            issuer_repo.save(i)

        names = [i.name for i in issuer_repo.list_all()]
        assert names == ["Alpha Bank", "Middle Bank", "Zebra Bank"]


class TestIssuerDelete:
    def test_delete_removes_issuer(self, issuer_repo) -> None:
        issuer = make_issuer()
        issuer_repo.save(issuer)

        issuer_repo.delete(issuer.id)
        assert issuer_repo.find_by_id(issuer.id) is None

    def test_delete_missing_id_is_silent(self, issuer_repo) -> None:
        # No exception, no error.
        issuer_repo.delete(uuid.uuid4())

    def test_cannot_delete_issuer_with_investments(
        self, issuer_repo, investment_repo
    ) -> None:
        issuer = make_issuer()
        issuer_repo.save(issuer)
        investment_repo.save(make_investment(issuer))

        with pytest.raises(IntegrityError):
            issuer_repo.delete(issuer.id)


# ---------- InvestmentRepository ----------


class TestInvestmentSave:
    def test_save_then_find(self, issuer_repo, investment_repo) -> None:
        issuer = make_issuer()
        issuer_repo.save(issuer)
        inv = make_investment(issuer)
        investment_repo.save(inv)

        loaded = investment_repo.find_by_id(inv.id)
        assert loaded is not None
        assert loaded == inv
        assert loaded.product == ProductType.CDB
        assert loaded.principal == Money.from_reais("10000")
        assert loaded.rate == PostFixedCDI.from_percent("110")
        assert loaded.issuer.id == issuer.id

    def test_save_is_upsert(self, issuer_repo, investment_repo) -> None:
        issuer = make_issuer()
        issuer_repo.save(issuer)
        inv = make_investment(issuer, description="Original")
        investment_repo.save(inv)

        inv.description = "Updated"
        investment_repo.save(inv)

        loaded = investment_repo.find_by_id(inv.id)
        assert loaded is not None
        assert loaded.description == "Updated"

    def test_save_without_issuer_fails(self, investment_repo) -> None:
        # The issuer was never saved. FK constraint fires.
        issuer = make_issuer()
        inv = make_investment(issuer)
        with pytest.raises(IntegrityError):
            investment_repo.save(inv)

    def test_find_by_id_returns_none_for_missing(self, investment_repo) -> None:
        assert investment_repo.find_by_id(uuid.uuid4()) is None


class TestInvestmentListAll:
    def test_empty_database_returns_empty_list(self, investment_repo) -> None:
        assert investment_repo.list_all() == []

    def test_lists_all_saved(self, issuer_repo, investment_repo) -> None:
        issuer = make_issuer()
        issuer_repo.save(issuer)

        a = make_investment(issuer, maturity_date=date(2026, 6, 1))
        b = make_investment(issuer, maturity_date=date(2027, 1, 15))
        investment_repo.save(a)
        investment_repo.save(b)

        ids = {i.id for i in investment_repo.list_all()}
        assert ids == {a.id, b.id}

    def test_results_ordered_by_maturity(
        self, issuer_repo, investment_repo
    ) -> None:
        issuer = make_issuer()
        issuer_repo.save(issuer)

        late = make_investment(issuer, maturity_date=date(2030, 1, 15))
        early = make_investment(issuer, maturity_date=date(2025, 1, 15))
        mid = make_investment(issuer, maturity_date=date(2027, 6, 1))
        for inv in [late, early, mid]:
            investment_repo.save(inv)

        all_invs = investment_repo.list_all()
        maturities = [i.maturity_date for i in all_invs]
        assert maturities == [
            date(2025, 1, 15),
            date(2027, 6, 1),
            date(2030, 1, 15),
        ]


class TestInvestmentDelete:
    def test_delete_removes_investment(
        self, issuer_repo, investment_repo
    ) -> None:
        issuer = make_issuer()
        issuer_repo.save(issuer)
        inv = make_investment(issuer)
        investment_repo.save(inv)

        investment_repo.delete(inv.id)
        assert investment_repo.find_by_id(inv.id) is None

    def test_delete_missing_id_is_silent(self, investment_repo) -> None:
        investment_repo.delete(uuid.uuid4())


# ---------- End-to-end realistic scenario ----------


class TestRealisticScenario:
    """A realistic flow: save several issuers and investments, query them."""

    def test_portfolio_round_trip(self, issuer_repo, investment_repo) -> None:
        # Setup: a commercial bank, a development bank, the treasury.
        inter = Issuer.create(
            "Banco Inter", "Banco Inter S.A.", IssuerKind.COMMERCIAL_BANK
        )
        bndes = Issuer.create("BNDES", "BNDES", IssuerKind.DEVELOPMENT_BANK)
        treasury = Issuer.treasury()
        for i in [inter, bndes, treasury]:
            issuer_repo.save(i)

        # A diversified portfolio.
        cdb = Investment.create(
            product=ProductType.CDB,
            issuer=inter,
            principal=Money.from_reais("50000"),
            rate=PostFixedCDI.from_percent("112"),
            purchase_date=date(2024, 6, 1),
            maturity_date=date(2027, 6, 1),
        )
        lcd = Investment.create(
            product=ProductType.LCD,
            issuer=bndes,
            principal=Money.from_reais("20000"),
            rate=PostFixedCDI.from_percent("100"),
            purchase_date=date(2026, 5, 4),
            maturity_date=date(2026, 10, 1),
            issue_date=date(2025, 10, 1),  # secondary market
        )
        tesouro = Investment.create(
            product=ProductType.TESOURO_IPCA,
            issuer=treasury,
            principal=Money.from_reais("100000"),
            rate=PostFixedIPCA.from_percent("5.75"),
            purchase_date=date(2024, 1, 15),
            maturity_date=date(2035, 5, 15),
        )
        for inv in [cdb, lcd, tesouro]:
            investment_repo.save(inv)

        # Query: all investments, ordered by maturity.
        portfolio = investment_repo.list_all()
        assert len(portfolio) == 3
        assert portfolio[0].id == lcd.id  # earliest maturity
        assert portfolio[2].id == tesouro.id  # latest maturity

        # Each one has its full domain identity reconstructed.
        loaded_cdb = investment_repo.find_by_id(cdb.id)
        assert loaded_cdb is not None
        assert loaded_cdb.issuer.name == "Banco Inter"
        assert loaded_cdb.is_fgc_covered is True

        loaded_tesouro = investment_repo.find_by_id(tesouro.id)
        assert loaded_tesouro is not None
        assert loaded_tesouro.is_fgc_covered is False
        assert isinstance(loaded_tesouro.rate, PostFixedIPCA)

        loaded_lcd = investment_repo.find_by_id(lcd.id)
        assert loaded_lcd is not None
        assert loaded_lcd.is_secondary_market is True
        assert loaded_lcd.security_term_days == 365