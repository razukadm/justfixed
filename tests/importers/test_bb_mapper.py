"""Tests for the BB LCA statement mapper — Layer 2 (bb_mapper.py).

Covers:
- Smoke tests for the two reused parsers (parse_brazilian_date,
  parse_brazilian_money) as exercised by bb_mapper.
- _parse_taxa_magnitude in isolation.
- _classify_taxa: one test per band, three boundary tests (3, 9, 50),
  and error cases.
- parse_taxa end-to-end string input.
- parse_row composition: full ParsedBBRow, matured-row saldo zero,
  per-rate-type rows, and contextual error messages.

Hand-computed expected values (all decimals shown):
  "95,00"  → Decimal("95.00")  / 100 = Decimal("0.9500")   → PostFixedCDI.cdi_percentage
  "12,50"  → Decimal("12.50") / 100 = Decimal("0.1250")   → Prefixed.annual_rate
  "6,50"   → Decimal("6.50")  / 100 = Decimal("0.0650")   → PostFixedIPCA.spread
  "1,85"   → Decimal("1.85")  / 100 = Decimal("0.0185")   → PostFixedCDIPlusSpread.spread
  "2.000.000,00" → Money(Decimal("2000000.00000000"), "BRL")
  "2.320.000,00" → Money(Decimal("2320000.00000000"), "BRL")
  "0,00"         → Money(Decimal("0.00000000"), "BRL")
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from justfixed.domain.money import Money
from justfixed.domain.product import ProductType
from justfixed.domain.rates import (
    PostFixedCDI,
    PostFixedCDIPlusSpread,
    PostFixedIPCA,
    Prefixed,
)
from justfixed.importers.bb import BBRow
from justfixed.importers.bb_mapper import (
    ParsedBBRow,
    _classify_taxa,
    _parse_taxa_magnitude,
    parse_row,
    parse_taxa,
)
from justfixed.importers.xp_mapper import parse_brazilian_date, parse_brazilian_money


# ── Convenience factory ────────────────────────────────────────────────────────

def _row(**overrides) -> BBRow:
    """Return a BBRow with fixture-row-0 defaults, overriding as specified."""
    defaults: dict = {
        "numero": "201.001.010.001.001",
        "data_aplicacao": "21/11/2024",
        "valor_emissao": "2.000.000,00",
        "saldo": "2.320.000,00",
        "taxa": "95,00",
        "data_vencimento": "05/11/2027",
    }
    defaults.update(overrides)
    return BBRow(**defaults)


# ── Smoke tests for reused parsers ────────────────────────────────────────────

class TestReusedParsers:
    def test_date_parses_dd_mm_yyyy(self):
        assert parse_brazilian_date("21/11/2024") == date(2024, 11, 21)

    def test_date_parses_maturity(self):
        assert parse_brazilian_date("05/11/2027") == date(2027, 11, 5)

    def test_money_parses_large_amount(self):
        result = parse_brazilian_money("2.000.000,00")
        assert result == Money(Decimal("2000000.00"), "BRL")

    def test_money_zero_is_valid(self):
        result = parse_brazilian_money("0,00")
        assert result == Money(Decimal("0"), "BRL")

    def test_money_medium_amount(self):
        result = parse_brazilian_money("554.000,00")
        assert result == Money(Decimal("554000.00"), "BRL")


# ── _parse_taxa_magnitude ──────────────────────────────────────────────────────

class TestParseTaxaMagnitude:
    def test_five_digit_value(self):
        assert _parse_taxa_magnitude("95,00") == Decimal("95.00")

    def test_two_decimal_places(self):
        assert _parse_taxa_magnitude("12,50") == Decimal("12.50")

    def test_small_value(self):
        assert _parse_taxa_magnitude("1,85") == Decimal("1.85")

    def test_integer_like(self):
        # "94,00" — trailing zeros retained in Decimal
        assert _parse_taxa_magnitude("94,00") == Decimal("94.00")

    def test_four_char_value(self):
        assert _parse_taxa_magnitude("6,50") == Decimal("6.50")

    def test_non_numeric_raises(self):
        with pytest.raises(ValueError, match="Not a valid taxa"):
            _parse_taxa_magnitude("abc")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="Not a valid taxa"):
            _parse_taxa_magnitude("")

    def test_percent_suffix_raises(self):
        # The BB taxa has no % suffix; reject if present
        with pytest.raises(ValueError, match="Not a valid taxa"):
            _parse_taxa_magnitude("95,00%")


# ── _classify_taxa: per-band and boundary tests ────────────────────────────────

class TestClassifyTaxa:

    # --- Representative value per band ---

    def test_band_cdi_representative(self):
        # "95,00" is the canonical CDI-linked LCA rate
        rate = _classify_taxa(Decimal("95.00"))
        assert isinstance(rate, PostFixedCDI)
        assert rate.cdi_percentage == Decimal("95.00") / Decimal("100")

    def test_band_prefixed_representative(self):
        rate = _classify_taxa(Decimal("12.50"))
        assert isinstance(rate, Prefixed)
        assert rate.annual_rate == Decimal("12.50") / Decimal("100")

    def test_band_ipca_representative(self):
        rate = _classify_taxa(Decimal("6.50"))
        assert isinstance(rate, PostFixedIPCA)
        assert rate.spread == Decimal("6.50") / Decimal("100")

    def test_band_cdi_plus_spread_representative(self):
        rate = _classify_taxa(Decimal("1.85"))
        assert isinstance(rate, PostFixedCDIPlusSpread)
        assert rate.spread == Decimal("1.85") / Decimal("100")

    # --- Boundary: exactly 50 → Prefixed (band is val > 50 for CDI) ---

    def test_boundary_50_is_prefixed_not_cdi(self):
        rate = _classify_taxa(Decimal("50"))
        assert isinstance(rate, Prefixed), (
            "50 must land in Prefixed (9–50 inclusive), not PostFixedCDI (>50 strict)"
        )

    def test_just_above_50_is_cdi(self):
        rate = _classify_taxa(Decimal("50.01"))
        assert isinstance(rate, PostFixedCDI)

    # --- Boundary: exactly 9 → Prefixed (band is val >= 9) ---

    def test_boundary_9_is_prefixed(self):
        rate = _classify_taxa(Decimal("9"))
        assert isinstance(rate, Prefixed), (
            "9 must land in Prefixed (9 ≤ val ≤ 50), not PostFixedIPCA"
        )

    def test_just_below_9_is_ipca(self):
        rate = _classify_taxa(Decimal("8.99"))
        assert isinstance(rate, PostFixedIPCA)

    # --- Boundary: exactly 3 → PostFixedIPCA (band is val >= 3) ---

    def test_boundary_3_is_ipca(self):
        rate = _classify_taxa(Decimal("3"))
        assert isinstance(rate, PostFixedIPCA), (
            "3 must land in PostFixedIPCA (3 ≤ val < 9), not PostFixedCDIPlusSpread"
        )

    def test_just_below_3_is_cdi_plus_spread(self):
        rate = _classify_taxa(Decimal("2.99"))
        assert isinstance(rate, PostFixedCDIPlusSpread)

    # --- Error cases ---

    def test_zero_raises(self):
        with pytest.raises(ValueError, match="positive"):
            _classify_taxa(Decimal("0"))

    def test_negative_raises(self):
        with pytest.raises(ValueError, match="positive"):
            _classify_taxa(Decimal("-1"))

    def test_very_small_positive_is_cdi_plus_spread(self):
        # 0.01 is positive and < 3 — valid, not an error
        rate = _classify_taxa(Decimal("0.01"))
        assert isinstance(rate, PostFixedCDIPlusSpread)


# ── parse_taxa end-to-end ──────────────────────────────────────────────────────

class TestParseTaxa:
    def test_cdi_from_string(self):
        rate = parse_taxa("95,00")
        assert isinstance(rate, PostFixedCDI)
        # 95.00 / 100 = 0.9500
        assert rate.cdi_percentage == Decimal("0.9500")

    def test_prefixed_from_string(self):
        rate = parse_taxa("12,50")
        assert isinstance(rate, Prefixed)
        # 12.50 / 100 = 0.1250
        assert rate.annual_rate == Decimal("0.1250")

    def test_ipca_from_string(self):
        rate = parse_taxa("6,50")
        assert isinstance(rate, PostFixedIPCA)
        # 6.50 / 100 = 0.0650
        assert rate.spread == Decimal("0.0650")

    def test_cdi_plus_from_string(self):
        rate = parse_taxa("1,85")
        assert isinstance(rate, PostFixedCDIPlusSpread)
        # 1.85 / 100 = 0.0185
        assert rate.spread == Decimal("0.0185")

    def test_non_numeric_string_raises(self):
        with pytest.raises(ValueError):
            parse_taxa("JURO MENSAL")

    def test_zero_string_raises(self):
        with pytest.raises(ValueError, match="positive"):
            parse_taxa("0,00")


# ── parse_row composition ─────────────────────────────────────────────────────

class TestParseRow:

    def test_full_active_row_all_fields(self):
        """Fixture row 0 — all six fields plus product type."""
        parsed = parse_row(_row())

        assert isinstance(parsed, ParsedBBRow)
        assert parsed.numero == "201.001.010.001.001"
        assert parsed.data_aplicacao == date(2024, 11, 21)
        assert parsed.data_vencimento == date(2027, 11, 5)
        # 2.000.000,00 → Decimal("2000000.00")
        assert parsed.valor_emissao == Money(Decimal("2000000.00"), "BRL")
        # 2.320.000,00 → Decimal("2320000.00")
        assert parsed.saldo == Money(Decimal("2320000.00"), "BRL")
        assert isinstance(parsed.rate, PostFixedCDI)
        # 95.00 / 100 = 0.9500
        assert parsed.rate.cdi_percentage == Decimal("0.9500")
        assert parsed.product == ProductType.LCA

    def test_matured_row_saldo_is_money_zero(self):
        """saldo '0,00' must parse to Money zero without error."""
        parsed = parse_row(_row(saldo="0,00", taxa="94,00"))
        assert parsed.saldo == Money(Decimal("0"), "BRL")
        assert isinstance(parsed.rate, PostFixedCDI)

    def test_prefixed_rate_row(self):
        """Fixture row 1 taxa values."""
        parsed = parse_row(_row(
            numero="201.002.150.002.002",
            data_aplicacao="10/12/2024",
            valor_emissao="500.000,00",
            saldo="554.000,00",
            taxa="12,50",
            data_vencimento="25/11/2027",
        ))
        assert isinstance(parsed.rate, Prefixed)
        # 12.50 / 100 = 0.1250
        assert parsed.rate.annual_rate == Decimal("0.1250")
        assert parsed.saldo == Money(Decimal("554000.00"), "BRL")
        assert parsed.data_aplicacao == date(2024, 12, 10)
        assert parsed.data_vencimento == date(2027, 11, 25)

    def test_ipca_rate_row(self):
        """Fixture row 2 taxa values."""
        parsed = parse_row(_row(
            numero="201.003.050.003.003",
            taxa="6,50",
            saldo="421.000,00",
        ))
        assert isinstance(parsed.rate, PostFixedIPCA)
        # 6.50 / 100 = 0.0650
        assert parsed.rate.spread == Decimal("0.0650")
        assert parsed.saldo == Money(Decimal("421000.00"), "BRL")

    def test_cdi_plus_rate_row(self):
        """Fixture row 3 taxa values."""
        parsed = parse_row(_row(
            numero="201.004.100.004.004",
            taxa="1,85",
            saldo="103.800,00",
        ))
        assert isinstance(parsed.rate, PostFixedCDIPlusSpread)
        # 1.85 / 100 = 0.0185
        assert parsed.rate.spread == Decimal("0.0185")
        assert parsed.saldo == Money(Decimal("103800.00"), "BRL")

    def test_product_is_always_lca(self):
        assert parse_row(_row()).product == ProductType.LCA

    def test_numero_preserved_verbatim(self):
        parsed = parse_row(_row(numero="202.001.050.005.005"))
        assert parsed.numero == "202.001.050.005.005"

    def test_bad_date_raises_contextual_error(self):
        """ValueError must mention the row's numero."""
        with pytest.raises(ValueError, match="201.001.010.001.001"):
            parse_row(_row(data_aplicacao="not-a-date"))

    def test_bad_taxa_raises_contextual_error(self):
        with pytest.raises(ValueError, match="201.001.010.001.001"):
            parse_row(_row(taxa="abc"))

    def test_bad_money_raises_contextual_error(self):
        with pytest.raises(ValueError, match="201.001.010.001.001"):
            parse_row(_row(valor_emissao="not-money"))

    def test_zero_taxa_raises_contextual_error(self):
        """taxa '0,00' must be rejected — not silently mapped."""
        with pytest.raises(ValueError, match="201.001.010.001.001"):
            parse_row(_row(taxa="0,00"))
