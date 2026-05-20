"""Tests for the BTG Pactual statement parser.

These tests verify the layer-1 parser: XLSX file -> list[BTGRow], with all
fields as raw strings. Domain interpretation is the next layer's job and
tested separately.

Fixture file: tests/importers/fixtures/synthetic_btg_statement.xlsx
A handcrafted two-sub-section file covering:
  - Multi-sheet workbook with only Renda Fixa parsed
  - Posicoes summary table correctly ignored
  - Two Detalhamento sub-sections (LCI POUPEX, LCA Banco do Brasil)
  - Blank row between sub-sections
  - Posicao Consolidada Por Emissor trailer as terminator
"""

from __future__ import annotations

from pathlib import Path

import openpyxl
import pytest

from justfixed.importers.btg import (
    BTGRow,
    RENDA_FIXA_SHEET_NAME,
    read_renda_fixa_rows,
)


FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "synthetic_btg_statement.xlsx"
)


def _build_test_xlsx(path: Path, rows: list[list]) -> None:
    """Write a minimal xlsx with a 'Renda Fixa' sheet containing the given rows."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = RENDA_FIXA_SHEET_NAME
    for row in rows:
        ws.append(row)
    wb.save(path)


# ---------- Fixture sanity ----------


class TestFixtureExists:
    """If this test fails, no other test in the file can pass."""

    def test_fixture_file_present(self) -> None:
        assert FIXTURE_PATH.exists(), (
            f"Fixture missing: {FIXTURE_PATH}. "
            "Run tests/importers/fixtures/create_synthetic_btg_statement.py "
            "to regenerate it."
        )


# ---------- Overall structure ----------


class TestStructure:
    def test_returns_list(self) -> None:
        result = read_renda_fixa_rows(FIXTURE_PATH)
        assert isinstance(result, list)

    def test_two_rows_total(self) -> None:
        rows = read_renda_fixa_rows(FIXTURE_PATH)
        assert len(rows) == 2

    def test_rows_are_btgrow_instances(self) -> None:
        rows = read_renda_fixa_rows(FIXTURE_PATH)
        for r in rows:
            assert isinstance(r, BTGRow)

    def test_first_row_is_lci_subsection(self) -> None:
        rows = read_renda_fixa_rows(FIXTURE_PATH)
        assert rows[0].product == "LCI"

    def test_second_row_is_lca_subsection(self) -> None:
        rows = read_renda_fixa_rows(FIXTURE_PATH)
        assert rows[1].product == "LCA"

    def test_file_order_preserved(self) -> None:
        rows = read_renda_fixa_rows(FIXTURE_PATH)
        products = [r.product for r in rows]
        assert products == ["LCI", "LCA"]


# ---------- Per-row content ----------


class TestRowContents:
    def test_lci_poupex_all_fields(self) -> None:
        rows = read_renda_fixa_rows(FIXTURE_PATH)
        r = rows[0]
        assert r.product == "LCI"
        assert r.issuer_name == "ASSOCIACAO DE POUPANCA E EMPRESTIMO POUPEX"
        assert r.ativo == "LCI-25I04325998"
        assert r.emissao_date_text == "2025-09-29 00:00:00"
        assert r.vencimento_date_text == "2027-09-16 00:00:00"
        assert r.aquisicao_date_text == "2025-09-29 00:00:00"
        assert r.liquidez == "Sim"
        assert r.dias_carencia == "185"
        assert r.data_inicial_liquidez == "2026-04-02 00:00:00"
        assert r.taxa_compra == "89,00% do CDI"
        assert r.quantidade == "43"
        assert r.preco_compra_text == "1000"
        assert r.valor_compra_text == "43000"
        assert r.preco_text == "1080"
        assert r.saldo_bruto_text == "46440"
        assert r.ir_text == "-"
        assert r.iof_text == "-"
        assert r.saldo_liquido_text == "46440"

    def test_lca_banco_do_brasil_all_fields(self) -> None:
        rows = read_renda_fixa_rows(FIXTURE_PATH)
        r = rows[1]
        assert r.product == "LCA"
        assert r.issuer_name == "BANCO DO BRASIL"
        assert r.ativo == "LCA-24A01234567"
        assert r.emissao_date_text == "2024-01-10 00:00:00"
        assert r.vencimento_date_text == "2026-03-15 00:00:00"
        assert r.aquisicao_date_text == "2024-03-15 00:00:00"
        assert r.liquidez == "Não"   # Não
        assert r.dias_carencia == "0"
        assert r.data_inicial_liquidez == ""
        assert r.taxa_compra == "115,00% do CDI"
        assert r.quantidade == "100"
        assert r.preco_compra_text == "1000"
        assert r.valor_compra_text == "100000"
        assert r.preco_text == "1050"
        assert r.saldo_bruto_text == "105000"
        assert r.ir_text == "-"
        assert r.iof_text == "-"
        assert r.saldo_liquido_text == "105000"


# ---------- Summary section is not parsed ----------


class TestSummaryIgnored:
    def test_posicoes_summary_not_double_counted(self) -> None:
        """The Posicoes summary table contains one row for the same LCI
        investment that also appears in Detalhamento. If the summary were
        parsed, we would see 3 rows (summary LCI + Detalhamento LCI + LCA).
        Exactly 2 rows confirms the summary is correctly skipped."""
        rows = read_renda_fixa_rows(FIXTURE_PATH)
        assert len(rows) == 2

    def test_no_duplicate_lci_from_summary(self) -> None:
        rows = read_renda_fixa_rows(FIXTURE_PATH)
        lci_rows = [r for r in rows if r.product == "LCI"]
        assert len(lci_rows) == 1


# ---------- Edge cases ----------


class TestEdgeCases:
    def test_missing_renda_fixa_sheet_raises_value_error(
        self, tmp_path: Path
    ) -> None:
        xlsx = tmp_path / "no_renda_fixa.xlsx"
        wb = openpyxl.Workbook()
        wb.active.title = "Other Sheet"
        wb.save(xlsx)
        with pytest.raises(ValueError, match="Renda Fixa"):
            read_renda_fixa_rows(xlsx)

    def test_empty_renda_fixa_sheet_returns_empty_list(
        self, tmp_path: Path
    ) -> None:
        xlsx = tmp_path / "empty.xlsx"
        _build_test_xlsx(xlsx, [])
        assert read_renda_fixa_rows(xlsx) == []

    def test_missing_file_raises_file_not_found(self) -> None:
        nonexistent = FIXTURE_PATH.parent / "does_not_exist.xlsx"
        with pytest.raises(FileNotFoundError):
            read_renda_fixa_rows(nonexistent)

    def test_empty_subsection_no_data_rows_before_total(
        self, tmp_path: Path
    ) -> None:
        """A sub-section header followed immediately by Total (no data rows)
        must yield nothing for that sub-section and not crash."""
        xlsx = tmp_path / "empty_subsection.xlsx"
        _build_test_xlsx(xlsx, [
            [None, "Posições Detalhadas"],
            [None, "Detalhamento > LCI | TEST BANK"],
            [None, "Ativo", "Emissão", "Vencimento"],  # column headers
            [None, "Total"],                             # immediate Total
        ])
        assert read_renda_fixa_rows(xlsx) == []

    def test_consolidada_anchor_stops_parsing(self, tmp_path: Path) -> None:
        """Any rows after the Posicao Consolidada Por Emissor header are
        not parsed, even if they look like Detalhamento data."""
        xlsx = tmp_path / "with_consolidada.xlsx"
        _build_test_xlsx(xlsx, [
            [None, "Posições Detalhadas"],
            [None, "Detalhamento > LCI | BANK A"],
            [None, "Ativo"],
            [None, "LCI-001", "2025-01-01", "2027-01-01", "2025-01-01",
             "Sim", "0", None, "90,00% do CDI", 10, 1000, 10000, 1050,
             10500, "-", "-", 10500],
            [None, "Total"],
            [None, "Posição Consolidada Por Emissor"],
            # These rows must be ignored:
            [None, "Detalhamento > CDB | BANK B"],
            [None, "Ativo"],
            [None, "CDB-002", "2025-01-01", "2027-01-01", "2025-01-01",
             "Não", "0", None, "95,00% do CDI", 5, 1000, 5000, 1060,
             5300, "-", "-", 5300],
        ])
        rows = read_renda_fixa_rows(xlsx)
        assert len(rows) == 1
        assert rows[0].product == "LCI"


# ---------- Frozen dataclass ----------


class TestBTGRowImmutability:
    def test_cannot_mutate_field(self) -> None:
        rows = read_renda_fixa_rows(FIXTURE_PATH)
        first = rows[0]
        with pytest.raises((AttributeError, Exception)):
            first.ativo = "tampered"  # type: ignore[misc]
