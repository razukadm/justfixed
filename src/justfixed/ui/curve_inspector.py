"""Curve Inspector windows — read-only yield-curve viewer.

Three separate top-level windows opened from View ▸ CDI Curve /
IPCA-real Curve / Prefixado Curve.  One class parameterised by series;
the three windows share this code.
"""

from __future__ import annotations

from PySide6.QtCharts import QChart, QChartView, QLineSeries, QScatterSeries, QValueAxis
from PySide6.QtCore import QMargins, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
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

    def _provenance_badge(self) -> str:
        if not self._fetch_result or self._fetch_result.source == "unavailable":
            return "no data"
        src = self._fetch_result.source
        t = self._fetch_result.source_time
        return f"{src} · {t:%H:%M}" if t else src

    def _status_bar_text(self) -> str:
        if not (self._curve and self._curve.vertices):
            return "Curve: unavailable"
        anchor = self._curve.anchor.strftime("%Y-%m-%d")
        return f"Curve: justfixed-data ({anchor})  ·  {len(self._curve.vertices)} vertices"

    def _table_rows(self) -> list[tuple[str, str, str]]:
        """Returns [(tenor, settle_date, rate_pct), ...] for the curve."""
        if not (self._curve and self._curve.vertices):
            return []
        rows = []
        for v in self._curve.vertices:
            tenor = f"{v.business_days} bd"
            settle = add_business_days(self._curve.anchor, v.business_days)
            settle_str = settle.strftime("%d/%m/%Y")
            rate_pct = _format_brazilian_percent(v.rate * 100)
            rows.append((tenor, settle_str, rate_pct))
        return rows

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self.setObjectName("CurveInspectorWindow")
        self._apply_stylesheet()
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 0)
        root.setSpacing(10)
        root.addWidget(self._build_provenance())
        root.addWidget(self._build_series_label())
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
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        lbl_asof = QLabel("Curve as-of:")
        lbl_asof.setStyleSheet(
            f"color: {_INK_3}; font-size: 11px; letter-spacing: 0.05em; border: none;"
        )

        val_asof = QLabel(self._provenance_asof())
        val_asof.setStyleSheet(
            f"font-family: Consolas, 'Courier New', monospace; "
            f"font-size: 11px; font-weight: 600; color: {_INK}; border: none;"
        )

        badge = QLabel(self._provenance_badge())
        badge.setStyleSheet(
            f"font-family: Consolas, 'Courier New', monospace; font-size: 11px; "
            f"color: {_INK_2}; background: {_PANEL}; "
            f"border: 1px solid {_CALLOUT_EDGE}; border-radius: 3px; padding: 3px 8px;"
        )

        layout.addWidget(lbl_asof)
        layout.addWidget(val_asof)
        layout.addStretch()
        layout.addWidget(badge)
        return frame

    def _build_series_label(self) -> QLabel:
        lbl = QLabel()
        lbl.setTextFormat(Qt.TextFormat.RichText)
        lbl.setText(self._series_label_html())
        lbl.setStyleSheet(f"color: {_INK}; font-size: 13px; padding: 2px 2px 4px;")
        lbl.setWordWrap(True)
        return lbl

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

        xs = [float(v.business_days) for v in self._curve.vertices]
        ys = [float(v.rate * 100) for v in self._curve.vertices]

        line = QLineSeries()
        pen = QPen(QColor(_INK))
        pen.setWidthF(1.5)
        line.setPen(pen)

        dots = QScatterSeries()
        dots.setColor(QColor(_INK))
        dots.setBorderColor(QColor(_INK))
        dots.setMarkerSize(6)

        for x, y in zip(xs, ys):
            line.append(x, y)
            dots.append(x, y)

        chart.addSeries(line)
        chart.addSeries(dots)

        x_axis = QValueAxis()
        x_axis.setTitleText("Business days")
        x_axis.setLabelFormat("%.0f")
        x_axis.setLabelsFont(QFont("Consolas", 8))
        x_axis.setTitleFont(QFont("Segoe UI", 9))
        x_axis.setRange(0, max(xs) * 1.02 if xs else 100)
        x_axis.setGridLineColor(QColor(_RULE_2))

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
        table = QTableWidget(len(rows), 3)
        table.setHorizontalHeaderLabels(["Tenor", "Settles on", "Rate a.a."])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(0, 80)
        table.setColumnWidth(2, 90)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setShowGrid(False)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        for r, (tenor, settle, rate) in enumerate(rows):
            t_item = QTableWidgetItem(tenor)
            t_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            s_item = QTableWidgetItem(settle)
            r_item = QTableWidgetItem(rate)
            r_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            table.setItem(r, 0, t_item)
            table.setItem(r, 1, s_item)
            table.setItem(r, 2, r_item)
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
