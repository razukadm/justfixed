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
from datetime import date

from sqlalchemy.orm import Session, sessionmaker

from justfixed.domain.investment import Investment
from justfixed.domain.issuer import Issuer
from justfixed.domain.money import Money
from justfixed.domain.product import ProductType
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
        
    def find_by_normalized_name(self, name: str) -> Issuer | None:
        """Return the Issuer whose normalized name matches, or None if not found.

        The input is normalized via Issuer.normalize_name before lookup, so
        callers can pass the raw name they have on hand — typically a parsed
        issuer name from an XP statement — without pre-normalizing.

        Args:
            name: Any string. Will be normalized (uppercase, trim, collapse
                  whitespace) before the database lookup.

        Returns:
            The matching Issuer, or None if no issuer with that normalized
            name exists.
        """
        normalized = Issuer.normalize_name(name)
        with session_scope(self._factory) as session:
            row = (
                session.query(IssuerRow)
                .filter(IssuerRow.normalized_name == normalized)
                .one_or_none()
            )
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
        
    def find_by_natural_key(
        self,
        issuer_id: uuid.UUID,
        product: ProductType,
        principal: Money,
        purchase_date: date,
        maturity_date: date,
    ) -> Investment | None:
        """Find an investment matching this natural key, or None.

        The natural key (issuer + product + principal + dates) is the
        importer's idempotency mechanism: re-importing the same XP statement
        finds existing rows by this key rather than creating duplicates.

        Note: there is no unique constraint enforcing this on the database.
        A user can legitimately hold two identical positions (separate
        orders, same broker, same day, same parameters). The natural key
        is the *importer's* deduplication contract, not a domain invariant.

        Args:
            issuer_id: UUID of the issuing entity.
            product: ProductType (CDB, LCI, etc.).
            principal: Money — exact match required (Decimal comparison).
            purchase_date: When this user acquired the position.
            maturity_date: When the position pays out.

        Returns:
            The matching Investment, or None if no investment with this
            natural key exists.

        Raises:
            sqlalchemy.exc.MultipleResultsFound: If more than one investment
            matches. This signals a data integrity problem — the natural key
            is treated as effectively unique by the importer, and the
            database having two matches means something bypassed it.
        """
        with session_scope(self._factory) as session:
            row = (
                session.query(InvestmentRow)
                .filter(InvestmentRow.issuer_id == issuer_id)
                .filter(InvestmentRow.product == product.value)
                .filter(InvestmentRow.principal_amount == principal.amount)
                .filter(InvestmentRow.principal_currency == principal.currency)
                .filter(InvestmentRow.purchase_date == purchase_date)
                .filter(InvestmentRow.maturity_date == maturity_date)
                .one_or_none()
            )
            if row is None:
                return None
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