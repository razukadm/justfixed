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
from justfixed.domain.rates import PostFixedIPCA
from justfixed.engine.accrual import _accrue_step, _resolve_rate, accrue
from justfixed.engine.calendar import business_days_between
from justfixed.engine.cashflow import CashFlow, CashFlowKind, schedule
from justfixed.engine.curve import Curve
from justfixed.engine.tax import TaxResult, compute_ir
from justfixed.engine.trace import (
    Assumptions,
    CurveProvenance,
    FlowTrace,
    ProjectionTrace,
    TaxTrace,
)


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
    ipca_curve: Curve | None = None,
    curve_source: str | None = None,
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
    return _compute_projection(
        investment,
        as_of=as_of,
        assumed_cdi=assumed_cdi,
        assumed_ipca=assumed_ipca,
        cdi_curve=cdi_curve,
        ipca_curve=ipca_curve,
        curve_source=curve_source,
    )[0]


def _compute_current_value(
    investment: Investment,
    as_of: date,
    *,
    assumed_cdi: Decimal | None,
    assumed_ipca: Decimal | None,
    cdi_curve: Curve | None = None,
    ipca_curve: Curve | None = None,
) -> Money:
    """Accrual from purchase_date to as_of, capped at maturity_date."""
    steps = _current_value_steps(
        investment, as_of,
        assumed_cdi=assumed_cdi,
        assumed_ipca=assumed_ipca,
        cdi_curve=cdi_curve,
        ipca_curve=ipca_curve,
    )
    return steps[-1].closing_balance if steps else investment.principal


def _sum_money(amounts: list[Money], *, currency: str) -> Money:
    """Sum a list of Money values, returning zero if the list is empty."""
    total = Money.zero(currency)
    for amount in amounts:
        total = total + amount
    return total


def _current_value_steps(
    investment: Investment,
    as_of: date,
    *,
    assumed_cdi: Decimal | None,
    assumed_ipca: Decimal | None,
    cdi_curve: Curve | None,
    ipca_curve: Curve | None,
) -> tuple:
    """Accrual step(s) for current value, or () when there is nothing to accrue."""
    if as_of <= investment.purchase_date:
        return ()

    effective_date = min(as_of, investment.maturity_date)
    bizdays = business_days_between(investment.purchase_date, effective_date)
    if bizdays == 0:
        return ()

    match investment.rate:
        case PostFixedIPCA():
            lookup_date = investment.maturity_date
        case _:
            lookup_date = effective_date

    rate_resolution = _resolve_rate(
        investment.rate,
        lookup_date=lookup_date,
        assumed_cdi=assumed_cdi,
        assumed_ipca=assumed_ipca,
        cdi_curve=cdi_curve,
        ipca_curve=ipca_curve,
    )
    step = _accrue_step(
        investment.principal,
        rate_resolution,
        from_date=investment.purchase_date,
        to_date=effective_date,
        business_days=bizdays,
    )
    return (step,)


def _flow_traces(
    investment: Investment,
    flows: list[CashFlow],
    *,
    assumed_cdi: Decimal | None,
    assumed_ipca: Decimal | None,
    cdi_curve: Curve | None,
    ipca_curve: Curve | None,
) -> tuple:
    """Build one FlowTrace per cash flow, mirroring schedule() without recomputing amounts."""
    currency = investment.principal.currency
    zero = Money.zero(currency)
    period_start = investment.purchase_date
    result: list[FlowTrace] = []

    for cf in flows:
        du = business_days_between(period_start, cf.date)

        match investment.rate:
            case PostFixedIPCA():
                lookup_date = investment.maturity_date
            case _:
                lookup_date = cf.date

        rate_resolution = _resolve_rate(
            investment.rate,
            lookup_date=lookup_date,
            assumed_cdi=assumed_cdi,
            assumed_ipca=assumed_ipca,
            cdi_curve=cdi_curve,
            ipca_curve=ipca_curve,
        )
        step = _accrue_step(
            investment.principal,
            rate_resolution,
            from_date=period_start,
            to_date=cf.date,
            business_days=du,
        )

        interest_component = step.closing_balance - investment.principal
        principal_component = (
            investment.principal
            if cf.kind in {CashFlowKind.PRINCIPAL, CashFlowKind.COUPON_AND_PRINCIPAL}
            else zero
        )

        result.append(FlowTrace(
            pay_date=cf.date,
            kind=cf.kind,
            amount=cf.amount,
            interest_component=interest_component,
            principal_component=principal_component,
            accrual=(step,),
        ))
        period_start = cf.date

    return tuple(result)


