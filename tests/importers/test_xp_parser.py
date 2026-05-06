"""Tests for the XP Investimentos statement parser.

These tests verify the layer-1 parser: XLSX file → list[XPRow], with
all fields as raw strings. Domain interpretation is the next layer's
job and tested separately.

Fixture file: tests/importers/fixtures/synthetic_xp_statement.xlsx
A handcrafted 6-row file mirroring the real XP layout, covering every
parsing concern (section transitions, blank rows, multiple rate formats,
products with JURO MENSAL hint, NTN-B vs commercial-bank issuers).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from justfixed.importers.xp import (
    RATE_SECTION_INFLACAO,
    RATE_SECTION_POS_FIXADO,
    RATE_SECTION_PREFIXADO,
    XPRow,
    read_renda_fixa_rows,
)


FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "synthetic_xp_statement.xlsx"
)


# ---------- Fixture sanity ----------


class TestFixtureExists:
    """If this test fails, no other test in the file can pass."""

    def test_fixture_file_present(self) -> None:
        assert FIXTURE_PATH.exists(), (
            f"Fixture missing: {FIXTURE_PATH}. "
            "Did you copy synthetic_xp_statement.xlsx into "
            "tests/importers/fixtures/?"
        )


# ---------- Overall structure ----------


class TestStructure:
    """The parser produces the expected number of rows in the right order."""

    def test_returns_list(self) -> None:
        result = read_renda_fixa_rows(FIXTURE_PATH)
        assert isinstance(result, list)

    def test_six_rows_total(self) -> None:
        rows = read_renda_fixa_rows(FIXTURE_PATH)
        assert len(rows) == 6

    def test_rows_are_xprow_instances(self) -> None:
        rows = read_renda_fixa_rows(FIXTURE_PATH)
        for r in rows:
            assert isinstance(r, XPRow)

    def test_two_pos_fixado_rows(self) -> None:
        rows = read_renda_fixa_rows(FIXTURE_PATH)
        pos_fixado = [r for r in rows if r.rate_section == RATE_SECTION_POS_FIXADO]
        assert len(pos_fixado) == 2

    def test_two_prefixado_rows(self) -> None:
        rows = read_renda_fixa_rows(FIXTURE_PATH)
        prefixado = [r for r in rows if r.rate_section == RATE_SECTION_PREFIXADO]
        assert len(prefixado) == 2

    def test_two_inflacao_rows(self) -> None:
        rows = read_renda_fixa_rows(FIXTURE_PATH)
        inflacao = [r for r in rows if r.rate_section == RATE_SECTION_INFLACAO]
        assert len(inflacao) == 2

    def test_file_order_preserved(self) -> None:
        """Sections appear in the file in this order: Pós-Fixado,
        Prefixado, Inflação. Rows within a section keep their order."""
        rows = read_renda_fixa_rows(FIXTURE_PATH)
        sections_in_order = [r.rate_section for r in rows]
        assert sections_in_order == [
            RATE_SECTION_POS_FIXADO,
            RATE_SECTION_POS_FIXADO,
            RATE_SECTION_PREFIXADO,
            RATE_SECTION_PREFIXADO,
            RATE_SECTION_INFLACAO,
            RATE_SECTION_INFLACAO,
        ]


# ---------- Per-row content ----------


class TestRowContents:
    """Each row's fields are extracted exactly as strings from the XLSX."""

    def test_lci_cef_pos_fixado(self) -> None:
        rows = read_renda_fixa_rows(FIXTURE_PATH)
        lci = rows[0]
        assert lci.rate_section == RATE_SECTION_POS_FIXADO
        assert lci.description == "LCI CEF - ABR/2027"
        assert lci.market_value == "R$ 50.000,00"
        assert lci.allocation_pct == "10,00%"
        assert lci.valor_aplicado == "R$ 45.000,00"
        assert lci.valor_original == "R$ 45.000,00"
        assert lci.rate_text == "95,50% CDI"
        assert lci.purchase_date_text == "02/04/2025"
        assert lci.maturity_date_text == "02/04/2027"
        assert lci.quantity_text == "1"
        assert lci.unit_price_text == "R$ 50.000,00"
        assert lci.ir_text == "R$ 0,00"
        assert lci.iof_text == "R$ 0,00"
        assert lci.net_value_text == "R$ 50.000,00"

    def test_cdb_bmg_cdi_plus_spread(self) -> None:
        """The CDI+spread rate format is captured verbatim;
        interpretation happens in the next layer."""
        rows = read_renda_fixa_rows(FIXTURE_PATH)
        cdb = rows[1]
        assert cdb.description == "CDB BMG - JUL/2027"
        assert cdb.rate_text == "CDI +2,05%"

    def test_lca_sicredi_prefixado(self) -> None:
        rows = read_renda_fixa_rows(FIXTURE_PATH)
        lca = rows[2]
        assert lca.rate_section == RATE_SECTION_PREFIXADO
        assert lca.description == "LCA SICREDI - NOV/2029"
        assert lca.rate_text == "+12,00%"

    def test_cdb_pine_juro_mensal(self) -> None:
        """The 'JURO MENSAL' marker in the description tells us
        this product has monthly coupons."""
        rows = read_renda_fixa_rows(FIXTURE_PATH)
        cdb = rows[3]
        assert cdb.description == "CDB PINE - JURO MENSAL - JAN/2031"
        assert "JURO MENSAL" in cdb.description
        assert cdb.rate_text == "+14,60%"

    def test_ntnb_inflacao(self) -> None:
        rows = read_renda_fixa_rows(FIXTURE_PATH)
        ntnb = rows[4]
        assert ntnb.rate_section == RATE_SECTION_INFLACAO
        assert ntnb.description == "NTN-B - AGO/2040"
        assert ntnb.rate_text == "IPC-A +7,31%"

    def test_lci_inter_inflacao(self) -> None:
        rows = read_renda_fixa_rows(FIXTURE_PATH)
        lci = rows[5]
        assert lci.rate_section == RATE_SECTION_INFLACAO
        assert lci.description == "LCI BANCO INTER - JUL/2027"
        assert lci.rate_text == "IPC-A +8,00%"


