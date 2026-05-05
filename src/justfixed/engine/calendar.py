"""Brazilian business-day calendar utilities.

All Brazilian fixed-income math uses the 252-day basis: interest accrues
over business days (dias úteis), not calendar days. Holidays are defined
by ANBIMA, the standard authority for the Brazilian financial market.

This module wraps the `bizdays` library's ANBIMA calendar with a clean
date-based API. The wrapper is thin on purpose — its job is to centralize
the dependency, not to add behavior.

Convention: all interval functions use half-open intervals [start, end),
i.e. start inclusive, end exclusive. This matches Python's `range()` and
is the correct semantic for financial accrual ("days from purchase up to
but not including maturity").
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache

from bizdays import Calendar


# Canonical denominator for Brazilian rate math. This is a *convention*,
# not the actual average number of business days per year (which is ~252
# but varies). All Brazilian rates are quoted on this basis.
BUSINESS_DAYS_PER_YEAR = 252


@lru_cache(maxsize=1)
def _anbima_calendar() -> Calendar:
    """Lazily load and cache the ANBIMA calendar.

    Loading the calendar reads holiday tables from disk; we do it once
    per process. The lru_cache makes this a singleton without explicit
    global state.
    """
    return Calendar.load("ANBIMA")


def business_days_between(start: date, end: date) -> int:
    """Count business days in the half-open interval [start, end).

    If end <= start, returns 0 (consistent with empty intervals).

    Examples (assuming a typical year):
        >>> business_days_between(date(2024, 1, 1), date(2024, 2, 1))
        22
        >>> business_days_between(date(2024, 1, 15), date(2024, 1, 15))
        0
    """
    if end <= start:
        return 0
    return _anbima_calendar().bizdays(start, end)


def is_business_day(d: date) -> bool:
    """True if the given date is a business day per ANBIMA."""
    return _anbima_calendar().isbizday(d)


def add_business_days(start: date, n: int) -> date:
    """Return the date `n` business days after `start`.

    If `start` itself is not a business day, the result is the `n`-th
    business day strictly after the next business day on/after start.
    Negative `n` is supported (subtracts business days).

    Used for coupon scheduling and other forward-counting operations.
    """
    cal = _anbima_calendar()
    return cal.offset(start, n)


def next_business_day(d: date) -> date:
    """Return d itself if it's a business day, else the next one.

    Used to "roll" a date forward to the next valid settlement day.
    """
    cal = _anbima_calendar()
    if cal.isbizday(d):
        return d
    return cal.offset(d, 1)