def _compute_projection(
    investment: Investment,
    *,
    as_of: date,
    assumed_cdi: Decimal | None,
    assumed_ipca: Decimal | None,
    cdi_curve: Curve | None,
    ipca_curve: Curve | None,
    curve_source: str | None = None,
) -> tuple:
    """Single computation that produces both ProjectionResult and ProjectionTrace."""
    # 1. Current value
    cv_steps = _current_value_steps(
        investment, as_of,
        assumed_cdi=assumed_cdi, assumed_ipca=assumed_ipca,
        cdi_curve=cdi_curve, ipca_curve=ipca_curve,
    )
    current_value = cv_steps[-1].closing_balance if cv_steps else investment.principal

    # 2. Cash flow schedule
    flows = schedule(
        investment,
        assumed_cdi=assumed_cdi, assumed_ipca=assumed_ipca,
        cdi_curve=cdi_curve, ipca_curve=ipca_curve,
    )

    # 3. Flow traces (mirror schedule, carry amounts up)
    flow_traces = _flow_traces(
        investment, flows,
        assumed_cdi=assumed_cdi, assumed_ipca=assumed_ipca,
        cdi_curve=cdi_curve, ipca_curve=ipca_curve,
    )

    # 4. Gross at maturity
    gross_at_maturity = _sum_money(
        [f.amount for f in flows], currency=investment.principal.currency
    )

    # 5. Tax
    rule = rules_for(investment.product)
    holding_calendar_days = (investment.maturity_date - investment.purchase_date).days
    tax_breakdown = compute_ir(
        principal=investment.principal,
        gross=gross_at_maturity,
        treatment=rule.tax_treatment,
        holding_days=holding_calendar_days,
    )

    # 6. Trace sub-objects
    tax_trace = TaxTrace(
        treatment=rule.tax_treatment,
        holding_calendar_days=holding_calendar_days,
        bracket_rate=tax_breakdown.tax_rate,
        taxable_gain=tax_breakdown.gain,
        tax_amount=tax_breakdown.tax_amount,
        iof_modeled=False,
    )

    curve_anchor = None
    curve_ref = None
    for step in cv_steps:
        if step.rate.source == "curve":
            curve_anchor = step.rate.curve_anchor
            curve_ref = step.rate.curve_ref
            break
    if curve_anchor is None:
        for ft in flow_traces:
            for step in ft.accrual:
                if step.rate.source == "curve":
                    curve_anchor = step.rate.curve_anchor
                    curve_ref = step.rate.curve_ref
                    break
            if curve_anchor is not None:
                break

    result = ProjectionResult(
        investment=investment,
        as_of=as_of,
        current_value=current_value,
        cash_flows=flows,
        gross_at_maturity=gross_at_maturity,
        tax_breakdown=tax_breakdown,
        net_at_maturity=tax_breakdown.net,
    )
    trace = ProjectionTrace(
        investment=investment,
        as_of=as_of,
        convention="252 bd/yr; B3/ANBIMA holidays",
        current_value=current_value,
        current_value_accrual=cv_steps,
        cash_flows=flow_traces,
        gross_at_maturity=gross_at_maturity,
        tax=tax_trace,
        net_at_maturity=tax_breakdown.net,
        assumptions=Assumptions(
            assumed_cdi=assumed_cdi,
            assumed_ipca=assumed_ipca,
        ),
        curve_provenance=CurveProvenance(
            source=curve_source,
            anchor=curve_anchor,
            curve_ref=curve_ref,
        ),
    )
    return result, trace


def project_traced(
    investment: Investment,
    *,
    as_of: date,
    assumed_cdi: Decimal | None = None,
    assumed_ipca: Decimal | None = None,
    cdi_curve: Curve | None = None,
    ipca_curve: Curve | None = None,
    curve_source: str | None = None,
) -> ProjectionTrace:
    """Project an investment and return the full calculation trace.

    Same inputs as project(); returns a ProjectionTrace containing both
    the results and every intermediate step that produced them.
    """
    return _compute_projection(
        investment,
        as_of=as_of,
        assumed_cdi=assumed_cdi,
        assumed_ipca=assumed_ipca,
        cdi_curve=cdi_curve,
        ipca_curve=ipca_curve,
        curve_source=curve_source,
    )[1]