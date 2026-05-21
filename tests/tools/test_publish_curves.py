"""Tests for tools/publish_curves.py — contract mapping, CSV/PDF parsing, JSON build."""
from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# tools/ is not on the installed package path; add it for direct import
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tools"))

from publish_curves import (  # noqa: E402
    _B3_MONTH_CODES,
    _di1_vertices_from_text,
    build_unified_json,
    contract_to_maturity,
    parse_anbima,
    parse_b3,
)
from justfixed.engine.calendar import is_business_day  # noqa: E402


# ── Helpers ───────────────────────────────────────────────────────────────────

# A minimal ANBIMA ETTJ CSV (Latin-1 compatible, semicolon-separated)
_ANBIMA_CSV = """\
Parametros;IPCA;PRE
20260515;x;y

Vertices;ETTJ IPCA;ETTJ PREF;Inflacao Implicita
21;9,23;14,56;5,02
42;9,45;14,52;4,84
63;9,56;14,48;4,69
126;9,72;14,38;4,28
252;9,95;14,20;3,87

Vertices;Taxa (%a.a.)
252;14,20
"""

_ANBIMA_BAD_RATE_CSV = """\
Vertices;ETTJ IPCA;ETTJ PREF;Inflacao Implicita
21;9,23;45,00;5,02

"""

# Two traded DI1 rows as extracted by pdfplumber from BDI_00 page 1095
_BDI_PAGE_TEXT = """\
Boletim Diario do Mercado
Derivativos
DI1N26 BRBMEFD1I611 FINANCIAL 14,3670 14,3620 14,3740 14,3680 14,3740 0,09 98.309,2400 14,3720 98.310,4500 - -1,2100 -1,2100 14,3710 14,3730 2.946 403.386 39.656.723.277
DI1J27 BRBMEFD1I7C2 FINANCIAL 14,1850 14,1650 14,2250 14,2020 14,2200 0,58 89.093,4500 14,2120 89.144,4500 - -51,0000 -51,0000 14,2200 14,2250 5.354 122.899 10.950.248.325
DI1F40 BRBMEFD1I8E6 FINANCIAL - - - - - - 16.496,7800 14,2220 16.811,3400 - -314,5600 -314,5600 - - - - -
"""

_BDI_BAD_RATE_TEXT = """\
DI1N26 BRBMEFD1I611 FINANCIAL 45,0000 45,0000 45,0000 45,0000 45,0000 0,00 99.000,0000 45,0000 99.000,0000 - 0,0000 0,0000 45,0000 45,0000 100 1000 1000000
"""

_AS_OF = date(2026, 5, 15)


# ── contract_to_maturity — all 12 month codes ─────────────────────────────────

class TestContractToMaturity:
    @pytest.mark.parametrize("letter,expected_month", list(_B3_MONTH_CODES.items()))
    def test_month_mapping(self, letter: str, expected_month: int) -> None:
        code = f"DI1{letter}27"
        result = contract_to_maturity(code)
        assert result.month == expected_month
        assert result.year == 2027

    @pytest.mark.parametrize("letter", list(_B3_MONTH_CODES.keys()))
    def test_result_is_business_day(self, letter: str) -> None:
        code = f"DI1{letter}27"
        result = contract_to_maturity(code)
        assert is_business_day(result), f"{code} maturity {result} is not a business day"

    def test_year_parsing(self) -> None:
        result = contract_to_maturity("DI1F30")
        assert result.year == 2030
        assert result.month == 1

    def test_result_on_or_after_first_of_month(self) -> None:
        result = contract_to_maturity("DI1J27")  # April 2027
        assert result >= date(2027, 4, 1)
        assert result < date(2027, 5, 1)


# ── parse_anbima ──────────────────────────────────────────────────────────────

