"""First-run seed loader for the issuers table (B9a Phase 3).

load_seed_if_empty() is the public entry point. Called once at app startup:
if the issuers table is empty, it populates it from the parsed seed payload.
If the table already has rows (user has imported data or a prior seed ran),
it does nothing — preserving user curation.

Seed JSON format (seed/issuers.json in the justfixed-data repo):
    {
      "as_of": "YYYY-MM-DD",
      "schema_version": 1,
      "note": "...",
      "issuers": [
        {"name": "...", "conglomerate": "...", "kind": "commercial_bank", "tax_id": ""},
        ...
      ]
    }

kind values match IssuerKind enum values: "commercial_bank",
"development_bank", "treasury".

Note: this module imports from persistence/ (IssuerRepository), which is a
cross-layer dependency not typical of other engine/ modules. It is placed
here rather than importers/ because it has no parsing or broker-format
coupling; the dependency is minimal and explicit.
"""

from __future__ import annotations

from justfixed.domain.issuer import Issuer, IssuerKind
from justfixed.persistence.repositories import IssuerRepository


def load_seed_if_empty(
    issuer_repo: IssuerRepository,
    seed_data: dict | None,
) -> int:
    """Load issuers from seed data if the database is empty.

    Returns the number of issuers inserted. Returns 0 if the DB already
    has issuers (preserving user curation) or if seed_data is None (fetch
    failed — silent fallback to empty DB).

    Args:
        issuer_repo: Repository for reading/writing Issuer entities.
        seed_data: Parsed JSON payload from the data repo, or None if
                   the fetch and cache both failed.

    Returns:
        Number of issuers inserted (0 means DB was not empty or no data).

    Raises:
        ValueError: if seed_data contains two entries whose names normalize
                    to the same string. A duplicate in the seed is a data
                    error; the caller should catch and log.
    """
    if issuer_repo.list_all():
        return 0  # DB not empty — preserve user curation

    if seed_data is None:
        return 0  # fetch failed — silent fallback

    issuers_data = seed_data.get("issuers", [])
    if not issuers_data:
        return 0

    # Validate before touching the DB: no two entries may share a normalized name.
    seen_normalized: set[str] = set()
    for entry in issuers_data:
        normalized = Issuer.normalize_name(entry["name"])
        if normalized in seen_normalized:
            raise ValueError(
                f"Seed data has duplicate normalized issuer name: {normalized!r}"
            )
        seen_normalized.add(normalized)

    for entry in issuers_data:
        issuer = Issuer.create(
            name=entry["name"],
            conglomerate=entry["conglomerate"],
            kind=IssuerKind(entry["kind"]),
            tax_id=entry.get("tax_id", ""),
        )
        issuer_repo.save(issuer)

    return len(issuers_data)
