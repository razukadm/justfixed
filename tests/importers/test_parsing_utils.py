"""Direct unit tests for _parsing_utils._parse_brazilian_percent_to_fraction.

The function lives in its own module so both xp_mapper and btg_mapper can
import it without either reaching into the other's internals (B32).
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from justfixed.importers._parsing_utils import _parse_brazilian_percent_to_fraction


class TestParseBrazilianPercentToFraction:
    def test_plain_percent(self) -> None:
        # "95,50%" → 95.50 / 100 = 0.9550
        assert _parse_brazilian_percent_to_fraction("95,50%") == Decimal("0.9550")

    def test_thousands_separator(self) -> None:
        # "1.000,00%" → 1000.00 / 100 = 10.0000
        assert _parse_brazilian_percent_to_fraction("1.000,00%") == Decimal("10.0000")

    def test_integer_percent_no_decimal(self) -> None:
        # "100%" → integer-only, decimal_part=None → combined "100.00" → 1.0000
        assert _parse_brazilian_percent_to_fraction("100%") == Decimal("1.0000")

    def test_leading_and_trailing_whitespace(self) -> None:
        # Regex anchors allow surrounding whitespace
        assert _parse_brazilian_percent_to_fraction("  95,50%  ") == Decimal("0.9550")

    def test_raises_on_malformed_string(self) -> None:
        with pytest.raises(ValueError, match="Not a valid Brazilian percent"):
            _parse_brazilian_percent_to_fraction("not-a-percent")

    def test_raises_on_missing_percent_sign(self) -> None:
        with pytest.raises(ValueError):
            _parse_brazilian_percent_to_fraction("95,50")

    def test_raises_on_empty_string(self) -> None:
        with pytest.raises(ValueError):
            _parse_brazilian_percent_to_fraction("")

    def test_cdi_spread_typical_value(self) -> None:
        # Typical CDI+ spread seen in real XP/BTG data: "100,00%"
        assert _parse_brazilian_percent_to_fraction("100,00%") == Decimal("1.0000")

    def test_small_fraction(self) -> None:
        # "0,50%" → 0.50 / 100 = 0.0050
        assert _parse_brazilian_percent_to_fraction("0,50%") == Decimal("0.0050")
