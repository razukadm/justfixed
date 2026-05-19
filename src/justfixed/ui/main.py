"""PySide6 main window for JustFixed — Milestone A′."""

from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import QDate, QLocale, QStandardPaths, QStringListModel, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QCompleter,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QStatusBar,
    QStyledItemDelegate,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from justfixed._build_info import BUILD_DATE, EXPIRY_DATE, VERSION, is_expired
from justfixed.domain.issuer import Issuer, IssuerKind, UNVERIFIED_CONGLOMERATE_PREFIX
from justfixed.domain.money import Money
from justfixed.domain.product import rules_for
from justfixed.domain.rates import (
    Prefixed,
    PostFixedCDI,
    PostFixedCDIPlusSpread,
    PostFixedIPCA,
    Rate,
    _format_brazilian_percent,
)
from justfixed.engine.curve import Curve
from justfixed.engine.fetcher import (
    CURVES_URL,
    FetchResult,
    fetch_curves,
    fetch_seed_data,
    parse_curve_payload,
)
from justfixed.engine.seed import load_seed_if_empty
from justfixed.engine.conglomerate_report import (
    ConglomerateDetailRow,
    ConglomerateSection,
    ConglomerateStatus,
    build_conglomerate_report,
    build_conglomerate_report_from_projections,
)
from justfixed.engine.fgc import ExposureStatus, fgc_concentration_report_from_projections
from justfixed.engine.projection import ProjectionResult, project
from justfixed.exports.calendar import export_maturity_calendar
from justfixed.importers.xp_loader import LoadResult, load_xp_statement
from justfixed.persistence.database import (
    Base,
    default_database_url,
    make_engine,
    make_session_factory,
)
from justfixed.persistence.repositories import (
    CurationMemoryRepository,
    InvestmentRepository,
    IssuerRepository,
)

# Hardcoded CDI assumption for milestone A′.
# Built 2026-05-08. Source: Selic at 14.50%/year per Copom decision
# 2026-04-29 (Banco Central / Agência Brasil); CDI typically Selic − 0.10
# p.p., giving ~14.40%. Verify and update at each rebuild until B10
# (real index data fetching) is implemented.
_ASSUMED_CDI = Decimal("0.144")

# Hardcoded IPCA assumption for milestone A′.
# Built 2026-05-08. Source: IPCA acumulado 12 meses March 2026 = 4.14%
# (IBGE, confirmed via investidor10.com.br). Verify and update at each
# rebuild until ROADMAP B10 (real index data fetching) is implemented.
_ASSUMED_IPCA = Decimal("0.0414")

_COL_ISSUER       = 0
_COL_CONGLOMERATE = 1
_COL_PRODUCT      = 2
_COL_TYPE         = 3
_COL_RATE         = 4
_COL_PRINCIPAL    = 5
_COL_MATURITY     = 6
_COL_CURRENT      = 7
_COL_PROJECTED    = 8
_COL_FGC          = 9
_NCOLS            = 10

_HEADERS = [
    "Issuer", "Conglomerate", "Product", "Type", "Rate",
    "Principal", "Maturity", "Current value", "Projected value", "FGC",
]

_PT_BR = QLocale(QLocale.Language.Portuguese, QLocale.Country.Brazil)

# Unified badge data for both ExposureStatus and ConglomerateStatus.
# Keyed by .value string — both enums share "under"/"approaching"/"over".
_BADGE_STYLE: dict[str, tuple[str, str]] = {
    "under":       ("● UNDER",       "#2ecc71"),
    "approaching": ("● APPROACHING", "#e67e22"),
    "over":        ("● OVER",        "#e74c3c"),
    "not_fgc":     ("N/A",           "#aaaaaa"),
}


def _make_fgc_badge(status, width: int) -> QLabel:
    """Return a styled FGC badge QLabel for either ExposureStatus or ConglomerateStatus."""
    text, color = _BADGE_STYLE[status.value]
    lbl = QLabel(text)
    lbl.setFixedWidth(width)
    lbl.setStyleSheet(f"color: {color};")
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return lbl

_HIGHLIGHT_COLOR = QColor("#FFF8DC")


def _format_type(rate: Rate) -> str:
    match rate:
        case Prefixed():               return "Pré"
        case PostFixedCDI():           return "Pós"
        case PostFixedCDIPlusSpread(): return "Pós+"
        case PostFixedIPCA():          return "IPCA+"
    return "?"


def _format_rate(rate: Rate, cdi_curve: Curve | None, maturity_date: date) -> str:
    if isinstance(rate, Prefixed):
        return _format_brazilian_percent(rate.annual_rate * 100)
    configured = rate.to_display()
    cdi = (
        cdi_curve.rate_at(maturity_date)
        if (cdi_curve is not None and cdi_curve.vertices)
        else _ASSUMED_CDI
    )
    match rate:
        case PostFixedCDI(cdi_percentage=p):
            effective = p * cdi
        case PostFixedCDIPlusSpread(spread=s):
            effective = cdi + s + (cdi * s)
        case PostFixedIPCA(spread=s):
            effective = _ASSUMED_IPCA + s + (_ASSUMED_IPCA * s)
        case _:
            return configured
    return f"{configured} ({_format_brazilian_percent(effective * 100)})"


# ── Utilities ─────────────────────────────────────────────────────────────────

