"""Tests for the Rate hierarchy."""
import dataclasses
from decimal import Decimal

import pytest

from justfixed.domain.rates import (
    PostFixedCDI,
    PostFixedCDIPlusSpread,
    PostFixedIPCA,
    Prefixed,
    Rate,
    rate_type_label,
)


# ---------- Prefixed ----------
class TestPrefixed:
    def test_from_decimal_fraction(self) -> None:
        r = Prefixed(Decimal("0.12"))
        assert r.annual_rate == Decimal("0.12")

    def test_from_percent_string(self) -> None:
        r = Prefixed.from_percent("12")
        assert r.annual_rate == Decimal("0.12")

    def test_from_percent_with_decimals(self) -> None:
        r = Prefixed.from_percent("12.5")
        assert r.annual_rate == Decimal("0.125")

    def test_annual_percent_property(self) -> None:
        r = Prefixed.from_percent("12")
        assert r.annual_percent == Decimal("12")

    def test_float_rejected(self) -> None:
        with pytest.raises(TypeError, match="cannot be constructed from float"):
            Prefixed(0.12)  # type: ignore[arg-type]

    def test_display(self) -> None:
        assert Prefixed.from_percent("12").to_display() == "12,00% a.a."

    def test_display_with_decimals(self) -> None:
        assert Prefixed.from_percent("12.5").to_display() == "12,50% a.a."

    def test_str_matches_display(self) -> None:
        r = Prefixed.from_percent("12")
        assert str(r) == "12,00% a.a."


# ---------- PostFixedCDI ----------
class TestPostFixedCDI:
    def test_from_decimal_fraction(self) -> None:
        r = PostFixedCDI(Decimal("1.12"))
        assert r.cdi_percentage == Decimal("1.12")

    def test_from_percent_string(self) -> None:
        r = PostFixedCDI.from_percent("112")
        assert r.cdi_percentage == Decimal("1.12")

    def test_from_percent_exactly_100(self) -> None:
        r = PostFixedCDI.from_percent("100")
        assert r.cdi_percentage == Decimal("1.00")

    def test_cdi_percent_value(self) -> None:
        r = PostFixedCDI.from_percent("112")
        assert r.cdi_percent_value == Decimal("112")

    def test_display(self) -> None:
        assert PostFixedCDI.from_percent("112").to_display() == "112,00% do CDI"

    def test_display_with_decimals(self) -> None:
        assert PostFixedCDI.from_percent("112.5").to_display() == "112,50% do CDI"

    def test_float_rejected(self) -> None:
        with pytest.raises(TypeError, match="cannot be constructed from float"):
            PostFixedCDI(1.12)  # type: ignore[arg-type]


# ---------- PostFixedIPCA ----------
class TestPostFixedIPCA:
    def test_from_decimal_fraction(self) -> None:
        r = PostFixedIPCA(Decimal("0.055"))
        assert r.spread == Decimal("0.055")

    def test_from_percent_string(self) -> None:
        r = PostFixedIPCA.from_percent("5.5")
        assert r.spread == Decimal("0.055")

    def test_spread_percent(self) -> None:
        r = PostFixedIPCA.from_percent("5.5")
        assert r.spread_percent == Decimal("5.5")

    def test_display(self) -> None:
        assert PostFixedIPCA.from_percent("5.5").to_display() == "IPCA + 5,50%"

    def test_display_zero_spread(self) -> None:
        # Edge case: IPCA + 0% means the bond just tracks inflation.
        assert PostFixedIPCA.from_percent("0").to_display() == "IPCA + 0,00%"

    def test_float_rejected(self) -> None:
        with pytest.raises(TypeError, match="cannot be constructed from float"):
            PostFixedIPCA(0.055)  # type: ignore[arg-type]


# ---------- Equality and immutability across types ----------
class TestEqualityAndImmutability:
    def test_same_type_equal_values_are_equal(self) -> None:
        a = PostFixedCDI.from_percent("112")
        b = PostFixedCDI(Decimal("1.12"))
        assert a == b

    def test_different_subclasses_not_equal(self) -> None:
        # A Prefixed 12% and a PostFixedCDI 112% are conceptually different,
        # even if their stored numbers happen to match. dataclass equality
        # respects the type, so these compare unequal.
        prefixed = Prefixed(Decimal("1.12"))
        post_cdi = PostFixedCDI(Decimal("1.12"))
        assert prefixed != post_cdi

    def test_cannot_mutate_prefixed(self) -> None:
        r = Prefixed.from_percent("12")
        with pytest.raises((AttributeError, TypeError)):
            r.annual_rate = Decimal("0.20")  # type: ignore[misc]

    def test_cannot_mutate_post_cdi(self) -> None:
        r = PostFixedCDI.from_percent("112")
        with pytest.raises((AttributeError, TypeError)):
            r.cdi_percentage = Decimal("1.20")  # type: ignore[misc]


