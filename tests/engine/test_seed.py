"""Tests for engine/seed.py — first-run seed loader."""

from __future__ import annotations

import pytest

from justfixed.engine.seed import load_seed_if_empty
from justfixed.persistence.database import Base, make_engine, make_session_factory
from justfixed.persistence.repositories import IssuerRepository


SAMPLE_SEED = {
    "as_of": "2026-05-15",
    "schema_version": 1,
    "issuers": [
        {
            "name": "Banco Inter",
            "conglomerate": "Banco Inter S.A.",
            "kind": "commercial_bank",
            "tax_id": "",
        },
        {
            "name": "BDMG",
            "conglomerate": "BDMG",
            "kind": "development_bank",
            "tax_id": "",
        },
    ],
}


@pytest.fixture
def factory():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    f = make_session_factory(engine)
    yield f
    engine.dispose()


@pytest.fixture
def issuer_repo(factory):
    return IssuerRepository(factory)


class TestLoadSeedIfEmpty:
    def test_inserts_all_issuers_on_empty_db(self, issuer_repo) -> None:
        inserted = load_seed_if_empty(issuer_repo, SAMPLE_SEED)
        assert inserted == 2
        assert len(issuer_repo.list_all()) == 2

    def test_does_nothing_on_nonempty_db(self, issuer_repo) -> None:
        load_seed_if_empty(issuer_repo, SAMPLE_SEED)
        # Second call must be a no-op even with the same data.
        inserted = load_seed_if_empty(issuer_repo, SAMPLE_SEED)
        assert inserted == 0
        assert len(issuer_repo.list_all()) == 2

    def test_does_nothing_when_seed_data_is_none(self, issuer_repo) -> None:
        inserted = load_seed_if_empty(issuer_repo, None)
        assert inserted == 0
        assert issuer_repo.list_all() == []

    def test_duplicate_normalized_names_raises(self, issuer_repo) -> None:
        bad_seed = {
            "issuers": [
                {"name": "Banco Inter",  "conglomerate": "X", "kind": "commercial_bank"},
                {"name": "banco inter",  "conglomerate": "Y", "kind": "commercial_bank"},
            ]
        }
        with pytest.raises(ValueError, match="duplicate"):
            load_seed_if_empty(issuer_repo, bad_seed)

    def test_preserves_conglomerate_field(self, issuer_repo) -> None:
        load_seed_if_empty(issuer_repo, SAMPLE_SEED)
        by_name = {i.name: i for i in issuer_repo.list_all()}
        assert by_name["Banco Inter"].conglomerate == "Banco Inter S.A."
        assert by_name["BDMG"].conglomerate == "BDMG"

    def test_empty_issuers_list_returns_zero(self, issuer_repo) -> None:
        inserted = load_seed_if_empty(issuer_repo, {"issuers": []})
        assert inserted == 0
        assert issuer_repo.list_all() == []

    def test_missing_issuers_key_returns_zero(self, issuer_repo) -> None:
        inserted = load_seed_if_empty(issuer_repo, {"as_of": "2026-05-15"})
        assert inserted == 0
        assert issuer_repo.list_all() == []