def compute_totals(
    investments: list,
    cache: list[ProjectionResult] | None,
) -> dict:
    """Summarise visible investments and their projection data.

    Returns a dict with four keys:
      principal_total     — always a Money (sum of inv.principal).
      current_value_total — Money if all investments are in cache, else None.
      projected_total     — Money (gross_at_maturity) if all in cache, else None.
      row_count           — int, always len(investments).

    None semantics: "we have investments but the cache doesn't cover all of
    them." Zero investments with a cache present gives zero totals, not None
    (an empty sum is unambiguously zero, not unknown).
    """
    row_count = len(investments)
    principal_total = sum((inv.principal for inv in investments), Money.zero())

    if not investments:
        current_value_total = Money.zero() if cache is not None else None
        projected_total = Money.zero() if cache is not None else None
        return {
            "principal_total": principal_total,
            "current_value_total": current_value_total,
            "projected_total": projected_total,
            "row_count": row_count,
        }

    if not cache:
        return {
            "principal_total": principal_total,
            "current_value_total": None,
            "projected_total": None,
            "row_count": row_count,
        }

    proj_by_id = {p.investment.id: p for p in cache}
    current_values: list[Money] = []
    projected_values: list[Money] = []
    for inv in investments:
        proj = proj_by_id.get(inv.id)
        if proj is None:
            return {
                "principal_total": principal_total,
                "current_value_total": None,
                "projected_total": None,
                "row_count": row_count,
            }
        current_values.append(proj.current_value)
        projected_values.append(proj.gross_at_maturity)

    return {
        "principal_total": principal_total,
        "current_value_total": sum(current_values, Money.zero()),
        "projected_total": sum(projected_values, Money.zero()),
        "row_count": row_count,
    }


# ── Background workers ────────────────────────────────────────────────────────

class _ImportWorker(QThread):
    finished = Signal(object)  # LoadResult
    error    = Signal(str)

    def __init__(self, path: Path, session_factory) -> None:
        super().__init__()
        self._path = path
        self._factory = session_factory

    def run(self) -> None:
        try:
            self.finished.emit(load_xp_statement(self._path, self._factory))
        except Exception as exc:
            self.error.emit(str(exc))


class _ProjectWorker(QThread):
    finished = Signal(object)  # list[ProjectionResult]
    error    = Signal(str)

    def __init__(self, investments: list, *, cdi_curve: Curve | None = None) -> None:
        super().__init__()
        self._investments = investments
        self._cdi_curve = cdi_curve

    def run(self) -> None:
        try:
            today = date.today()
            results = [
                project(
                    inv,
                    as_of=today,
                    assumed_cdi=_ASSUMED_CDI,
                    assumed_ipca=_ASSUMED_IPCA,
                    cdi_curve=self._cdi_curve,
                )
                for inv in self._investments
            ]
            self.finished.emit(results)
        except Exception as exc:
            self.error.emit(str(exc))


# ── Delegate ──────────────────────────────────────────────────────────────────

class ConglomerateEditDelegate(QStyledItemDelegate):
    """Inline editor for the Conglomerate column (column 1).

    Double-click opens a QLineEdit with autocomplete from the union of
    verified in-use conglomerates and all curation memory entries. On
    commit, the new value is validated, written to the issuer and curation
    memory, then the table refreshes.
    """

    def __init__(self, main_window, session_factory) -> None:
        super().__init__()  # No Qt parent — MainWindow holds self._delegate
        self._main_window = main_window
        self._session_factory = session_factory

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)

        issuer_repo = IssuerRepository(self._session_factory)
        curation_repo = CurationMemoryRepository(self._session_factory)

        # Verified in-use conglomerate strings (no [unverified] prefix)
        verified = {
            i.conglomerate
            for i in issuer_repo.list_all()
            if not i.conglomerate.startswith(UNVERIFIED_CONGLOMERATE_PREFIX)
        }
        # All curation memory entries; curation wins on canonical case
        curation = curation_repo.list_all()

        seen_lower: dict[str, str] = {}
        for cong in verified:
            seen_lower[cong.lower()] = cong
        for cong in curation.values():
            seen_lower[cong.lower()] = cong

        completer_model = QStringListModel(sorted(seen_lower.values()), editor)
        completer = QCompleter(completer_model, editor)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        editor.setCompleter(completer)
        return editor

    def setEditorData(self, editor, index) -> None:
        editor.setText(index.data() or "")

    def setModelData(self, editor, model, index) -> None:
        text = editor.text().strip()

        if not text:
            QMessageBox.warning(
                self._main_window,
                "Invalid conglomerate",
                "Conglomerate cannot be empty. Please enter a value.",
            )
            return

        if len(text) > 100:
            QMessageBox.warning(
                self._main_window,
                "Invalid conglomerate",
                "Conglomerate too long. Please enter 100 characters or fewer.",
            )
            return

        if text.startswith(UNVERIFIED_CONGLOMERATE_PREFIX.rstrip()):
            QMessageBox.warning(
                self._main_window,
                "Invalid conglomerate",
                "The [unverified] prefix is reserved for system use. "
                "Please enter the conglomerate name without it.",
            )
            return

        visible = self._main_window.visible_investments()
        issuer = visible[index.row()].issuer

        old_string = issuer.conglomerate  # captured for session 2 signal emit
        issuer.conglomerate = text

        try:
            IssuerRepository(self._session_factory).save(issuer)
        except Exception:
            logging.exception("Failed to save issuer conglomerate")
            issuer.conglomerate = old_string
            self._main_window.statusBar().showMessage(
                "Failed to save issuer; conglomerate unchanged.", 4000
            )
            return

        try:
            CurationMemoryRepository(self._session_factory).set(
                Issuer.normalize_name(issuer.name), text
            )
        except Exception:
            logging.warning(
                "Curation memory write failed for %r; issuer save succeeded",
                issuer.name,
            )

        self._main_window.trigger_conglomerate_highlight(issuer.id)

    def updateEditorGeometry(self, editor, option, index) -> None:
        editor.setGeometry(option.rect)


