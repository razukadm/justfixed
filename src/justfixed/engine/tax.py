"""IR (Imposto de Renda) tax engine for Brazilian fixed income.

Two regimes:

1. IR_REGRESSIVE (CDB, LC, Tesouro): a 4-bracket table on the GAIN
   (final - principal), based on holding period in CALENDAR DAYS:

       0-180 days        : 22.5%
       181-360 days      : 20.0%
       361-720 days      : 17.5%
       721+ days         : 15.0%

   Note: holding period is in calendar days, NOT business days. This
   is per Brazilian tax law (IN RFB 1585/2015) and is one of the few
   places the law uses calendar days instead of bizdays.

2. IR_EXEMPT (LCI, LCA, LCD): tax is always zero for individuals (PF).

The engine doesn't know about Investments; it operates on Money +
holding period + tax treatment. Higher layers (projection.py) will
look up the treatment from ProductRules and call this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from justfixed.domain.money import Money
from justfixed.domain.product import TaxTreatment


# IR regressive brackets, ordered ascending by max_days. The last bracket
# has max_days=None meaning "anything beyond the prior threshold."
@dataclass(frozen=True, slots=True)
class _Bracket:
    max_days: int | None
    rate: Decimal


_REGRESSIVE_BRACKETS: tuple[_Bracket, ...] = (
    _Bracket(max_days=180, rate=Decimal("0.225")),
    _Bracket(max_days=360, rate=Decimal("0.20")),
    _Bracket(max_days=720, rate=Decimal("0.175")),
    _Bracket(max_days=None, rate=Decimal("0.15")),  # 721+
)


@dataclass(frozen=True, slots=True)
class TaxResult:
    """The breakdown of an IR calculation."""

    gross: Money       # what was earned before tax (final amount)
    gain: Money        # gross - principal
    tax_rate: Decimal  # the rate applied (0 for exempt)
    tax_amount: Money  # tax charged
    net: Money         # gross - tax_amount


def regressive_rate_for(holding_days: int) -> Decimal:
    """Return the IR rate that applies to a holding period in calendar days.

    Raises ValueError on negative input.
    """
    if holding_days < 0:
        raise ValueError(
            f"holding_days must be non-negative; got {holding_days}"
        )
    for bracket in _REGRESSIVE_BRACKETS:
        if bracket.max_days is None or holding_days <= bracket.max_days:
            return bracket.rate
    # Unreachable — the last bracket has max_days=None.
    raise AssertionError("No bracket matched; regressive table is malformed.")


def compute_ir(
    principal: Money,
    gross: Money,
    treatment: TaxTreatment,
    holding_days: int,
) -> TaxResult:
    """Compute the IR tax on a position's gain.

    Args:
        principal: Amount originally invested.
        gross: Amount before tax (principal + accrued interest).
        treatment: Which tax regime applies (from ProductRules).
        holding_days: Calendar days between purchase and the taxable event.

    Returns:
        A TaxResult with the full breakdown.

    Raises:
        ValueError: If gross < principal (negative gain — not normal but
            possible in mark-to-market scenarios; we don't tax losses).
        ValueError: If currencies of principal and gross don't match.
    """
    if principal.currency != gross.currency:
        raise ValueError(
            f"Currency mismatch: principal {principal.currency} "
            f"vs gross {gross.currency}"
        )

    gain = gross - principal

    # No tax on losses (negative gain). This isn't a current MVP scenario
    # (accrual-only never goes negative), but adds robustness for the
    # future MtM phase.
    if gain.amount < Decimal("0"):
        return TaxResult(
            gross=gross,
            gain=gain,
            tax_rate=Decimal("0"),
            tax_amount=Money.zero(gross.currency),
            net=gross,
        )

    match treatment:
        case TaxTreatment.IR_EXEMPT:
            rate = Decimal("0")
        case TaxTreatment.IR_REGRESSIVE:
            rate = regressive_rate_for(holding_days)
        case _:
            raise ValueError(f"Unknown tax treatment: {treatment}")

    tax_amount = gain * rate
    net = gross - tax_amount

    return TaxResult(
        gross=gross,
        gain=gain,
        tax_rate=rate,
        tax_amount=tax_amount,
        net=net,
    )


@dataclass(frozen=True, slots=True)
class FlowTaxResult:
    """Per-flow IR breakdown produced by compute_ir_schedule."""

    holding_days: int
    bracket_rate: Decimal
    taxable_interest: Money
    tax_amount: Money


def compute_ir_schedule(
    flow_interests: list[tuple[Money, int]],
    *,
    principal: Money,
    gross: Money,
    treatment: TaxTreatment,
) -> tuple[TaxResult, tuple[FlowTaxResult, ...]]:
    """Compute IR by taxing each cash flow at its own regressive bracket.

    Args:
        flow_interests: (interest_component, holding_days) per flow, chronological.
            holding_days is purchase->pay_date in calendar days (not period-to-period).
        principal: Amount originally invested.
        gross: Total received pre-tax (sum of all cash flow amounts).
        treatment: Which tax regime applies.

    Returns:
        (aggregate TaxResult, tuple of per-flow FlowTaxResult).
        aggregate.tax_rate is the effective blended rate (= single bracket for one flow).
        For negative gain, per_flow is () and tax is zero.

    KEY INVARIANT: for a single-element flow_interests where interest == gain and
    treatment == IR_REGRESSIVE, the returned aggregate matches compute_ir() exactly.
    """
    if principal.currency != gross.currency:
        raise ValueError(
            f"Currency mismatch: principal {principal.currency} "
            f"vs gross {gross.currency}"
        )
    for i, (interest, _) in enumerate(flow_interests):
        if interest.currency != gross.currency:
            raise ValueError(
                f"Currency mismatch: flow {i} interest {interest.currency} "
                f"vs gross {gross.currency}"
            )

    gain = gross - principal

    if gain.amount < Decimal("0"):
        return (
            TaxResult(
                gross=gross,
                gain=gain,
                tax_rate=Decimal("0"),
                tax_amount=Money.zero(gross.currency),
                net=gross,
            ),
            (),
        )

    per_flow: list[FlowTaxResult] = []
    total_tax = Money.zero(gross.currency)

    for interest, holding_days in flow_interests:
        if treatment == TaxTreatment.IR_EXEMPT:
            rate = Decimal("0")
        else:
            rate = regressive_rate_for(holding_days)
        tax_i = interest * rate
        per_flow.append(FlowTaxResult(
            holding_days=holding_days,
            bracket_rate=rate,
            taxable_interest=interest,
            tax_amount=tax_i,
        ))
        total_tax = total_tax + tax_i

    if treatment == TaxTreatment.IR_EXEMPT or gain.amount <= Decimal("0"):
        effective_rate = Decimal("0")
    elif len(per_flow) == 1:
        # Single-flow (bullet): effective rate IS the bracket rate — avoid the
        # quantization error that (tax_8dp / gain_8dp) would introduce.
        effective_rate = per_flow[0].bracket_rate
    else:
        effective_rate = total_tax.amount / gain.amount

    aggregate = TaxResult(
        gross=gross,
        gain=gain,
        tax_rate=effective_rate,
        tax_amount=total_tax,
        net=gross - total_tax,
    )
    return (aggregate, tuple(per_flow))