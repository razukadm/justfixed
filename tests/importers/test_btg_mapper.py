"""Tests for the BTGRow -> typed-data mapper.

These are pure unit tests — no XLSX fixture, no database. Each parser
is tested in isolation with carefully chosen string inputs that
exercise the formats BTG produces, plus malformed inputs that strict
parsing must reject.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from justfixed.domain.money import Money
from justfixed.domain.product import CouponFrequency, ProductType
from justfixed.domain.rates import PostFixedCDI
from justfixed.importers.btg import BTGRow
from justfixed.importers.btg_mapper import (
    ParsedBTGRow,
    parse_btg_datetime_string,
    parse_btg_decimal,
    parse_btg_product,
    parse_btg_rate,
    parse_row,
)


# ---------- Helpers ----------


def _btg_row(**overrides) -> BTGRow:
    """Build a BTGRow matching the real file's one position, with field overrides.

    parse_row only touches the fields that map to ParsedBTGRow. The
    remaining fields (liquidez, preco_*, saldo_*, etc.) are carried
    through as-is and are not read by the mapper.
    """
    defaults = dict(
        product="LCI",
        issuer_name="ASSOCIACAO DE POUPANCA E EMPRESTIMO POUPEX",
        ativo="LCI-25I04325998",
        emissao_date_text="2025-09-29 00:00:00",
        vencimento_date_text="2027-09-16 00:00:00",
        aquisicao_date_text="2025-09-29 00:00:00",
        liquidez="Sim",
        dias_carencia="185",
        data_inicial_liquidez="2026-04-02 00:00:00",
        taxa_compra="89,00% do CDI",
        quantidade="43",
        preco_compra_text="1000",
        valor_compra_text="43000",
        preco_text="1080.15641",
        saldo_bruto_text="46446.72",
        ir_text="-",
        iof_text="-",
        saldo_liquido_text="46446.72",
    )
    defaults.update(overrides)
    return BTGRow(**defaults)


# ---------- Date parsing ----------


class TestParseBTGDatetimeString:
    def test_valid_date(self) -> None:
        assert parse_btg_datetime_string("2025-09-29 00:00:00") == date(2025, 9, 29)

    def test_another_valid_date(self) -> None:
        assert parse_btg_datetime_string("2027-09-16 00:00:00") == date(2027, 9, 16)

    def test_brazilian_format_rejected(self) -> None:
        with pytest.raises(ValueError, match="Not a valid BTG datetime"):
            parse_btg_datetime_string("29/09/2025")

    def test_iso_date_without_time_rejected(self) -> None:
        with pytest.raises(ValueError, match="Not a valid BTG datetime"):
            parse_btg_datetime_string("2025-09-29")

    def test_garbage_rejected(self) -> None:
        with pytest.raises(ValueError):
            parse_btg_datetime_string("not a date")

    def test_invalid_month_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid date components"):
            parse_btg_datetime_string("2025-13-01 00:00:00")

    def test_invalid_day_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid date components"):
            parse_btg_datetime_string("2025-01-32 00:00:00")


# ---------- Decimal parsing ----------


class TestParseBTGDecimal:
    def test_integer_string(self) -> None:
        assert parse_btg_decimal("43000") == Decimal("43000")

    def test_float_with_many_decimals(self) -> None:
        assert parse_btg_decimal("1080.15641") == Decimal("1080.15641")

    def test_zero(self) -> None:
        assert parse_btg_decimal("0") == Decimal("0")

    def test_brazilian_format_rejected(self) -> None:
        # "R$ 1.000,00" is not a Python numeric repr; must be rejected.
        with pytest.raises(ValueError, match="Not a valid numeric string"):
            parse_btg_decimal("R$ 1.000,00")

    def test_comma_decimal_rejected(self) -> None:
        # "1080,15" uses a comma decimal separator — not Python repr.
        with pytest.raises(ValueError):
            parse_btg_decimal("1080,15")

    def test_garbage_rejected(self) -> None:
        with pytest.raises(ValueError):
            parse_btg_decimal("not a number")

    def test_empty_rejected(self) -> None:
        with pytest.raises(ValueError):
            parse_btg_decimal("")

    def test_nan_rejected(self) -> None:
        with pytest.raises(ValueError, match="not finite"):
            parse_btg_decimal("NaN")

    def test_infinity_rejected(self) -> None:
        with pytest.raises(ValueError, match="not finite"):
            parse_btg_decimal("Infinity")


# ---------- Rate parsing ----------


class TestParseBTGRate:
    def test_cdi_with_do(self) -> None:
        rate = parse_btg_rate("89,00% do CDI")
        assert isinstance(rate, PostFixedCDI)
        assert rate.cdi_percentage == Decimal("0.89")

    def test_cdi_without_do(self) -> None:
        # "do" is optional; "95,00% CDI" must also be recognized.
        rate = parse_btg_rate("95,00% CDI")
        assert isinstance(rate, PostFixedCDI)
        assert rate.cdi_percentage == Decimal("0.95")

    def test_cdi_above_100_percent(self) -> None:
        rate = parse_btg_rate("115,00% do CDI")
        assert isinstance(rate, PostFixedCDI)
        assert rate.cdi_percentage == Decimal("1.15")

    def test_unrecognized_format_raises_with_raw_text(self) -> None:
        raw = "IPCA + 5,00%"
        with pytest.raises(ValueError, match="IPCA"):
            parse_btg_rate(raw)

    def test_garbage_rejected(self) -> None:
        with pytest.raises(ValueError, match="Unrecognized BTG rate format"):
            parse_btg_rate("definitely not a rate")


# ---------- Product mapping ----------


class TestParseBTGProduct:
    def test_lci(self) -> None:
        assert parse_btg_product("LCI") == ProductType.LCI

    def test_lca(self) -> None:
        assert parse_btg_product("LCA") == ProductType.LCA

    def test_cdb(self) -> None:
        assert parse_btg_product("CDB") == ProductType.CDB

    def test_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="Unrecognized BTG product type"):
            parse_btg_product("XYZ")

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_btg_product("")


# ---------- Composition: parse_row ----------


class TestParseRow:
    def test_returns_parsed_btg_row(self) -> None:
        parsed = parse_row(_btg_row())
        assert isinstance(parsed, ParsedBTGRow)

    def test_lci_poupex_all_fields(self) -> None:
        """End-to-end: the real file's one position parses to the right typed values."""
        parsed = parse_row(_btg_row())
        assert parsed.product == ProductType.LCI
        assert parsed.issuer_name == "ASSOCIACAO DE POUPANCA E EMPRESTIMO POUPEX"
        assert parsed.principal == Money(amount=Decimal("43000"), currency="BRL")
        assert isinstance(parsed.rate, PostFixedCDI)
        assert parsed.rate.cdi_percentage == Decimal("0.89")
        assert parsed.purchase_date == date(2025, 9, 29)
        assert parsed.issue_date == date(2025, 9, 29)
        assert parsed.maturity_date == date(2027, 9, 16)
        assert parsed.coupon_frequency == CouponFrequency.NONE
        assert parsed.description == (
            "LCI ASSOCIACAO DE POUPANCA E EMPRESTIMO POUPEX - SET/2027"
        )

    def test_description_uses_correct_month(self) -> None:
        # Verify the Portuguese month table with a different month (March).
        row = _btg_row(
            product="LCA",
            issuer_name="BANCO DO BRASIL",
            vencimento_date_text="2026-03-15 00:00:00",
            taxa_compra="115,00% do CDI",
        )
        parsed = parse_row(row)
        assert parsed.description == "LCA BANCO DO BRASIL - MAR/2026"

    def test_full_issuer_name_preserved(self) -> None:
        # Issuer name is passed through as-is (no truncation or normalization).
        parsed = parse_row(_btg_row())
        assert parsed.issuer_name == "ASSOCIACAO DE POUPANCA E EMPRESTIMO POUPEX"

    def test_purchase_date_from_aquisicao_not_emissao(self) -> None:
        # purchase_date must be sourced from aquisicao_date_text; emissao is issue_date.
        row = _btg_row(
            aquisicao_date_text="2025-10-01 00:00:00",
            emissao_date_text="2025-09-29 00:00:00",
        )
        parsed = parse_row(row)
        assert parsed.purchase_date == date(2025, 10, 1)
        assert parsed.issue_date == date(2025, 9, 29)


# ---------- Error wrapping ----------


class TestParseRowErrors:
    def test_malformed_date_names_row_in_error(self) -> None:
        row = _btg_row(aquisicao_date_text="not a date")
        with pytest.raises(ValueError, match="ASSOCIACAO"):
            parse_row(row)

    def test_malformed_decimal_names_row_in_error(self) -> None:
        row = _btg_row(valor_compra_text="R$ 43.000,00")
        with pytest.raises(ValueError, match="LCI-25I04325998"):
            parse_row(row)

    def test_unrecognized_rate_names_row_in_error(self) -> None:
        row = _btg_row(taxa_compra="FIXO 12%")
        with pytest.raises(ValueError, match="ASSOCIACAO"):
            parse_row(row)

    def test_unknown_product_names_row_in_error(self) -> None:
        row = _btg_row(product="CRA")
        with pytest.raises(ValueError, match="LCI-25I04325998"):
            parse_row(row)
