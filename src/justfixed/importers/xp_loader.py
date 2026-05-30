"""Layer 3 of the XP importer: persists parsed rows to the database.

This module is the seam between parsed-but-unsaved data (the output of
xp.py + xp_mapper.py) and rows-in-the-database. It handles:

  - Issuer reconciliation: matching a parsed issuer name against existing
    issuers via normalized-name lookup, creating new ones when missing.
  - Treasury routing: parsed name "Tesouro Nacional" maps to the
    Issuer.treasury() factory rather than creating a duplicate.
  - Investment idempotency: an investment matching an existing row's
    natural key (issuer + product + principal + dates) is skipped, so
    re-importing the same XP statement does not create duplicates.

The single public entry point is `load_xp_statement(path)`. Internal
helpers (issuer resolution, conglomerate handling) are not part of the
public API and may change shape without notice.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from justfixed.domain.investment import Investment, InvestmentSource
from justfixed.domain.issuer import Issuer, UNVERIFIED_CONGLOMERATE_PREFIX
from justfixed.importers._kind_catalog import classify_issuer_kind
from justfixed.importers.loader_types import LoadResult
from justfixed.importers.xp import read_renda_fixa_rows
from justfixed.importers.xp_mapper import parse_row
from justfixed.persistence.repositories import (
    CurationMemoryRepository,
    InvestmentRepository,
    IssuerRepository,
)


def load_xp_statement(
    path: Path, session_factory: sessionmaker[Session]
) -> LoadResult:
    """Read an XP statement, reconcile issuers, persist investments idempotently.

    Args:
        path: Filesystem path to the XP statement (.xlsx file).
        session_factory: SQLAlchemy session factory bound to the target
                         database engine. Repositories will be constructed
                         from this factory internally.

    Returns:
        A LoadResult summarizing how many investments were newly inserted
        vs. skipped, and how many issuers were newly created vs. reused.

    Raises:
        FileNotFoundError: If `path` does not exist.
        ValueError: If any row in the statement fails parsing
                    (propagated from xp_mapper.parse_row).
        sqlalchemy.exc.IntegrityError: If a database constraint is
                                       violated (typically indicates
                                       data corruption).
    """
    issuer_repo = IssuerRepository(session_factory)
    investment_repo = InvestmentRepository(session_factory)
    curation_repo = CurationMemoryRepository(session_factory)

    inserted = 0
    skipped = 0
    issuers_created = 0
    issuers_reused = 0

    raw_rows = read_renda_fixa_rows(path)
    for raw in raw_rows:
        parsed = parse_row(raw)

        issuer, was_created = _resolve_issuer(parsed.issuer_name, issuer_repo, curation_repo)
        if was_created:
            issuers_created += 1
        else:
            issuers_reused += 1

        # Idempotency check: does an investment with this natural key
        # already exist? If so, skip — re-running the import does not
        # create duplicates and does not modify existing records.
        existing = investment_repo.find_by_natural_key(
            issuer_id=issuer.id,
            product=parsed.product,
            principal=parsed.principal,
            purchase_date=parsed.purchase_date,
            maturity_date=parsed.maturity_date,
        )
        if existing is not None:
            skipped += 1
            continue

        # Build and save. Investment.create defaults issue_date to
        # purchase_date — appropriate for primary-market positions, which
        # is what XP statements report. Secondary-market case is not
        # distinguished in the XP data and would need a separate input.
        investment = Investment.create(
            product=parsed.product,
            issuer=issuer,
            principal=parsed.principal,
            rate=parsed.rate,
            purchase_date=parsed.purchase_date,
            maturity_date=parsed.maturity_date,
            coupon_frequency=parsed.coupon_frequency,
            source=InvestmentSource.XP_IMPORT,
        )
        investment_repo.save(investment)
        inserted += 1

    return LoadResult(
        inserted=inserted,
        skipped=skipped,
        issuers_created=issuers_created,
        issuers_reused=issuers_reused,
    )

def _resolve_issuer(
    parsed_name: str,
    issuer_repo: IssuerRepository,
    curation_repo: CurationMemoryRepository,
) -> tuple[Issuer, bool]:
    """Resolve a parsed issuer name to an existing or newly-created Issuer.

    Treasury (parsed name "Tesouro Nacional") routes to Issuer.treasury(),
    which carries the canonical CNPJ and TREASURY kind. Everything else
    is created with conglomerate drawn from curation memory if a curated
    entry exists, falling back to the [unverified] prefix otherwise.
    Issuer kind is determined by classify_issuer_kind (shared catalog
    in _kind_catalog.py); unknown names default to COMMERCIAL_BANK.

    Args:
        parsed_name: Issuer name as emitted by xp_mapper.parse_issuer_name.
                     "Tesouro Nacional" for treasuries; otherwise the bank's
                     short code (e.g. "BMG", "CEF", "BANCO INTER").
        issuer_repo: Repository for lookup and persistence.
        curation_repo: Repository for curated conglomerate lookups.

    Returns:
        A tuple (issuer, was_created) where was_created is True if this
        call inserted a new row, False if an existing row was reused.
    """
    existing = issuer_repo.find_by_normalized_name(parsed_name)
    if existing is not None:
        return existing, False

    if parsed_name == "Tesouro Nacional":
        new_issuer = Issuer.treasury()
    else:
        normalized = Issuer.normalize_name(parsed_name)
        curated = curation_repo.get(normalized)
        conglomerate = (
            curated if curated is not None
            else f"{UNVERIFIED_CONGLOMERATE_PREFIX}{parsed_name}"
        )
        kind = classify_issuer_kind(normalized)
        new_issuer = Issuer.create(
            name=parsed_name,
            conglomerate=conglomerate,
            kind=kind,
        )

    issuer_repo.save(new_issuer)
    return new_issuer, True