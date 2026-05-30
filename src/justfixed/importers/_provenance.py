"""Import-provenance helpers shared by the three loaders.

Placed in importers rather than persistence so the loaders can import it
without an intra-layer cycle. The import direction is:
    importers._provenance  →  persistence.mappers  →  domain.*
persistence.mappers has no back-edge into importers, so no cycle.
"""
from __future__ import annotations

from justfixed.domain.investment import InvestmentSource
from justfixed.persistence.mappers import CUSTODIAN_BY_SOURCE


def custodian_for_source(source: InvestmentSource) -> str | None:
    """Custodian display string for an import provenance, or None.

    Single-sourced from persistence.mappers.CUSTODIAN_BY_SOURCE so
    import-time custodian and the B42 backfill agree by construction.
    Returns None for MANUAL (no broker provenance).
    """
    return CUSTODIAN_BY_SOURCE.get(source.value)
