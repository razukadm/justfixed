"""Generator for the synthetic BTG statement fixture.

Run to regenerate synthetic_btg_statement.xlsx:
    python tests/importers/fixtures/create_synthetic_btg_statement.py

The fixture exercises:
  - Multi-sheet workbook (Capa, Sumario, Renda Fixa, Renda Variavel,
    Conta Corrente, Valores em Transito, Fale Conosco) — only Renda Fixa
    is parsed.
  - Posicoes summary table (rows 2-9) correctly ignored by the parser.
  - Detalhamento section with TWO sub-sections to exercise state-machine
    transitions: LCI from POUPEX (sub-section 1) and LCA from Banco do
    Brasil (sub-section 2, invented for multi-section coverage).
  - Blank row between sub-sections (row 18).
  - Posicao Consolidada Por Emissor trailer on row 24 (terminator).

Sub-section 1 (LCI POUPEX): emissao == aquisicao, matching the real
000739520.xlsx file.
Sub-section 2 (LCA Banco do Brasil): emissao (2024-01-10) intentionally
DIFFERS from aquisicao (2024-03-15) — this is a secondary-market purchase,
where the security was issued before it was acquired. The gap lets
test_issue_date_on_loaded_investment prove that btg_loader passes
issue_date from emissao_date_text rather than defaulting it to
purchase_date (which is sourced from aquisicao).

Values use integers for all numeric fields to avoid float round-trip
ambiguity through Excel. The layer-1 parser captures them via str() — the
mapper tests exercise actual numeric parsing against its own inputs.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import openpyxl


OUTPUT_PATH = Path(__file__).parent / "synthetic_btg_statement.xlsx"

_DETAIL_HEADERS = [
    "Ativo", "Emissão", "Vencimento", "Aquisição", "Liquidez",
    "Dias de carência para liquidez", "Data inicial de liquidez",
    "Taxa Compra", "Quantidade", "Preço Compra R$", "Valor Compra R$",
    "Preço R$", "Saldo Bruto R$", "IR R$", "IOF R$", "Saldo Líquido R$",
]


def _detail_header_row() -> list:
    return [None] + _DETAIL_HEADERS


def _data_row(
    ativo, emissao, vencimento, aquisicao, liquidez, dias_carencia,
    data_inicial_liquidez, taxa_compra, quantidade, preco_compra,
    valor_compra, preco, saldo_bruto, ir, iof, saldo_liquido,
) -> list:
    return [
        None, ativo, emissao, vencimento, aquisicao, liquidez, dias_carencia,
        data_inicial_liquidez, taxa_compra, quantidade, preco_compra,
        valor_compra, preco, saldo_bruto, ir, iof, saldo_liquido,
    ]


def _total_row() -> list:
    return [None, "Total"]


def create_fixture() -> None:
    wb = openpyxl.Workbook()
    wb.active.title = "Capa"
    for name in [
        "Sumario", "Renda Fixa", "Renda Variavel",
        "Conta Corrente", "Valores em Trânsito", "Fale Conosco",
    ]:
        wb.create_sheet(name)

    ws = wb["Renda Fixa"]

    sheet_rows = [
        # Row 1 — blank
        [None],
        # Row 2 — sheet title (ignored)
        [None, "Renda Fixa"],
        # Row 3 — blank
        [None],
        # Row 4 — Posicoes summary section header (ignored)
        [None, "Posições"],
        # Row 5 — blank
        [None],
        # Row 6 — summary product header (ignored)
        [None, "Posição > LCI"],
        # Row 7 — summary column headers (ignored; parser is before DETALHAMENTO_ANCHOR)
        [None, "Ativo", "Emissão", "Vencimento"],
        # Row 8 — summary data row for LCI POUPEX (ignored; same investment as
        #          Detalhamento row 1 — row count verifies it is NOT double-counted)
        [None, "LCI-25I04325998", datetime(2025, 9, 29), datetime(2027, 9, 16)],
        # Row 9 — summary Total (ignored)
        _total_row(),
        # Row 10 — blank
        [None],
        # Row 11 — blank
        [None],
        # Row 12 — DETALHAMENTO_ANCHOR; parsing begins after this row
        [None, "Posições Detalhadas"],
        # Row 13 — blank
        [None],
        # Row 14 — sub-section 1 header
        [None, "Detalhamento > LCI | ASSOCIACAO DE POUPANCA E EMPRESTIMO POUPEX"],
        # Row 15 — column headers (skipped: col B == "Ativo")
        _detail_header_row(),
        # Row 16 — sub-section 1 data row
        _data_row(
            ativo="LCI-25I04325998",
            emissao=datetime(2025, 9, 29),
            vencimento=datetime(2027, 9, 16),
            aquisicao=datetime(2025, 9, 29),
            liquidez="Sim",
            dias_carencia=185,
            data_inicial_liquidez=datetime(2026, 4, 2),
            taxa_compra="89,00% do CDI",
            quantidade=43,
            preco_compra=1000,
            valor_compra=43000,
            preco=1080,
            saldo_bruto=46440,
            ir="-",
            iof="-",
            saldo_liquido=46440,
        ),
        # Row 17 — sub-section 1 Total (terminates sub-section)
        _total_row(),
        # Row 18 — blank separator between sub-sections
        [None],
        # Row 19 — sub-section 2 header (invented: LCA from Banco do Brasil)
        [None, "Detalhamento > LCA | BANCO DO BRASIL"],
        # Row 20 — column headers
        _detail_header_row(),
        # Row 21 — sub-section 2 data row
        # emissao (2024-01-10) deliberately differs from aquisicao (2024-03-15):
        # secondary-market purchase. This lets the loader test prove issue_date
        # is read from emissao, not defaulted from purchase_date (aquisicao).
        _data_row(
            ativo="LCA-24A01234567",
            emissao=datetime(2024, 1, 10),
            vencimento=datetime(2026, 3, 15),
            aquisicao=datetime(2024, 3, 15),
            liquidez="Não",
            dias_carencia=0,
            data_inicial_liquidez=None,
            taxa_compra="115,00% do CDI",
            quantidade=100,
            preco_compra=1000,
            valor_compra=100000,
            preco=1050,
            saldo_bruto=105000,
            ir="-",
            iof="-",
            saldo_liquido=105000,
        ),
        # Row 22 — sub-section 2 Total
        _total_row(),
        # Row 23 — blank
        [None],
        # Row 24 — CONSOLIDADA_ANCHOR (terminates parsing)
        [None, "Posição Consolidada Por Emissor"],
    ]

    for row in sheet_rows:
        ws.append(row)

    wb.save(OUTPUT_PATH)
    print(f"Created {OUTPUT_PATH}")


if __name__ == "__main__":
    create_fixture()
