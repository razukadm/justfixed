"""Tests for product taxonomy — ProductRule and CouponFrequency."""

from __future__ import annotations

from justfixed.domain.product import CouponFrequency


class TestCouponFrequencyToDisplay:
    def test_none_returns_portuguese(self) -> None:
        assert CouponFrequency.NONE.to_display() == "Nenhum"

    def test_monthly_returns_portuguese(self) -> None:
        assert CouponFrequency.MONTHLY.to_display() == "Mensal"

    def test_semi_annual_returns_portuguese(self) -> None:
        assert CouponFrequency.SEMI_ANNUAL.to_display() == "Semestral"
