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


class TestIssuerFindByNormalizedName:
    def test_returns_none_when_database_is_empty(self, issuer_repo) -> None:
        assert issuer_repo.find_by_normalized_name("Banco Inter") is None

    def test_returns_none_when_no_match(self, issuer_repo) -> None:
        issuer_repo.save(make_issuer("Banco Inter"))
        assert issuer_repo.find_by_normalized_name("Banco BV") is None

    def test_finds_issuer_by_exact_name(self, issuer_repo) -> None:
        saved = make_issuer("Banco Inter")
        issuer_repo.save(saved)
        found = issuer_repo.find_by_normalized_name("Banco Inter")
        assert found is not None
        assert found.id == saved.id
        assert found.name == "Banco Inter"

    def test_finds_issuer_by_lowercase_name(self, issuer_repo) -> None:
        saved = make_issuer("Banco Inter")
        issuer_repo.save(saved)
        found = issuer_repo.find_by_normalized_name("banco inter")
        assert found is not None
        assert found.id == saved.id

    def test_finds_issuer_by_name_with_extra_whitespace(self, issuer_repo) -> None:
        saved = make_issuer("Banco Inter")
        issuer_repo.save(saved)
        found = issuer_repo.find_by_normalized_name("  Banco   Inter  ")
        assert found is not None
        assert found.id == saved.id

    def test_does_not_find_distinct_issuers_with_similar_names(
        self, issuer_repo
    ) -> None:
        # "Banco Inter" and "Banco Inter S/A" normalize to different strings;
        # the lookup must not collapse them. This documents that we
        # deliberately do not try to be clever about punctuation variants.
        issuer_repo.save(make_issuer("Banco Inter S/A"))
        assert issuer_repo.find_by_normalized_name("Banco Inter") is None

    def test_unique_constraint_prevents_duplicate_normalized_names(
        self, issuer_repo
    ) -> None:
        # "Banco Inter" and "BANCO INTER" normalize to the same string.
        # The database's unique index on normalized_name must reject the
        # second insert. We catch IntegrityError specifically — a different
        # exception would mean the constraint is wrong or missing.
        from sqlalchemy.exc import IntegrityError

        issuer_repo.save(make_issuer("Banco Inter"))
        with pytest.raises(IntegrityError):
            issuer_repo.save(make_issuer("BANCO INTER"))

    def test_finds_treasury_by_canonical_name(self, issuer_repo) -> None:
        # The Tesouro Nacional issuer must be findable via its canonical name
        # — this is exactly how the loader will route NTN-B parsings.
        treasury = Issuer.treasury()
        issuer_repo.save(treasury)
        found = issuer_repo.find_by_normalized_name("Tesouro Nacional")
        assert found is not None
        assert found.id == treasury.id

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