# ---------- Skipping non-Renda-Fixa content ----------


class TestSkippedSections:
    """The parser must skip Previdência and Fundos sections cleanly."""

    def test_no_pension_fund_rows(self) -> None:
        """The fixture has 'Some Pension Fund' as a row label inside
        Previdência Privada. None should appear in our output."""
        rows = read_renda_fixa_rows(FIXTURE_PATH)
        descriptions = [r.description for r in rows]
        for d in descriptions:
            assert "Pension" not in d
            assert "Fund" not in d  # 'Some Fund' from Fundos section

    def test_only_renda_fixa_descriptions_present(self) -> None:
        rows = read_renda_fixa_rows(FIXTURE_PATH)
        descriptions = [r.description for r in rows]
        # All real descriptions start with a known fixed-income product prefix.
        valid_prefixes = ("LCI ", "LCA ", "CDB ", "NTN-B")
        for d in descriptions:
            assert d.startswith(valid_prefixes), (
                f"Unexpected description leaked through: {d!r}"
            )


# ---------- Error handling ----------


class TestErrorHandling:
    def test_missing_file_raises(self) -> None:
        nonexistent = FIXTURE_PATH.parent / "does_not_exist.xlsx"
        with pytest.raises(FileNotFoundError):
            read_renda_fixa_rows(nonexistent)


# ---------- Frozen dataclass ----------


class TestXPRowImmutability:
    """XPRow is frozen: parsed rows cannot be mutated after construction."""

    def test_cannot_mutate_field(self) -> None:
        rows = read_renda_fixa_rows(FIXTURE_PATH)
        first = rows[0]
        with pytest.raises((AttributeError, Exception)):
            first.description = "tampered"  # type: ignore[misc]