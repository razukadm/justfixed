"""Tests for the Money value object."""

from decimal import Decimal

import pytest

from justfixed.domain.money import Money


# ---------- Construction ----------
class TestConstruction:
    """Money should accept valid inputs and reject invalid ones."""

    def test_from_string(self) -> None:
        m = Money.from_reais("100.50")
        assert m.amount == Decimal("100.50")
        assert m.currency == "BRL"

    def test_from_int(self) -> None:
        m = Money.from_reais(100)
        assert m.amount == Decimal("100")

    def test_from_decimal(self) -> None:
        m = Money.from_reais(Decimal("100.50"))
        assert m.amount == Decimal("100.50")

    def test_zero(self) -> None:
        assert Money.zero().amount == Decimal("0")

    def test_float_rejected_in_factory(self) -> None:
        with pytest.raises(TypeError, match="not float"):
            Money.from_reais(100.50)  # type: ignore[arg-type]

    def test_float_rejected_in_constructor(self) -> None:
        with pytest.raises(TypeError, match="cannot be constructed from float"):
            Money(100.50)  # type: ignore[arg-type]


# ---------- Equality and immutability ----------
class TestImmutability:
    def test_equal_by_value(self) -> None:
        a = Money.from_reais("100.00")
        b = Money.from_reais("100")
        assert a == b

    def test_different_amounts_not_equal(self) -> None:
        assert Money.from_reais("100") != Money.from_reais("101")

    def test_cannot_mutate(self) -> None:
        m = Money.from_reais("100")
        with pytest.raises((AttributeError, TypeError)):
            m.amount = Decimal("200")  # type: ignore[misc]


# ---------- Arithmetic ----------
class TestArithmetic:
    def test_addition(self) -> None:
        result = Money.from_reais("100.50") + Money.from_reais("49.50")
        assert result == Money.from_reais("150.00")

    def test_subtraction(self) -> None:
        result = Money.from_reais("100.00") - Money.from_reais("30.00")
        assert result == Money.from_reais("70.00")

    def test_multiplication_by_int(self) -> None:
        result = Money.from_reais("100") * 3
        assert result == Money.from_reais("300")

    def test_multiplication_by_decimal(self) -> None:
        # Compound factor of 1.12 (12% rate) on R$ 1000.
        result = Money.from_reais("1000") * Decimal("1.12")
        assert result == Money.from_reais("1120.00")

    def test_right_multiplication(self) -> None:
        # Scalar on the left should also work.
        result = 3 * Money.from_reais("100")
        assert result == Money.from_reais("300")

    def test_division(self) -> None:
        result = Money.from_reais("100") / 4
        assert result == Money.from_reais("25.00")

    def test_money_times_money_forbidden(self) -> None:
        with pytest.raises(TypeError, match="Money by Money"):
            Money.from_reais("10") * Money.from_reais("10")  # type: ignore[operator]

    def test_money_times_float_forbidden(self) -> None:
        with pytest.raises(TypeError, match="not float"):
            Money.from_reais("10") * 1.5  # type: ignore[operator]

    def test_negation(self) -> None:
        assert -Money.from_reais("100") == Money.from_reais("-100")


# ---------- Currency safety ----------
class TestCurrencySafety:
    def test_cannot_add_different_currencies(self) -> None:
        brl = Money.from_reais("100", currency="BRL")
        usd = Money.from_reais("100", currency="USD")
        with pytest.raises(ValueError, match="Currency mismatch"):
            _ = brl + usd

    def test_cannot_compare_different_currencies(self) -> None:
        brl = Money.from_reais("100", currency="BRL")
        usd = Money.from_reais("100", currency="USD")
        with pytest.raises(ValueError, match="Currency mismatch"):
            _ = brl < usd


# ---------- Comparison ----------
class TestComparison:
    def test_less_than(self) -> None:
        assert Money.from_reais("99") < Money.from_reais("100")

    def test_greater_than(self) -> None:
        assert Money.from_reais("101") > Money.from_reais("100")

    def test_less_or_equal(self) -> None:
        assert Money.from_reais("100") <= Money.from_reais("100")
        assert Money.from_reais("99") <= Money.from_reais("100")


# ---------- Brazilian display ----------
class TestDisplay:
    def test_simple_amount(self) -> None:
        assert Money.from_reais("100").to_display() == "R$ 100,00"

    def test_amount_with_decimals(self) -> None:
        assert Money.from_reais("1234.56").to_display() == "R$ 1.234,56"

    def test_large_amount(self) -> None:
        assert Money.from_reais("1234567.89").to_display() == "R$ 1.234.567,89"

    def test_negative_amount(self) -> None:
        assert Money.from_reais("-1234.56").to_display() == "-R$ 1.234,56"

    def test_zero(self) -> None:
        assert Money.zero().to_display() == "R$ 0,00"

    def test_str_uses_display(self) -> None:
        assert str(Money.from_reais("100")) == "R$ 100,00"


# ---------- Precision ----------
class TestPrecision:
    """Internal precision should survive compound multiplication."""

    def test_compound_does_not_lose_cents(self) -> None:
        # Multiply by 1.0001 a thousand times. The naive float approach
        # would drift; Decimal with 8 internal decimals should not.
        m = Money.from_reais("1000")
        factor = Decimal("1.0001")
        for _ in range(1000):
            m = m * factor
        # 1000 * 1.0001^1000 ≈ 1105.16 (theoretical: 1105.156541...)
        # We allow a tight tolerance because we quantize to 8 decimals.
        assert Money.from_reais("1105.15") < m < Money.from_reais("1105.17")