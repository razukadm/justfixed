"""Tests for CurveInspectorWindow.

Uses the 'real method, MagicMock self' pattern — no Qt windows instantiated.
Tests cover: series titles, precise label strings (including IPCA-real warning),
cross-check link sets, availability detection, table row counts, the
unavailable-state degradation, and hover-sync index mapping.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

from justfixed.engine.calendar import add_business_days
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

def _settle_ms(d: date) -> float:
    """Milliseconds since UTC epoch for midnight UTC on date d."""
    return float(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)


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

    def test_each_row_has_two_elements(self) -> None:
        curve = _make_curve(1)
        rows = CurveInspectorWindow._table_rows(_mock(SERIES_CDI, curve=curve))
        assert len(rows[0]) == 2

    def test_settle_date_is_first_column(self) -> None:
        curve = _make_curve(1)
        rows = CurveInspectorWindow._table_rows(_mock(SERIES_CDI, curve=curve))
        assert "/" in rows[0][0]

    def test_rate_is_second_column(self) -> None:
        curve = _make_curve(1)
        rows = CurveInspectorWindow._table_rows(_mock(SERIES_CDI, curve=curve))
        assert "%" in rows[0][1]

    def test_rate_uses_brazilian_comma_format(self) -> None:
        curve = _make_curve(1)
        rows = CurveInspectorWindow._table_rows(_mock(SERIES_CDI, curve=curve))
        rate_str = rows[0][1]
        assert "," in rate_str
        assert "%" in rate_str

    def test_rate_no_english_dot_decimal(self) -> None:
        curve = _make_curve(1)
        rows = CurveInspectorWindow._table_rows(_mock(SERIES_CDI, curve=curve))
        # The fractional part should not contain a dot
        rate_str = rows[0][1].rstrip("%")
        assert "." not in rate_str.split(",")[1] if "," in rate_str else True

    def test_empty_when_curve_none(self) -> None:
        rows = CurveInspectorWindow._table_rows(_mock(SERIES_CDI, curve=None))
        assert rows == []

    def test_settle_date_format_ddmmyyyy(self) -> None:
        curve = _make_curve(1)
        rows = CurveInspectorWindow._table_rows(_mock(SERIES_CDI, curve=curve))
        settle = rows[0][0]
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
    def test_chart_xs_returns_settlement_date_ms(self) -> None:
        curve = _make_curve(3, anchor="2026-05-20")
        m = _mock(SERIES_CDI, curve=curve)
        xs = CurveInspectorWindow._chart_xs(m)
        anchor = date.fromisoformat("2026-05-20")
        expected = [
            _settle_ms(add_business_days(anchor, 63)),
            _settle_ms(add_business_days(anchor, 126)),
            _settle_ms(add_business_days(anchor, 189)),
        ]
        assert xs == expected

    def test_chart_xs_first_value_matches_first_settlement_date(self) -> None:
        curve = _make_curve(1, anchor="2026-05-20")
        m = _mock(SERIES_CDI, curve=curve)
        xs = CurveInspectorWindow._chart_xs(m)
        settle = add_business_days(date.fromisoformat("2026-05-20"), 63)
        assert xs[0] == _settle_ms(settle)

    def test_chart_xs_empty_when_no_curve(self) -> None:
        m = _mock(SERIES_CDI, curve=None)
        assert CurveInspectorWindow._chart_xs(m) == []

    def test_chart_xs_length_matches_vertex_count(self) -> None:
        curve = _make_curve(7)
        m = _mock(SERIES_IPCA, curve=curve)
        assert len(CurveInspectorWindow._chart_xs(m)) == 7


# ── Hover-sync index mapping ──────────────────────────────────────────────────

_MS_A = 1_700_000_000_000.0
_MS_B = 1_710_000_000_000.0
_MS_C = 1_720_000_000_000.0


class TestVertexIndexForPoint:
    def test_matches_first_vertex_approximately(self) -> None:
        # Qt hovered signal hands back near-but-not-bit-identical values
        xs = [_MS_A, _MS_B, _MS_C]
        ys = [14.40, 14.41, 14.42]
        assert CurveInspectorWindow._vertex_index_for_point(xs, ys, _MS_A + 50, 14.40) == 0

    def test_matches_middle_vertex_approximately(self) -> None:
        xs = [_MS_A, _MS_B, _MS_C]
        ys = [14.40, 14.41, 14.42]
        assert CurveInspectorWindow._vertex_index_for_point(xs, ys, _MS_B + 50, 14.41) == 1

    def test_matches_last_vertex_approximately(self) -> None:
        xs = [_MS_A, _MS_B, _MS_C]
        ys = [14.40, 14.41, 14.42]
        assert CurveInspectorWindow._vertex_index_for_point(xs, ys, _MS_C - 50, 14.42) == 2

    def test_nearest_returned_for_off_point_input(self) -> None:
        # Even a far-off query returns the nearest vertex — nearest-match, not exact-gate
        xs = [_MS_A, _MS_B, _MS_C]
        ys = [14.40, 14.41, 14.42]
        assert CurveInspectorWindow._vertex_index_for_point(xs, ys, _MS_C + 1e11, 14.50) == 2

    def test_empty_lists_return_none(self) -> None:
        assert CurveInspectorWindow._vertex_index_for_point([], [], _MS_A, 14.0) is None

    def test_single_vertex_matches_approximately(self) -> None:
        xs = [_MS_A]
        ys = [14.40]
        assert CurveInspectorWindow._vertex_index_for_point(xs, ys, _MS_A + 50, 14.40) == 0

    def test_near_but_not_exact_still_matches(self) -> None:
        # y offset of 0.001 — nearest-match returns the only vertex, not None
        xs = [_MS_A]
        ys = [14.40]
        assert CurveInspectorWindow._vertex_index_for_point(xs, ys, _MS_A, 14.401) == 0

    def test_returns_int_for_valid_point(self) -> None:
        xs = [_MS_A, _MS_B]
        ys = [14.40, 14.41]
        result = CurveInspectorWindow._vertex_index_for_point(xs, ys, _MS_A + 50, 14.40)
        assert isinstance(result, int)

    def test_uses_full_xy_metric_for_disambiguation(self) -> None:
        # Two vertices with identical x, differing y — nearest by full x+y metric picks correct one
        xs = [_MS_A, _MS_A]
        ys = [14.40, 14.50]
        assert CurveInspectorWindow._vertex_index_for_point(xs, ys, _MS_A, 14.50) == 1