class TestParseAnbima:
    def test_returns_five_vertices_each(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "ettj.csv"
        csv_file.write_text(_ANBIMA_CSV, encoding="latin-1")
        pre, ipca = parse_anbima(csv_file, _AS_OF)
        assert len(pre) == 5
        assert len(ipca) == 5

    def test_pre_rate_converted_from_percent(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "ettj.csv"
        csv_file.write_text(_ANBIMA_CSV, encoding="latin-1")
        pre, _ = parse_anbima(csv_file, _AS_OF)
        # First vertex: 14,56 % → 0.1456
        assert pre[0].business_days == 21
        assert pre[0].rate == Decimal("0.1456")

    def test_ipca_rate_converted_from_percent(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "ettj.csv"
        csv_file.write_text(_ANBIMA_CSV, encoding="latin-1")
        _, ipca = parse_anbima(csv_file, _AS_OF)
        # First vertex: 9,23 % → 0.0923
        assert ipca[0].business_days == 21
        assert ipca[0].rate == Decimal("0.0923")

    def test_vertices_monotonically_increasing(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "ettj.csv"
        csv_file.write_text(_ANBIMA_CSV, encoding="latin-1")
        pre, ipca = parse_anbima(csv_file, _AS_OF)
        for verts in (pre, ipca):
            bdays = [v.business_days for v in verts]
            assert bdays == sorted(bdays)

    def test_rejects_out_of_range_rate(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "bad.csv"
        csv_file.write_text(_ANBIMA_BAD_RATE_CSV, encoding="latin-1")
        with pytest.raises(SystemExit):
            parse_anbima(csv_file, _AS_OF)

    def test_missing_header_aborts(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "empty.csv"
        csv_file.write_text("no header here\n", encoding="latin-1")
        with pytest.raises(SystemExit):
            parse_anbima(csv_file, _AS_OF)


# ── _di1_vertices_from_text (internal helper for parse_b3) ───────────────────

class TestDi1VerticesFromText:
    def test_extracts_traded_contracts(self) -> None:
        verts = _di1_vertices_from_text(_BDI_PAGE_TEXT, _AS_OF)
        codes_rates = {v.business_days: v.rate for v in verts}
        # All three rows should produce vertices (DI1N26, DI1J27, DI1F40)
        assert len(verts) == 3

    def test_settlement_rate_divided_by_100(self) -> None:
        # DI1N26 settlement rate is 14,3720 → 0.143720
        verts = _di1_vertices_from_text(_BDI_PAGE_TEXT, _AS_OF)
        # Sort by business_days ascending; DI1N26 (Jul 2026) is nearest
        nearest = min(verts, key=lambda v: v.business_days)
        assert nearest.rate == Decimal("0.143720")

    def test_no_trade_contract_still_extracted(self) -> None:
        # DI1F40 has '-' in trading fields but a valid settlement rate
        only_no_trade = """\
DI1F40 BRBMEFD1I8E6 FINANCIAL - - - - - - 16.496,7800 14,2220 16.811,3400 - -314,5600 -314,5600 - - - - -
"""
        verts = _di1_vertices_from_text(only_no_trade, _AS_OF)
        assert len(verts) == 1
        assert verts[0].rate == Decimal("0.142220")

    def test_no_di1_rows_returns_empty(self) -> None:
        verts = _di1_vertices_from_text("No futures data here.", _AS_OF)
        assert verts == []

    def test_expired_contract_skipped(self) -> None:
        # DI1F26 (Jan 2026) is in the past relative to as_of=2026-05-15
        text = """\
DI1F26 BRBMEFD1I000 FINANCIAL - - - - - - 99.000,0000 14,0000 99.000,0000 - 0,0000 0,0000 - - - - -
"""
        verts = _di1_vertices_from_text(text, _AS_OF)
        assert verts == []

    def test_aborts_on_implausible_rate(self) -> None:
        with pytest.raises(SystemExit):
            _di1_vertices_from_text(_BDI_BAD_RATE_TEXT, _AS_OF)


# ── parse_b3 via mocked fitz ──────────────────────────────────────────────────

def _row_to_words(tokens: list[str], y1: float) -> list[tuple]:
    """Build fitz word tuples for a list of tokens placed on a single visual row at y1.

    Each tuple is (x0, y0, x1, y1, word, block_no, line_no, word_no).
    """
    result = []
    x = 0.0
    for i, tok in enumerate(tokens):
        w = float(len(tok)) * 8.0
        result.append((x, y1 - 12.0, x + w, y1, tok, 0, 0, i))
        x += w + 4.0
    return result


# Word-tuple equivalent of the three DI1 rows from _BDI_PAGE_TEXT, each on its
# own y-row so the grouping logic reassembles them into the same single-line format
# that _DI1_ROW_RE expects.
_BDI_PAGE_WORDS: list[tuple] = (
    _row_to_words(
        ["DI1N26", "BRBMEFD1I611", "FINANCIAL", "14,3670", "14,3620", "14,3740",
         "14,3680", "14,3740", "0,09", "98.309,2400", "14,3720", "98.310,4500",
         "-", "-1,2100", "-1,2100", "14,3710", "14,3730", "2.946", "403.386",
         "39.656.723.277"],
        y1=100.0,
    )
    + _row_to_words(
        ["DI1J27", "BRBMEFD1I7C2", "FINANCIAL", "14,1850", "14,1650", "14,2250",
         "14,2020", "14,2200", "0,58", "89.093,4500", "14,2120", "89.144,4500",
         "-", "-51,0000", "-51,0000", "14,2200", "14,2250", "5.354", "122.899",
         "10.950.248.325"],
        y1=200.0,
    )
    + _row_to_words(
        ["DI1F40", "BRBMEFD1I8E6", "FINANCIAL", "-", "-", "-", "-", "-", "-",
         "16.496,7800", "14,2220", "16.811,3400", "-", "-314,5600", "-314,5600",
         "-", "-", "-", "-", "-"],
        y1=300.0,
    )
)

# A page with no DI1[A-Z]\d{2} tokens — parse_b3 should skip it entirely.
_NO_DI1_WORDS: list[tuple] = _row_to_words(["no", "futures", "here"], y1=50.0)


def _make_mock_pdf(page_word_lists: list[list[tuple]]) -> MagicMock:
    """Build a MagicMock that mimics fitz's doc API with word-level extraction.

    Each entry in page_word_lists is the list of word tuples returned by
    page.get_text("words") for that page.
    """
    pages = []
    for word_tuples in page_word_lists:
        page = MagicMock()
        page.get_text.return_value = word_tuples
        pages.append(page)
    doc = MagicMock()
    doc.page_count = len(pages)
    doc.__getitem__ = lambda s, i: pages[i]
    return MagicMock(return_value=doc)


class TestParseB3:
    def test_returns_vertices_from_di1_page(self, tmp_path: Path) -> None:
        fake_pdf = tmp_path / "BDI_00.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4")  # not a real PDF; fitz is mocked
        mock_open = _make_mock_pdf([_NO_DI1_WORDS, _BDI_PAGE_WORDS])
        with patch("publish_curves.fitz.open", mock_open):
            verts = parse_b3(fake_pdf, _AS_OF)
        assert len(verts) == 3

    def test_vertices_sorted_ascending(self, tmp_path: Path) -> None:
        fake_pdf = tmp_path / "BDI_00.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4")
        mock_open = _make_mock_pdf([_BDI_PAGE_WORDS])
        with patch("publish_curves.fitz.open", mock_open):
            verts = parse_b3(fake_pdf, _AS_OF)
        bdays = [v.business_days for v in verts]
        assert bdays == sorted(bdays)

    def test_aborts_on_no_di1_rows(self, tmp_path: Path) -> None:
        fake_pdf = tmp_path / "BDI_00.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4")
        mock_open = _make_mock_pdf([_NO_DI1_WORDS])
        with patch("publish_curves.fitz.open", mock_open):
            with pytest.raises(SystemExit):
                parse_b3(fake_pdf, _AS_OF)


# ── parse_b3 realistic-shape regression ──────────────────────────────────────

def _real_row(
    tokens: list[str],
    x0s: list[float],
    y1: float,
    line_no: int = 0,
) -> list[tuple]:
    """Build word tuples with explicitly supplied x0 positions (non-uniform gaps).

    Simulates real pymupdf output where right-aligned numeric columns produce
    varying x0 positions across rows depending on token width.
    """
    return [
        (x0, y1 - 10.2, x0 + 5.4 * len(tok), y1, tok, 0, line_no, word_no)
        for word_no, (tok, x0) in enumerate(zip(tokens, x0s))
    ]


# Three DI1 settlement rows with realistic, non-uniform column x-positions.
# These values reflect actual BDI table layout: right-aligned numerics shift
# x0 per row; the var% column (col 8) shifts col 9 (prev PU) when negative.
#
# Settlement rates at token index 7 after FINANCIAL:
#   DI1F27 → 14,0590 → Decimal("0.140590")   ← regression guard assertion
#   DI1F35 → 14,1700 → Decimal("0.141700")
#   DI1J28 → 13,9950 → Decimal("0.139950")
_REAL_DI1_PAGE_WORDS: list[tuple] = (
    _real_row(
        ["DI1F27", "BRBMEFD1I4Z0", "FINANCIAL",
         "14,1300", "14,0300", "14,1600", "14,0900", "14,0750",
         "-0,51", "92.179,4400", "14,0590", "92.134,7300",
         "-", "44,7100", "44,7100", "14,0700", "14,0800", "28.694", "850.519"],
        [28.1, 74.3, 162.8,
         230.5, 270.8, 311.2, 351.5, 391.9,
         441.3, 463.5, 533.8, 572.5,
         631.3, 643.8, 685.2, 726.4, 769.1, 809.8, 843.7],
        y1=720.5, line_no=0,
    )
    + _real_row(
        ["DI1F35", "BRBMEFD1I6J9", "FINANCIAL",
         "14,3050", "14,1600", "14,3550", "14,2370", "14,2050",
         "-1,05", "32.131,0900", "14,1700", "31.686,1400",
         "-", "444,9500", "14,2050", "14,2150", "12.564", "44.731",
         "1.429.977.212"],
        [28.1, 74.3, 162.8,
         230.5, 270.8, 311.2, 351.5, 391.9,
         440.4, 471.2, 533.8, 572.5,      # col 9 shifted right: "-1,05" is wider
         631.3, 643.8, 691.3, 729.8, 769.1, 810.3, 840.1],
        y1=732.8, line_no=1,
    )
    + _real_row(
        ["DI1J28", "BRBMEFD1I5K1", "FINANCIAL",
         "14,0500", "13,9800", "14,0700", "14,0100", "14,0200",
         "0,12", "78.234,5600", "13,9950", "78.189,2300",
         "-", "45,3300", "45,3300", "13,9900", "14,0100", "15.432", "234.567",
         "3.456.789.012"],
        [28.1, 74.3, 162.8,
         230.5, 270.8, 311.2, 351.5, 391.9,
         442.6, 463.5, 533.8, 572.5,
         631.3, 643.8, 685.2, 726.4, 769.1, 809.8, 843.7, 890.5],
        y1=745.1, line_no=2,
    )
)


class TestParseB3RealShape:
    """Regression guard: parse_b3 extracts correct vertices from realistic word-layout data.

    Catches column-drift bugs where non-uniform x-spacing causes row reconstruction
    to assemble tokens in the wrong order, placing the wrong value at index 7.
    """

    def test_correct_vertex_count(self, tmp_path: Path) -> None:
        fake_pdf = tmp_path / "BDI_00.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4")
        mock_open = _make_mock_pdf([_REAL_DI1_PAGE_WORDS])
        with patch("publish_curves.fitz.open", mock_open):
            verts = parse_b3(fake_pdf, _AS_OF)
        assert len(verts) == 3

    def test_vertices_sorted_ascending(self, tmp_path: Path) -> None:
        fake_pdf = tmp_path / "BDI_00.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4")
        mock_open = _make_mock_pdf([_REAL_DI1_PAGE_WORDS])
        with patch("publish_curves.fitz.open", mock_open):
            verts = parse_b3(fake_pdf, _AS_OF)
        bdays = [v.business_days for v in verts]
        assert bdays == sorted(bdays)

    def test_di1f27_settlement_rate(self, tmp_path: Path) -> None:
        """Token index 7 after FINANCIAL must survive non-uniform column spacing.

        DI1F27 (Jan 2027) is the nearest maturity; its settlement rate 14,0590
        must appear as Decimal("0.140590"), not a neighbour column's value.
        """
        fake_pdf = tmp_path / "BDI_00.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4")
        mock_open = _make_mock_pdf([_REAL_DI1_PAGE_WORDS])
        with patch("publish_curves.fitz.open", mock_open):
            verts = parse_b3(fake_pdf, _AS_OF)
        nearest = min(verts, key=lambda v: v.business_days)
        assert nearest.rate == Decimal("0.140590")


