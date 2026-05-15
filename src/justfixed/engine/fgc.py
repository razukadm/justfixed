"""FGC concentration engine.

Computes per-conglomerate FGC (Fundo Garantidor de Créditos) exposure for
a portfolio of investments. The FGC guarantees up to R$ 250,000 per CPF
per conglomerate. This engine reports current and peak gross exposure so
users can see which conglomerates are approaching or exceeding the limit.

Design notes:
- Exposure is GROSS (pre-tax). FGC reimbursement covers the full gross
  amount owed; IR is the government's share regardless of a default.
- One project() call per investment is sufficient. result.current_value
  gives gross value at as_of; result.gross_at_maturity gives the gross
  peak at that investment's own maturity. Both fields are on the same
  ProjectionResult, so no second call with as_of=maturity_date is needed.
- Treasury is filtered by issuer.kind == TREASURY, not by product type.
  The issuer kind is the authoritative signal for FGC coverage.
- peak_exposure is the sum of each investment's gross value at its own
  maturity — a deliberate conservative overestimate. Simultaneous peaks
  are impossible, but the false positive is safe; a false negative would
  mislead the user about future risk.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum

from justfixed.domain.investment import Investment
from justfixed.domain.issuer import IssuerKind, UNVERIFIED_CONGLOMERATE_PREFIX
from justfixed.domain.money import Money
from justfixed.domain.product import ProductType
from justfixed.engine.projection import ProjectionResult, project

# ── Module-level constants ────────────────────────────────────────────────────

FGC_PER_CONGLOMERATE_LIMIT = Money.from_reais("250000")
FGC_APPROACHING_THRESHOLD  = Money.from_reais("200000")


# ── Data structures ───────────────────────────────────────────────────────────

class ExposureStatus(Enum):
    UNDER       = "under"
    APPROACHING = "approaching"
    OVER        = "over"


@dataclass(frozen=True)
class InvestmentExposure:
    """Gross exposure data for one investment, for the future timeline view."""

    investment_id: uuid.UUID
    issuer_name: str
    product: ProductType
    purchase_date: date
    maturity_date: date
    principal: Money
    current_value: Money   # gross value at the report's as_of date
    peak_value: Money      # gross value at this investment's own maturity


@dataclass(frozen=True)
class ConglomerateExposure:
    """FGC gross exposure aggregated for one conglomerate."""

    conglomerate_name: str
    investments: list[InvestmentExposure]   # sorted by maturity_date ascending
    current_exposure: Money                  # sum of current_value across investments
    peak_exposure: Money                     # sum of peak_value across investments
    current_status: ExposureStatus
    peak_status: ExposureStatus
    is_unverified: bool                      # True if name starts with UNVERIFIED prefix


@dataclass(frozen=True)
class FGCReport:
    """Top-level FGC concentration report for the portfolio."""

    conglomerates: list[ConglomerateExposure]   # sorted by current_exposure desc
    as_of: date

    @property
    def total_current_exposure(self) -> Money:
        return _sum_money(c.current_exposure for c in self.conglomerates)

    @property
    def total_peak_exposure(self) -> Money:
        return _sum_money(c.peak_exposure for c in self.conglomerates)

    @property
    def conglomerates_at_or_over_limit(self) -> list[ConglomerateExposure]:
        """Conglomerates whose current exposure exceeds the FGC R$250k limit
        (i.e., have uncovered amounts in case of conglomerate failure)."""
        return [c for c in self.conglomerates
                if c.current_status == ExposureStatus.OVER]

    @property
    def conglomerates_by_name(self) -> list[ConglomerateExposure]:
        """Same conglomerates, sorted alphabetically by name. Useful for stable test iteration."""
        return sorted(self.conglomerates, key=lambda c: c.conglomerate_name)


# ── Public API ────────────────────────────────────────────────────────────────

def fgc_concentration_report(
    investments: list[Investment],
    as_of: date,
    assumed_cdi: Decimal,
    assumed_ipca: Decimal | None = None,
) -> FGCReport:
    """Compute FGC concentration exposure across the portfolio.

    Args:
        investments: All investments in the portfolio. Treasury holdings are
            filtered out internally; pass everything and let this function sort.
        as_of: The valuation date for current exposure. Tests pass fixed dates;
            production UI passes date.today().
        assumed_cdi: Annualized CDI rate (e.g. Decimal("0.12") for 12%).
            Required by project() for post-fixed investments; unused for
            Prefixed and IPCA but always required for API consistency.

    Returns:
        FGCReport with conglomerates sorted by current_exposure descending
        (alphabetical name as tiebreaker).
    """
    # Step 1 — Filter to FGC-covered investments.
    # Filter on issuer.kind, not product type: the issuer is the authoritative
    # signal for FGC coverage. (Investment.__post_init__ ensures issuer.kind
    # is in product.allowed_issuer_kinds, so either would work in practice,
    # but the issuer kind is the conceptually correct predicate.)
    fgc_investments = [
        inv for inv in investments
        if inv.issuer.kind != IssuerKind.TREASURY
    ]

    if not fgc_investments:
        return FGCReport(conglomerates=[], as_of=as_of)

    # Step 2 — Project each investment once.
    # result.current_value  = gross value at as_of (accrual only, no tax).
    # result.gross_at_maturity = gross value at own maturity (peak exposure).
    # One call per investment suffices; no second call with as_of=maturity_date
    # is needed because both values live on the same ProjectionResult.
    projections: list[ProjectionResult] = [
        project(inv, as_of=as_of, assumed_cdi=assumed_cdi, assumed_ipca=assumed_ipca)
        for inv in fgc_investments
    ]

    return _build_report_from_projections(projections, as_of)


def fgc_concentration_report_from_projections(
    projections: list[ProjectionResult],
) -> FGCReport:
    """Compute FGC concentration exposure from already-projected results.

    Use this when projections are already computed and cached to avoid
    re-projecting on a conglomerate rename. Equivalent to
    fgc_concentration_report but consumes current_value from each
    ProjectionResult directly instead of calling project() internally.

    Args:
        projections: Already-computed projection results. Treasury holdings
            are filtered out internally. Pass all cached projections.

    Returns:
        FGCReport with conglomerates sorted by current_exposure descending.
        as_of is taken from the projections' shared as_of date.

    Raises:
        ValueError: If projections have more than one distinct as_of date.
    """
    if not projections:
        return FGCReport(conglomerates=[], as_of=date.today())

    as_of_dates = {p.as_of for p in projections}
    if len(as_of_dates) > 1:
        raise ValueError(
            f"All projections must share the same as_of date; got {sorted(as_of_dates)}"
        )
    as_of = next(iter(as_of_dates))

    fgc_projections = [
        p for p in projections
        if p.investment.issuer.kind != IssuerKind.TREASURY
    ]
    return _build_report_from_projections(fgc_projections, as_of)


# ── Private helpers ───────────────────────────────────────────────────────────

def _classify_status(exposure: Money) -> ExposureStatus:
    if exposure > FGC_PER_CONGLOMERATE_LIMIT:
        return ExposureStatus.OVER
    if exposure >= FGC_APPROACHING_THRESHOLD:
        return ExposureStatus.APPROACHING
    return ExposureStatus.UNDER


def _sum_money(amounts: Iterable[Money]) -> Money:
    total = Money.zero()
    for amount in amounts:
        total = total + amount
    return total


def _build_report_from_projections(
    projections: list[ProjectionResult],
    as_of: date,
) -> FGCReport:
    """Aggregate already-filtered, already-projected results into an FGCReport.

    Treasury filtering must be done by the caller before passing projections.
    """
    if not projections:
        return FGCReport(conglomerates=[], as_of=as_of)

    groups: dict[str, list[ProjectionResult]] = defaultdict(list)
    for proj in projections:
        groups[proj.investment.issuer.conglomerate].append(proj)

    conglomerate_list: list[ConglomerateExposure] = []
    for cname, projs in groups.items():
        projs_sorted = sorted(projs, key=lambda p: p.investment.maturity_date)

        inv_exposures = [
            InvestmentExposure(
                investment_id=proj.investment.id,
                issuer_name=proj.investment.issuer.name,
                product=proj.investment.product,
                purchase_date=proj.investment.purchase_date,
                maturity_date=proj.investment.maturity_date,
                principal=proj.investment.principal,
                current_value=proj.current_value,
                peak_value=proj.gross_at_maturity,
            )
            for proj in projs_sorted
        ]

        current_exposure = _sum_money(e.current_value for e in inv_exposures)
        peak_exposure    = _sum_money(e.peak_value    for e in inv_exposures)

        conglomerate_list.append(ConglomerateExposure(
            conglomerate_name=cname,
            investments=inv_exposures,
            current_exposure=current_exposure,
            peak_exposure=peak_exposure,
            current_status=_classify_status(current_exposure),
            peak_status=_classify_status(peak_exposure),
            is_unverified=cname.startswith(UNVERIFIED_CONGLOMERATE_PREFIX),
        ))

    conglomerate_list.sort(
        key=lambda c: (-c.current_exposure.amount, c.conglomerate_name)
    )
    return FGCReport(conglomerates=conglomerate_list, as_of=as_of)
