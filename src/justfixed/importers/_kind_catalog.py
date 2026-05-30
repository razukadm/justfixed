"""Shared issuer-kind classifier for the importer loaders.

Merges the per-loader name→IssuerKind tables that previously lived
separately in xp_loader (_DEVELOPMENT_BANK_NAMES) and btg_loader
(_ISSUER_KIND_CATALOG) into one canonical lookup (B33). Neither source
table shared keys, so the merge is lossless.

Keys are fully normalized issuer names as produced by
Issuer.normalize_name (strip, collapse whitespace, uppercase).
normalize_name does NOT shorten, so multi-word names like POUPEX's
full institution name must be used verbatim.
"""
from __future__ import annotations

from justfixed.domain.issuer import IssuerKind

# Add entries as real broker data surfaces new issuer kinds,
# per the audit-when-it-crashes rule in CLAUDE.md.
_ISSUER_KIND_CATALOG: dict[str, IssuerKind] = {
    # Development bank — originally xp_loader._DEVELOPMENT_BANK_NAMES.
    "BDMG": IssuerKind.DEVELOPMENT_BANK,
    # Savings-and-loan association — full normalized institution name.
    # Originally btg_loader._ISSUER_KIND_CATALOG.
    "ASSOCIACAO DE POUPANCA E EMPRESTIMO POUPEX": IssuerKind.SAVINGS_LOAN_ASSOCIATION,
}


def classify_issuer_kind(normalized_name: str) -> IssuerKind:
    """Return the IssuerKind for a normalized issuer name.

    Defaults to COMMERCIAL_BANK for names not in the catalog.
    """
    return _ISSUER_KIND_CATALOG.get(normalized_name, IssuerKind.COMMERCIAL_BANK)
