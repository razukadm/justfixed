"""Top-level projection engine: the engine's public API.

Given an Investment, an as-of date, and assumed rates, return a
ProjectionResult containing everything the UI needs to display:

- current_value: what the investment is worth on as_of (accrual to date)
- cash_flows: the schedule of payments (1 for bullets, N for coupon)
- gross_at_maturity: total received, pre-tax
- tax_breakdown: the IR calculation
- net_at_maturity: total received, post-tax

Simplifications for MVP (documented; future Phase 2 will refine):
- Coupon-paying products: IR is computed on the SUM of gains using the
  total holding-period bracket. The actual per-coupon withholding rule
  produces slightly less favorable numbers in early years. The error
  is small for typical retail holdings.
- Mark-to-market: not implemented. current_value uses accrual only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from justfixed.domain.investment import Investment
from justfixed.domain.money import Money
from justfixed.domain.product import rules_for
from justfixed.engine.accrual import accrue
from justfixed.engine.calendar import business_days_between
from justfixed.engine.cashflow import CashFlow, schedule
from justfixed.engine.curve import Curve
from justfixed.engine.tax import TaxResult, compute_ir


@dataclass(frozen=True, slots=True)
class ProjectionResult:
    """Everything we can say about an investment as of a given date."""

    investment: Investment
    as_of: date
    current_value: Money
    cash_flows: list[CashFlow]
    gross_at_maturity: Money
    tax_breakdown: TaxResult
    net_at_maturity: Money

    @property
    def gain_at_maturity(self) -> Money:
        """Convenience: gross - principal."""
        return self.gross_at_maturity - self.investment.principal

    @property
    def tax_amount(self) -> Money:
        """Convenience: shortcut to tax_breakdown.tax_amount."""
        return self.tax_breakdown.tax_amount


def project(
    investment: Investment,
    *,
    as_of: date,
    assumed_cdi: Decimal | None = None,
    assumed_ipca: Decimal | None = None,
    cdi_curve: Curve | None = None,
) -> ProjectionResult:
    """Project an investment's value as of a given date and at maturity.

    Args:
        investment: The Investment to project.
        as_of: The "today" date for current-value calculation. Typically
            the actual current date but can be any date for "what if"
            scenarios.
        assumed_cdi: Required for PostFixedCDI rates; ignored otherwise.
        assumed_ipca: Required for PostFixedIPCA rates; ignored otherwise.

    Returns:
        A ProjectionResult with current_value, cash_flows, and net/gross
        maturity numbers.

    Notes:
        - If as_of < purchase_date: current_value = principal (no accrual yet).
        - If as_of >= maturity_date: current_value = gross_at_maturity.
        - Otherwise: current_value = principal accrued to as_of.
    """
    # ----- 1. Current value (accrual from purchase to as_of) -----
    current_value = _compute_current_value(
        investment, as_of,
        assumed_cdi=assumed_cdi,
        assumed_ipca=assumed_ipca,
        cdi_curve=cdi_curve,
    )

    # ----- 2. Cash flow schedule -----
    flows = schedule(
        investment,
        assumed_cdi=assumed_cdi,
        assumed_ipca=assumed_ipca,
        cdi_curve=cdi_curve,
    )

    # ----- 3. Gross at maturity (sum of all cash flows) -----
    gross_at_maturity = _sum_money(
        [f.amount for f in flows], currency=investment.principal.currency
    )

    # ----- 4. Tax: applied to total gain over the holding period -----
    rule = rules_for(investment.product)
    holding_calendar_days = (investment.maturity_date - investment.purchase_date).days
    tax_breakdown = compute_ir(
        principal=investment.principal,
        gross=gross_at_maturity,
        treatment=rule.tax_treatment,
        holding_days=holding_calendar_days,
    )

    return ProjectionResult(
        investment=investment,
        as_of=as_of,
        current_value=current_value,
        cash_flows=flows,
        gross_at_maturity=gross_at_maturity,
        tax_breakdown=tax_breakdown,
        net_at_maturity=tax_breakdown.net,
    )


def _compute_current_value(
    investment: Investment,
    as_of: date,
    *,
    assumed_cdi: Decimal | None,
    assumed_ipca: Decimal | None,
    cdi_curve: Curve | None = None,
) -> Money:
    """Accrual from purchase_date to as_of, capped at maturity_date."""
    if as_of <= investment.purchase_date:
        # Hasn't started earning yet (or just bought).
        return investment.principal

    # Don't accrue past maturity.
    effective_date = min(as_of, investment.maturity_date)
    bizdays = business_days_between(investment.purchase_date, effective_date)
    effective_cdi = (
        cdi_curve.rate_at(effective_date)
        if (cdi_curve is not None and cdi_curve.vertices)
        else assumed_cdi
    )
    return accrue(
        investment.principal,
        investment.rate,
        bizdays,
        assumed_cdi=effective_cdi,
        assumed_ipca=assumed_ipca,
    )


def _sum_money(amounts: list[Money], *, currency: str) -> Money:
    """Sum a list of Money values, returning zero if the list is empty."""
    total = Money.zero(currency)
    for amount in amounts:
        total = total + amount
    return total