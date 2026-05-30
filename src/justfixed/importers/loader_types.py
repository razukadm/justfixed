"""Shared result types for the importer loaders.

LoadResult was originally defined in xp_loader and imported by btg_loader,
bb_loader, and detection as a cross-sibling dependency. It lives here so
all loaders can import from a neutral shared module (B33).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LoadResult:
    """Summary of what happened during a load_*_statement call.

    Useful for the UI to display "Imported 94 positions: 12 new,
    82 already known" after a run.

    Attributes:
        inserted: Investments newly inserted into the database.
        skipped: Investments already present (matched by natural key).
        issuers_created: Issuers newly inserted into the database.
        issuers_reused: Issuers already present (matched by normalized name).
    """

    inserted: int
    skipped: int
    issuers_created: int
    issuers_reused: int
    skipped_matured: int = 0  # matured positions skipped before persist (BB only)
