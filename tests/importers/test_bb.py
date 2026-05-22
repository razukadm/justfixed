"""Tests for the BB LCA statement parser — Layer 1 (bb.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from justfixed.importers.bb import BBRow, read_lca_rows

_FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_bb_statement.txt"


def test_row_count():
    rows = read_lca_rows(_FIXTURE)
    assert len(rows) == 9


def test_active_row_fields():
    rows = read_lca_rows(_FIXTURE)
    row = rows[0]
    assert row.numero          == "201.001.010.001.001"
    assert row.data_aplicacao  == "21/11/2024"
    assert row.valor_emissao   == "2.000.000,00"
    assert row.saldo           == "2.320.000,00"
    assert row.taxa            == "95,00"
    assert row.data_vencimento == "05/11/2027"


def test_matured_row_is_included():
    rows = read_lca_rows(_FIXTURE)
    # Row at index 4 is the first matured position (saldo "0,00")
    assert rows[4].saldo == "0,00"


def test_all_matured_rows_included():
    rows = read_lca_rows(_FIXTURE)
    matured = [r for r in rows if r.saldo == "0,00"]
    assert len(matured) == 4


def test_total_line_not_in_rows():
    rows = read_lca_rows(_FIXTURE)
    assert all(r.numero != "TOTAL" for r in rows)
    assert all("TOTAL" not in r.numero for r in rows)


def test_all_rows_are_bbrow_instances():
    rows = read_lca_rows(_FIXTURE)
    assert all(isinstance(r, BBRow) for r in rows)


def test_missing_section_raises():
    tmp = Path(__file__).parent / "fixtures" / "_bb_no_section.txt"
    tmp.write_text("BANCO DO BRASIL S/A\n\nNenhuma secao aqui.\n", encoding="utf-8")
    try:
        with pytest.raises(ValueError, match="RESUMO DAS APLICAÇÕES LCA"):
            read_lca_rows(tmp)
    finally:
        tmp.unlink(missing_ok=True)


def test_missing_column_header_raises():
    content = (
        "BANCO DO BRASIL S/A\n\n"
        "RESUMO DAS APLICAÇÕES LCA\n"
        # No NÚMERO header line follows
        "------------------\n"
        "00000000001    01/03/2024     1.300.000,00     1.350.500,00    95,00     28/02/2027\n"
        "TOTAL\n"
    )
    tmp = Path(__file__).parent / "fixtures" / "_bb_no_header.txt"
    tmp.write_text(content, encoding="utf-8")
    try:
        with pytest.raises(ValueError, match="NÚMERO"):
            read_lca_rows(tmp)
    finally:
        tmp.unlink(missing_ok=True)


def test_file_not_found_raises():
    with pytest.raises(FileNotFoundError):
        read_lca_rows(Path("nonexistent_bb_statement.txt"))
