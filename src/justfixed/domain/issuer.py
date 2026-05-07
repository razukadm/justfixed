"""Issuer entity: a bank or government entity that issues fixed-income products.

Issuers are entities (have identity), unlike Money and Rate (value objects).
Two Issuers with the same name and CNPJ are still distinct if their UUIDs
differ. This matters for data deduplication and audit trails.

FGC coverage is determined by the issuer's kind:
- COMMERCIAL_BANK and DEVELOPMENT_BANK: FGC-covered (R$250k per CPF per
  conglomerate, R$1M per 4-year period overall).
- TREASURY: not FGC-covered (sovereign credit only).

The conglomerate field exists separately from name because the FGC limit
is calculated per conglomerate, not per brand. Itau and Unibanco are
distinct names but a single conglomerate.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Self


# Marker prefix written into Issuer.conglomerate when the issuer's
# origin (e.g. the XP importer) has no curated conglomerate mapping.
# The FGC concentration check (when built) treats issuers with this
# prefix as "needs human review" — the user, or a future curated
# mapping, replaces the prefixed value with the real conglomerate name
# (e.g. "Itaú Unibanco Holding").
#
# This is a string convention, not a schema constraint. Future migration
# to a nullable conglomerate field would replace these values with NULL
# via a one-line UPDATE.
UNVERIFIED_CONGLOMERATE_PREFIX = "[unverified] "


class IssuerKind(Enum):
    """Categorization of issuers for FGC and product-eligibility logic."""

    COMMERCIAL_BANK = "commercial_bank"
    DEVELOPMENT_BANK = "development_bank"
    TREASURY = "treasury"

    @property
    def is_fgc_covered(self) -> bool:
        """Whether products from this issuer kind are FGC-covered."""
        return self in {IssuerKind.COMMERCIAL_BANK, IssuerKind.DEVELOPMENT_BANK}


def _normalize_cnpj(cnpj: str) -> str:
    """Strip non-digits from a CNPJ. Returns 14-digit string or empty."""
    digits = re.sub(r"\D", "", cnpj)
    if digits and len(digits) != 14:
        raise ValueError(
            f"CNPJ must have 14 digits after normalization; got {len(digits)}: {cnpj!r}"
        )
    return digits


@dataclass(slots=True)
class Issuer:
    """A bank or government entity issuing fixed-income products.

    Identity is by UUID (`id`), not by name or CNPJ. This means two Issuer
    instances with the same name but different IDs are distinct entities.
    Use `Issuer.create(...)` to construct new issuers with auto-generated IDs;
    pass an explicit `id` only when reconstructing from persistence.
    """

    name: str
    conglomerate: str
    kind: IssuerKind
    tax_id: str = ""  # CNPJ, normalized to 14 digits, "" if unknown
    id: uuid.UUID = field(default_factory=uuid.uuid4)

    def __post_init__(self) -> None:
        # Normalize fields. Fail fast on bad data.
        if not self.name.strip():
            raise ValueError("Issuer name cannot be empty.")
        if not self.conglomerate.strip():
            raise ValueError("Issuer conglomerate cannot be empty.")
        self.name = self.name.strip()
        self.conglomerate = self.conglomerate.strip()
        self.tax_id = _normalize_cnpj(self.tax_id) if self.tax_id else ""

    @classmethod
    def create(
        cls,
        name: str,
        conglomerate: str,
        kind: IssuerKind,
        tax_id: str = "",
    ) -> Self:
        """Create a new Issuer with an auto-generated UUID."""
        return cls(
            name=name,
            conglomerate=conglomerate,
            kind=kind,
            tax_id=tax_id,
        )

    @classmethod
    def treasury(cls) -> Self:
        """The singleton-ish Tesouro Nacional issuer.

        Note: a fresh UUID is generated per call; in persistence we'll
        store one canonical Treasury record with a stable ID.
        """
        return cls(
            name="Tesouro Nacional",
            conglomerate="Tesouro Nacional",
            kind=IssuerKind.TREASURY,
            tax_id="00394460000141",  # CNPJ of Secretaria do Tesouro Nacional
        )
    
    @classmethod
    def normalize_name(cls, name: str) -> str:
        """Return a canonical form of an issuer name for matching.

        Used by persistence to find existing issuers regardless of
        capitalization or incidental whitespace differences. Two names
        that normalize to the same string are treated as the same issuer.

        Rules:
          1. Strip leading/trailing whitespace
          2. Collapse internal whitespace runs to a single space
          3. Uppercase

        Punctuation and accents are preserved: "Banco BV S/A" and
        "Banco BV SA" remain distinct, as do "São" and "Sao". The
        loader matches on exact (post-normalization) equality only.

        Examples:
            >>> Issuer.normalize_name("Banco BV S/A")
            'BANCO BV S/A'
            >>> Issuer.normalize_name("  banco  bv  s/a  ")
            'BANCO BV S/A'
        """
        return re.sub(r"\s+", " ", name.strip()).upper()
    
    @property
    def is_fgc_covered(self) -> bool:
        """Whether products from this issuer are FGC-covered.

        Convenience accessor; the underlying logic lives on IssuerKind.
        """
        return self.kind.is_fgc_covered

    @property
    def tax_id_display(self) -> str:
        """Format CNPJ as XX.XXX.XXX/XXXX-XX for display."""
        if not self.tax_id:
            return ""
        c = self.tax_id
        return f"{c[0:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:14]}"

    # Identity-based equality. Two issuers are equal iff their IDs match.
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Issuer):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        # Required because we defined __eq__. Hashing by id keeps Issuers
        # usable as dict keys / set members.
        return hash(self.id)