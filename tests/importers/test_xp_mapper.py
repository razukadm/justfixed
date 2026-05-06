"""Tests for the XPRow → typed-data mapper.

These are pure unit tests — no XLSX fixture, no database. Each parser
is tested in isolation with carefully chosen string inputs that
exercise the full range of formats the real XP file produces, plus
malformed inputs that strict parsing must reject.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from justfixed.domain.money import Money
from justfixed.domain.product import CouponFrequency, ProductType
from justfixed.domain.rates import (
    PostFixedCDI,
    PostFixedCDIPlusSpread,
    PostFixedIPCA,
    Prefixed,
)
from justfixed.importers.xp import XPRow, read_renda_fixa_rows
from justfixed.importers.xp_mapper import (
    ParsedXPRow,
    parse_brazilian_date,
    parse_brazilian_money,
    parse_issuer_name,
    parse_product_and_coupon,
    parse_rate,
    parse_row,
)


# ---------- Brazilian money ----------


class TestParseMoney:
    def test_with_currency_prefix(self) -> None:
        assert parse_brazilian_money("R$ 45.000,00") == Money.from_reais("45000")

    def test_without_currency_prefix(self) -> None:
        assert parse_brazilian_money("45.000,00") == Money.from_reais("45000")

    def test_with_decimals(self) -> None:
        assert parse_brazilian_money("R$ 1.234,56") == Money.from_reais("1234.56")

    def test_small_amount(self) -> None:
        assert parse_brazilian_money("0,01") == Money.from_reais("0.01")

    def test_no_decimal_part(self) -> None:
        assert parse_brazilian_money("R$ 100") == Money.from_reais("100")

    def test_large_amount_with_multiple_thousands_separators(self) -> None:
        # R$ 4.384.738,96 — your actual portfolio total
        assert parse_brazilian_money("R$ 4.384.738,96") == Money.from_reais(
            "4384738.96"
        )

    def test_currency_is_brl(self) -> None:
        assert parse_brazilian_money("R$ 100,00").currency == "BRL"

    def test_us_format_rejected(self) -> None:
        # Strict parser must NOT accept "1,234.56" — that's US format.
        with pytest.raises(ValueError):
            parse_brazilian_money("1,234.56")

    def test_empty_string_rejected(self) -> None:
        with pytest.raises(ValueError):
            parse_brazilian_money("")

    def test_garbage_rejected(self) -> None:
        with pytest.raises(ValueError):
            parse_brazilian_money("not a number")

    def test_only_currency_symbol_rejected(self) -> None:
        with pytest.raises(ValueError):
            parse_brazilian_money("R$")


# ---------- Brazilian date ----------


class TestParseDate:
    def test_simple_date(self) -> None:
        assert parse_brazilian_date("02/04/2025") == date(2025, 4, 2)

    def test_two_digit_day_and_month(self) -> None:
        assert parse_brazilian_date("15/12/2030") == date(2030, 12, 15)

    def test_first_of_year(self) -> None:
        assert parse_brazilian_date("01/01/2026") == date(2026, 1, 1)

    def test_last_of_year(self) -> None:
        assert parse_brazilian_date("31/12/2026") == date(2026, 12, 31)

    def test_leap_day(self) -> None:
        assert parse_brazilian_date("29/02/2024") == date(2024, 2, 29)

    def test_iso_format_rejected(self) -> None:
        # We only accept Brazilian DD/MM/YYYY.
        with pytest.raises(ValueError):
            parse_brazilian_date("2025-04-02")

    # Note: we cannot defend against US-formatted dates that happen to be
    # also-valid Brazilian dates ("04/02/2025" is April 2 in BR, Feb 4 in
    # US — both valid). Our parser trusts the source. The format check
    # only catches structurally wrong inputs (month >12, day >31, etc.),
    # which the test_invalid_month_rejected and test_invalid_day_rejected
    # tests cover.

    def test_invalid_day_rejected(self) -> None:
        with pytest.raises(ValueError):
            parse_brazilian_date("32/01/2025")

    def test_invalid_month_rejected(self) -> None:
        with pytest.raises(ValueError):
            parse_brazilian_date("01/13/2025")

    def test_garbage_rejected(self) -> None:
        with pytest.raises(ValueError):
            parse_brazilian_date("not a date")


# ---------- Rate parsing ----------


class TestParseRate:
    def test_pos_fixado_cdi_percent(self) -> None:
        rate = parse_rate("95,50% CDI")
        assert isinstance(rate, PostFixedCDI)
        assert rate.cdi_percentage == Decimal("0.955")

    def test_cdi_plus_spread(self) -> None:
        rate = parse_rate("CDI +2,05%")
        assert isinstance(rate, PostFixedCDIPlusSpread)
        assert rate.spread == Decimal("0.0205")

    def test_ipca_plus_spread(self) -> None:
        rate = parse_rate("IPC-A +7,31%")
        assert isinstance(rate, PostFixedIPCA)
        assert rate.spread == Decimal("0.0731")

    def test_prefixed_with_plus(self) -> None:
        rate = parse_rate("+12,00%")
        assert isinstance(rate, Prefixed)
        assert rate.annual_rate == Decimal("0.12")

    def test_prefixed_without_plus(self) -> None:
        # XP usually writes "+12,00%" but accept "12,00%" too.
        rate = parse_rate("12,00%")
        assert isinstance(rate, Prefixed)
        assert rate.annual_rate == Decimal("0.12")

    def test_cdi_with_lowercase(self) -> None:
        # Defensive: case-insensitive recognition of "CDI" and "IPC-A".
        rate = parse_rate("100,00% cdi")
        assert isinstance(rate, PostFixedCDI)

    def test_high_cdi_multiplier(self) -> None:
        # Real position from your portfolio: 135% CDI.
        rate = parse_rate("135,00% CDI")
        assert isinstance(rate, PostFixedCDI)
        assert rate.cdi_percentage == Decimal("1.35")

    def test_garbage_rejected(self) -> None:
        with pytest.raises(ValueError, match="Unrecognized rate format"):
            parse_rate("definitely not a rate")

    def test_empty_rejected(self) -> None:
        with pytest.raises(ValueError):
            parse_rate("")

    def test_cdi_without_percent_rejected(self) -> None:
        # "CDI" alone (no spread, no multiplier) is ambiguous — reject.
        with pytest.raises(ValueError):
            parse_rate("CDI")


# ---------- Product and coupon ----------


class TestParseProductAndCoupon:
    def test_lci_bullet(self) -> None:
        product, coupon = parse_product_and_coupon("LCI CEF - ABR/2027")
        assert product == ProductType.LCI
        assert coupon == CouponFrequency.NONE

    def test_lca_bullet(self) -> None:
        product, coupon = parse_product_and_coupon(
            "LCA BANCO COOPERATIVO SICOOB - MAI/2030"
        )
        assert product == ProductType.LCA
        assert coupon == CouponFrequency.NONE

    def test_cdb_bullet(self) -> None:
        product, coupon = parse_product_and_coupon("CDB BMG - JUL/2027")
        assert product == ProductType.CDB
        assert coupon == CouponFrequency.NONE

    def test_lca_with_juro_mensal(self) -> None:
        product, coupon = parse_product_and_coupon(
            "LCA BANCO BV S/A - JURO MENSAL - MAR/2029"
        )
        assert product == ProductType.LCA
        assert coupon == CouponFrequency.MONTHLY

    def test_cdb_with_juro_mensal(self) -> None:
        product, coupon = parse_product_and_coupon(
            "CDB PINE - JURO MENSAL - JAN/2031"
        )
        assert product == ProductType.CDB
        assert coupon == CouponFrequency.MONTHLY

    def test_juro_semestral(self) -> None:
        # Synthetic case — your portfolio doesn't have any, but we should
        # handle them if XP starts producing them.
        product, coupon = parse_product_and_coupon(
            "CDB SOME BANK - JURO SEMESTRAL - JUN/2030"
        )
        assert product == ProductType.CDB
        assert coupon == CouponFrequency.SEMI_ANNUAL

    def test_ntnb_is_tesouro_ipca(self) -> None:
        product, coupon = parse_product_and_coupon("NTN-B - AGO/2040")
        assert product == ProductType.TESOURO_IPCA
        assert coupon == CouponFrequency.NONE

    def test_unknown_product_rejected(self) -> None:
        with pytest.raises(ValueError, match="Cannot identify product"):
            parse_product_and_coupon("XYZ MYSTERY - JAN/2030")

    def test_empty_description_rejected(self) -> None:
        with pytest.raises(ValueError):
            parse_product_and_coupon("")


# ---------- Issuer name extraction ----------


class TestParseIssuerName:
    def test_simple_lci(self) -> None:
        assert parse_issuer_name("LCI CEF - ABR/2027") == "CEF"

    def test_multi_word_issuer(self) -> None:
        assert (
            parse_issuer_name("LCA BANCO COOPERATIVO SICOOB - MAI/2030")
            == "BANCO COOPERATIVO SICOOB"
        )

    def test_issuer_with_juro_mensal_in_middle(self) -> None:
        # The JURO MENSAL marker is between the issuer name and the
        # maturity hint. Stripping it should leave clean issuer text.
        assert (
            parse_issuer_name("LCA BANCO BV S/A - JURO MENSAL - MAR/2029")
            == "BANCO BV S/A"
        )

    def test_issuer_with_juro_semestral_in_middle(self) -> None:
        assert (
            parse_issuer_name("CDB SOME BANK - JURO SEMESTRAL - DEZ/2030")
            == "SOME BANK"
        )

    def test_cdb_issuer(self) -> None:
        assert parse_issuer_name("CDB BMG - JUL/2027") == "BMG"

    def test_ntnb_returns_tesouro(self) -> None:
        assert parse_issuer_name("NTN-B - AGO/2040") == "Tesouro Nacional"

    def test_issuer_with_special_chars(self) -> None:
        assert (
            parse_issuer_name("CDB BANCO C6 CONSIGNADO S.A. - AGO/2026")
            == "BANCO C6 CONSIGNADO S.A."
        )

    def test_unknown_prefix_rejected(self) -> None:
        with pytest.raises(ValueError, match="Cannot extract issuer"):
            parse_issuer_name("XYZ SOMETHING - JAN/2030")


# ---------- Composition: parse_row over a constructed XPRow ----------


def _xp_row(
    *,
    description: str,
    rate_text: str,
    valor_original: str = "R$ 45.000,00",
    purchase_date_text: str = "02/04/2025",
    maturity_date_text: str = "02/04/2027",
    rate_section: str = "Pós-Fixado",
) -> XPRow:
    """Build an XPRow with sensible defaults for fields parse_row doesn't use.

    parse_row only touches description, rate_text, valor_original, and the
    two date fields. The other XPRow fields can be empty strings — the
    parser doesn't read them at this layer.
    """
    return XPRow(
        rate_section=rate_section,
        description=description,
        market_value="",
        allocation_pct="",
        valor_aplicado="",
        valor_original=valor_original,
        rate_text=rate_text,
        purchase_date_text=purchase_date_text,
        maturity_date_text=maturity_date_text,
        quantity_text="",
        unit_price_text="",
        ir_text="",
        iof_text="",
        net_value_text="",
    )


class TestParseRow:
    def test_returns_parsed_xp_row(self) -> None:
        row = _xp_row(description="LCI CEF - ABR/2027", rate_text="95,50% CDI")
        parsed = parse_row(row)
        assert isinstance(parsed, ParsedXPRow)

    def test_lci_cef_full_parse(self) -> None:
        """End-to-end: an LCI from the synthetic fixture parses to the
        right typed values."""
        row = _xp_row(
            description="LCI CEF - ABR/2027",
            rate_text="95,50% CDI",
            valor_original="R$ 45.000,00",
            purchase_date_text="02/04/2025",
            maturity_date_text="02/04/2027",
        )
        parsed = parse_row(row)
        assert parsed.product == ProductType.LCI
        assert parsed.issuer_name == "CEF"
        assert parsed.principal == Money.from_reais("45000")
        assert isinstance(parsed.rate, PostFixedCDI)
        assert parsed.rate.cdi_percentage == Decimal("0.955")
        assert parsed.purchase_date == date(2025, 4, 2)
        assert parsed.maturity_date == date(2027, 4, 2)
        assert parsed.coupon_frequency == CouponFrequency.NONE

    def test_cdi_plus_spread_full_parse(self) -> None:
        row = _xp_row(
            description="CDB BMG - JUL/2027",
            rate_text="CDI +2,05%",
            valor_original="R$ 22.000,00",
            purchase_date_text="30/10/2025",
            maturity_date_text="16/07/2027",
        )
        parsed = parse_row(row)
        assert parsed.product == ProductType.CDB
        assert parsed.issuer_name == "BMG"
        assert isinstance(parsed.rate, PostFixedCDIPlusSpread)
        assert parsed.rate.spread == Decimal("0.0205")

    def test_juro_mensal_detected_through_composition(self) -> None:
        row = _xp_row(
            description="LCA BANCO BV S/A - JURO MENSAL - MAR/2029",
            rate_text="+12,00%",
            valor_original="R$ 64.085,97",
            purchase_date_text="05/05/2026",
            maturity_date_text="26/03/2029",
        )
        parsed = parse_row(row)
        assert parsed.product == ProductType.LCA
        assert parsed.issuer_name == "BANCO BV S/A"
        assert parsed.coupon_frequency == CouponFrequency.MONTHLY
        assert isinstance(parsed.rate, Prefixed)
        assert parsed.rate.annual_rate == Decimal("0.12")

    def test_ntnb_full_parse(self) -> None:
        row = _xp_row(
            description="NTN-B - AGO/2040",
            rate_text="IPC-A +7,31%",
            valor_original="R$ 98.604,89",
            purchase_date_text="10/04/2026",
            maturity_date_text="15/08/2040",
        )
        parsed = parse_row(row)
        assert parsed.product == ProductType.TESOURO_IPCA
        assert parsed.issuer_name == "Tesouro Nacional"
        assert isinstance(parsed.rate, PostFixedIPCA)
        assert parsed.rate.spread == Decimal("0.0731")

    def test_description_preserved(self) -> None:
        """The original description is kept on ParsedXPRow for debugging."""
        original = "LCA BANCO COOPERATIVO SICOOB - MAI/2030"
        row = _xp_row(description=original, rate_text="92,50% CDI")
        parsed = parse_row(row)
        assert parsed.description == original


class TestParseRowErrors:
    """Strict parsing: malformed rows raise contextual ValueError."""

    def test_unrecognized_product_includes_description_in_error(self) -> None:
        row = _xp_row(description="XYZ MYSTERY - JAN/2030", rate_text="+12,00%")
        with pytest.raises(ValueError, match="XYZ MYSTERY"):
            parse_row(row)

    def test_unrecognized_rate_includes_description_in_error(self) -> None:
        row = _xp_row(
            description="LCI CEF - ABR/2027", rate_text="this is not a rate"
        )
        with pytest.raises(ValueError, match="LCI CEF"):
            parse_row(row)

    def test_malformed_date_includes_description_in_error(self) -> None:
        row = _xp_row(
            description="LCI CEF - ABR/2027",
            rate_text="95,50% CDI",
            purchase_date_text="not a date",
        )
        with pytest.raises(ValueError, match="LCI CEF"):
            parse_row(row)

    def test_malformed_money_includes_description_in_error(self) -> None:
        row = _xp_row(
            description="LCI CEF - ABR/2027",
            rate_text="95,50% CDI",
            valor_original="not a number",
        )
        with pytest.raises(ValueError, match="LCI CEF"):
            parse_row(row)


# ---------- Real fixture round-trip ----------


_FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "synthetic_xp_statement.xlsx"
)


class TestParseRowOnFixture:
    """Run parse_row over every XPRow from the synthetic fixture.
    All 6 must parse without errors."""

    def test_all_six_rows_parse(self) -> None:
        rows = read_renda_fixa_rows(_FIXTURE_PATH)
        parsed_list = [parse_row(r) for r in rows]
        assert len(parsed_list) == 6

    def test_all_four_rate_types_present_in_fixture(self) -> None:
        rows = read_renda_fixa_rows(_FIXTURE_PATH)
        parsed_list = [parse_row(r) for r in rows]
        rate_types = {type(p.rate).__name__ for p in parsed_list}
        assert rate_types == {
            "PostFixedCDI",
            "PostFixedCDIPlusSpread",
            "Prefixed",
            "PostFixedIPCA",
        }