# ── Main window ───────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("JustFixed")
        self.setMinimumSize(1100, 600)

        try:
            engine = make_engine(default_database_url())
            Base.metadata.create_all(engine)
            self._session_factory = make_session_factory(engine)
            self._repo = InvestmentRepository(self._session_factory)
        except Exception as exc:
            QMessageBox.critical(None, "Database error", str(exc))
            sys.exit(1)

        # Seed DB on first run (empty DB only; no-op on every subsequent launch).
        _seed_count = 0
        try:
            _seed_data = fetch_seed_data()
            _seed_count = load_seed_if_empty(IssuerRepository(self._session_factory), _seed_data)
            if _seed_count > 0:
                print(f"Seeded {_seed_count} issuers on first run.", file=sys.stderr)
        except Exception as exc:
            print(f"Seed load failed (continuing): {exc}", file=sys.stderr)

        # Loaded investments — only mutated by refresh_table(), never by
        # error handlers, so a failed import/project leaves the previous
        # list intact and _set_busy(False) re-enables buttons correctly.
        self._investments: list = []
        self._hide_matured: bool = True
        self._filter_issuer: str | None = None
        self._filter_conglomerate: str | None = None
        # projection_cache holds the most recent projection results. Kept as a
        # list to match the worker return type and from_projections overload
        # signatures. Invalidated on: import done, Clear DB. Not invalidated on
        # Hide matured toggle — _refresh_conglomerates filters the cached list
        # to the currently visible set on each render.
        self.projection_cache: list[ProjectionResult] | None = None
        self._cdi_curve: Curve | None = None
        self._pre_curve: Curve | None = None
        self._ipca_curve: Curve | None = None
        self._fetch_result: FetchResult | None = None
        self._curve_source: str = "unavailable"
        self._seed_loaded_count: int = _seed_count
        self._expanded_conglomerates: set[str] = set()
        self._cong_section_widgets: dict[str, tuple] = {}  # cname → (plus_label, detail_container)
        self._highlight_timer: QTimer | None = None  # keeps highlight timer alive for cancellation
        self._worker: QThread | None = None  # keeps worker alive during run

        self._build_ui()
        self.refresh_table()
        self._fetch_curve()
        if self._investments:
            self._on_project_clicked()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self._tabs = QTabWidget()
        self.setCentralWidget(self._tabs)
        self._conglomerates_tab = QWidget()
        _cong_outer = QVBoxLayout(self._conglomerates_tab)
        _cong_outer.setContentsMargins(8, 8, 8, 8)
        _cong_outer.setSpacing(6)
        self._cong_scroll = QScrollArea()
        self._cong_scroll.setWidgetResizable(True)
        self._cong_body = QWidget()
        self._cong_layout = QVBoxLayout(self._cong_body)
        self._cong_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._cong_scroll.setWidget(self._cong_body)
        _cong_outer.addWidget(self._cong_scroll)
        cong_bottom = QHBoxLayout()
        self._cong_project_btn = QPushButton("Project as of today")
        self._cong_project_btn.clicked.connect(self._on_project_clicked)
        cong_bottom.addStretch()
        cong_bottom.addWidget(self._cong_project_btn)
        _cong_outer.addLayout(cong_bottom)
        self._tabs.addTab(self._conglomerates_tab, "Conglomerates")
        central = QWidget()
        self._tabs.addTab(central, "Investments")
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # Top — import controls
        top = QHBoxLayout()
        self._import_btn = QPushButton("Import XP statement…")
        self._import_btn.clicked.connect(self._on_import_clicked)
        self._status_label = QLabel("Ready.")
        top.addWidget(self._import_btn)
        top.addWidget(self._status_label, stretch=1)
        root.addLayout(top)

        # Filter row — issuer and conglomerate dropdowns
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Conglomerate:"))
        self._conglomerate_combo = QComboBox()
        self._conglomerate_combo.addItem("All")
        self._conglomerate_combo.textActivated.connect(self._on_conglomerate_filter_changed)
        filter_row.addWidget(self._conglomerate_combo)
        filter_row.addSpacing(12)
        filter_row.addWidget(QLabel("Issuer:"))
        self._issuer_combo = QComboBox()
        self._issuer_combo.addItem("All")
        self._issuer_combo.textActivated.connect(self._on_issuer_filter_changed)
        filter_row.addWidget(self._issuer_combo)
        filter_row.addStretch()
        root.addLayout(filter_row)

        # Middle — table or empty-state label (swapped via QStackedWidget)
        self._stack = QStackedWidget()

        self._table = QTableWidget(0, _NCOLS)
        self._table.setHorizontalHeaderLabels(_HEADERS)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.verticalHeader().setVisible(False)
        hdr = self._table.horizontalHeader()
        _Stretch = QHeaderView.ResizeMode.Stretch
        _Fixed   = QHeaderView.ResizeMode.Fixed
        for col in (_COL_ISSUER, _COL_CONGLOMERATE, _COL_RATE):
            hdr.setSectionResizeMode(col, _Stretch)
        for col, px in ((_COL_PRODUCT, 80), (_COL_TYPE, 60), (_COL_FGC, 110)):
            hdr.setSectionResizeMode(col, _Fixed)
            self._table.setColumnWidth(col, px)
        self._delegate = ConglomerateEditDelegate(self, self._session_factory)
        self._table.setItemDelegateForColumn(_COL_CONGLOMERATE, self._delegate)
        self._table.cellDoubleClicked.connect(self._on_cell_double_clicked)

        self._empty_label = QLabel(
            "Import an XP statement to see your investments."
        )
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._stack.addWidget(self._table)        # index 0 — has data
        self._stack.addWidget(self._empty_label)  # index 1 — empty
        root.addWidget(self._stack, stretch=1)

        # Totals strip — principal, current, projected, row count
        totals_row = QHBoxLayout()
        self._principal_label = QLabel("Principal: —")
        self._current_label = QLabel("Current: —")
        self._projected_label = QLabel("Projected: —")
        self._rows_label = QLabel("Rows: 0")
        totals_row.addWidget(self._principal_label)
        totals_row.addSpacing(16)
        totals_row.addWidget(self._current_label)
        totals_row.addSpacing(16)
        totals_row.addWidget(self._projected_label)
        totals_row.addStretch()
        totals_row.addWidget(self._rows_label)
        root.addLayout(totals_row)

        # Bottom — action buttons
        bottom = QHBoxLayout()
        self._project_btn = QPushButton("Project as of today")
        self._project_btn.clicked.connect(self._on_project_clicked)
        self._export_btn = QPushButton("Export calendar…")
        self._export_btn.clicked.connect(self._on_export_clicked)
        bottom.addStretch()
        bottom.addWidget(self._project_btn)
        bottom.addWidget(self._export_btn)
        root.addLayout(bottom)

        status_bar = QStatusBar()
        self._curve_label = QLabel("")
        status_bar.addPermanentWidget(self._curve_label)
        self._ts_label = QLabel("")
        status_bar.addPermanentWidget(self._ts_label)
        self.setStatusBar(status_bar)

        # Menu bar — File (Clear DB when JUSTFIXED_DEV set) + View
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("File")
        if os.environ.get("JUSTFIXED_DEV"):
            clear_db_action = QAction("Clear Database…", self)
            clear_db_action.triggered.connect(self._on_clear_db_clicked)
            file_menu.addAction(clear_db_action)
            self._dev_tab = self._build_dev_tab()
            self._tabs.addTab(self._dev_tab, "Dev")
        view_menu = menu_bar.addMenu("View")
        self._hide_matured_action = QAction("Hide matured investments", self)
        self._hide_matured_action.setCheckable(True)
        self._hide_matured_action.setChecked(True)
        self._hide_matured_action.triggered.connect(self._on_hide_matured_toggled)
        view_menu.addAction(self._hide_matured_action)
        help_menu = menu_bar.addMenu("Help")
        about_action = QAction("About JustFixed", self)
        about_action.triggered.connect(self._on_about_clicked)
        help_menu.addAction(about_action)

    def _make_summary_row(
        self, section: ConglomerateSection, index: int = 0
    ) -> tuple[QWidget, QLabel]:
        row_widget = QWidget()
        bg = "#ffffff" if index % 2 == 0 else "#f5f5f5"
        row_widget.setObjectName(f"congRow{index}")
        row_widget.setStyleSheet(
            f"#congRow{index} {{ background-color: {bg}; border-bottom: 1px solid #dddddd; }}"
        )
        h = QHBoxLayout(row_widget)
        h.setContentsMargins(8, 6, 8, 6)

        plus = QLabel("+")
        plus.setFixedWidth(20)
        h.addWidget(plus)

        name = QLabel(section.conglomerate_name)
        h.addWidget(name, stretch=1)

        d = section.next_maturity
        next_lbl = QLabel(
            _PT_BR.toString(QDate(d.year, d.month, d.day), QLocale.FormatType.ShortFormat)
        )
        next_lbl.setFixedWidth(120)
        h.addWidget(next_lbl)

        principal_lbl = QLabel(section.total_principal.to_display())
        principal_lbl.setFixedWidth(120)
        h.addWidget(principal_lbl)

        current_lbl = QLabel(section.total_current_value.to_display())
        current_lbl.setFixedWidth(120)
        h.addWidget(current_lbl)

        projected_lbl = QLabel(section.total_projected_value.to_display())
        projected_lbl.setFixedWidth(120)
        h.addWidget(projected_lbl)

        h.addWidget(_make_fgc_badge(section.summary_fgc_status, 130))

        return row_widget, plus

    def _make_section_widget(self, section: ConglomerateSection, idx: int) -> QWidget:
        expanded = section.conglomerate_name in self._expanded_conglomerates
        wrapper = QWidget()
        vbox = QVBoxLayout(wrapper)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        summary_row, plus_label = self._make_summary_row(section, idx)
        plus_label.setText("−" if expanded else "+")

        detail = self._make_detail_container(section)
        detail.setVisible(expanded)

        cname = section.conglomerate_name
        summary_row.setCursor(Qt.CursorShape.PointingHandCursor)
        summary_row.mousePressEvent = lambda event, n=cname: self._toggle_section(n)

        vbox.addWidget(summary_row)
        vbox.addWidget(detail)

        self._cong_section_widgets[cname] = (plus_label, detail)
        return wrapper

    def _toggle_section(self, cname: str) -> None:
        if cname not in self._cong_section_widgets:
            return
        plus_label, detail_container = self._cong_section_widgets[cname]
        if cname in self._expanded_conglomerates:
            self._expanded_conglomerates.discard(cname)
            detail_container.setVisible(False)
            plus_label.setText("+")
        else:
            self._expanded_conglomerates.add(cname)
            detail_container.setVisible(True)
            plus_label.setText("−")

    def _make_detail_container(self, section: ConglomerateSection) -> QWidget:
        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(20, 0, 0, 0)
        vbox.setSpacing(0)
        vbox.addWidget(self._make_detail_header())
        for idx, row in enumerate(section.rows):
            vbox.addWidget(self._make_detail_row(row, idx))
        return container

    def _make_detail_header(self) -> QWidget:
        w = QWidget()
        w.setObjectName("detailHeader")
        w.setStyleSheet(
            "#detailHeader { background-color: #f0f0f0; border-bottom: 1px solid #dddddd; }"
            " QLabel { font-weight: bold; }"
        )
        h = QHBoxLayout(w)
        h.setContentsMargins(8, 4, 8, 4)
        for text, width, stretch in [
            ("Maturity",            100, 0),
            ("Issuer",                0, 1),
            ("Product",             100, 0),
            ("Principal",           110, 0),
            ("Current value",       110, 0),
            ("Projected value",     110, 0),
            ("Projected Balance",   120, 0),
            ("FGC",                 110, 0),
        ]:
            lbl = QLabel(text)
            if width:
                lbl.setFixedWidth(width)
            h.addWidget(lbl, stretch=stretch)
        return w

    def _make_detail_row(self, row: ConglomerateDetailRow, idx: int) -> QWidget:
        w = QWidget()
        bg = "#fafafa" if idx % 2 == 0 else "#f0f0f0"
        w.setObjectName(f"detailRow{idx}")
        w.setStyleSheet(
            f"#detailRow{idx} {{ background-color: {bg}; border-bottom: 1px solid #eeeeee; }}"
        )
        h = QHBoxLayout(w)
        h.setContentsMargins(8, 4, 8, 4)

        d = row.maturity_date
        mat_lbl = QLabel(
            _PT_BR.toString(QDate(d.year, d.month, d.day), QLocale.FormatType.ShortFormat)
        )
        mat_lbl.setFixedWidth(100)
        h.addWidget(mat_lbl)

        issuer_lbl = QLabel(row.issuer_name)
        h.addWidget(issuer_lbl, stretch=1)

        product_lbl = QLabel(rules_for(row.product).display_name)
        product_lbl.setFixedWidth(100)
        h.addWidget(product_lbl)

        for val, width in [
            (row.principal.to_display(),        110),
            (row.current_value.to_display(),     110),
            (row.projected_value.to_display(),   110),
            (row.projected_balance.to_display(), 120),
        ]:
            lbl = QLabel(val)
            lbl.setFixedWidth(width)
            h.addWidget(lbl)

        h.addWidget(_make_fgc_badge(row.fgc_status, 110))

        return w

    def _clear_cong_layout(self) -> None:
        while self._cong_layout.count():
            item = self._cong_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _make_summary_header(self) -> QWidget:
        row_widget = QWidget()
        row_widget.setObjectName("congHeader")
        row_widget.setStyleSheet(
            "#congHeader { background-color: #eaeaea; border-bottom: 1px solid #dddddd; }"
            " QLabel { font-weight: bold; }"
        )
        h = QHBoxLayout(row_widget)
        h.setContentsMargins(8, 6, 8, 6)

        spacer = QLabel()
        spacer.setFixedWidth(20)
        h.addWidget(spacer)

        h.addWidget(QLabel("Conglomerate"), stretch=1)

        for text, width in [
            ("Next maturity",   120),
            ("Principal",       120),
            ("Current value",   120),
            ("Projected value", 120),
            ("FGC",             130),
        ]:
            lbl = QLabel(text)
            lbl.setFixedWidth(width)
            h.addWidget(lbl)

        return row_widget

    def _refresh_conglomerates(self) -> None:
        self._clear_cong_layout()
        self._cong_section_widgets = {}
        if self.projection_cache is None:
            placeholder = QLabel('Press "Project as of today" to populate.')
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._cong_layout.addWidget(placeholder)
            return
        visible_ids = {inv.id for inv in self.visible_investments(apply_filter=False)}
        projections = [p for p in self.projection_cache if p.investment.id in visible_ids]
        if not projections:
            empty = QLabel("No investments to display.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._cong_layout.addWidget(empty)
            return
        report = build_conglomerate_report_from_projections(projections, as_of=date.today())
        self._cong_layout.addWidget(self._make_summary_header())
        for idx, section in enumerate(report.sections):
            self._cong_layout.addWidget(self._make_section_widget(section, idx))

    def _on_about_clicked(self) -> None:
        QMessageBox.about(
            self,
            "About JustFixed",
            f"Version: {VERSION}\n"
            f"Build date: {BUILD_DATE:%Y-%m-%d}\n"
            f"Expires: {EXPIRY_DATE:%Y-%m-%d}",
        )

    # ── Busy state ────────────────────────────────────────────────────────────

    def _set_busy(self, busy: bool) -> None:
        """Disable all action buttons while any background worker is running.

        Prevents overlapping operations that would corrupt table state.
        On un-busy, delegates project/export enable state to
        _update_button_states() so data-driven rules (needs investments,
        needs a future maturity) are re-evaluated against the current list.
        """
        self._import_btn.setEnabled(not busy)
        if busy:
            self._project_btn.setEnabled(False)
            self._cong_project_btn.setEnabled(False)
            self._export_btn.setEnabled(False)
        else:
            self._update_button_states()

    # ── Table ─────────────────────────────────────────────────────────────────

    def refresh_table(self, highlight_issuer_id: uuid.UUID | None = None) -> None:
        """Reload all investments from DB and repopulate the table."""
        self._investments = self._repo.list_all()
        self._populate_filter_dropdowns()
        visible = self.visible_investments()
        scroll_y = self._table.verticalScrollBar().value()
        self._table.setRowCount(len(visible))

        projection_map: dict[uuid.UUID, ProjectionResult] = {}
        status_by_investment: dict[uuid.UUID, ExposureStatus] = {}
        if self.projection_cache is not None:
            fgc_report = fgc_concentration_report_from_projections(self.projection_cache)
            projection_map = {p.investment.id: p for p in self.projection_cache}
            status_by_investment = {
                inv_exposure.investment_id: c.current_status
                for c in fgc_report.conglomerates
                for inv_exposure in c.investments
            }

        for row, inv in enumerate(visible):
            proj = projection_map.get(inv.id)
            self._populate_row(
                row, inv,
                current_value=proj.current_value if proj else None,
                projected_value=proj.gross_at_maturity if proj else None,
                fgc_status=status_by_investment.get(inv.id),
                highlight=(inv.issuer.id == highlight_issuer_id),
            )
        # setValue clamps to the scrollbar's valid range, so scroll_y past the
        # new content end (e.g. after Clear DB or Hide-matured toggle) is safe.
        self._table.verticalScrollBar().setValue(scroll_y)
        self._stack.setCurrentIndex(0 if self._investments else 1)
        self._update_button_states()
        self._update_totals()
        self._refresh_conglomerates()

    def _update_totals(self) -> None:
        visible = self.visible_investments()
        totals = compute_totals(visible, self.projection_cache)

        principal = totals["principal_total"].to_display()
        current = (
            totals["current_value_total"].to_display()
            if totals["current_value_total"] is not None else "—"
        )
        projected = (
            totals["projected_total"].to_display()
            if totals["projected_total"] is not None else "—"
        )

        self._principal_label.setText(f"Principal: {principal}")
        self._current_label.setText(f"Current: {current}")
        self._projected_label.setText(f"Projected: {projected}")

        filtered_count = len(visible)
        filter_active = (
            self._filter_issuer is not None or self._filter_conglomerate is not None
        )
        if filter_active:
            unfiltered_count = len(self.visible_investments(apply_filter=False))
            self._rows_label.setText(f"Rows: {filtered_count} of {unfiltered_count}")
        else:
            self._rows_label.setText(f"Rows: {filtered_count}")

    def _populate_filter_dropdowns(self) -> None:
        issuer_names = sorted({i.issuer.name for i in self._investments})
        conglomerate_names = sorted({i.issuer.conglomerate for i in self._investments})
        for combo, names, current in (
            (self._issuer_combo, issuer_names, self._filter_issuer),
            (self._conglomerate_combo, conglomerate_names, self._filter_conglomerate),
        ):
            combo.clear()
            combo.addItem("All")
            for name in names:
                combo.addItem(name)
            if current is not None and combo.findText(current) != -1:
                combo.setCurrentText(current)

    def _on_issuer_filter_changed(self, text: str) -> None:
        self._filter_issuer = None if text == "All" else text
        self.refresh_table()

    def _on_conglomerate_filter_changed(self, text: str) -> None:
        self._filter_conglomerate = None if text == "All" else text
        self.refresh_table()

    def visible_investments(self, *, apply_filter: bool = True) -> list:
        result = self._investments
        if apply_filter:
            if self._filter_issuer is not None:
                result = [i for i in result if i.issuer.name == self._filter_issuer]
            if self._filter_conglomerate is not None:
                result = [i for i in result if i.issuer.conglomerate == self._filter_conglomerate]
        if self._hide_matured:
            today = date.today()
            result = [i for i in result if i.maturity_date > today]
        return sorted(result, key=lambda i: i.maturity_date)

    def _populate_row(
        self,
        row: int,
        inv,
        *,
        current_value: Money | None,
        projected_value: Money | None,
        fgc_status: ExposureStatus | None,
        highlight: bool = False,
    ) -> None:
        self._cell(row, _COL_ISSUER, inv.issuer.name)

        # Conglomerate — gray italic when [unverified]
        cong = inv.issuer.conglomerate
        cong_item = QTableWidgetItem(cong)
        if cong.startswith(UNVERIFIED_CONGLOMERATE_PREFIX):
            font = cong_item.font()
            font.setItalic(True)
            cong_item.setFont(font)
            cong_item.setForeground(QColor("#888888"))
        self._table.setItem(row, _COL_CONGLOMERATE, cong_item)

        self._cell(row, _COL_PRODUCT, rules_for(inv.product).display_name)
        self._cell(row, _COL_TYPE, _format_type(inv.rate))
        self._cell(row, _COL_RATE, _format_rate(inv.rate, self._cdi_curve, inv.maturity_date))
        self._cell(row, _COL_PRINCIPAL, inv.principal.to_display())

        d = inv.maturity_date
        self._cell(
            row, _COL_MATURITY,
            _PT_BR.toString(QDate(d.year, d.month, d.day), QLocale.FormatType.ShortFormat),
        )

        self._cell(row, _COL_CURRENT, current_value.to_display() if current_value else "")
        self._cell(row, _COL_PROJECTED, projected_value.to_display() if projected_value else "")

        # FGC badge
        if inv.issuer.kind == IssuerKind.TREASURY:
            badge = QTableWidgetItem("N/A — Tesouro")
            badge.setForeground(QColor("#aaaaaa"))
        elif fgc_status is None:
            badge = QTableWidgetItem("—")
        else:
            label, color = _BADGE_STYLE[fgc_status.value]
            badge = QTableWidgetItem(label)
            badge.setForeground(QColor(color))
        badge.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._table.setItem(row, _COL_FGC, badge)

        if highlight:
            for col in range(_NCOLS):
                item = self._table.item(row, col)
                if item is not None:
                    item.setBackground(_HIGHLIGHT_COLOR)

    def _cell(self, row: int, col: int, text: str) -> None:
        self._table.setItem(row, col, QTableWidgetItem(text))

    def _update_button_states(self) -> None:
        today = date.today()
        self._project_btn.setEnabled(bool(self._investments))
        self._cong_project_btn.setEnabled(bool(self._investments))
        self._export_btn.setEnabled(
            any(inv.maturity_date >= today for inv in self._investments)
        )

    def trigger_conglomerate_highlight(self, issuer_id: uuid.UUID) -> None:
        """Highlight all rows for issuer_id for 3 seconds, then snap back.

        Cancels any in-flight highlight before starting a new one. If the
        prior timer's queued callback fires after cancellation (race window
        measured in microseconds), the worst outcome is a spurious clear-
        refresh — safe but visible. Fix if ever observed: disconnect before
        stop.
        """
        if self._highlight_timer is not None:
            self._highlight_timer.stop()
        self.refresh_table(highlight_issuer_id=issuer_id)
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(3000)
        timer.timeout.connect(lambda: self.refresh_table(highlight_issuer_id=None))
        timer.start()
        self._highlight_timer = timer

    def _on_hide_matured_toggled(self, checked: bool) -> None:
        self._hide_matured = checked
        self.refresh_table()

    def _on_clear_db_clicked(self) -> None:
        count = len(self._investments)
        if count == 0:
            self.statusBar().showMessage("Database is already empty.", 6000)
            return
        reply = QMessageBox.question(
            self,
            "Clear Database",
            f"Clear all {count} investments from the database? "
            "This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        deleted_investments, _ = self._repo.delete_all()
        self.projection_cache = None
        self._expanded_conglomerates.clear()
        self._ts_label.setText("")
        self.refresh_table()
        self._status_label.setText("Ready.")
        self.statusBar().showMessage(f"Cleared {deleted_investments} investments.")

    def _on_cell_double_clicked(self, row: int, column: int) -> None:
        if column == _COL_CONGLOMERATE:
            self._table.editItem(self._table.item(row, column))

    # ── Import ────────────────────────────────────────────────────────────────

    def _on_import_clicked(self) -> None:
        dirs = QStandardPaths.standardLocations(
            QStandardPaths.StandardLocation.DownloadLocation
        )
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Import XP statement",
            dirs[0] if dirs else "",
            "Excel files (*.xlsx)",
        )
        if not path_str:
            return

        self._set_busy(True)
        self._status_label.setText(f"Loading {Path(path_str).name}…")

        self._worker = _ImportWorker(Path(path_str), self._session_factory)
        self._worker.finished.connect(self._on_import_done)
        self._worker.error.connect(self._on_import_error)
        self._worker.start()

    def _on_import_done(self, result: LoadResult) -> None:
        self._set_busy(False)
        self._status_label.setText(
            f"Loaded {result.inserted + result.skipped} investments "
            f"({result.inserted} new, {result.skipped} unchanged)."
        )
        self.projection_cache = None
        self._expanded_conglomerates.clear()
        self._ts_label.setText("")
        self.refresh_table()

    def _on_import_error(self, message: str) -> None:
        # _investments unchanged — failed import did not reach refresh_table().
        self._set_busy(False)
        self._status_label.setText("Ready.")
        QMessageBox.critical(self, "Import failed", message)

    # ── Project ───────────────────────────────────────────────────────────────

    def _fetch_curve(self) -> None:
        self._fetch_result = fetch_curves()
        self._cdi_curve = self._fetch_result.curve
        self._pre_curve = self._fetch_result.pre
        self._ipca_curve = self._fetch_result.ipca_real
        self._curve_source = self._fetch_result.source
        self._update_curve_label(self._curve_source, self._cdi_curve)
        if hasattr(self, "_dev_cdi_label"):
            self._refresh_dev_tab_curves()

    def _update_curve_label(self, source: str, curve: Curve | None) -> None:
        if curve and curve.vertices:
            self._curve_label.setText(f"Curve: {source} ({curve.anchor:%Y-%m-%d})")
        elif source == "unavailable":
            self._curve_label.setText("Curve: unavailable")
        else:
            self._curve_label.setText(f"Curve: {source} (no data)")

    def _refresh_dev_tab_curves(self) -> None:
        fetch_source = self._fetch_result.source if self._fetch_result else "unavailable"
        fetch_time = self._fetch_result.source_time if self._fetch_result else None

        def _summary(curve: Curve | None, source: str) -> str:
            if not curve or not curve.vertices:
                return f"source: {source}  ·  no data"
            first = curve.vertices[0]
            last = curve.vertices[-1]
            line1 = (
                f"source: {source}  ·  anchor: {curve.anchor:%Y-%m-%d}  ·  "
                f"{len(curve.vertices)} vertices"
            )
            if fetch_time and source != "manual":
                line1 += f"  ·  fetched {fetch_time:%H:%M:%S}"
            line2 = (
                f"first: {first.business_days}bd @ {first.rate:.4%}  ·  "
                f"last: {last.business_days}bd @ {last.rate:.4%}"
            )
            return f"{line1}\n{line2}"

        self._dev_cdi_label.setText(_summary(self._cdi_curve, self._curve_source))
        self._dev_pre_label.setText(_summary(self._pre_curve, fetch_source))
        self._dev_ipca_label.setText(_summary(self._ipca_curve, fetch_source))

    def _build_dev_tab(self) -> QWidget:
        tab = QWidget()
        root = QVBoxLayout(tab)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(6)
        root.setAlignment(Qt.AlignmentFlag.AlignTop)

        bold = QFont()
        bold.setBold(True)

        def _title(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setFont(bold)
            return lbl

        def _sep() -> QFrame:
            f = QFrame()
            f.setFrameShape(QFrame.Shape.HLine)
            f.setFrameShadow(QFrame.Shadow.Sunken)
            return f

        # --- Curves ---
        root.addWidget(_title("Active curves"))
        root.addWidget(QLabel(f"Source URL: {CURVES_URL}"))
        root.addSpacing(4)

        for attr, label_text in (
            ("_dev_cdi_label", "CDI (B3 DI1 futures):"),
            ("_dev_pre_label", "PRE (ANBIMA ETTJ):"),
            ("_dev_ipca_label", "IPCA real (ANBIMA ETTJ):"),
        ):
            root.addWidget(QLabel(label_text))
            lbl = QLabel("  loading…")
            root.addWidget(lbl)
            setattr(self, attr, lbl)

        root.addWidget(_sep())

        # --- Seed ---
        root.addWidget(_title("Seed status"))
        if self._seed_loaded_count > 0:
            seed_text = f"Loaded this session: yes ({self._seed_loaded_count} issuers)"
        else:
            seed_text = "Loaded this session: no"
        root.addWidget(QLabel(seed_text))

        root.addWidget(_sep())

        # --- Admin tools ---
        root.addWidget(_title("Admin tools"))
        root.addWidget(QLabel("Data repo: https://github.com/razukadm/justfixed-data"))
        root.addWidget(QLabel("Publish script: tools/publish_curves.py"))
        root.addWidget(QLabel("Docs: docs/BUILD.md"))
        root.addSpacing(4)

        load_btn = QPushButton("Load curve from file…")
        load_btn.clicked.connect(self._on_load_curve_from_file_clicked)
        root.addWidget(load_btn)

        root.addStretch()
        return tab

    def _on_load_curve_from_file_clicked(self) -> None:
        dirs = QStandardPaths.standardLocations(
            QStandardPaths.StandardLocation.DownloadLocation
        )
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Load curve from file",
            dirs[0] if dirs else "",
            "JSON files (*.json)",
        )
        if not path_str:
            return
        try:
            data = json.loads(Path(path_str).read_text(encoding="utf-8"))
            loaded_curve = parse_curve_payload(data)
            if loaded_curve is None or not loaded_curve.vertices:
                QMessageBox.warning(
                    self, "Load curve",
                    f"{Path(path_str).name}: no CDI curve data found in file.",
                )
                return
        except Exception as exc:
            QMessageBox.warning(
                self, "Load curve",
                f"Failed to parse {Path(path_str).name}:\n{exc}",
            )
            return

        self._cdi_curve = loaded_curve
        self._curve_source = "manual"
        self._update_curve_label("manual", loaded_curve)
        if hasattr(self, "_dev_cdi_label"):
            self._refresh_dev_tab_curves()
        self._on_project_clicked()

    def _on_project_clicked(self) -> None:
        self._set_busy(True)

        self._worker = _ProjectWorker(
            self.visible_investments(apply_filter=False),
            cdi_curve=self._cdi_curve,
        )
        self._worker.finished.connect(self._on_project_done)
        self._worker.error.connect(self._on_project_error)
        self._worker.start()

    def _on_project_done(self, results: list) -> None:
        self._set_busy(False)
        self._ts_label.setText(f"Projected: {datetime.now():%Y-%m-%d %H:%M}")
        self.statusBar().showMessage(
            f"Projected {len(results)} investments as of {date.today():%d/%m/%Y}.", 6000
        )
        self.projection_cache = results
        self.refresh_table()

    def _on_project_error(self, message: str) -> None:
        self._set_busy(False)
        QMessageBox.critical(self, "Projection failed", message)

    # ── Calendar export ───────────────────────────────────────────────────────

    def _on_export_clicked(self) -> None:
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Export maturity calendar",
            "justfixed-maturities.ics",
            "iCalendar files (*.ics)",
        )
        if not path_str:
            return
        try:
            ics = export_maturity_calendar(
                self.visible_investments(), as_of=date.today(), assumed_cdi=_ASSUMED_CDI, assumed_ipca=_ASSUMED_IPCA
            )
            Path(path_str).write_bytes(ics)
            self.statusBar().showMessage(f"Calendar exported to {path_str}.", 8000)
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    app = QApplication(sys.argv)
    if is_expired():
        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("JustFixed")
        box.setText(
            f"This version (v{VERSION}) expired on {EXPIRY_DATE.isoformat()}.\n\n"
            "Please contact the developer for an updated version."
        )
        box.exec()
        sys.exit(1)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