# ---------- Polymorphism check ----------
class TestPolymorphism:
    """All three rate kinds should be usable as Rate."""

    def test_all_subclasses_are_rate(self) -> None:
        rates: list[Rate] = [
            Prefixed.from_percent("12"),
            PostFixedCDI.from_percent("112"),
            PostFixedIPCA.from_percent("5.5"),
        ]
        for r in rates:
            assert isinstance(r, Rate)
            # to_display works for every kind
            assert isinstance(r.to_display(), str)


# ---------- Pattern matching (preview of engine usage) ----------
class TestMatching:
    """Demonstrate the dispatch pattern the engine will use."""

    def describe(self, rate: Rate) -> str:
        match rate:
            case Prefixed():
                return "fixed annual"
            case PostFixedCDI():
                return "tracks CDI"
            case PostFixedIPCA():
                return "tracks inflation"
            case _:
                # If we ever add a fourth Rate subclass and forget to handle
                # it here, this branch fires and the test fails.
                raise AssertionError(f"Unhandled rate type: {type(rate).__name__}")

    def test_match_prefixed(self) -> None:
        assert self.describe(Prefixed.from_percent("12")) == "fixed annual"

    def test_match_post_cdi(self) -> None:
        assert self.describe(PostFixedCDI.from_percent("112")) == "tracks CDI"

    def test_match_post_ipca(self) -> None:
        assert self.describe(PostFixedIPCA.from_percent("5.5")) == "tracks inflation"


class TestPostFixedCDIPlusSpread:
    """The CDI + fixed spread rate (e.g. 'CDI + 2,05%')."""

    def test_from_decimal_fraction(self) -> None:
        rate = PostFixedCDIPlusSpread(Decimal("0.0205"))
        assert rate.spread == Decimal("0.0205")

    def test_from_percent_string(self) -> None:
        rate = PostFixedCDIPlusSpread.from_percent("2.05")
        assert rate.spread == Decimal("0.0205")

    def test_from_percent_with_decimals(self) -> None:
        rate = PostFixedCDIPlusSpread.from_percent("3.75")
        assert rate.spread == Decimal("0.0375")

    def test_spread_percent_property(self) -> None:
        rate = PostFixedCDIPlusSpread.from_percent("2.05")
        assert rate.spread_percent == Decimal("2.05")

    def test_float_rejected(self) -> None:
        with pytest.raises(TypeError):
            PostFixedCDIPlusSpread(0.0205)  # type: ignore[arg-type]

    def test_display(self) -> None:
        rate = PostFixedCDIPlusSpread.from_percent("2.05")
        assert rate.to_display() == "CDI + 2,05%"

    def test_display_with_zero_spread(self) -> None:
        rate = PostFixedCDIPlusSpread(Decimal("0"))
        assert rate.to_display() == "CDI + 0,00%"

    def test_distinct_from_post_fixed_cdi(self) -> None:
        """A 110% CDI rate is NOT equal to a CDI+10% rate, even though
        they're textually similar. They're different math entirely."""
        cdi_pct = PostFixedCDI.from_percent("110")
        cdi_plus = PostFixedCDIPlusSpread.from_percent("10")
        assert cdi_pct != cdi_plus

    def test_immutable(self) -> None:
        rate = PostFixedCDIPlusSpread.from_percent("2.05")
        with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
            rate.spread = Decimal("0.05")  # type: ignore[misc]

    def test_is_a_rate(self) -> None:
        rate = PostFixedCDIPlusSpread.from_percent("2.05")
        assert isinstance(rate, Rate)


# ---------- rate_type_label ----------
class TestRateTypeLabel:
    def test_prefixed(self) -> None:
        assert rate_type_label(Prefixed.from_percent("12")) == "Pré"

    def test_post_fixed_cdi(self) -> None:
        assert rate_type_label(PostFixedCDI.from_percent("112")) == "Pós"

    def test_post_fixed_cdi_plus_spread(self) -> None:
        assert rate_type_label(PostFixedCDIPlusSpread.from_percent("2.05")) == "Pós+"

    def test_post_fixed_ipca(self) -> None:
        assert rate_type_label(PostFixedIPCA.from_percent("5.5")) == "IPCA+"