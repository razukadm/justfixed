"""Rate types for Brazilian fixed-income products.

Three rate kinds are supported:
- Prefixed: a fixed annual rate, e.g. 12% a.a.
- PostFixedCDI: a percentage of the CDI rate, e.g. 112% do CDI.
- PostFixedIPCA: IPCA + a fixed annual spread, e.g. IPCA + 5.5% a.a.

Design notes:
- Rates are value objects: immutable, comparable by value.
- Rate types are a sealed hierarchy (closed sum type). To add a new
  rate kind, you must (a) add a subclass here and (b) update every
  match statement in the engine. The type checker will flag misses.
- The math of "apply this rate over a period" lives in the engine,
  not on the rate classes. Rates are pure data.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Self


def _to_decimal(value: str | int | Decimal) -> Decimal:
    """Coerce input to Decimal, rejecting floats."""
    if isinstance(value, float):
        raise TypeError(
            "Rates cannot be constructed from float. Use Decimal or string, "
            "e.g. PostFixedCDI.from_percent('112')."
        )
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _format_brazilian_percent(value: Decimal, places: int = 2) -> str:
    """Format a Decimal as a Brazilian percentage string.

    Example: Decimal('5.5') -> '5,50%'
    """
    # Use English comma-and-period, then swap.
    formatted = f"{value:,.{places}f}"
    swapped = formatted.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{swapped}%"


@dataclass(frozen=True, slots=True)
class Rate:
    """Abstract base for all rate types.

    Subclasses are sealed: only Prefixed, PostFixedCDI, PostFixedIPCA exist.
    Do not instantiate this directly.
    """

    def to_display(self) -> str:
        raise NotImplementedError("Subclasses must implement to_display.")

    def __str__(self) -> str:
        return self.to_display()


@dataclass(frozen=True, slots=True)
class Prefixed(Rate):
    """A fixed annual rate, expressed as a decimal fraction.

    Example: Prefixed(Decimal('0.12')) means 12% a.a.

    The annual_rate is stored as a fraction (0.12), not as a percentage (12).
    Use the `from_percent` factory if you have a percentage value.
    """

    annual_rate: Decimal

    def __post_init__(self) -> None:
        normalized = _to_decimal(self.annual_rate)
        object.__setattr__(self, "annual_rate", normalized)

    @classmethod
    def from_percent(cls, percent: str | int | Decimal) -> Self:
        """Construct from a percentage value, e.g. '12' for 12% a.a."""
        return cls(_to_decimal(percent) / Decimal("100"))

    @property
    def annual_percent(self) -> Decimal:
        """The annual rate as a percentage value (e.g. 12 for 12%)."""
        return self.annual_rate * Decimal("100")

    def to_display(self) -> str:
        return f"{_format_brazilian_percent(self.annual_percent)} a.a."


@dataclass(frozen=True, slots=True)
class PostFixedCDI(Rate):
    """A post-fixed rate expressed as a percentage of the CDI.

    Example: PostFixedCDI(Decimal('1.12')) means 112% do CDI.

    The cdi_percentage is stored as a fraction-multiplier (1.12), not
    as a percentage (112). Use `from_percent` if you have a percentage.
    """

    cdi_percentage: Decimal

    def __post_init__(self) -> None:
        normalized = _to_decimal(self.cdi_percentage)
        object.__setattr__(self, "cdi_percentage", normalized)

    @classmethod
    def from_percent(cls, percent: str | int | Decimal) -> Self:
        """Construct from a percentage value, e.g. '112' for 112% do CDI."""
        return cls(_to_decimal(percent) / Decimal("100"))

    @property
    def cdi_percent_value(self) -> Decimal:
        """The CDI multiplier as a percentage (e.g. 112 for 112%)."""
        return self.cdi_percentage * Decimal("100")

    def to_display(self) -> str:
        return f"{_format_brazilian_percent(self.cdi_percent_value)} do CDI"


@dataclass(frozen=True, slots=True)
class PostFixedIPCA(Rate):
    """IPCA + a fixed annual spread.

    Example: PostFixedIPCA(Decimal('0.055')) means IPCA + 5.5% a.a.

    The spread is stored as a fraction (0.055), not as a percentage (5.5).
    Use `from_percent` if you have a percentage.
    """

    spread: Decimal

    def __post_init__(self) -> None:
        normalized = _to_decimal(self.spread)
        object.__setattr__(self, "spread", normalized)

    @classmethod
    def from_percent(cls, percent: str | int | Decimal) -> Self:
        """Construct from a percentage value, e.g. '5.5' for IPCA + 5.5%."""
        return cls(_to_decimal(percent) / Decimal("100"))

    @property
    def spread_percent(self) -> Decimal:
        """The spread as a percentage (e.g. 5.5 for IPCA + 5.5%)."""
        return self.spread * Decimal("100")

    def to_display(self) -> str:
        return f"IPCA + {_format_brazilian_percent(self.spread_percent)}"