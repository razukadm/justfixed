"""Cash flow scheduling for fixed-income investments.

Two responsibilities:

1. coupon_dates(investment): when does each periodic payment occur?
   - For bullets: empty list (or just the maturity, depending on view)
   - For semi-annual: every 6 months back from maturity
   - For monthly: every 1 month back from maturity
   Coupon dates falling on non-business days roll forward to the next
   business day (standard Brazilian convention).

2. schedule(investment, ...): the full CashFlow list with amounts.
   - Each periodic coupon pays the interest accrued over its period.
   - Final payment combines last coupon + principal.

Simplifications for MVP (accrual-only, no DI-curve MtM):
- Coupon amounts are computed by accruing the principal over the period
  between coupon dates. Principal stays at face value.
- For PostFixedCDI/IPCA, the same assumed_cdi/assumed_ipca is used for
  every period. This is fine for projection but NOT mark-to-market.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum

from dateutil.relativedelta import relativedelta

from justfixed.domain.investment import Investment
from justfixed.domain.money import Money
from justfixed.domain.product import CouponFrequency
from justfixed.engine.accrual import accrue
from justfixed.engine.calendar import (
    business_days_between,
    next_business_day,
)
from justfixed.engine.curve import Curve


class CashFlowKind(Enum):
    """What a cash flow represents."""

    COUPON = "coupon"                                 # interim interest payment
    PRINCIPAL = "principal"                           # principal-only (bullet)
    COUPON_AND_PRINCIPAL = "coupon_and_principal"     # final payment combining both


@dataclass(frozen=True, slots=True)
class CashFlow:
    """A scheduled payment from an investment to its holder.

    Dates are calendar dates that have been rolled forward to the next
    business day if necessary. Amounts are gross (pre-tax).
    """

    date: date
    amount: Money
    kind: CashFlowKind


def coupon_dates(investment: Investment) -> list[date]:
    """Return the list of coupon dates for this investment, ascending.

    For bullets (CouponFrequency.NONE), returns an empty list — the
    maturity-only payment is handled by `schedule()`, not here.

    Coupon dates are computed by stepping BACKWARD from maturity in
    the appropriate interval, then rolled forward to business days
    if they fall on weekends/holidays. The maturity date itself is
    NOT included (it's the principal payment, returned separately).
    Only coupon dates strictly between purchase_date and maturity_date
    are included.
    """
    freq = investment.coupon_frequency
    if freq == CouponFrequency.NONE:
        return []

    # Step size by frequency.
    if freq == CouponFrequency.MONTHLY:
        step = relativedelta(months=1)
    elif freq == CouponFrequency.SEMI_ANNUAL:
        step = relativedelta(months=6)
    else:
        raise ValueError(f"Unsupported coupon frequency: {freq}")

    # Walk backward from maturity, collecting dates.
    dates: list[date] = []
    cursor = investment.maturity_date - step
    while cursor > investment.purchase_date:
        # Roll forward to the next business day if needed.
        rolled = next_business_day(cursor)
        # If rolling forward pushes us past maturity, drop the date —
        # it would conflict with the final principal payment.
        if rolled < investment.maturity_date:
            dates.append(rolled)
        cursor = cursor - step

    # We collected oldest-last; reverse to chronological order.
    dates.reverse()
    return dates


def schedule(
    investment: Investment,
    *,
    assumed_cdi: Decimal | None = None,
    assumed_ipca: Decimal | None = None,
    cdi_curve: Curve | None = None,
    ipca_curve: Curve | None = None,
) -> list[CashFlow]:
    """Generate the full cash flow schedule for an investment.

    Args:
        investment: The Investment to schedule.
        assumed_cdi: Required for PostFixedCDI rates; ignored otherwise.
        assumed_ipca: Required for PostFixedIPCA rates; ignored otherwise.

    Returns:
        A chronological list of CashFlow objects.
        - For bullets: one CashFlow at maturity, kind=PRINCIPAL.
        - For coupon products: N coupons at intermediate dates, plus
          a final CashFlow at maturity with kind=COUPON_AND_PRINCIPAL.

    Each coupon's amount is the interest accrued on the principal over
    that coupon's period. The final payment includes principal.
    """
    if investment.is_bullet:
        # Single payment at maturity: full accrual over the holding period.
        bizdays = business_days_between(
            investment.purchase_date, investment.maturity_date
        )
        effective_cdi = (
            cdi_curve.rate_at(investment.maturity_date)
            if (cdi_curve is not None and cdi_curve.vertices)
            else assumed_cdi
        )
        effective_ipca = (
            ipca_curve.rate_at(investment.maturity_date)
            if (ipca_curve is not None and ipca_curve.vertices)
            else assumed_ipca
        )
        gross = accrue(
            investment.principal,
            investment.rate,
            bizdays,
            assumed_cdi=effective_cdi,
            assumed_ipca=effective_ipca,
        )
        return [
            CashFlow(
                date=investment.maturity_date,
                amount=gross,
                kind=CashFlowKind.PRINCIPAL,
            )
        ]

    # Coupon-paying product. Build the date sequence: purchase, then
    # each coupon date, then maturity.
    coupon_ds = coupon_dates(investment)
    flows: list[CashFlow] = []
    period_start = investment.purchase_date

    # Each coupon: interest accrued over [period_start, coupon_date].
    for coupon_date in coupon_ds:
        bizdays = business_days_between(period_start, coupon_date)
        effective_cdi = (
            cdi_curve.rate_at(coupon_date)
            if (cdi_curve is not None and cdi_curve.vertices)
            else assumed_cdi
        )
        # IPCA diverges from CDI here: breakeven is a term expectation for the
        # whole instrument, so all flows use rate_at(maturity), not rate_at(coupon_date).
        effective_ipca = (
            ipca_curve.rate_at(investment.maturity_date)
            if (ipca_curve is not None and ipca_curve.vertices)
            else assumed_ipca
        )
        accrued = accrue(
            investment.principal,
            investment.rate,
            bizdays,
            assumed_cdi=effective_cdi,
            assumed_ipca=effective_ipca,
        )
        coupon_amount = accrued - investment.principal
        flows.append(
            CashFlow(
                date=coupon_date,
                amount=coupon_amount,
                kind=CashFlowKind.COUPON,
            )
        )
        period_start = coupon_date

    # Final payment: last coupon + principal.
    bizdays = business_days_between(period_start, investment.maturity_date)
    effective_cdi = (
        cdi_curve.rate_at(investment.maturity_date)
        if (cdi_curve is not None and cdi_curve.vertices)
        else assumed_cdi
    )
    effective_ipca = (
        ipca_curve.rate_at(investment.maturity_date)
        if (ipca_curve is not None and ipca_curve.vertices)
        else assumed_ipca
    )
    accrued = accrue(
        investment.principal,
        investment.rate,
        bizdays,
        assumed_cdi=effective_cdi,
        assumed_ipca=effective_ipca,
    )
    final_coupon = accrued - investment.principal
    final_amount = final_coupon + investment.principal
    flows.append(
        CashFlow(
            date=investment.maturity_date,
            amount=final_amount,
            kind=CashFlowKind.COUPON_AND_PRINCIPAL,
        )
    )

    return flows