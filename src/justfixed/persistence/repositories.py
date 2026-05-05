"""Repository layer: clean API for saving and loading domain entities.

Repositories are the only public access point to persistence outside
this package. The engine, UI, and importers should depend on these
classes, not on SQLAlchemy directly.

Lifecycle:
- A repository is constructed with a session factory (sessionmaker).
- Each method opens a short-lived session, does its work, commits or
  rolls back via session_scope, and closes the session.
- This means each method call is one self-contained transaction.
  If you need cross-entity transactions, that's a future enhancement.

Save semantics:
- save() is upsert: insert if the row's id doesn't exist, update if it
  does. We use SQLAlchemy's session.merge() for this.

Idempotency:
- delete() is silent on missing rows.
- save() is naturally idempotent (calling it twice with the same data
  produces the same result).
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session, sessionmaker

from justfixed.domain.investment import Investment
from justfixed.domain.issuer import Issuer
from justfixed.persistence.database import session_scope
from justfixed.persistence.mappers import (
    investment_from_row,
    investment_to_row,
    issuer_from_row,
    issuer_to_row,
)
from justfixed.persistence.models import InvestmentRow, IssuerRow


class IssuerRepository:
    """Persistence access for Issuer entities."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._factory = session_factory

    def save(self, issuer: Issuer) -> None:
        """Insert or update the issuer. Idempotent."""
        row = issuer_to_row(issuer)
        with session_scope(self._factory) as session:
            session.merge(row)

    def find_by_id(self, issuer_id: uuid.UUID) -> Issuer | None:
        """Return the Issuer with this id, or None if not found."""
        with session_scope(self._factory) as session:
            row = session.get(IssuerRow, issuer_id)
            if row is None:
                return None
            return issuer_from_row(row)

    def list_all(self) -> list[Issuer]:
        """Return all issuers, ordered by name."""
        with session_scope(self._factory) as session:
            rows = (
                session.query(IssuerRow)
                .order_by(IssuerRow.name)
                .all()
            )
            return [issuer_from_row(r) for r in rows]

    def delete(self, issuer_id: uuid.UUID) -> None:
        """Delete the issuer. Silent if it doesn't exist.

        Raises if the issuer has investments referencing it (FK RESTRICT).
        """
        with session_scope(self._factory) as session:
            row = session.get(IssuerRow, issuer_id)
            if row is not None:
                session.delete(row)


class InvestmentRepository:
    """Persistence access for Investment entities.

    Note: the Issuer for an investment must already be saved via
    IssuerRepository.save() before save()-ing the investment, or the
    foreign-key constraint will raise IntegrityError.
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._factory = session_factory

    def save(self, investment: Investment) -> None:
        """Insert or update the investment. Idempotent.

        The investment's issuer must already exist in the database.
        """
        row = investment_to_row(investment)
        with session_scope(self._factory) as session:
            session.merge(row)

    def find_by_id(self, investment_id: uuid.UUID) -> Investment | None:
        """Return the Investment with this id, or None if not found."""
        with session_scope(self._factory) as session:
            row = session.get(InvestmentRow, investment_id)
            if row is None:
                return None
            # The relationship is eager-loaded (lazy="joined" on the model),
            # so row.issuer is already populated.
            issuer = issuer_from_row(row.issuer)
            return investment_from_row(row, issuer)

    def list_all(self) -> list[Investment]:
        """Return all investments, ordered by maturity_date ascending."""
        with session_scope(self._factory) as session:
            rows = (
                session.query(InvestmentRow)
                .order_by(InvestmentRow.maturity_date)
                .all()
            )
            return [
                investment_from_row(r, issuer_from_row(r.issuer))
                for r in rows
            ]

    def delete(self, investment_id: uuid.UUID) -> None:
        """Delete the investment. Silent if it doesn't exist."""
        with session_scope(self._factory) as session:
            row = session.get(InvestmentRow, investment_id)
            if row is not None:
                session.delete(row)