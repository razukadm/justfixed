"""Curve Inspector windows — read-only yield-curve viewer.

Three separate top-level windows opened from View ▸ CDI Curve /
IPCA-real Curve / Prefixado Curve.  One class parameterised by series;
the three windows share this code.
"""

from __future__ import annotations

from PySide6.QtCharts import QChart, QChartView, QDateTimeAxis, QLineSeries, QScatterSeries, QValueAxis
from PySide6.QtCore import QDate, QDateTime, QEvent, QMargins, QPointF, Qt, QTime, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from justfixed.domain.rates import _format_brazilian_percent
from justfixed.engine.calendar import add_business_days
from justfixed.engine.curve import Curve
from justfixed.engine.fetcher import FetchResult

# ── Cross-check URLs ──────────────────────────────────────────────────────────

_INFOMONEY_URL = "https://www.infomoney.com.br/ferramentas/juros-futuros-di/"
_ANBIMA_URL = "https://www.anbima.com.br/informacoes/est-termo/CZ.asp"
# TODO: re-verify — B3 reorganizes these paths.
_B3_REFERENCE_RATES_URL = (
    "https://sistemaswebb3-derivativos.b3.com.br/referenceRatesPage/all?language=pt-br"
)

# ── Design tokens (from wireframe CSS custom properties) ──────────────────────

_INK          = "#1a1a1a"
_INK_2        = "#4a4a4a"
_INK_3        = "#888888"
_PAPER        = "#fafaf7"
_PANEL        = "#ffffff"
_PANEL_2      = "#f4f4f1"
_RULE         = "#d9d6cf"
_RULE_2       = "#ececea"
_LINK         = "#1f6feb"
_WARN         = "#e67e22"
_CALLOUT_BG   = "#eef4fb"
_CALLOUT_EDGE = "#c5dbf2"
_ACCENT       = "#d35400"
_ROW_HOVER    = "#fff7d6"

# ── Series keys ───────────────────────────────────────────────────────────────

SERIES_CDI  = "cdi"
SERIES_IPCA = "ipca"
SERIES_PRE  = "pre"


