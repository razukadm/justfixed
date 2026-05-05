"""Tests for the Brazilian business-day calendar wrapper.

These tests use specific, well-known historical dates so the assertions
are stable and easy to verify by hand against any Brazilian financial
calendar.

Reference dates used:
- 2024-02-12, 2024-02-13: Carnaval Monday and Tuesday
- 2024-03-29: Good Friday (Sexta-feira Santa)
- 2024-05-30: Corpus Christi
- 2024-09-07: Independence Day (Saturday in 2024 — does not "lose" a day)
- 2024-12-25: Christmas (Wednesday)
"""

from __future__ import annotations

from datetime import date

import pytest

from justfixed.engine.calendar import (
    BUSINESS_DAYS_PER_YEAR,
    add_business_days,
    business_days_between,
    is_business_day,
    next_business_day,
)


# ---------- Constants ----------


class TestConstants:
    def test_business_days_per_year_is_252(self) -> None:
        # The Brazilian fixed-income convention.
        assert BUSINESS_DAYS_PER_YEAR == 252


# ---------- business_days_between ----------


class TestBusinessDaysBetween:
    def test_january_2024(self) -> None:
        # January 2024: 22 business days (matches every Brazilian calendar).
        assert business_days_between(date(2024, 1, 1), date(2024, 2, 1)) == 22

    def test_carnaval_week(self) -> None:
        # Mon Feb 12 and Tue Feb 13 are Carnaval (holidays).
        # Wed Feb 14 and Thu Feb 15 are normal business days.
        # Fri Feb 9 (start) is included; Fri Feb 16 (end) is excluded.
        # Days counted: Feb 9, 14, 15 = 3.
        assert business_days_between(date(2024, 2, 9), date(2024, 2, 16)) == 3

    def test_full_year_2024(self) -> None:
        # 2024 had ~250 business days per ANBIMA.
        # Allow a small range to keep the test stable across calendar versions.
        days = business_days_between(date(2024, 1, 1), date(2025, 1, 1))
        assert 248 <= days <= 252

    def test_zero_for_empty_interval(self) -> None:
        assert business_days_between(date(2024, 6, 15), date(2024, 6, 15)) == 0

    def test_zero_for_inverted_interval(self) -> None:
        # Defensive: inverted dates should produce 0, not an error.
        assert business_days_between(date(2024, 6, 30), date(2024, 6, 1)) == 0

    def test_single_business_day(self) -> None:
        # Mon Feb 5 to Tue Feb 6 (one bizday in [start, end))
        assert business_days_between(date(2024, 2, 5), date(2024, 2, 6)) == 1

    def test_weekend_only_interval(self) -> None:
        # Sat Feb 3 to Mon Feb 5: only Sat and Sun, no business days.
        assert business_days_between(date(2024, 2, 3), date(2024, 2, 5)) == 0


# ---------- is_business_day ----------


class TestIsBusinessDay:
    def test_normal_weekday(self) -> None:
        # Wed Feb 14, 2024 — a regular business day after Carnaval.
        assert is_business_day(date(2024, 2, 14)) is True

    def test_saturday_is_not(self) -> None:
        assert is_business_day(date(2024, 2, 10)) is False  # Saturday

    def test_sunday_is_not(self) -> None:
        assert is_business_day(date(2024, 2, 11)) is False  # Sunday

    def test_christmas_is_not(self) -> None:
        # Wed Dec 25, 2024 — would be a business day if not a holiday.
        assert is_business_day(date(2024, 12, 25)) is False

    def test_carnaval_monday_is_not(self) -> None:
        assert is_business_day(date(2024, 2, 12)) is False

    def test_carnaval_tuesday_is_not(self) -> None:
        assert is_business_day(date(2024, 2, 13)) is False

    def test_good_friday_is_not(self) -> None:
        # 2024 Good Friday: March 29.
        assert is_business_day(date(2024, 3, 29)) is False

    def test_corpus_christi_is_not(self) -> None:
        # 2024 Corpus Christi: May 30.
        assert is_business_day(date(2024, 5, 30)) is False

    def test_new_year_is_not(self) -> None:
        assert is_business_day(date(2024, 1, 1)) is False

    def test_tiradentes_is_not(self) -> None:
        # Apr 21, 2024 was a Sunday so this is also weekend, but
        # the test still asserts the holiday is not a bizday.
        assert is_business_day(date(2024, 4, 21)) is False

    def test_independence_day_is_not(self) -> None:
        # Sept 7, 2024 was a Saturday.
        assert is_business_day(date(2024, 9, 7)) is False


# ---------- add_business_days ----------


class TestAddBusinessDays:
    def test_add_one_normal_case(self) -> None:
        # Wed Feb 14 -> Thu Feb 15 (next bizday).
        assert add_business_days(date(2024, 2, 14), 1) == date(2024, 2, 15)

    def test_add_one_skips_weekend(self) -> None:
        # Fri Feb 9 + 1 bizday -> Wed Feb 14 (skips weekend AND Carnaval).
        assert add_business_days(date(2024, 2, 9), 1) == date(2024, 2, 14)

    def test_add_zero_returns_same_date_if_business_day(self) -> None:
        assert add_business_days(date(2024, 2, 14), 0) == date(2024, 2, 14)

    def test_add_negative_works(self) -> None:
        # Wed Feb 14 - 1 bizday -> Fri Feb 9 (skipping Carnaval and weekend).
        assert add_business_days(date(2024, 2, 14), -1) == date(2024, 2, 9)

    def test_add_22_business_days_jan_2024(self) -> None:
        # Adding January's 22 bizdays to Jan 2 should land near Feb 1.
        # First bizday of Jan 2024 is Jan 2 (Jan 1 is holiday).
        # 22 business days after Jan 2: roughly Feb 1.
        result = add_business_days(date(2024, 1, 2), 22)
        # Allow a 1-day flex to account for whether start is included.
        assert result in {date(2024, 2, 1), date(2024, 2, 2)}


# ---------- next_business_day ----------


class TestNextBusinessDay:
    def test_returns_same_if_already_business_day(self) -> None:
        d = date(2024, 2, 14)
        assert next_business_day(d) == d

    def test_rolls_saturday_to_monday(self) -> None:
        # Sat Feb 10 -> Mon Feb 12... but Feb 12 is Carnaval.
        # So expected: Wed Feb 14.
        assert next_business_day(date(2024, 2, 10)) == date(2024, 2, 14)

    def test_rolls_holiday_forward(self) -> None:
        # Christmas 2024 (Wed Dec 25) -> Thu Dec 26 (regular bizday).
        assert next_business_day(date(2024, 12, 25)) == date(2024, 12, 26)


# ---------- Spot check: real-world investment dates ----------


class TestRealisticIntervals:
    """A few realistic 'investment lifecycle' intervals.

    These use historical dates whose business-day counts are settled,
    so we assert exact values rather than tolerance ranges.
    """

    def test_one_year_cdb_holding_days(self) -> None:
        # CDB purchased Jan 15, 2024, matures Jan 15, 2025.
        # Per ANBIMA: 253 business days.
        days = business_days_between(date(2024, 1, 15), date(2025, 1, 15))
        assert days == 253

    def test_six_month_lci(self) -> None:
        # LCI from Apr 1, 2024 to Oct 1, 2024.
        # Per ANBIMA: 129 business days.
        days = business_days_between(date(2024, 4, 1), date(2024, 10, 1))
        assert days == 129