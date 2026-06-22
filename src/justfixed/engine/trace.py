"""Audit calculation-trace contract for finding F-01.

This module is the single-source data layer for JustFixed's calculation
transparency requirement: every number surfaced in a projection can be
traced back to its exact inputs and formula steps.

Design invariants:
- All dataclasses are frozen and slotted — trace objects are immutable
  value types; no mutation after construction.
- Populated by the single-source engine computation in projection.py;
  no calculations happen here.
- TaxTrace.iof_modeled is always False today: the IOF (Imposto sobre
  Operações Financeiras) tax on redemptions before 30 days is not yet
  modeled.  This is a self-disclosing omission of finding F-06.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from justfixed.domain.investment import Investment
from justfixed.domain.money import Money
from justfixed.domain.product import TaxTreatment

if TYPE_CHECKING:
    from justfixed.engine.cashflow import CashFlowKind


@dataclass(frozen=True, slots=True)
class RateResolution:
    """How the effective annual rate was derived for one accrual step."""

    rate_kind: str                          # type(rate).__name__
    effective_annual_rate: Decimal
    source: str                             # "fixed" | "curve" | "assumed_fallback"
    resolved_index_rate: Decimal | None     # CDI/IPCA level actually used; None for Prefixed
    index_multiplier_or_spread: Decimal | None  # CDI: full multiplier (e.g. Decimal("1.10"));
                                                 # CDI+spread / IPCA: the spread; None for Prefixed
    curve_anchor: date | None               # curve.anchor when source=="curve", else None
    curve_tenor_date: date | None           # the date passed to rate_at(); None when no curve
    curve_ref: str | None = None            # content hash / as_of — left None until Track B


@dataclass(frozen=True, slots=True)
class AccrualStep:
    """One compound-interest step: [from_date, to_date] at one resolved rate."""

    from_date: date
    to_date: date
    business_days: int                      # Du
    rate: RateResolution
    factor: Decimal                         # raw, full-precision (1+r)**(Du/252) — NOT quantized
    opening_balance: Money
    closing_balance: Money                  # Money(opening_balance.amount * factor) at 8 dp


@dataclass(frozen=True, slots=True)
class FlowTrace:
    """Audit record for one cash flow from the schedule."""

    pay_date: date
    kind: CashFlowKind                      # real enum stored at runtime; type-only import
    amount: Money                           # carried up from schedule()'s CashFlow — never recomputed
    interest_component: Money
    principal_component: Money              # principal returned by this flow (zero for COUPON)
    accrual: tuple[AccrualStep, ...]        # one step, mirroring schedule's single accrue per flow


@dataclass(frozen=True, slots=True)
class TaxTrace:
    """IR (Imposto de Renda) calculation breakdown."""

    treatment: TaxTreatment
    holding_calendar_days: int
    bracket_rate: Decimal
    taxable_gain: Money
    tax_amount: Money
    iof_modeled: bool                       # always False today (F-06 not yet modeled)


@dataclass(frozen=True, slots=True)
class Assumptions:
    """The index-rate assumptions passed into the projection."""

    assumed_cdi: Decimal | None
    assumed_ipca: Decimal | None


@dataclass(frozen=True, slots=True)
class CurveProvenance:
    """Data-provenance layer for the yield curve used in this projection."""

    source: str | None                      # "live"|"cached"|"unavailable" — None in Slice 1
    anchor: date | None
    curve_ref: str | None = None            # content hash — None until Track B


@dataclass(frozen=True, slots=True)
class ProjectionTrace:
    """Complete audit trace for one call to project_traced().

    Echoes investment (principal, rate, dates, product, coupon_frequency)
    by reference — no duplicate copies of those fields.
    """

    investment: Investment
    as_of: date
    convention: str
    current_value: Money
    current_value_accrual: tuple[AccrualStep, ...]  # () when no accrual; else one step
    cash_flows: tuple[FlowTrace, ...]
    gross_at_maturity: Money
    tax: TaxTrace
    net_at_maturity: Money
    assumptions: Assumptions
    curve_provenance: CurveProvenance
