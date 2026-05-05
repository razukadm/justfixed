"""Money value object using Decimal for exact arithmetic.

Brazilian context:
- Currency is BRL (Real).
- Display format: R$ 1.234,56 (period thousands separator, comma decimal).
- Internal precision: 8 decimal places (sufficient for compound rate math
  without rounding error accumulation).

Design notes:
- Money is a value object: immutable, comparable by value.
- Forbidden: Money * Money (meaningless), Money + scalar (ambiguous units).
- Allowed: Money + Money (same currency), Money * Decimal/int (scalar),
  Money / Decimal/int (scalar), comparisons.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Self


# Internal precision for Money amounts. 8 places is enough to multiply
# by daily compound factors many times without losing cents.
_INTERNAL_PRECISION = Decimal("0.00000001")

# Display precision: 2 decimal places for BRL.
_DISPLAY_PRECISION = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class Money:
    """An amount of money in a specific currency.

    Use the factory methods `from_reais` or `zero` rather than calling
    the constructor directly with raw Decimal values.
    """

    amount: Decimal
    currency: str = "BRL"

    def __post_init__(self) -> None:
        # Defensive: callers should pass Decimal, but coerce strings/ints
        # to be friendly. Floats are forbidden — they reintroduce the very
        # problem Money exists to prevent.
        if isinstance(self.amount, float):
            raise TypeError(
                "Money cannot be constructed from float. "
                "Use Decimal or string instead, e.g. Money.from_reais('100.50')."
            )
        if not isinstance(self.amount, Decimal):
            # Bypass frozen=True via object.__setattr__ for normalization.
            object.__setattr__(self, "amount", Decimal(self.amount))
        # Normalize precision so equality works as expected.
        normalized = self.amount.quantize(_INTERNAL_PRECISION, rounding=ROUND_HALF_EVEN)
        object.__setattr__(self, "amount", normalized)

    # ------------- Factories -------------
    @classmethod
    def from_reais(cls, amount: str | int | Decimal, currency: str = "BRL") -> Self:
        """Construct a Money value from a string, int, or Decimal."""
        if isinstance(amount, float):
            raise TypeError("Use a string or Decimal, not float.")
        return cls(Decimal(str(amount)), currency)

    @classmethod
    def zero(cls, currency: str = "BRL") -> Self:
        return cls(Decimal("0"), currency)

    # ------------- Arithmetic -------------
    def __add__(self, other: Money) -> Money:
        self._require_same_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._require_same_currency(other)
        return Money(self.amount - other.amount, self.currency)

    def __mul__(self, scalar: Decimal | int) -> Money:
        if isinstance(scalar, Money):
            raise TypeError("Cannot multiply Money by Money.")
        if isinstance(scalar, float):
            raise TypeError("Multiply Money only by Decimal or int, not float.")
        return Money(self.amount * Decimal(scalar), self.currency)

    __rmul__ = __mul__  # supports `2 * money` as well as `money * 2`

    def __truediv__(self, scalar: Decimal | int) -> Money:
        if isinstance(scalar, Money):
            raise TypeError("Money / Money is not defined here.")
        if isinstance(scalar, float):
            raise TypeError("Divide Money only by Decimal or int, not float.")
        return Money(self.amount / Decimal(scalar), self.currency)

    def __neg__(self) -> Money:
        return Money(-self.amount, self.currency)

    # ------------- Comparison -------------
    def __lt__(self, other: Money) -> bool:
        self._require_same_currency(other)
        return self.amount < other.amount

    def __le__(self, other: Money) -> bool:
        self._require_same_currency(other)
        return self.amount <= other.amount

    def __gt__(self, other: Money) -> bool:
        self._require_same_currency(other)
        return self.amount > other.amount

    def __ge__(self, other: Money) -> bool:
        self._require_same_currency(other)
        return self.amount >= other.amount

    # ------------- Display -------------
    def to_display(self) -> str:
        """Format as Brazilian currency: R$ 1.234,56."""
        rounded = self.amount.quantize(_DISPLAY_PRECISION, rounding=ROUND_HALF_EVEN)
        # Format with English convention first, then swap separators.
        sign = "-" if rounded < 0 else ""
        abs_str = f"{abs(rounded):,.2f}"  # e.g. "1,234.56"
        # Swap: ',' (thousands) <-> '.' (decimal)
        swapped = abs_str.replace(",", "X").replace(".", ",").replace("X", ".")
        return f"{sign}R$ {swapped}"

    def __str__(self) -> str:
        return self.to_display()

    # ------------- Internal helpers -------------
    def _require_same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise ValueError(
                f"Currency mismatch: {self.currency} vs {other.currency}"
            )