"""Layer 3 of the BB importer: persists parsed rows to the database.

This module is the seam between parsed-but-unsaved data (the output of
bb.py + bb_mapper.py) and rows-in-the-database. It handles:

  - Matured-row filtering: rows with saldo == Money zero are skipped and
    counted in LoadResult.skipped_matured. Only active positions are
    persisted. Rationale: matured positions have maturity dates in the past
    and would fail the domain's maturity_date > purchase_date invariant for
    live portfolio projections.
  - Issuer reconciliation: all BB LCA rows are issued by Banco do Brasil
    (the bank itself). The issuer is resolved by normalized name, created
    once on first encounter, and reused for every subsequent row in the file.
  - Investment idempotency: an investment matching an existing row's
    natural key (issuer + product + principal + dates) is skipped, so
    re-importing the same BB statement does not create duplicates.

The single public entry point is `load_bb_statement(path)`. Internal
helpers are not part of the public API and may change without notice.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from justfixed.domain.investment import Investment, InvestmentSource
from justfixed.domain.issuer import Issuer, IssuerKind, UNVERIFIED_CONGLOMERATE_PREFIX
from justfixed.domain.money import Money
from justfixed.importers.bb import read_lca_rows
from justfixed.importers.bb_mapper import parse_row
from justfixed.importers.xp_loader import LoadResult
from justfixed.persistence.repositories import (
    CurationMemoryRepository,
    InvestmentRepository,
    IssuerRepository,
)

# All rows in a BB LCA statement are issued by the bank itself.
_BB_ISSUER_NAME = "Banco do Brasil S/A"


def load_bb_statement(
    path: Path, session_factory: sessionmaker[Session]
) -> LoadResult:
    """Read a BB SISBB LCA statement, skip matured positions, persist active ones.

    Args:
        path: Filesystem path to a BB SISBB .txt statement.
        session_factory: SQLAlchemy session factory bound to the target
                         database engine. Repositories are constructed
                         from this factory internally.

    Returns:
        A LoadResult summarizing how many investments were newly inserted
        vs. skipped (including matured), and the matured-skip count.

    Raises:
        FileNotFoundError: If `path` does not exist.
        ValueError: If the file is a BB SISBB statement but lacks the LCA
                    section (e.g. a future Tesouro statement), or if an
                    active row fails parsing or domain validation.
        sqlalchemy.exc.IntegrityError: If a database constraint is
                                       violated (typically indicates
                                       data corruption).
    """
    issuer_repo    = IssuerRepository(session_factory)
    investment_repo = InvestmentRepository(session_factory)
    curation_repo  = CurationMemoryRepository(session_factory)

    try:
        raw_rows = read_lca_rows(path)
    except ValueError as exc:
        if "RESUMO DAS APLICAÇÕES LCA" in str(exc):
            raise ValueError(
                f"This Banco do Brasil statement does not contain an LCA section "
                f"({path.name}). BB Tesouro Direto statements are not yet supported."
            ) from exc
        raise

    inserted        = 0
    skipped         = 0
    skipped_matured = 0
    issuers_created = 0
    issuers_reused  = 0

    for raw in raw_rows:
        parsed = parse_row(raw)

        # Matured positions (saldo zero) are skipped — they have past maturity
        # dates and are not part of the current-holdings model. Count in both
        # skipped and skipped_matured.
        if parsed.saldo <= Money.zero(parsed.saldo.currency):
            skipped         += 1
            skipped_matured += 1
            continue

        issuer, was_created = _resolve_bb_issuer(issuer_repo, curation_repo)
        if was_created:
            issuers_created += 1
        else:
            issuers_reused += 1

        existing = investment_repo.find_by_natural_key(
            issuer_id=issuer.id,
            product=parsed.product,
            principal=parsed.valor_emissao,
            purchase_date=parsed.data_aplicacao,
            maturity_date=parsed.data_vencimento,
        )
        if existing is not None:
            skipped += 1
            continue

        # purchase_date = data_aplicacao (primary-market: bought at issuance).
        # coupon_frequency defaults to NONE — BB LCA statements carry no coupon
        # detail; bullet is the safe default.
        investment = Investment.create(
            product=parsed.product,
            issuer=issuer,
            principal=parsed.valor_emissao,
            rate=parsed.rate,
            purchase_date=parsed.data_aplicacao,
            maturity_date=parsed.data_vencimento,
            source=InvestmentSource.BB_IMPORT,
        )
        investment_repo.save(investment)
        inserted += 1

    return LoadResult(
        inserted=inserted,
        skipped=skipped,
        issuers_created=issuers_created,
        issuers_reused=issuers_reused,
        skipped_matured=skipped_matured,
    )


def _resolve_bb_issuer(
    issuer_repo: IssuerRepository,
    curation_repo: CurationMemoryRepository,
) -> tuple[Issuer, bool]:
    """Resolve the Banco do Brasil issuer, creating it on first call.

    All BB LCA rows share one issuer. After the first active row creates
    the issuer, subsequent calls reuse it.

    Returns:
        (issuer, was_created) — was_created is True only on first insert.
    """
    existing = issuer_repo.find_by_normalized_name(_BB_ISSUER_NAME)
    if existing is not None:
        return existing, False

    normalized = Issuer.normalize_name(_BB_ISSUER_NAME)
    curated = curation_repo.get(normalized)
    conglomerate = (
        curated if curated is not None
        else f"{UNVERIFIED_CONGLOMERATE_PREFIX}{_BB_ISSUER_NAME}"
    )
    new_issuer = Issuer.create(
        name=_BB_ISSUER_NAME,
        conglomerate=conglomerate,
        kind=IssuerKind.COMMERCIAL_BANK,
    )
    issuer_repo.save(new_issuer)
    return new_issuer, True