# ── build_unified_json ────────────────────────────────────────────────────────

class TestBuildUnifiedJson:
    def _sample_verts(self) -> list:
        from publish_curves import Vertex
        return [
            Vertex(business_days=21, rate=Decimal("0.1437")),
            Vertex(business_days=252, rate=Decimal("0.1421")),
        ]

    def test_top_level_keys(self) -> None:
        v = self._sample_verts()
        result = build_unified_json(_AS_OF, v, v, v)
        assert set(result.keys()) == {"as_of", "schema_version", "cdi", "pre", "ipca_real"}

    def test_as_of_isoformat(self) -> None:
        v = self._sample_verts()
        result = build_unified_json(_AS_OF, v, [], [])
        assert result["as_of"] == "2026-05-15"

    def test_schema_version_is_1(self) -> None:
        v = self._sample_verts()
        result = build_unified_json(_AS_OF, v, [], [])
        assert result["schema_version"] == 1

    def test_cdi_anchor_matches_as_of(self) -> None:
        v = self._sample_verts()
        result = build_unified_json(_AS_OF, v, [], [])
        assert result["cdi"]["anchor"] == "2026-05-15"

    def test_cdi_vertices_present(self) -> None:
        v = self._sample_verts()
        result = build_unified_json(_AS_OF, v, [], [])
        assert len(result["cdi"]["vertices"]) == 2
        assert result["cdi"]["vertices"][0]["business_days"] == 21
        assert result["cdi"]["vertices"][0]["rate"] == pytest.approx(0.1437)

    def test_empty_pre_and_ipca_allowed(self) -> None:
        v = self._sample_verts()
        result = build_unified_json(_AS_OF, v, [], [])
        assert result["pre"]["vertices"] == []
        assert result["ipca_real"]["vertices"] == []

    def test_fetcher_can_parse_cdi_section(self) -> None:
        """The JSON we produce must be parseable by the existing fetcher."""
        from justfixed.engine.fetcher import _parse_cdi_curve
        v = self._sample_verts()
        payload = build_unified_json(_AS_OF, v, [], [])
        curve = _parse_cdi_curve(payload)
        assert curve is not None
        assert len(curve.vertices) == 2
