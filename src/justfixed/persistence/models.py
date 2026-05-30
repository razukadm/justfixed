"""SQLAlchemy ORM models — the row shape on disk.

These classes are NOT the domain entities. They are row-shaped data
objects that mirror the database schema. The mapping between domain
objects and these rows happens in `mappers.py`.

Naming convention: ORM classes end in `Row` to make the distinction
visible at every call site (e.g. `IssuerRow` here vs `Issuer` in domain).

Schema notes:
- UUIDs stored as 36-char strings via SQLAlchemy's Uuid type. SQLite
  has no native UUID type; the string form is human-inspectable.
- Decimal stored as Numeric(20, 8) — 20 total digits, 8 after the
  decimal — matching our domain Money precision.
- Enums stored as their `.value` strings (e.g. 'cdb', 'post_fixed_cdi').
  Readable in the database and stable across Python versions.
- Rate is stored as two columns: rate_kind + rate_value. The mapper
  reconstructs the right Rate subclass from these.
- created_at / updated_at are persistence audit fields, not domain.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from justfixed.persistence.database import Base


def _utc_now() -> datetime:
    """Return the current UTC datetime for audit timestamps."""
    return datetime.now(timezone.utc)


class IssuerRow(Base):
    """Row shape for the `issuers` table."""

    __tablename__ = "issuers"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    normalized_name: Mapped[str] = mapped_column(
        String, nullable=False, unique=True, index=True
    )
    conglomerate: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    tax_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        onupdate=_utc_now,
    )

    def __repr__(self) -> str:
        return f"IssuerRow(id={self.id}, name={self.name!r}, kind={self.kind!r})"


class InvestmentRow(Base):
    """Row shape for the `investments` table."""

    __tablename__ = "investments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    product: Mapped[str] = mapped_column(String, nullable=False)

    # FK to the issuer. ondelete='RESTRICT' so we can't accidentally
    # orphan investments by deleting an issuer with positions still open.
    issuer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("issuers.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # Money split into amount and currency.
    principal_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 8), nullable=False
    )
    principal_currency: Mapped[str] = mapped_column(
        String, nullable=False, default="BRL"
    )

    # Rate split into kind discriminator and a single decimal value.
    rate_kind: Mapped[str] = mapped_column(String, nullable=False)
    rate_value: Mapped[Decimal] = mapped_column(
        Numeric(20, 8), nullable=False
    )

    purchase_date: Mapped[date] = mapped_column(nullable=False)
    maturity_date: Mapped[date] = mapped_column(nullable=False)
    issue_date: Mapped[date] = mapped_column(nullable=False)

    coupon_frequency: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False, default="")
    source: Mapped[str] = mapped_column(String, nullable=False, default="xp_import")
    custodian: Mapped[str | None] = mapped_column(String, nullable=True, default=None)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        onupdate=_utc_now,
    )

    # Convenience relationship for tests/debugging. Repository code
    # generally won't use this — explicit joins are clearer.
    issuer: Mapped[IssuerRow] = relationship(IssuerRow, lazy="joined")

    def __repr__(self) -> str:
        return (
            f"InvestmentRow(id={self.id}, product={self.product!r}, "
            f"principal={self.principal_amount} {self.principal_currency})"
        )


class CurationMemoryRow(Base):
    """Row shape for the `curation_memory` table.

    Stores a curated conglomerate string keyed by normalized issuer name.
    When the loader creates a new issuer, it checks this table first; if
    a match exists, the curated conglomerate is used instead of the
    [unverified] default. The primary key is the normalized name so each
    issuer has at most one curated entry.
    """

    __tablename__ = "curation_memory"

    normalized_issuer_name: Mapped[str] = mapped_column(
        String, primary_key=True
    )
    conglomerate: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        onupdate=_utc_now,
    )

    def __repr__(self) -> str:
        return (
            f"CurationMemoryRow("
            f"normalized_issuer_name={self.normalized_issuer_name!r}, "
            f"conglomerate={self.conglomerate!r})"
        )