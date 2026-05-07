"""Tests for the ORM row models — schema and basic CRUD against SQLite."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from justfixed.persistence.database import (
    Base,
    make_engine,
    make_session_factory,
    session_scope,
)
from justfixed.persistence.models import InvestmentRow, IssuerRow


# ---------- Test fixtures ----------


@pytest.fixture
def factory():
    """Fresh in-memory SQLite database with schema, per test."""
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    yield factory
    engine.dispose()


def make_issuer_row(**overrides) -> IssuerRow:
    """Build an IssuerRow with sensible defaults."""
    defaults = {
        "id": uuid.uuid4(),
        "name": "Banco Inter",
        "normalized_name": "BANCO INTER",
        "conglomerate": "Banco Inter S.A.",
        "kind": "commercial_bank",
        "tax_id": "00416968000101",
    }
    defaults.update(overrides)
    return IssuerRow(**defaults)


def make_investment_row(issuer_id: uuid.UUID, **overrides) -> InvestmentRow:
    """Build an InvestmentRow with sensible defaults."""
    defaults = {
        "id": uuid.uuid4(),
        "product": "cdb",
        "issuer_id": issuer_id,
        "principal_amount": Decimal("10000.00"),
        "principal_currency": "BRL",
        "rate_kind": "post_fixed_cdi",
        "rate_value": Decimal("1.10"),
        "purchase_date": date(2024, 1, 15),
        "maturity_date": date(2026, 1, 15),
        "issue_date": date(2024, 1, 15),
        "coupon_frequency": "none",
        "description": "",
    }
    defaults.update(overrides)
    return InvestmentRow(**defaults)


# ---------- Schema creation ----------


class TestSchemaCreation:
    def test_create_all_succeeds(self, factory) -> None:
        # Just creating the fixture means create_all already ran.
        with session_scope(factory) as session:
            assert session.query(IssuerRow).count() == 0
            assert session.query(InvestmentRow).count() == 0


# ---------- IssuerRow round-trip ----------


class TestIssuerRow:
    def test_insert_and_load(self, factory) -> None:
        row_id = uuid.uuid4()
        with session_scope(factory) as session:
            session.add(make_issuer_row(id=row_id))

        with session_scope(factory) as session:
            loaded = session.get(IssuerRow, row_id)
            assert loaded is not None
            assert loaded.name == "Banco Inter"
            assert loaded.conglomerate == "Banco Inter S.A."
            assert loaded.kind == "commercial_bank"
            assert loaded.tax_id == "00416968000101"

    def test_uuid_round_trip(self, factory) -> None:
        # UUID stored as string but exposed as uuid.UUID.
        row_id = uuid.uuid4()
        with session_scope(factory) as session:
            session.add(make_issuer_row(id=row_id))

        with session_scope(factory) as session:
            loaded = session.get(IssuerRow, row_id)
            assert isinstance(loaded.id, uuid.UUID)
            assert loaded.id == row_id

    def test_audit_timestamps_populated(self, factory) -> None:
        row_id = uuid.uuid4()
        with session_scope(factory) as session:
            session.add(make_issuer_row(id=row_id))

        with session_scope(factory) as session:
            loaded = session.get(IssuerRow, row_id)
            assert loaded.created_at is not None
            assert loaded.updated_at is not None

    def test_default_tax_id_is_empty(self, factory) -> None:
        row_id = uuid.uuid4()
        with session_scope(factory) as session:
            row = IssuerRow(
                id=row_id,
                name="No Tax ID Bank",
                normalized_name="NO TAX ID BANK",
                conglomerate="No Tax ID",
                kind="commercial_bank",
            )
            session.add(row)

        with session_scope(factory) as session:
            loaded = session.get(IssuerRow, row_id)
            assert loaded.tax_id == ""


# ---------- InvestmentRow round-trip ----------


class TestInvestmentRow:
    def test_insert_and_load(self, factory) -> None:
        issuer_id = uuid.uuid4()
        inv_id = uuid.uuid4()

        with session_scope(factory) as session:
            session.add(make_issuer_row(id=issuer_id))
            session.add(make_investment_row(issuer_id=issuer_id, id=inv_id))

        with session_scope(factory) as session:
            loaded = session.get(InvestmentRow, inv_id)
            assert loaded is not None
            assert loaded.product == "cdb"
            assert loaded.issuer_id == issuer_id
            assert loaded.principal_amount == Decimal("10000.00")
            assert loaded.principal_currency == "BRL"
            assert loaded.rate_kind == "post_fixed_cdi"
            assert loaded.rate_value == Decimal("1.10")
            assert loaded.purchase_date == date(2024, 1, 15)
            assert loaded.maturity_date == date(2026, 1, 15)
            assert loaded.issue_date == date(2024, 1, 15)
            assert loaded.coupon_frequency == "none"

    def test_decimal_precision_preserved(self, factory) -> None:
        # Critical for financial software: 8 decimal places must round-trip
        # exactly, with no float drift.
        issuer_id = uuid.uuid4()
        inv_id = uuid.uuid4()
        precise = Decimal("12345.67891234")

        with session_scope(factory) as session:
            session.add(make_issuer_row(id=issuer_id))
            session.add(
                make_investment_row(
                    issuer_id=issuer_id,
                    id=inv_id,
                    principal_amount=precise,
                )
            )

        with session_scope(factory) as session:
            loaded = session.get(InvestmentRow, inv_id)
            assert loaded.principal_amount == precise

    def test_relationship_loads_issuer(self, factory) -> None:
        issuer_id = uuid.uuid4()
        inv_id = uuid.uuid4()

        with session_scope(factory) as session:
            session.add(make_issuer_row(id=issuer_id))
            session.add(make_investment_row(issuer_id=issuer_id, id=inv_id))

        with session_scope(factory) as session:
            loaded = session.get(InvestmentRow, inv_id)
            assert loaded.issuer is not None
            assert loaded.issuer.id == issuer_id
            assert loaded.issuer.name == "Banco Inter"


# ---------- Foreign key enforcement ----------


class TestForeignKeyConstraint:
    def test_investment_with_nonexistent_issuer_rejected(self, factory) -> None:
        # The FK constraint should prevent orphan rows. This relies on
        # the PRAGMA foreign_keys=ON we set in database.py.
        nonexistent_issuer = uuid.uuid4()
        with pytest.raises(IntegrityError):
            with session_scope(factory) as session:
                session.add(make_investment_row(issuer_id=nonexistent_issuer))

    def test_cannot_delete_issuer_with_investments(self, factory) -> None:
        issuer_id = uuid.uuid4()
        inv_id = uuid.uuid4()

        with session_scope(factory) as session:
            session.add(make_issuer_row(id=issuer_id))
            session.add(make_investment_row(issuer_id=issuer_id, id=inv_id))

        # ondelete=RESTRICT means deleting the issuer fails.
        with pytest.raises(IntegrityError):
            with session_scope(factory) as session:
                issuer = session.get(IssuerRow, issuer_id)
                session.delete(issuer)


# ---------- Update behavior ----------


class TestUpdates:
    def test_updated_at_advances_on_change(self, factory) -> None:
        import time

        row_id = uuid.uuid4()
        with session_scope(factory) as session:
            session.add(make_issuer_row(id=row_id))

        # Capture initial timestamp.
        with session_scope(factory) as session:
            initial = session.get(IssuerRow, row_id).updated_at

        # Sleep briefly to ensure measurable timestamp delta.
        time.sleep(0.01)

        with session_scope(factory) as session:
            row = session.get(IssuerRow, row_id)
            row.name = "Renamed Bank"

        with session_scope(factory) as session:
            after = session.get(IssuerRow, row_id).updated_at
            assert after > initial