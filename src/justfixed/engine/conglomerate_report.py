"""Conglomerate consolidated report engine for B24.

Produces per-conglomerate sections from a portfolio of investments.
Each section has summary data (collapsed view) and per-investment detail
rows (expanded view) with FGC status badges.

Key semantic decisions (from ROADMAP.md B24, Option B):
- All values are gross (gross_at_maturity). No net/post-tax display.
- Projected Balance: cumulative gross_at_maturity, sequential drawdown,
  maturity-ascending. FGC badge evaluates against the same number the user sees.
- Tesouro sections: all FGC statuses are NOT_FGC. A section is Treasury iff
  ALL its investments have issuer.kind == IssuerKind.TREASURY. Mixed sections
  (any non-Treasury investment) evaluate FGC normally.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum

from justfixed.domain.investment import Investment
from justfixed.domain.issuer import IssuerKind
from justfixed.domain.money import Money
from justfixed.domain.product import ProductType
from justfixed.engine.fgc import FGC_APPROACHING_THRESHOLD, FGC_PER_CONGLOMERATE_LIMIT
from justfixed.engine.projection import project


# ── Status enum ───────────────────────────────────────────────────────────────

class ConglomerateStatus(Enum):
    UNDER       = "under"
    APPROACHING = "approaching"
    OVER        = "over"
    NOT_FGC     = "not_fgc"   # Tesouro investments; FGC protection does not apply


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ConglomerateDetailRow:
    """One investment in the expanded conglomerate section view."""

    maturity_date: date
    issuer_name: str
    product: ProductType
    principal: Money
    current_value: Money       # gross accrual to as_of (pre-tax)
    projected_value: Money     # gross_at_maturity (pre-tax owed at maturity)
    projected_balance: Money   # cumulative gross: this row + all later-maturing rows
    fgc_status: ConglomerateStatus


@dataclass(frozen=True)
class ConglomerateSection:
    """One conglomerate group in the UI accordion."""

    conglomerate_name: str
    investment_count: int
    total_principal: Money
    total_current_value: Money
    total_projected_value: Money   # gross; displayed at summary level
    next_maturity: date            # earliest maturity_date among rows
    summary_fgc_status: ConglomerateStatus
    rows: list[ConglomerateDetailRow]   # sorted by maturity_date ascending


@dataclass(frozen=True)
class ConglomerateReport:
    """Top-level report for the B24 Conglomerates tab."""

    sections: list[ConglomerateSection]   # sorted alphabetically by conglomerate_name
    as_of: date


# ── Public API ────────────────────────────────────────────────────────────────

def build_conglomerate_report(
    investments: list[Investment],
    as_of: date,
    assumed_cdi: Decimal,
    assumed_ipca: Decimal | None = None,
) -> ConglomerateReport:
    """Produce the conglomerate consolidated report.

    Args:
        investments: Investments to include. No filtering is applied; the
            caller is responsible for applying the Hide-matured toggle or any
            other filter before calling. Tesouro investments are included and
            rendered with NOT_FGC status.
        as_of: Valuation date for current_value. Passed to project() unchanged.
        assumed_cdi: Annualized CDI rate (e.g. Decimal("0.12") for 12%).
            Required by project() for PostFixedCDI/PostFixedCDIPlusSpread.
        assumed_ipca: Annualized IPCA rate. Required for PostFixedIPCA.

    Returns:
        ConglomerateReport with sections sorted alphabetically by name.
    """
    if not investments:
        return ConglomerateReport(sections=[], as_of=as_of)

    projections = [
        project(inv, as_of=as_of, assumed_cdi=assumed_cdi, assumed_ipca=assumed_ipca)
        for inv in investments
    ]

    groups: dict[str, list] = defaultdict(list)
    for proj in projections:
        groups[proj.investment.issuer.conglomerate].append(proj)

    sections: list[ConglomerateSection] = []
    for cname, projs in groups.items():
        projs_sorted = sorted(projs, key=lambda p: p.investment.maturity_date)

        # A section is Treasury iff ALL its investments are Treasury-issued.
        # Mixed sections (any non-Treasury investment) evaluate FGC normally.
        is_treasury = all(
            p.investment.issuer.kind == IssuerKind.TREASURY for p in projs_sorted
        )

        # Walk right-to-left to compute sequential-drawdown balances.
        rows_reversed: list[ConglomerateDetailRow] = []
        gross_running = Money.zero()
        for proj in reversed(projs_sorted):
            gross_running = gross_running + proj.gross_at_maturity
            fgc_status = (
                ConglomerateStatus.NOT_FGC
                if is_treasury
                else _classify(gross_running)
            )
            rows_reversed.append(ConglomerateDetailRow(
                maturity_date=proj.investment.maturity_date,
                issuer_name=proj.investment.issuer.name,
                product=proj.investment.product,
                principal=proj.investment.principal,
                current_value=proj.current_value,
                projected_value=proj.gross_at_maturity,
                projected_balance=gross_running,
                fgc_status=fgc_status,
            ))
        rows = list(reversed(rows_reversed))

        total_principal       = _sum_money(r.principal      for r in rows)
        total_current_value   = _sum_money(r.current_value  for r in rows)
        total_projected_value = _sum_money(r.projected_value for r in rows)
        next_maturity = rows[0].maturity_date   # earliest (rows sorted asc)

        summary_fgc_status = (
            ConglomerateStatus.NOT_FGC
            if is_treasury
            else _classify(total_projected_value)
        )

        sections.append(ConglomerateSection(
            conglomerate_name=cname,
            investment_count=len(rows),
            total_principal=total_principal,
            total_current_value=total_current_value,
            total_projected_value=total_projected_value,
            next_maturity=next_maturity,
            summary_fgc_status=summary_fgc_status,
            rows=rows,
        ))

    sections.sort(key=lambda s: s.conglomerate_name)
    return ConglomerateReport(sections=sections, as_of=as_of)


# ── Private helpers ───────────────────────────────────────────────────────────

def _classify(amount: Money) -> ConglomerateStatus:
    """Map a gross exposure amount to UNDER / APPROACHING / OVER.

    Thresholds are imported from fgc.py (single source of truth). NOT_FGC
    is assigned by the caller based on issuer kind, never by this function.
    """
    if amount > FGC_PER_CONGLOMERATE_LIMIT:
        return ConglomerateStatus.OVER
    if amount >= FGC_APPROACHING_THRESHOLD:
        return ConglomerateStatus.APPROACHING
    return ConglomerateStatus.UNDER


def _sum_money(amounts: Iterable[Money]) -> Money:
    total = Money.zero()
    for amount in amounts:
        total = total + amount
    return total