class TestInvestmentFindByNaturalKey:
    # The natural key is (issuer_id, product, principal, purchase_date,
    # maturity_date). All five fields participate. The "differs" tests
    # below collectively prove that — drop any one filter from the
    # production code and one of these tests fails.

    def test_returns_none_when_database_is_empty(
        self, issuer_repo, investment_repo
    ) -> None:
        # Arrange a fake key. The issuer doesn't even exist in the DB —
        # the lookup should still gracefully return None, not crash.
        result = investment_repo.find_by_natural_key(
            issuer_id=uuid.uuid4(),
            product=ProductType.CDB,
            principal=Money.from_reais("10000"),
            purchase_date=date(2024, 1, 15),
            maturity_date=date(2026, 1, 15),
        )
        assert result is None

    def test_finds_matching_investment(
        self, issuer_repo, investment_repo
    ) -> None:
        issuer = make_issuer()
        issuer_repo.save(issuer)
        inv = make_investment(issuer)
        investment_repo.save(inv)

        found = investment_repo.find_by_natural_key(
            issuer_id=issuer.id,
            product=inv.product,
            principal=inv.principal,
            purchase_date=inv.purchase_date,
            maturity_date=inv.maturity_date,
        )
        assert found is not None
        assert found.id == inv.id

    def test_returns_none_when_issuer_differs(
        self, issuer_repo, investment_repo
    ) -> None:
        issuer = make_issuer("Banco Inter")
        issuer_repo.save(issuer)
        other_issuer = make_issuer("Banco BV")
        issuer_repo.save(other_issuer)
        investment_repo.save(make_investment(issuer))

        result = investment_repo.find_by_natural_key(
            issuer_id=other_issuer.id,
            product=ProductType.CDB,
            principal=Money.from_reais("10000"),
            purchase_date=date(2024, 1, 15),
            maturity_date=date(2026, 1, 15),
        )
        assert result is None

    def test_returns_none_when_product_differs(
        self, issuer_repo, investment_repo
    ) -> None:
        issuer = make_issuer()
        issuer_repo.save(issuer)
        investment_repo.save(make_investment(issuer, product=ProductType.CDB))

        result = investment_repo.find_by_natural_key(
            issuer_id=issuer.id,
            product=ProductType.LCI,  # Different product, all else equal
            principal=Money.from_reais("10000"),
            purchase_date=date(2024, 1, 15),
            maturity_date=date(2026, 1, 15),
        )
        assert result is None

    def test_returns_none_when_principal_differs(
        self, issuer_repo, investment_repo
    ) -> None:
        # One cent difference must be enough to miss the match.
        # Decimal comparison is exact; this proves the query uses it
        # correctly rather than (say) an integer-rounded comparison.
        issuer = make_issuer()
        issuer_repo.save(issuer)
        investment_repo.save(
            make_investment(issuer, principal=Money.from_reais("10000.00"))
        )

        result = investment_repo.find_by_natural_key(
            issuer_id=issuer.id,
            product=ProductType.CDB,
            principal=Money.from_reais("10000.01"),
            purchase_date=date(2024, 1, 15),
            maturity_date=date(2026, 1, 15),
        )
        assert result is None

    def test_returns_none_when_purchase_date_differs(
        self, issuer_repo, investment_repo
    ) -> None:
        issuer = make_issuer()
        issuer_repo.save(issuer)
        investment_repo.save(
            make_investment(issuer, purchase_date=date(2024, 1, 15))
        )

        result = investment_repo.find_by_natural_key(
            issuer_id=issuer.id,
            product=ProductType.CDB,
            principal=Money.from_reais("10000"),
            purchase_date=date(2024, 1, 16),  # One day later
            maturity_date=date(2026, 1, 15),
        )
        assert result is None

    def test_returns_none_when_maturity_date_differs(
        self, issuer_repo, investment_repo
    ) -> None:
        issuer = make_issuer()
        issuer_repo.save(issuer)
        investment_repo.save(
            make_investment(issuer, maturity_date=date(2026, 1, 15))
        )

        result = investment_repo.find_by_natural_key(
            issuer_id=issuer.id,
            product=ProductType.CDB,
            principal=Money.from_reais("10000"),
            purchase_date=date(2024, 1, 15),
            maturity_date=date(2026, 1, 16),  # One day later
        )
        assert result is None

    def test_finds_correct_match_among_multiple_investments(
        self, issuer_repo, investment_repo
    ) -> None:
        # Realistic case: multiple investments share some fields, the
        # query has to pick the right one.
        issuer = make_issuer()
        issuer_repo.save(issuer)
        target = make_investment(
            issuer,
            principal=Money.from_reais("25000"),
            purchase_date=date(2024, 6, 1),
            maturity_date=date(2027, 6, 1),
        )
        investment_repo.save(target)
        # Decoys: same issuer, same product, but different other fields.
        investment_repo.save(
            make_investment(
                issuer,
                principal=Money.from_reais("10000"),
                purchase_date=date(2024, 6, 1),
                maturity_date=date(2027, 6, 1),
            )
        )
        investment_repo.save(
            make_investment(
                issuer,
                principal=Money.from_reais("25000"),
                purchase_date=date(2024, 6, 2),
                maturity_date=date(2027, 6, 1),
            )
        )
        investment_repo.save(
            make_investment(
                issuer,
                principal=Money.from_reais("25000"),
                purchase_date=date(2024, 6, 1),
                maturity_date=date(2027, 6, 2),
            )
        )

        found = investment_repo.find_by_natural_key(
            issuer_id=issuer.id,
            product=target.product,
            principal=target.principal,
            purchase_date=target.purchase_date,
            maturity_date=target.maturity_date,
        )
        assert found is not None
        assert found.id == target.id
        

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


class TestInvestmentDeleteAll:
    def test_delete_all_returns_counts(
        self, issuer_repo, investment_repo
    ) -> None:
        a = make_issuer("Banco Alpha")
        b = make_issuer("Banco Beta")
        issuer_repo.save(a)
        issuer_repo.save(b)
        investment_repo.save(make_investment(a, maturity_date=date(2026, 6, 1)))
        investment_repo.save(make_investment(b, maturity_date=date(2027, 1, 15)))
        investment_repo.save(make_investment(b, maturity_date=date(2028, 3, 1)))

        assert investment_repo.delete_all() == (3, 2)

    def test_delete_all_empties_both_repos(
        self, issuer_repo, investment_repo
    ) -> None:
        a = make_issuer("Banco Alpha")
        b = make_issuer("Banco Beta")
        issuer_repo.save(a)
        issuer_repo.save(b)
        investment_repo.save(make_investment(a, maturity_date=date(2026, 6, 1)))
        investment_repo.save(make_investment(b, maturity_date=date(2027, 1, 15)))
        investment_repo.save(make_investment(b, maturity_date=date(2028, 3, 1)))

        investment_repo.delete_all()

        assert investment_repo.list_all() == []
        assert issuer_repo.list_all() == []

    def test_delete_all_on_empty_db(self, investment_repo) -> None:
        # Exercises the empty-orphan-list guard in delete_all.
        assert investment_repo.delete_all() == (0, 0)

    def test_save_works_after_delete_all(
        self, issuer_repo, investment_repo
    ) -> None:
        a = make_issuer("Banco Alpha")
        issuer_repo.save(a)
        investment_repo.save(make_investment(a))
        investment_repo.delete_all()

        b = make_issuer("Banco Beta")
        issuer_repo.save(b)
        inv = make_investment(b)
        investment_repo.save(inv)

        loaded = investment_repo.list_all()
        assert len(loaded) == 1
        assert loaded[0].id == inv.id


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