class CurveInspectorWindow(QWidget):
    """Read-only window showing one yield-curve series (CDI, IPCA-real, or Prefixado)."""

    def __init__(
        self,
        series: str,
        curve: Curve | None,
        fetch_result: FetchResult | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self._series = series
        self._curve = curve
        self._fetch_result = fetch_result
        self._table: QTableWidget | None = None
        self._highlight_dot: QScatterSeries | None = None
        self._hover_xs: list[float] = []
        self._hover_ys: list[float] = []
        self._hover_row: int = -1
        self._build_ui()
        self.setWindowTitle(self._series_title())
        self.resize(960, 640)

    # ── Logical methods (testable with MagicMock self) ────────────────────────

    def _series_title(self) -> str:
        return {
            SERIES_CDI:  "JustFixed — CDI Curve",
            SERIES_IPCA: "JustFixed — IPCA-real Curve",
            SERIES_PRE:  "JustFixed — Prefixado Curve",
        }[self._series]

    def _series_label_html(self) -> str:
        """Rich-text label placed between provenance callout and body."""
        if self._series == SERIES_CDI:
            return (
                f"<b>CDI curve</b> — DI1 futures "
                f"<span style='color: {_INK_3}; font-style: italic;'>"
                f"(interbank deposit rate).</span>"
            )
        if self._series == SERIES_IPCA:
            return (
                f"<b>IPCA real-rate curve</b> — corresponds to ANBIMA ETTJ, the "
                f"<span style='font-family: Consolas, monospace;'>ETTJ IPCA</span> column. "
                f"<span style='color: {_WARN}; font-weight: 600;'>"
                f"Real-yield term structure</span> "
                f"<span style='color: {_INK_3}; font-style: italic;'>"
                f"— not monthly IPCA inflation.</span>"
            )
        # SERIES_PRE
        return (
            f"<b>Prefixado curve</b> — corresponds to ANBIMA ETTJ, the "
            f"<span style='font-family: Consolas, monospace;'>ETTJ PRE</span> column."
        )

    def _cross_check_links(self) -> list[tuple[str, str, str]]:
        """Returns list of (display_label, qualifier, url) for this series."""
        if self._series == SERIES_CDI:
            return [
                ("B3 — Taxas Referenciais", "source of record", _B3_REFERENCE_RATES_URL),
                ("InfoMoney — Juros Futuros DI", "quick visual check", _INFOMONEY_URL),
            ]
        return [
            ("ANBIMA — Estrutura a Termo (ETTJ)", "source of record", _ANBIMA_URL),
        ]

    def _is_available(self) -> bool:
        return bool(self._curve and self._curve.vertices)

    def _provenance_asof(self) -> str:
        if self._curve and self._curve.anchor:
            return self._curve.anchor.strftime("%Y-%m-%d")
        return "—"

    def _status_bar_text(self) -> str:
        if not (self._curve and self._curve.vertices):
            return "Curve: unavailable"
        anchor = self._curve.anchor.strftime("%Y-%m-%d")
        return f"Curve: justfixed-data ({anchor})  ·  {len(self._curve.vertices)} vertices"

    def _table_rows(self) -> list[tuple[str, str]]:
        """Returns [(settle_date, rate_pct), ...] for the curve."""
        if not (self._curve and self._curve.vertices):
            return []
        rows = []
        for v in self._curve.vertices:
            settle = add_business_days(self._curve.anchor, v.business_days)
            settle_str = settle.strftime("%d/%m/%Y")
            rate_pct = _format_brazilian_percent(v.rate * 100)
            rows.append((settle_str, rate_pct))
        return rows

    def _chart_xs(self) -> list[float]:
        """X values for the chart: settlement date as milliseconds since UTC epoch."""
        if not (self._curve and self._curve.vertices):
            return []
        result = []
        for v in self._curve.vertices:
            settle = add_business_days(self._curve.anchor, v.business_days)
            qdt = QDateTime(
                QDate(settle.year, settle.month, settle.day),
                QTime(0, 0, 0),
                Qt.TimeSpec.UTC,
            )
            result.append(float(qdt.toMSecsSinceEpoch()))
        return result

    @staticmethod
    def _vertex_index_for_point(
        xs: list[float], ys: list[float], px: float, py: float
    ) -> int | None:
        """Return the index of the nearest vertex to (px, py), or None if xs is empty.

        Uses nearest-vertex semantics rather than an exact-equality gate.
        QScatterSeries.hovered only fires when the cursor is genuinely over a
        plotted point, so the nearest vertex is always the correct match.
        An absolute tolerance (e.g. 1e-9) breaks at ms-epoch x-scales (~1.7e12)
        where one floating-point ULP is on the order of 1e-4.
        """
        if not xs:
            return None
        return min(range(len(xs)), key=lambda i: abs(xs[i] - px) + abs(ys[i] - py))

    # ── Hover-sync handlers ───────────────────────────────────────────────────

    def eventFilter(self, obj, event: QEvent) -> bool:
        if self._table is not None and obj is self._table.viewport():
            if event.type() == QEvent.Type.MouseMove:
                row = self._table.rowAt(int(event.position().y()))
                self._on_table_hover_row(row)
            elif event.type() == QEvent.Type.Leave:
                self._clear_hover()
        return super().eventFilter(obj, event)

    def _on_chart_hover(self, point: QPointF, state: bool) -> None:
        # Defer all updates: modifying a QScatterSeries synchronously inside
        # QXYSeries.hovered crashes QtCharts (C++-level reentrancy in the
        # hit-test code path). QTimer.singleShot(0) queues the work to run
        # after the signal dispatch returns.
        try:
            if not state:
                QTimer.singleShot(0, self._clear_hover)
                return
            idx = self._vertex_index_for_point(
                self._hover_xs, self._hover_ys, point.x(), point.y()
            )
            if idx is None:
                return
            def _deferred(i: int = idx) -> None:
                self._highlight_table_row(i)
                self._highlight_chart_dot(i)
            QTimer.singleShot(0, _deferred)
        except Exception:
            import traceback
            traceback.print_exc()

    def _on_table_hover_row(self, row: int) -> None:
        if row < 0:
            self._clear_hover()
            return
        self._highlight_table_row(row)
        self._highlight_chart_dot(row)

    def _highlight_table_row(self, idx: int) -> None:
        if self._table is None:
            return
        if self._hover_row >= 0 and self._hover_row != idx:
            for col in range(self._table.columnCount()):
                item = self._table.item(self._hover_row, col)
                if item is not None:
                    item.setBackground(QBrush())
        self._hover_row = idx
        brush = QBrush(QColor(_ROW_HOVER))
        for col in range(self._table.columnCount()):
            item = self._table.item(idx, col)
            if item is not None:
                item.setBackground(brush)
        visible_item = self._table.item(idx, 0)
        if visible_item is not None:
            self._table.scrollToItem(
                visible_item, QAbstractItemView.ScrollHint.EnsureVisible
            )

    def _highlight_chart_dot(self, idx: int) -> None:
        if self._highlight_dot is None:
            return
        self._highlight_dot.clear()
        if 0 <= idx < len(self._hover_xs):
            self._highlight_dot.append(self._hover_xs[idx], self._hover_ys[idx])

    def _clear_hover(self) -> None:
        if self._table is not None and self._hover_row >= 0:
            for col in range(self._table.columnCount()):
                item = self._table.item(self._hover_row, col)
                if item is not None:
                    item.setBackground(QBrush())
        self._hover_row = -1
        if self._highlight_dot is not None:
            self._highlight_dot.clear()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self.setObjectName("CurveInspectorWindow")
        self._apply_stylesheet()
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 0)
        root.setSpacing(10)
        root.addWidget(self._build_provenance())
        if self._is_available():
            root.addWidget(self._build_body(), stretch=1)
        else:
            root.addWidget(self._build_unavailable(), stretch=1)
        root.addWidget(self._build_crosscheck())
        root.addWidget(self._build_status_bar())

    def _apply_stylesheet(self) -> None:
        self.setStyleSheet(f"""
            QWidget#CurveInspectorWindow {{
                background: {_PAPER};
            }}
            QFrame#provenance {{
                background: {_CALLOUT_BG};
                border: 1px solid {_CALLOUT_EDGE};
                border-radius: 5px;
            }}
            QFrame#crosscheck {{
                background: {_PANEL_2};
                border: none;
                border-top: 1px solid {_RULE_2};
            }}
            QFrame#panel_frame {{
                background: {_PANEL};
                border: 1px solid {_RULE};
                border-radius: 4px;
            }}
            QTableWidget {{
                gridline-color: {_RULE_2};
                background: {_PANEL};
                alternate-background-color: #fafaf8;
                border: none;
                font-family: Consolas, "Courier New", monospace;
                font-size: 12px;
                color: {_INK};
            }}
            QHeaderView::section {{
                background: #fbfbf9;
                border: none;
                border-bottom: 1px solid {_RULE};
                font-weight: 600;
                color: {_INK_2};
                font-size: 12px;
                padding: 6px 10px;
            }}
        """)

    def _build_provenance(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("provenance")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        # Row 1: series label (rich text, same content as before)
        series_lbl = QLabel()
        series_lbl.setTextFormat(Qt.TextFormat.RichText)
        series_lbl.setText(self._series_label_html())
        series_lbl.setStyleSheet(f"color: {_INK}; font-size: 13px; border: none;")
        series_lbl.setWordWrap(True)
        layout.addWidget(series_lbl)

        # Row 2: 1px divider in callout-edge color
        divider = QWidget()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background: {_CALLOUT_EDGE};")
        layout.addWidget(divider)

        # Row 3: as-of row — uppercase label + mono date value
        asof_row = QWidget()
        asof_row.setStyleSheet("background: transparent;")
        asof_layout = QHBoxLayout(asof_row)
        asof_layout.setContentsMargins(0, 0, 0, 0)
        asof_layout.setSpacing(6)

        lbl_asof = QLabel("CURVE AS-OF")
        lbl_asof.setStyleSheet(
            f"color: {_INK_3}; font-size: 9px; letter-spacing: 0.06em; border: none;"
        )

        val_asof = QLabel(self._provenance_asof())
        val_asof.setStyleSheet(
            f"font-family: Consolas, 'Courier New', monospace; "
            f"font-size: 9px; font-weight: 500; color: {_INK}; border: none;"
        )

        asof_layout.addWidget(lbl_asof)
        asof_layout.addWidget(val_asof)
        asof_layout.addStretch()
        layout.addWidget(asof_row)
        return frame

    def _build_body(self) -> QWidget:
        body = QWidget()
        body.setStyleSheet(f"background: {_PAPER};")
        layout = QHBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(self._build_chart_panel(), stretch=58)
        layout.addWidget(self._build_table_panel(), stretch=42)
        return body

    def _build_chart_panel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("panel_frame")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        n = len(self._curve.vertices)
        layout.addWidget(self._make_panel_header("Curve shape", f"{n} vertices"))
        layout.addWidget(self._build_chart(), stretch=1)
        return frame

    def _build_chart(self) -> QChartView:
        chart = QChart()
        chart.setBackgroundBrush(QColor(_PANEL))
        chart.setBackgroundRoundness(0)
        chart.setMargins(QMargins(4, 4, 4, 4))
        chart.legend().setVisible(False)

        xs = self._chart_xs()
        ys = [float(v.rate * 100) for v in self._curve.vertices]
        self._hover_xs = xs
        self._hover_ys = ys

        line = QLineSeries()
        pen = QPen(QColor(_INK))
        pen.setWidthF(1.5)
        line.setPen(pen)

        dots = QScatterSeries()
        dots.setColor(QColor(_INK))
        dots.setBorderColor(QColor(_INK))
        dots.setMarkerSize(6)

        self._highlight_dot = QScatterSeries()
        self._highlight_dot.setColor(QColor(_ACCENT))
        self._highlight_dot.setBorderColor(QColor(_ACCENT))
        self._highlight_dot.setMarkerSize(10)

        for x, y in zip(xs, ys):
            line.append(x, y)
            dots.append(x, y)

        chart.addSeries(line)
        chart.addSeries(dots)
        chart.addSeries(self._highlight_dot)
        dots.hovered.connect(self._on_chart_hover)

        x_axis = QDateTimeAxis()
        x_axis.setTitleText("Settlement date")
        x_axis.setFormat("MMM yyyy")
        x_axis.setLabelsFont(QFont("Segoe UI", 8))
        x_axis.setTitleFont(QFont("Segoe UI", 9))
        x_axis.setTickCount(7)
        x_axis.setGridLineColor(QColor(_RULE_2))
        if xs:
            span_ms = max(xs) - min(xs)
            margin_ms = int(span_ms * 0.02)
            x_axis.setRange(
                QDateTime.fromMSecsSinceEpoch(int(min(xs)) - margin_ms),
                QDateTime.fromMSecsSinceEpoch(int(max(xs)) + margin_ms),
            )

        y_min, y_max = min(ys), max(ys)
        y_margin = max((y_max - y_min) * 0.05, 0.1)
        y_axis = QValueAxis()
        y_axis.setTitleText("Rate (% a.a.)")
        y_axis.setLabelFormat("%.2f%%")
        y_axis.setLabelsFont(QFont("Consolas", 8))
        y_axis.setTitleFont(QFont("Segoe UI", 9))
        y_axis.setRange(y_min - y_margin, y_max + y_margin)
        y_axis.setTickCount(6)
        y_axis.setGridLineColor(QColor(_RULE_2))

        chart.addAxis(x_axis, Qt.AlignmentFlag.AlignBottom)
        chart.addAxis(y_axis, Qt.AlignmentFlag.AlignLeft)
        line.attachAxis(x_axis)
        line.attachAxis(y_axis)
        dots.attachAxis(x_axis)
        dots.attachAxis(y_axis)
        self._highlight_dot.attachAxis(x_axis)
        self._highlight_dot.attachAxis(y_axis)

        view = QChartView(chart)
        view.setRenderHint(QPainter.RenderHint.Antialiasing)
        view.setStyleSheet("border: none;")
        return view

    def _build_table_panel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("panel_frame")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        n = len(self._curve.vertices)
        layout.addWidget(self._make_panel_header("Vertices", f"{n} rows"))
        layout.addWidget(self._build_table(), stretch=1)
        return frame

    def _build_table(self) -> QTableWidget:
        rows = self._table_rows()
        table = QTableWidget(len(rows), 2)
        table.setHorizontalHeaderLabels(["Settles on", "Rate a.a."])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(1, 90)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setShowGrid(False)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        for r, (settle, rate) in enumerate(rows):
            s_item = QTableWidgetItem(settle)
            r_item = QTableWidgetItem(rate)
            r_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            table.setItem(r, 0, s_item)
            table.setItem(r, 1, r_item)
        self._table = table
        table.setMouseTracking(True)
        table.viewport().setMouseTracking(True)
        table.viewport().installEventFilter(self)
        return table

    def _build_crosscheck(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("crosscheck")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(4)

        src_lbl = QLabel(
            "Source: <b>justfixed-data</b>, compiled from ANBIMA / B3 published curves."
        )
        src_lbl.setTextFormat(Qt.TextFormat.RichText)
        src_lbl.setStyleSheet(f"color: {_INK_2}; font-size: 12px; border: none;")
        layout.addWidget(src_lbl)

        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {_RULE};")
        layout.addWidget(sep)

        verify_lbl = QLabel("Verify this data against the source:")
        verify_lbl.setStyleSheet(f"color: {_INK_2}; font-size: 12px; padding-top: 2px; border: none;")
        layout.addWidget(verify_lbl)

        link_row = QHBoxLayout()
        link_row.setSpacing(20)
        for display_label, qualifier, url in self._cross_check_links():
            lbl = QLabel(
                f'<a href="{url}" style="color: {_LINK}; text-decoration: none;">'
                f'{display_label} ↗</a>'
                f' <span style="color: {_INK_3}; font-size: 11px;">{qualifier}</span>'
            )
            lbl.setTextFormat(Qt.TextFormat.RichText)
            lbl.setOpenExternalLinks(True)
            lbl.setStyleSheet("font-size: 13px; border: none;")
            link_row.addWidget(lbl)
        link_row.addStretch()
        layout.addLayout(link_row)
        return frame

    def _build_status_bar(self) -> QLabel:
        lbl = QLabel(self._status_bar_text())
        lbl.setObjectName("CurveStatusBar")
        lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lbl.setFixedHeight(22)
        lbl.setStyleSheet(
            f"background: #f7f6f3; border: none; border-top: 1px solid {_RULE}; "
            f"font-family: Consolas, 'Courier New', monospace; "
            f"font-size: 11px; color: {_INK_3}; padding: 0px 10px; margin: 0;"
        )
        return lbl

    def _build_unavailable(self) -> QWidget:
        container = QWidget()
        container.setStyleSheet(
            f"background: #fdfbf6; border: 1px dashed {_RULE}; border-radius: 4px;"
        )
        layout = QVBoxLayout(container)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(8)

        heading = QLabel("Curve data unavailable")
        heading.setStyleSheet(
            f"font-size: 15px; font-weight: 600; color: {_INK}; border: none;"
        )
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)

        body = QLabel(
            "Could not fetch or load a cached curve for this series.\n"
            "The window cannot show vertices until data is available."
        )
        body.setStyleSheet(f"color: {_INK_2}; font-size: 13px; border: none;")
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.setWordWrap(True)

        layout.addWidget(heading)
        layout.addWidget(body)
        return container

    def _make_panel_header(self, title: str, meta: str) -> QWidget:
        w = QWidget()
        w.setStyleSheet(
            f"background: {_PANEL_2}; border-bottom: 1px solid {_RULE_2}; border-radius: 0px;"
        )
        layout = QHBoxLayout(w)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(4)
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(f"font-weight: 600; color: {_INK}; background: transparent;")
        meta_lbl = QLabel(meta)
        meta_lbl.setStyleSheet(
            f"font-family: Consolas, 'Courier New', monospace; "
            f"font-size: 11px; color: {_INK_3}; background: transparent;"
        )
        layout.addWidget(title_lbl)
        layout.addStretch()
        layout.addWidget(meta_lbl)
        return w
