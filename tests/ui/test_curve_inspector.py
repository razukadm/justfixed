"""Tests for CurveInspectorWindow.

Uses the 'real method, MagicMock self' pattern — no Qt windows instantiated.
Tests cover: series titles, precise label strings (including IPCA-real warning),
cross-check link sets, availability detection, table row counts, and the
unavailable-state degradation.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

from justfixed.engine.curve import Curve, CurveVertex
from justfixed.engine.fetcher import FetchResult
from justfixed.ui.curve_inspector import (
    SERIES_CDI,
    SERIES_IPCA,
    SERIES_PRE,
    CurveInspectorWindow,
    _ANBIMA_URL,
    _B3_REFERENCE_RATES_URL,
    _INFOMONEY_URL,
    _WARN,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_curve(n: int = 3, anchor: str = "2026-05-20") -> Curve:
    vertices = tuple(
        CurveVertex(
            business_days=(i + 1) * 63,
            rate=Decimal("0.1440") + Decimal("0.0001") * i,
        )
        for i in range(n)
    )
    return Curve(anchor=date.fromisoformat(anchor), vertices=vertices)


def _mock(
    series: str,
    curve: Curve | None = None,
    fetch_result: FetchResult | None = None,
) -> MagicMock:
    m = MagicMock(spec=CurveInspectorWindow)
    m._series = series
    m._curve = curve
    m._fetch_result = fetch_result
    return m


# ── Series title ──────────────────────────────────────────────────────────────

class TestSeriesTitle:
    def test_cdi(self) -> None:
        assert CurveInspectorWindow._series_title(_mock(SERIES_CDI)) == "JustFixed — CDI Curve"

    def test_ipca(self) -> None:
        assert CurveInspectorWindow._series_title(_mock(SERIES_IPCA)) == "JustFixed — IPCA-real Curve"

    def test_pre(self) -> None:
        assert CurveInspectorWindow._series_title(_mock(SERIES_PRE)) == "JustFixed — Prefixado Curve"


# ── Series label HTML ─────────────────────────────────────────────────────────

class TestSeriesLabelHtml:
    def test_cdi_contains_correct_description(self) -> None:
        html = CurveInspectorWindow._series_label_html(_mock(SERIES_CDI))
        assert "CDI curve" in html
        assert "DI1 futures" in html
        assert "interbank deposit rate" in html

    def test_ipca_contains_full_label(self) -> None:
        html = CurveInspectorWindow._series_label_html(_mock(SERIES_IPCA))
        assert "IPCA real-rate curve" in html
        assert "ANBIMA ETTJ" in html
        assert "ETTJ IPCA" in html

    def test_ipca_contains_mandatory_warning_text(self) -> None:
        html = CurveInspectorWindow._series_label_html(_mock(SERIES_IPCA))
        assert "Real-yield term structure" in html

    def test_ipca_clarifier_present(self) -> None:
        html = CurveInspectorWindow._series_label_html(_mock(SERIES_IPCA))
        assert "not monthly IPCA inflation" in html

    def test_ipca_warning_uses_warn_color(self) -> None:
        html = CurveInspectorWindow._series_label_html(_mock(SERIES_IPCA))
        warn_pos = html.index("Real-yield term structure")
        assert _WARN in html[:warn_pos]

    def test_pre_contains_correct_description(self) -> None:
        html = CurveInspectorWindow._series_label_html(_mock(SERIES_PRE))
        assert "Prefixado curve" in html
        assert "ANBIMA ETTJ" in html
        assert "ETTJ PRE" in html


# ── Cross-check links ─────────────────────────────────────────────────────────

class TestCrossCheckLinks:
    def test_cdi_has_two_links(self) -> None:
        links = CurveInspectorWindow._cross_check_links(_mock(SERIES_CDI))
        assert len(links) == 2

    def test_cdi_includes_b3_url(self) -> None:
        urls = {lnk[2] for lnk in CurveInspectorWindow._cross_check_links(_mock(SERIES_CDI))}
        assert _B3_REFERENCE_RATES_URL in urls

    def test_cdi_includes_infomoney_url(self) -> None:
        urls = {lnk[2] for lnk in CurveInspectorWindow._cross_check_links(_mock(SERIES_CDI))}
        assert _INFOMONEY_URL in urls

    def test_ipca_has_one_link(self) -> None:
        links = CurveInspectorWindow._cross_check_links(_mock(SERIES_IPCA))
        assert len(links) == 1

    def test_ipca_link_is_anbima(self) -> None:
        links = CurveInspectorWindow._cross_check_links(_mock(SERIES_IPCA))
        assert links[0][2] == _ANBIMA_URL

    def test_pre_has_one_link(self) -> None:
        links = CurveInspectorWindow._cross_check_links(_mock(SERIES_PRE))
        assert len(links) == 1

    def test_pre_link_is_anbima(self) -> None:
        links = CurveInspectorWindow._cross_check_links(_mock(SERIES_PRE))
        assert links[0][2] == _ANBIMA_URL

    def test_each_link_is_three_tuple(self) -> None:
        for series in (SERIES_CDI, SERIES_IPCA, SERIES_PRE):
            for lnk in CurveInspectorWindow._cross_check_links(_mock(series)):
                assert len(lnk) == 3, f"Expected 3-tuple for {series}"


# ── Availability ──────────────────────────────────────────────────────────────

class TestIsAvailable:
    def test_none_curve_not_available(self) -> None:
        assert not CurveInspectorWindow._is_available(_mock(SERIES_CDI, curve=None))

    def test_curve_with_vertices_is_available(self) -> None:
        assert CurveInspectorWindow._is_available(_mock(SERIES_CDI, curve=_make_curve()))

    def test_available_for_all_series(self) -> None:
        curve = _make_curve()
        for series in (SERIES_CDI, SERIES_IPCA, SERIES_PRE):
            assert CurveInspectorWindow._is_available(_mock(series, curve=curve))


# ── Table rows ────────────────────────────────────────────────────────────────

class TestTableRows:
    def test_row_count_matches_vertex_count_three(self) -> None:
        curve = _make_curve(3)
        rows = CurveInspectorWindow._table_rows(_mock(SERIES_CDI, curve=curve))
        assert len(rows) == 3

    def test_row_count_matches_vertex_count_seven(self) -> None:
        curve = _make_curve(7)
        rows = CurveInspectorWindow._table_rows(_mock(SERIES_IPCA, curve=curve))
        assert len(rows) == 7

    def test_cdi_47_vertex_row_count(self) -> None:
        curve = _make_curve(47)
        rows = CurveInspectorWindow._table_rows(_mock(SERIES_CDI, curve=curve))
        assert len(rows) == 47

    def test_each_row_has_three_elements(self) -> None:
        curve = _make_curve(1)
        rows = CurveInspectorWindow._table_rows(_mock(SERIES_CDI, curve=curve))
        assert len(rows[0]) == 3

    def test_tenor_ends_with_bd(self) -> None:
        curve = _make_curve(1)
        rows = CurveInspectorWindow._table_rows(_mock(SERIES_CDI, curve=curve))
        assert rows[0][0].endswith(" bd")

    def test_tenor_shows_business_day_count(self) -> None:
        curve = _make_curve(1)  # first vertex at 63 bd
        rows = CurveInspectorWindow._table_rows(_mock(SERIES_CDI, curve=curve))
        assert rows[0][0] == "63 bd"

    def test_rate_uses_brazilian_comma_format(self) -> None:
        curve = _make_curve(1)
        rows = CurveInspectorWindow._table_rows(_mock(SERIES_CDI, curve=curve))
        rate_str = rows[0][2]
        assert "," in rate_str
        assert "%" in rate_str

    def test_rate_no_english_dot_decimal(self) -> None:
        curve = _make_curve(1)
        rows = CurveInspectorWindow._table_rows(_mock(SERIES_CDI, curve=curve))
        # The fractional part should not contain a dot
        rate_str = rows[0][2].rstrip("%")
        assert "." not in rate_str.split(",")[1] if "," in rate_str else True

    def test_empty_when_curve_none(self) -> None:
        rows = CurveInspectorWindow._table_rows(_mock(SERIES_CDI, curve=None))
        assert rows == []

    def test_settle_date_format_ddmmyyyy(self) -> None:
        curve = _make_curve(1)
        rows = CurveInspectorWindow._table_rows(_mock(SERIES_CDI, curve=curve))
        settle = rows[0][1]
        parts = settle.split("/")
        assert len(parts) == 3
        assert len(parts[0]) == 2   # dd
        assert len(parts[1]) == 2   # mm
        assert len(parts[2]) == 4   # yyyy


# ── Unavailable-state degradation ─────────────────────────────────────────────

class TestUnavailableState:
    def test_provenance_asof_shows_dash_when_no_curve(self) -> None:
        assert CurveInspectorWindow._provenance_asof(_mock(SERIES_CDI, curve=None)) == "—"

    def test_provenance_badge_method_removed(self) -> None:
        assert not hasattr(CurveInspectorWindow, "_provenance_badge")

    def test_asof_works_without_fetch_result(self) -> None:
        curve = _make_curve(anchor="2026-05-20")
        m = _mock(SERIES_CDI, curve=curve, fetch_result=None)
        assert CurveInspectorWindow._provenance_asof(m) == "2026-05-20"

    def test_status_bar_shows_unavailable_when_no_curve(self) -> None:
        m = _mock(SERIES_CDI, curve=None)
        assert CurveInspectorWindow._status_bar_text(m) == "Curve: unavailable"

    def test_cross_check_links_still_present_when_unavailable(self) -> None:
        m = _mock(SERIES_CDI, curve=None)
        links = CurveInspectorWindow._cross_check_links(m)
        assert len(links) == 2  # CDI links remain even with no data


# ── Provenance with live data ─────────────────────────────────────────────────

class TestProvenanceWithData:
    def test_asof_shows_anchor_date(self) -> None:
        curve = _make_curve(anchor="2026-05-20")
        m = _mock(SERIES_CDI, curve=curve)
        assert CurveInspectorWindow._provenance_asof(m) == "2026-05-20"

    def test_status_bar_shows_anchor_and_vertex_count(self) -> None:
        curve = _make_curve(47, anchor="2026-05-20")
        m = _mock(SERIES_CDI, curve=curve)
        text = CurveInspectorWindow._status_bar_text(m)
        assert "2026-05-20" in text
        assert "47 vertices" in text
        assert "justfixed-data" in text


# ── Chart x values ────────────────────────────────────────────────────────────

class TestChartXValues:
    def test_chart_xs_converts_bd_to_years(self) -> None:
        curve = _make_curve(3)  # vertices at 63, 126, 189 bd
        m = _mock(SERIES_CDI, curve=curve)
        xs = CurveInspectorWindow._chart_xs(m)
        assert xs == [63 / 252, 126 / 252, 189 / 252]

    def test_chart_xs_uses_business_days_per_year_constant(self) -> None:
        from justfixed.engine.calendar import BUSINESS_DAYS_PER_YEAR
        curve = _make_curve(1)
        m = _mock(SERIES_CDI, curve=curve)
        xs = CurveInspectorWindow._chart_xs(m)
        assert xs[0] == 63 / BUSINESS_DAYS_PER_YEAR

    def test_chart_xs_empty_when_no_curve(self) -> None:
        m = _mock(SERIES_CDI, curve=None)
        assert CurveInspectorWindow._chart_xs(m) == []

    def test_chart_xs_length_matches_vertex_count(self) -> None:
        curve = _make_curve(7)
        m = _mock(SERIES_IPCA, curve=curve)
        assert len(CurveInspectorWindow._chart_xs(m)) == 7
