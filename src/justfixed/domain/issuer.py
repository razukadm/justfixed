"""Issuer entity: a bank or government entity that issues fixed-income products.

Issuers are entities (have identity), unlike Money and Rate (value objects).
Two Issuers with the same name and CNPJ are still distinct if their UUIDs
differ. This matters for data deduplication and audit trails.

FGC coverage is determined by the issuer's kind. Every deposit-taking kind is
covered (R$250k per CPF per conglomerate, R$1M per 4-year period overall;
FGCoop provides the equivalent for COOP). Only TREASURY (sovereign credit) and
OTHERS are uncovered — see IssuerKind.is_deposit_guaranteed, which returns True
for every kind except those two.

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

_UNVERIFIED_DISPLAY_PREFIX = "[não verificado] "


def display_conglomerate(conglomerate: str) -> str:
    """Render form of a conglomerate string.

    Swaps the stored ``[unverified] `` sentinel prefix for its pt-BR display
    form. Display-only — the stored value is never changed; no-op for verified
    (curated) names.
    """
    if conglomerate.startswith(UNVERIFIED_CONGLOMERATE_PREFIX):
        return _UNVERIFIED_DISPLAY_PREFIX + conglomerate[len(UNVERIFIED_CONGLOMERATE_PREFIX):]
    return conglomerate


class IssuerKind(Enum):
    """Categorization of issuers by institution type.

    FGC-covered categories (R$250k per institution per CPF):
      MULTIPLE_BANK                     → Bancos múltiplos
      COMMERCIAL_BANK                   → Bancos comerciais
      INVESTMENT_BANK                   → Bancos de investimento
      DEVELOPMENT_BANK                  → Bancos de desenvolvimento
      CAIXA_ECONOMICA                   → Caixa Econômica Federal
      CREDIT_FINANCE_INVESTMENT_COMPANY → Sociedades de crédito, financiamento e investimento
      REAL_ESTATE_CREDIT_COMPANY        → Sociedades de crédito imobiliário
      MORTGAGE_COMPANY                  → Companhias hipotecárias
      SAVINGS_LOAN_ASSOCIATION          → Associações de poupança e empréstimo

    FGCoop-covered (separate fund, also R$250k per institution per CPF):
      COOP                              → Cooperativas de crédito

    Not covered by any deposit-guarantee fund:
      TREASURY                          → Tesouro Nacional — sovereign credit only
      OTHERS                            → Outside any of the above categories
    """

    MULTIPLE_BANK                     = "multiple_bank"
    COMMERCIAL_BANK                   = "commercial_bank"
    INVESTMENT_BANK                   = "investment_bank"
    DEVELOPMENT_BANK                  = "development_bank"
    CAIXA_ECONOMICA                   = "caixa_economica"
    CREDIT_FINANCE_INVESTMENT_COMPANY = "credit_finance_investment_company"
    REAL_ESTATE_CREDIT_COMPANY        = "real_estate_credit_company"
    MORTGAGE_COMPANY                  = "mortgage_company"
    SAVINGS_LOAN_ASSOCIATION          = "savings_loan_association"
    COOP                              = "coop"
    TREASURY                          = "treasury"
    OTHERS                            = "others"

    @property
    def is_deposit_guaranteed(self) -> bool:
        """True for any kind covered by a deposit-guarantee fund.

        FGC covers the nine bank/finance categories (R$250k per institution).
        FGCoop covers COOP (also R$250k per institution). TREASURY is sovereign
        credit with no fund. OTHERS is outside any fund.

        The specific fund and its limits are not modelled yet — see the
        GuaranteeFund milestone in ROADMAP.md. This bool is correct and
        sufficient for per-institution R$250k checks, but cannot express
        divergent limits or separate global-ceiling buckets (FGC vs FGCoop).
        """
        return self not in {IssuerKind.TREASURY, IssuerKind.OTHERS}


_ISSUER_KIND_DISPLAY: dict[IssuerKind, str] = {
    IssuerKind.MULTIPLE_BANK: "Banco múltiplo",
    IssuerKind.COMMERCIAL_BANK: "Banco comercial",
    IssuerKind.INVESTMENT_BANK: "Banco de investimento",
    IssuerKind.DEVELOPMENT_BANK: "Banco de desenvolvimento",
    IssuerKind.CAIXA_ECONOMICA: "Caixa econômica",
    IssuerKind.CREDIT_FINANCE_INVESTMENT_COMPANY: "Sociedade de crédito, financiamento e investimento",
    IssuerKind.REAL_ESTATE_CREDIT_COMPANY: "Sociedade de crédito imobiliário",
    IssuerKind.MORTGAGE_COMPANY: "Companhia hipotecária",
    IssuerKind.SAVINGS_LOAN_ASSOCIATION: "Associação de poupança e empréstimo",
    IssuerKind.COOP: "Cooperativa de crédito",
    IssuerKind.TREASURY: "Tesouro",
    IssuerKind.OTHERS: "Outros",
}


def display_issuer_kind(kind: IssuerKind) -> str:
    """pt-BR display label for an issuer kind. Display-only; stored value unchanged."""
    return _ISSUER_KIND_DISPLAY[kind]


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
    def is_deposit_guaranteed(self) -> bool:
        """Whether this issuer's products are covered by a deposit-guarantee fund.

        Convenience accessor; the underlying logic lives on IssuerKind.
        """
        return self.kind.is_deposit_guaranteed

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