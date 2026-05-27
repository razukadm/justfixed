"""PySide6 main window for JustFixed — Milestone A′."""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import sys
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from PySide6.QtCore import QDate, QEvent, QLocale, QStandardPaths, QStringListModel, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDateEdit,
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
    QSplitter,
    QStackedLayout,
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
from justfixed.ui.qss import make_stylesheet
from justfixed.ui.theme import COLORS, FONTS
from justfixed.ui.curve_inspector import (
    CurveInspectorWindow,
    SERIES_CDI,
    SERIES_IPCA,
    SERIES_PRE,
)
from justfixed.domain.issuer import Issuer, IssuerKind, UNVERIFIED_CONGLOMERATE_PREFIX
from justfixed.domain.investment import Investment, InvestmentSource
from justfixed.domain.money import Money
from justfixed.domain.product import CouponFrequency, ProductType, rules_for
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
from justfixed.importers.detection import Broker, load_statement
from justfixed.importers.xp_mapper import parse_brazilian_money
from justfixed.importers.xp_loader import LoadResult
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
    "Principal", "Maturity", "Current", "Projected", "FGC",
]

_PT_BR = QLocale(QLocale.Language.Portuguese, QLocale.Country.Brazil)

# Unified badge data for both ExposureStatus and ConglomerateStatus.
# Keyed by .value string — both enums share "under"/"approaching"/"over".
_BADGE_STYLE: dict[str, tuple[str, str]] = {
    "under":       ("● UNDER",       COLORS.FGC_UNDER),
    "approaching": ("● APPROACHING", COLORS.WARN),
    "over":        ("● OVER",        COLORS.FGC_OVER),
    "not_fgc":     ("N/A",           COLORS.FGC_NA),
}


def _make_fgc_badge(status, width: int) -> QLabel:
    """Return a styled FGC badge QLabel for either ExposureStatus or ConglomerateStatus."""
    text, _ = _BADGE_STYLE[status.value]
    lbl = QLabel(text)
    lbl.setFixedWidth(width)
    lbl.setProperty("fgcStatus", status.value)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return lbl

_HIGHLIGHT_COLOR = QColor(COLORS.HIGHLIGHT_ROW)
_MONO_FONT = QFont(FONTS.MONO_FAMILY, FONTS.MONO_SIZE)
_MATURED_COLOR = QColor(COLORS.INK_3)   # whole-row demote + PAID text color


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

def _is_matured(inv) -> bool:
    """True when investment.maturity_date <= today (maturity-day = already paid)."""
    return inv.maturity_date <= date.today()


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
    finished = Signal(object)  # tuple[Broker, LoadResult]
    error    = Signal(str)

    def __init__(self, path: Path, session_factory) -> None:
        super().__init__()
        self._path = path
        self._factory = session_factory

    def run(self) -> None:
        try:
            self.finished.emit(load_statement(self._path, self._factory))
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


# ── Editable field widget ─────────────────────────────────────────────────────

class _EditableField(QWidget):
    """A field showing a QLabel in view mode, swapping to an editor on double-click.

    Editability is controlled per-investment via set_value(editable=...).
    On commit (Enter or focus-loss from the editor), calls save_fn(key, typed_value).
    save_fn returns the new formatted string on success, raises on failure.
    error_fn(message) is called with a string on failure or None to clear the error.
    """

    _DATE_KEYS = frozenset({"purchase_date", "issue_date", "maturity_date"})
    _COMBO_KEYS = frozenset({"coupon_frequency"})
    _RATE_KEYS = frozenset({"rate"})

    def __init__(self, key: str, save_fn, error_fn, parent=None) -> None:
        super().__init__(parent)
        self._key = key
        self._save_fn = save_fn
        self._error_fn = error_fn
        self._editable = False
        self._raw_value = None
        self._committing = False

        self._stack = QStackedLayout(self)

        self._label = QLabel()
        self._label.setWordWrap(True)
        self._label.installEventFilter(self)
        self._stack.addWidget(self._label)   # index 0: view mode

        self._editor: QWidget | None = None  # added at index 1 on first use

    # ── Public API ────────────────────────────────────────────────────────────

    def text(self) -> str:
        """Return the label text (compatible with QLabel.text() call sites)."""
        return self._label.text()

    def set_value(self, raw_value, formatted: str, *, editable: bool) -> None:
        """Set displayed value and editability. Always reverts to view mode."""
        self._raw_value = raw_value
        self._editable = editable
        self._label.setText(formatted)
        self._show_label()

    def revert_to_view(self) -> None:
        """Discard any in-progress edit silently and return to label mode."""
        self._show_label()

    def set_display_font(self, font: QFont) -> None:
        self._label.setFont(font)

    # ── Event filter ──────────────────────────────────────────────────────────

    def eventFilter(self, obj, event) -> bool:
        if (
            obj is self._label
            and self._editable
            and event.type() == QEvent.Type.MouseButtonDblClick
        ):
            self._show_editor()
            return True
        return False

    # ── Mode switching ────────────────────────────────────────────────────────

    def _show_label(self) -> None:
        self._stack.setCurrentIndex(0)

    def _show_editor(self) -> None:
        if self._editor is None:
            self._editor = self._build_editor()
            self._stack.addWidget(self._editor)  # index 1
        self._seed_editor()
        self._stack.setCurrentIndex(1)
        self._editor.setFocus()

    # ── Editor construction ───────────────────────────────────────────────────

    def _build_editor(self) -> QWidget:
        if self._key in self._DATE_KEYS:
            editor = QDateEdit()
            editor.setDisplayFormat("dd/MM/yyyy")
            editor.editingFinished.connect(self._commit)
            return editor
        if self._key in self._COMBO_KEYS:
            editor = QComboBox()
            for cf in CouponFrequency:
                editor.addItem(cf.to_display(), cf)
            editor.activated.connect(lambda _idx: self._commit())
            return editor
        if self._key in self._RATE_KEYS:
            editor = _RateEditor()
            editor.commit_requested.connect(self._commit)
            return editor
        editor = QLineEdit()
        editor.editingFinished.connect(self._commit)
        return editor

    def _seed_editor(self) -> None:
        if self._key in self._DATE_KEYS:
            d = self._raw_value
            self._editor.setDate(QDate(d.year, d.month, d.day))
        elif self._key in self._COMBO_KEYS:
            idx = self._editor.findData(self._raw_value)
            if idx >= 0:
                self._editor.setCurrentIndex(idx)
        elif self._key in self._RATE_KEYS:
            self._editor.set_rate(self._raw_value)
        elif self._key == "principal":
            self._editor.setText(
                self._raw_value.to_display() if self._raw_value is not None else ""
            )
        else:
            self._editor.setText(self._raw_value or "")

    # ── Commit ────────────────────────────────────────────────────────────────

    def _commit(self) -> None:
        if self._committing:
            return
        self._committing = True
        try:
            self._do_commit()
        finally:
            self._committing = False

    def _do_commit(self) -> None:
        try:
            typed = self._extract_value()
        except ValueError as exc:
            self._error_fn(str(exc))
            return

        try:
            formatted = self._save_fn(self._key, typed)
        except Exception as exc:
            self._error_fn(str(exc))
            return

        self._raw_value = typed
        self._label.setText(formatted)
        self._error_fn(None)
        self._show_label()

    def _extract_value(self):
        if self._key in self._DATE_KEYS:
            qd = self._editor.date()
            return date(qd.year(), qd.month(), qd.day())
        if self._key in self._COMBO_KEYS:
            return self._editor.currentData()
        if self._key in self._RATE_KEYS:
            return self._editor.get_rate()
        if self._key == "principal":
            return parse_brazilian_money(self._editor.text().strip())
        return self._editor.text()


# ── Rate editor helpers ───────────────────────────────────────────────────────

def _pct_to_display(value: Decimal) -> str:
    """Format a Decimal percentage for the rate editor line edit (no % suffix)."""
    return _format_brazilian_percent(value).rstrip("%")


def _parse_rate_percent(text: str) -> Decimal:
    """Parse a rate percentage from user input. Strict Brazilian format: comma
    as decimal separator, no period allowed (percentages carry no thousands
    separator in this UI). Strips trailing '%'. Raises ValueError on any
    period or unparseable input.
    """
    s = text.strip().rstrip("%").strip()
    if "." in s:
        raise ValueError(
            f"Use vírgula como separador decimal (ex: 112,50), não ponto: {text!r}"
        )
    s = s.replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        raise ValueError(f"Valor inválido: {text!r}")


_RATE_TYPE_ENTRIES = [
    # (combo label, data key, suffix label)
    ("% do CDI",  "cdi_pct",   "% do CDI"),
    ("CDI +",     "cdi_plus",  "% a.a."),
    ("IPCA +",    "ipca_plus", "% a.a."),
    ("Prefixado", "prefixed",  "% a.a."),
]


class _RateEditor(QWidget):
    """Composite editor for a Rate: type combo + numeric line edit + suffix label.

    Public API:
      set_rate(rate)  — seed from an existing Rate object
      get_rate()      — parse and return a Rate; raises ValueError on bad input
      commit_requested — Signal fired when Enter is pressed in the line edit
    """

    commit_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)

        self._combo = QComboBox()
        for label, key, _suffix in _RATE_TYPE_ENTRIES:
            self._combo.addItem(label, key)
        self._combo.currentIndexChanged.connect(self._on_type_changed)

        self._line = QLineEdit()
        self._line.setFixedWidth(80)
        self._line.editingFinished.connect(self.commit_requested)

        self._suffix_lbl = QLabel()

        row.addWidget(self._combo)
        row.addWidget(self._line)
        row.addWidget(self._suffix_lbl)
        row.addStretch()

        self._update_suffix()

    # ── Public ────────────────────────────────────────────────────────────────

    def set_rate(self, rate: Rate) -> None:
        """Seed the editor from an existing Rate object."""
        if isinstance(rate, PostFixedCDI):
            self._combo.setCurrentIndex(0)
            self._line.setText(_pct_to_display(rate.cdi_percent_value))
        elif isinstance(rate, PostFixedCDIPlusSpread):
            self._combo.setCurrentIndex(1)
            self._line.setText(_pct_to_display(rate.spread_percent))
        elif isinstance(rate, PostFixedIPCA):
            self._combo.setCurrentIndex(2)
            self._line.setText(_pct_to_display(rate.spread_percent))
        elif isinstance(rate, Prefixed):
            self._combo.setCurrentIndex(3)
            self._line.setText(_pct_to_display(rate.annual_percent))
        self._update_suffix()

    def get_rate(self) -> Rate:
        """Parse the editor state and return a Rate. Raises ValueError on bad input."""
        pct = _parse_rate_percent(self._line.text())
        key = self._combo.currentData()
        if key == "cdi_pct":
            return PostFixedCDI.from_percent(pct)
        if key == "cdi_plus":
            return PostFixedCDIPlusSpread.from_percent(pct)
        if key == "ipca_plus":
            return PostFixedIPCA.from_percent(pct)
        return Prefixed.from_percent(pct)

    def setFocus(self) -> None:  # type: ignore[override]
        self._line.setFocus()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _on_type_changed(self) -> None:
        self._update_suffix()

    def _update_suffix(self) -> None:
        idx = self._combo.currentIndex()
        if 0 <= idx < len(_RATE_TYPE_ENTRIES):
            self._suffix_lbl.setText(_RATE_TYPE_ENTRIES[idx][2])


# ── Detail panel ──────────────────────────────────────────────────────────────

class InvestmentDetailPanel(QWidget):
    """Field-by-field detail panel shown alongside the investments table.

    Visibility is controlled by MainWindow based on table selection:
    show_investment() and clear() update contents only; MainWindow
    calls show()/hide() based on whether a row is selected. Single
    source of truth: the table's selection state.

    The closed signal fires when the user clicks the close button.
    MainWindow's handler clears the table selection, which drives
    _on_selection_changed to call clear() and hide().

    session_factory and main_window are stored for per-field editing
    (commit 5b). Injected here so the constructor signature is stable
    across both commits.
    """

    closed = Signal()
    investment_deleted = Signal(uuid.UUID)

    _FIELD_KEYS = [
        ("Issuer",        "issuer"),
        ("Conglomerate",  "conglomerate"),
        ("Product",       "product"),
        ("Principal",     "principal"),
        ("Rate",          "rate"),
        ("Purchase date", "purchase_date"),
        ("Issue date",    "issue_date"),
        ("Maturity date", "maturity_date"),
        ("Coupon",        "coupon_frequency"),
        ("Description",   "description"),
    ]

    _EDITABLE_FOR_MANUAL = frozenset({
        "principal", "rate", "purchase_date", "issue_date",
        "maturity_date", "coupon_frequency", "description",
    })
    _EDITABLE_FOR_IMPORT = frozenset({"description"})
    _MONO_FIELD_KEYS = frozenset({"rate", "purchase_date", "issue_date", "maturity_date", "principal"})

    def __init__(self, session_factory, main_window, parent=None) -> None:
        super().__init__(parent)
        self._session_factory = session_factory
        self._main_window = main_window
        self._current_inv = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        header = QHBoxLayout()
        self._identity_label = QLabel("No investment selected.")
        self._identity_label.setProperty("role", "panelTitle")
        self._close_btn = QPushButton("✕")
        self._close_btn.setFixedSize(24, 24)
        self._close_btn.clicked.connect(lambda: self.closed.emit())
        header.addWidget(self._identity_label, stretch=1)
        header.addWidget(self._close_btn)
        layout.addLayout(header)

        self._source_banner = QLabel()
        self._source_banner.setProperty("role", "infoBanner")
        self._source_banner.hide()
        layout.addWidget(self._source_banner)

        self._error_label = QLabel()
        self._error_label.setProperty("role", "error")
        self._error_label.setWordWrap(True)
        self._error_label.hide()
        layout.addWidget(self._error_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(2)

        self._field_values: dict[str, _EditableField] = {}
        for label_text, key in self._FIELD_KEYS:
            row = QHBoxLayout()
            row.setContentsMargins(0, 2, 0, 2)
            lbl = QLabel(label_text + ":")
            lbl.setProperty("role", "fieldLabel")
            lbl.setFixedWidth(100)
            lbl.setAlignment(Qt.AlignmentFlag.AlignTop)
            val = _EditableField(key, self._save_field, self._set_error)
            if key in self._MONO_FIELD_KEYS:
                val.set_display_font(_MONO_FONT)
            self._field_values[key] = val
            row.addWidget(lbl)
            row.addWidget(val, stretch=1)
            body_layout.addLayout(row)

        body_layout.addStretch()
        scroll.setWidget(body)
        layout.addWidget(scroll, stretch=1)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep)

        self._delete_btn = QPushButton("Delete investment")
        self._delete_btn.setProperty("role", "danger")
        self._delete_btn.setEnabled(False)
        self._delete_btn.clicked.connect(self._on_delete_clicked)
        layout.addWidget(self._delete_btn)

    def show_investment(self, inv) -> None:
        self._set_error(None)
        self._delete_btn.setEnabled(True)

        # Same-id refresh (e.g. re-entrancy from refresh_table after a field
        # save): adopt the freshly-persisted object and update header widgets
        # only. Skip the set_value loop so any field mid-commit is not reset.
        if self._current_inv is not None and inv.id == self._current_inv.id:
            self._current_inv = inv
            product_name = rules_for(inv.product).display_name
            self._identity_label.setText(f"{inv.issuer.name} — {product_name}")
            if inv.source != InvestmentSource.MANUAL:
                self._source_banner.setText("Imported — only description is editable.")
                self._source_banner.show()
            else:
                self._source_banner.hide()
            return

        # Genuine row switch: full rebuild, discarding any in-progress edit.
        self._current_inv = inv
        product_name = rules_for(inv.product).display_name
        self._identity_label.setText(f"{inv.issuer.name} — {product_name}")

        if inv.source != InvestmentSource.MANUAL:
            self._source_banner.setText("Imported — only description is editable.")
            self._source_banner.show()
        else:
            self._source_banner.hide()

        editable_keys = (
            self._EDITABLE_FOR_MANUAL
            if inv.source == InvestmentSource.MANUAL
            else self._EDITABLE_FOR_IMPORT
        )

        def _fmt_date(d: date) -> str:
            return _PT_BR.toString(
                QDate(d.year, d.month, d.day), QLocale.FormatType.ShortFormat
            )

        f = self._field_values
        f["issuer"].set_value(inv.issuer.name, inv.issuer.name, editable=False)
        f["conglomerate"].set_value(inv.issuer.conglomerate, inv.issuer.conglomerate, editable=False)
        f["product"].set_value(product_name, product_name, editable=False)
        f["principal"].set_value(inv.principal, inv.principal.to_display(), editable="principal" in editable_keys)
        f["rate"].set_value(inv.rate, inv.rate.to_display(), editable="rate" in editable_keys)
        f["purchase_date"].set_value(inv.purchase_date, _fmt_date(inv.purchase_date), editable="purchase_date" in editable_keys)
        f["issue_date"].set_value(inv.issue_date, _fmt_date(inv.issue_date), editable="issue_date" in editable_keys)
        f["maturity_date"].set_value(inv.maturity_date, _fmt_date(inv.maturity_date), editable="maturity_date" in editable_keys)
        f["coupon_frequency"].set_value(inv.coupon_frequency, inv.coupon_frequency.to_display(), editable="coupon_frequency" in editable_keys)
        f["description"].set_value(inv.description or "", inv.description or "—", editable="description" in editable_keys)

    def clear(self) -> None:
        self._current_inv = None
        self._identity_label.setText("No investment selected.")
        self._source_banner.hide()
        self._set_error(None)
        self._delete_btn.setEnabled(False)
        for field in self._field_values.values():
            field.set_value(None, "", editable=False)

    # ── Delete ────────────────────────────────────────────────────────────────

    def _on_delete_clicked(self) -> None:
        inv = self._current_inv
        if inv is None:
            return
        product_name = rules_for(inv.product).display_name
        maturity_str = _PT_BR.toString(
            QDate(inv.maturity_date.year, inv.maturity_date.month, inv.maturity_date.day),
            QLocale.FormatType.ShortFormat,
        )
        reply = QMessageBox.question(
            self,
            "Delete Investment",
            f"Permanently delete this investment?\n\n"
            f"{inv.issuer.name}  ·  {product_name}\n"
            f"Principal: {inv.principal.to_display()}  ·  Maturity: {maturity_str}\n\n"
            "This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        InvestmentRepository(self._session_factory).delete(inv.id)
        self.investment_deleted.emit(inv.id)

    # ── Field save helpers ────────────────────────────────────────────────────

    def _save_field(self, key: str, typed_value) -> str:
        """Validate, persist, and refresh for one field edit.

        Returns the new formatted string on success. Raises ValueError (from
        Investment.__post_init__) or Exception (from the repo) on failure.
        The caller (_EditableField._do_commit) catches and shows the error.
        """
        new_inv = dataclasses.replace(self._current_inv, **{key: typed_value})
        InvestmentRepository(self._session_factory).save(new_inv)
        self._current_inv = new_inv
        self._main_window.refresh_table()
        return self._format_field(key, new_inv)

    def _format_field(self, key: str, inv) -> str:
        if key == "rate":
            return inv.rate.to_display()
        if key == "principal":
            return inv.principal.to_display()
        if key in ("purchase_date", "issue_date", "maturity_date"):
            d = getattr(inv, key)
            return _PT_BR.toString(
                QDate(d.year, d.month, d.day), QLocale.FormatType.ShortFormat
            )
        if key == "coupon_frequency":
            return inv.coupon_frequency.to_display()
        if key == "description":
            return inv.description or "—"
        return ""

    def _set_error(self, message: str | None) -> None:
        if message is None:
            self._error_label.setText("")
            self._error_label.hide()
        else:
            self._error_label.setText(message)
            self._error_label.show()


# ── Add-investment form ───────────────────────────────────────────────────────

_NEW_ISSUER_SENTINEL = "__new_issuer__"


class _AddInvestmentPanel(QWidget):
    """Form for creating a new Investment from scratch (source=MANUAL).

    reset() must be called before each use — it clears all editors and
    re-populates the issuer combo from the DB so newly-added issuers
    from a prior session appear in the list.
    """

    saved     = Signal(uuid.UUID)
    cancelled = Signal()

    def __init__(self, session_factory, main_window, parent=None) -> None:
        super().__init__(parent)
        self._session_factory = session_factory
        self._main_window = main_window

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        header = QHBoxLayout()
        title = QLabel("Add Investment")
        title.setProperty("role", "panelTitle")
        self._close_btn = QPushButton("✕")
        self._close_btn.setFixedSize(24, 24)
        self._close_btn.clicked.connect(lambda: self.cancelled.emit())
        header.addWidget(title, stretch=1)
        header.addWidget(self._close_btn)
        layout.addLayout(header)

        self._error_label = QLabel()
        self._error_label.setProperty("role", "error")
        self._error_label.setWordWrap(True)
        self._error_label.hide()
        layout.addWidget(self._error_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        self._body_layout = QVBoxLayout(body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(2)

        self._build_form()

        self._body_layout.addStretch()
        scroll.setWidget(body)
        layout.addWidget(scroll, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._save_btn = QPushButton("Save investment")
        self._save_btn.clicked.connect(self._on_save_clicked)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(lambda: self.cancelled.emit())
        btn_row.addWidget(self._save_btn)
        btn_row.addWidget(self._cancel_btn)
        layout.addLayout(btn_row)

    # ── Form construction ─────────────────────────────────────────────────────

    def _add_form_row(self, label_text: str, widget: QWidget) -> None:
        row = QHBoxLayout()
        row.setContentsMargins(0, 2, 0, 2)
        lbl = QLabel(label_text + ":")
        lbl.setProperty("role", "fieldLabel")
        lbl.setFixedWidth(100)
        lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        row.addWidget(lbl)
        row.addWidget(widget, stretch=1)
        self._body_layout.addLayout(row)

    def _build_form(self) -> None:
        # Issuer combo
        self._issuer_combo = QComboBox()
        self._issuer_combo.currentIndexChanged.connect(self._on_issuer_combo_changed)
        self._add_form_row("Issuer", self._issuer_combo)

        # New-issuer sub-group — revealed when the sentinel entry is selected
        self._new_issuer_group = QWidget()
        nig = QVBoxLayout(self._new_issuer_group)
        nig.setContentsMargins(104, 0, 0, 0)  # indent to align under the field column
        nig.setSpacing(2)

        self._new_name_edit = QLineEdit()
        self._new_name_edit.setPlaceholderText("Issuer name")
        name_row = QHBoxLayout()
        name_lbl = QLabel("Name:")
        name_lbl.setProperty("role", "subLabel")
        name_lbl.setFixedWidth(96)
        name_row.addWidget(name_lbl)
        name_row.addWidget(self._new_name_edit)
        nig.addLayout(name_row)

        self._new_kind_combo = QComboBox()
        for kind in IssuerKind:
            self._new_kind_combo.addItem(kind.value.replace("_", " ").title(), kind)
        kind_row = QHBoxLayout()
        kind_lbl = QLabel("Type:")
        kind_lbl.setProperty("role", "subLabel")
        kind_lbl.setFixedWidth(96)
        kind_row.addWidget(kind_lbl)
        kind_row.addWidget(self._new_kind_combo)
        nig.addLayout(kind_row)

        self._new_cong_edit = QLineEdit()
        self._new_cong_edit.setPlaceholderText(
            "Conglomerate (leave blank to mark as unverified)"
        )
        cong_row = QHBoxLayout()
        cong_lbl = QLabel("Conglomerate:")
        cong_lbl.setProperty("role", "subLabel")
        cong_lbl.setFixedWidth(96)
        cong_row.addWidget(cong_lbl)
        cong_row.addWidget(self._new_cong_edit)
        nig.addLayout(cong_row)

        self._new_issuer_group.hide()
        self._body_layout.addWidget(self._new_issuer_group)

        # Product
        self._product_combo = QComboBox()
        for pt in ProductType:
            self._product_combo.addItem(rules_for(pt).display_name, pt)
        self._add_form_row("Product", self._product_combo)

        # Principal
        self._principal_edit = QLineEdit()
        self._principal_edit.setPlaceholderText("e.g. 10.000,00")
        self._add_form_row("Principal", self._principal_edit)

        # Rate — reuse _RateEditor directly
        self._rate_editor = _RateEditor()
        self._add_form_row("Rate", self._rate_editor)

        # Dates
        self._purchase_date_edit = QDateEdit()
        self._purchase_date_edit.setDisplayFormat("dd/MM/yyyy")
        self._add_form_row("Purchase date", self._purchase_date_edit)

        self._issue_date_edit = QDateEdit()
        self._issue_date_edit.setDisplayFormat("dd/MM/yyyy")
        self._add_form_row("Issue date", self._issue_date_edit)

        self._maturity_date_edit = QDateEdit()
        self._maturity_date_edit.setDisplayFormat("dd/MM/yyyy")
        self._add_form_row("Maturity date", self._maturity_date_edit)

        # Coupon frequency
        self._coupon_combo = QComboBox()
        for cf in CouponFrequency:
            self._coupon_combo.addItem(cf.to_display(), cf)
        self._add_form_row("Coupon", self._coupon_combo)

        # Description
        self._description_edit = QLineEdit()
        self._description_edit.setPlaceholderText("Optional note")
        self._add_form_row("Description", self._description_edit)

    # ── Public API ────────────────────────────────────────────────────────────

    def reset(self) -> None:
        """Clear the form and re-populate the issuer combo from the DB."""
        self._set_error(None)
        self._populate_issuer_combo()
        self._product_combo.setCurrentIndex(0)
        self._principal_edit.setText("")
        self._rate_editor.set_rate(PostFixedCDI.from_percent("100"))
        today = date.today()
        qtoday = QDate(today.year, today.month, today.day)
        self._purchase_date_edit.setDate(qtoday)
        self._issue_date_edit.setDate(qtoday)
        mat = today + timedelta(days=365)
        self._maturity_date_edit.setDate(QDate(mat.year, mat.month, mat.day))
        idx = self._coupon_combo.findData(CouponFrequency.NONE)
        if idx >= 0:
            self._coupon_combo.setCurrentIndex(idx)
        self._description_edit.setText("")
        self._new_name_edit.setText("")
        self._new_cong_edit.setText("")
        self._new_kind_combo.setCurrentIndex(0)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _populate_issuer_combo(self) -> None:
        self._issuer_combo.blockSignals(True)
        self._issuer_combo.clear()
        issuers = IssuerRepository(self._session_factory).list_all()
        for issuer in sorted(issuers, key=lambda i: i.name):
            self._issuer_combo.addItem(issuer.name, issuer)
        self._issuer_combo.addItem("➕ Add new issuer…", _NEW_ISSUER_SENTINEL)
        self._issuer_combo.blockSignals(False)
        self._issuer_combo.setCurrentIndex(0)
        self._on_issuer_combo_changed()

    def _on_issuer_combo_changed(self) -> None:
        data = self._issuer_combo.currentData()
        self._new_issuer_group.setVisible(data == _NEW_ISSUER_SENTINEL)

    def _on_save_clicked(self) -> None:
        self._set_error(None)

        try:
            issuer = self._resolve_issuer()
        except ValueError as exc:
            self._set_error(str(exc))
            return

        try:
            principal = parse_brazilian_money(self._principal_edit.text().strip())
        except Exception as exc:
            self._set_error(f"Principal: {exc}")
            return

        try:
            rate = self._rate_editor.get_rate()
        except ValueError as exc:
            self._set_error(f"Rate: {exc}")
            return

        product       = self._product_combo.currentData()
        purchase_date = self._qdate_to_date(self._purchase_date_edit.date())
        issue_date    = self._qdate_to_date(self._issue_date_edit.date())
        maturity_date = self._qdate_to_date(self._maturity_date_edit.date())
        coupon_frequency = self._coupon_combo.currentData()
        description   = self._description_edit.text().strip()

        try:
            investment = Investment(
                product=product,
                issuer=issuer,
                principal=principal,
                rate=rate,
                purchase_date=purchase_date,
                maturity_date=maturity_date,
                issue_date=issue_date,
                coupon_frequency=coupon_frequency,
                description=description,
                source=InvestmentSource.MANUAL,
            )
        except ValueError as exc:
            self._set_error(str(exc))
            return

        InvestmentRepository(self._session_factory).save(investment)
        self.saved.emit(investment.id)

    def _resolve_issuer(self) -> Issuer:
        """Return the selected Issuer, persisting a new one if the sentinel is active."""
        data = self._issuer_combo.currentData()
        if data != _NEW_ISSUER_SENTINEL:
            return data  # stored Issuer object

        name = self._new_name_edit.text().strip()
        if not name:
            raise ValueError("Issuer name cannot be empty.")
        kind        = self._new_kind_combo.currentData()
        conglomerate = self._new_cong_edit.text().strip()
        if not conglomerate:
            conglomerate = f"{UNVERIFIED_CONGLOMERATE_PREFIX}{name}"

        existing = IssuerRepository(self._session_factory).find_by_normalized_name(name)
        if existing is not None:
            raise ValueError(
                f"An issuer named \"{existing.name}\" already exists — "
                "select it from the list instead."
            )

        new_issuer = Issuer.create(name=name, conglomerate=conglomerate, kind=kind)
        IssuerRepository(self._session_factory).save(new_issuer)
        return new_issuer

    @staticmethod
    def _qdate_to_date(qd: QDate) -> date:
        return date(qd.year(), qd.month(), qd.day())

    def _set_error(self, message: str | None) -> None:
        if message is None:
            self._error_label.setText("")
            self._error_label.hide()
        else:
            self._error_label.setText(message)
            self._error_label.show()


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
        if hasattr(sys, "_MEIPASS"):
            _icon_path = Path(sys._MEIPASS) / "assets" / "icon.ico"
        else:
            _icon_path = Path(__file__).parent.parent.parent.parent / "assets" / "icon.ico"
        self.setWindowIcon(QIcon(str(_icon_path)))
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
        self._set_startup_tab()
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
        self._cong_project_btn.setProperty("role", "secondary")
        cong_bottom.addStretch()
        cong_bottom.addWidget(self._cong_project_btn)
        _cong_outer.addLayout(cong_bottom)
        self._tabs.addTab(self._conglomerates_tab, "Conglomerates")
        central = QWidget()
        self._tabs.addTab(central, "Investments")
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # Toolbar — action buttons + status label
        toolbar = QHBoxLayout()
        self._import_btn = QPushButton("Import Statement…")
        self._import_btn.clicked.connect(self._on_import_clicked)
        self._import_btn.setProperty("role", "toolbar")
        self._add_btn = QPushButton("Add investment…")
        self._add_btn.clicked.connect(self._on_add_investment_clicked)
        self._add_btn.setProperty("role", "toolbar")
        self._project_btn = QPushButton("Project as of today")
        self._project_btn.clicked.connect(self._on_project_clicked)
        self._project_btn.setProperty("role", "toolbar")
        self._export_btn = QPushButton("Export calendar…")
        self._export_btn.clicked.connect(self._on_export_clicked)
        self._export_btn.setProperty("role", "toolbar")
        self._status_label = QLabel("Ready.")
        toolbar.addWidget(self._import_btn)
        toolbar.addWidget(self._add_btn)
        toolbar.addWidget(self._project_btn)
        toolbar.addWidget(self._export_btn)
        toolbar.addStretch()
        toolbar.addWidget(self._status_label)
        root.addLayout(toolbar)

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
        filter_row.addSpacing(16)
        self._hide_matured_cb = QCheckBox("Hide matured")
        self._hide_matured_cb.setChecked(True)
        self._hide_matured_cb.toggled.connect(self._on_hide_matured_toggled)
        filter_row.addWidget(self._hide_matured_cb)
        filter_row.addStretch()
        root.addLayout(filter_row)

        # Middle — table or empty-state label (swapped via QStackedWidget)
        self._stack = QStackedWidget()

        self._table = QTableWidget(0, _NCOLS)
        self._table.setHorizontalHeaderLabels(_HEADERS)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(26)
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

        self._stack.addWidget(self._table)                      # index 0 — has data
        self._stack.addWidget(self._build_empty_state_widget()) # index 1 — empty

        self._detail_panel = InvestmentDetailPanel(self._session_factory, self)
        self._detail_panel.closed.connect(self._on_panel_close_requested)
        self._detail_panel.investment_deleted.connect(self._on_investment_deleted)

        self._add_panel = _AddInvestmentPanel(self._session_factory, self)
        self._add_panel.saved.connect(self._on_add_saved)
        self._add_panel.cancelled.connect(self._on_panel_close_requested)

        self._right_pane = QStackedWidget()
        self._right_pane.addWidget(self._detail_panel)  # index 0
        self._right_pane.addWidget(self._add_panel)     # index 1
        self._right_pane.hide()

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.addWidget(self._stack)
        self._splitter.addWidget(self._right_pane)
        self._splitter.setSizes([700, 300])
        root.addWidget(self._splitter, stretch=1)

        # Totals strip — principal, current, projected, row count
        totals_row = QHBoxLayout()
        self._principal_label = QLabel("Principal: —")
        self._principal_label.setFont(_MONO_FONT)
        self._current_label = QLabel("Current: —")
        self._current_label.setFont(_MONO_FONT)
        self._projected_label = QLabel("Projected: —")
        self._projected_label.setFont(_MONO_FONT)
        self._rows_label = QLabel("Rows: 0")
        totals_row.addWidget(self._principal_label)
        totals_row.addSpacing(16)
        totals_row.addWidget(self._current_label)
        totals_row.addSpacing(16)
        totals_row.addWidget(self._projected_label)
        totals_row.addStretch()
        totals_row.addWidget(self._rows_label)
        root.addLayout(totals_row)

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
        view_menu.addSeparator()
        for _title, _series in (
            ("CDI Curve", SERIES_CDI),
            ("IPCA-real Curve", SERIES_IPCA),
            ("Prefixado Curve", SERIES_PRE),
        ):
            _act = QAction(_title, self)
            _act.triggered.connect(
                lambda checked=False, s=_series: self._open_curve_inspector(s)
            )
            view_menu.addAction(_act)
        help_menu = menu_bar.addMenu("Help")
        about_action = QAction("About JustFixed", self)
        about_action.triggered.connect(self._on_about_clicked)
        help_menu.addAction(about_action)

    def _build_empty_state_widget(self) -> QWidget:
        self._empty_widget = QWidget()
        _ew_layout = QVBoxLayout(self._empty_widget)
        _ew_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _ew_label = QLabel(
            "No investments yet.\n"
            "Import an XP statement, or add an investment manually."
        )
        _ew_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _ew_layout.addWidget(_ew_label)
        _ew_layout.addSpacing(12)
        self._empty_import_btn = QPushButton("Import Statement…")
        self._empty_import_btn.clicked.connect(self._on_import_clicked)
        self._empty_import_btn.setProperty("role", "secondary")
        self._empty_add_btn = QPushButton("Add investment…")
        self._empty_add_btn.clicked.connect(self._on_add_investment_clicked)
        self._empty_add_btn.setProperty("role", "secondary")
        _ew_layout.addWidget(self._empty_import_btn)
        _ew_layout.addSpacing(4)
        _ew_layout.addWidget(self._empty_add_btn)
        return self._empty_widget

    def _make_summary_row(
        self, section: ConglomerateSection, index: int = 0
    ) -> tuple[QWidget, QLabel]:
        row_widget = QWidget()
        row_widget.setProperty("congRowParity", "even" if index % 2 == 0 else "odd")
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
        next_lbl.setFont(_MONO_FONT)
        h.addWidget(next_lbl)

        principal_lbl = QLabel(section.total_principal.to_display())
        principal_lbl.setFixedWidth(120)
        principal_lbl.setFont(_MONO_FONT)
        h.addWidget(principal_lbl)

        current_lbl = QLabel(section.total_current_value.to_display())
        current_lbl.setFixedWidth(120)
        current_lbl.setFont(_MONO_FONT)
        h.addWidget(current_lbl)

        projected_lbl = QLabel(section.total_projected_value.to_display())
        projected_lbl.setFixedWidth(120)
        projected_lbl.setFont(_MONO_FONT)
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
        h = QHBoxLayout(w)
        h.setContentsMargins(8, 4, 8, 4)
        for text, width, stretch in [
            ("Maturity",            100, 0),
            ("Issuer",                0, 1),
            ("Product",             100, 0),
            ("Principal",           110, 0),
            ("Current",             110, 0),
            ("Projected",           110, 0),
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
        w.setProperty("detailRowParity", "even" if idx % 2 == 0 else "odd")
        h = QHBoxLayout(w)
        h.setContentsMargins(8, 4, 8, 4)

        d = row.maturity_date
        mat_lbl = QLabel(
            _PT_BR.toString(QDate(d.year, d.month, d.day), QLocale.FormatType.ShortFormat)
        )
        mat_lbl.setFixedWidth(100)
        mat_lbl.setFont(_MONO_FONT)
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
            lbl.setFont(_MONO_FONT)
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
        h = QHBoxLayout(row_widget)
        h.setContentsMargins(8, 6, 8, 6)

        spacer = QLabel()
        spacer.setFixedWidth(20)
        h.addWidget(spacer)

        h.addWidget(QLabel("Conglomerate"), stretch=1)

        for text, width in [
            ("Next maturity",   120),
            ("Principal",       120),
            ("Current",   120),
            ("Projected", 120),
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
        self._add_btn.setEnabled(not busy)
        if busy:
            self._project_btn.setEnabled(False)
            self._cong_project_btn.setEnabled(False)
            self._export_btn.setEnabled(False)
        else:
            self._update_button_states()

    # ── Table ─────────────────────────────────────────────────────────────────

    def refresh_table(self, highlight_issuer_id: uuid.UUID | None = None) -> None:
        """Reload all investments from DB and repopulate the table."""
        _selected_id = self._capture_selected_id()

        self._investments = self._repo.list_all()
        self._populate_filter_dropdowns()
        visible = self.visible_investments()
        scroll_y = self._table.verticalScrollBar().value()

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

        self._table.blockSignals(True)
        self._table.setRowCount(len(visible))
        for row, inv in enumerate(visible):
            proj = projection_map.get(inv.id)
            self._populate_row(
                row, inv,
                current_value=proj.current_value if proj else None,
                projected_value=proj.gross_at_maturity if proj else None,
                fgc_status=status_by_investment.get(inv.id),
                highlight=(inv.issuer.id == highlight_issuer_id),
            )
        self._table.blockSignals(False)

        # setValue clamps to the scrollbar's valid range, so scroll_y past the
        # new content end (e.g. after Clear DB or Hide-matured toggle) is safe.
        self._table.verticalScrollBar().setValue(scroll_y)
        self._restore_selection(_selected_id, visible)
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
            cong_item.setForeground(QColor(COLORS.INK_3))
        self._table.setItem(row, _COL_CONGLOMERATE, cong_item)

        self._cell(row, _COL_PRODUCT, rules_for(inv.product).display_name)
        self._cell(row, _COL_TYPE, _format_type(inv.rate))
        self._cell(row, _COL_RATE, _format_rate(inv.rate, self._cdi_curve, inv.maturity_date), mono=True)
        self._cell(row, _COL_PRINCIPAL, inv.principal.to_display(), mono=True)

        d = inv.maturity_date
        self._cell(
            row, _COL_MATURITY,
            _PT_BR.toString(QDate(d.year, d.month, d.day), QLocale.FormatType.ShortFormat),
            mono=True,
        )

        show_paid = _is_matured(inv) and not self._hide_matured

        if show_paid:
            for col in (_COL_CURRENT, _COL_PROJECTED):
                paid = QTableWidgetItem("PAID")
                paid.setFont(_MONO_FONT)
                self._table.setItem(row, col, paid)
        else:
            self._cell(row, _COL_CURRENT, current_value.to_display() if current_value else "", mono=True)
            self._cell(row, _COL_PROJECTED, projected_value.to_display() if projected_value else "", mono=True)

        # FGC badge
        if inv.issuer.kind == IssuerKind.TREASURY:
            badge = QTableWidgetItem("N/A — Tesouro")
            badge.setForeground(QColor(COLORS.FGC_NA))
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

        # Demote entire row to muted ink when showing PAID (matured, toggle OFF).
        if show_paid:
            for col in range(_NCOLS):
                item = self._table.item(row, col)
                if item is not None:
                    item.setForeground(_MATURED_COLOR)

    def _cell(self, row: int, col: int, text: str, *, mono: bool = False) -> None:
        item = QTableWidgetItem(text)
        if mono:
            item.setFont(_MONO_FONT)
        self._table.setItem(row, col, item)

    def _update_button_states(self) -> None:
        today = date.today()
        self._project_btn.setEnabled(bool(self._investments))
        self._cong_project_btn.setEnabled(bool(self._investments))
        self._export_btn.setEnabled(
            any(inv.maturity_date >= today for inv in self._investments)
        )

    def _capture_selected_id(self) -> uuid.UUID | None:
        items = self._table.selectedItems()
        if not items:
            return None
        row = items[0].row()
        visible = self.visible_investments()
        return visible[row].id if row < len(visible) else None

    def _restore_selection(self, selected_id: uuid.UUID | None, visible: list) -> None:
        if selected_id is None:
            return
        for i, inv in enumerate(visible):
            if inv.id == selected_id:
                self._table.selectRow(i)
                return
        self._detail_panel.clear()
        self._right_pane.hide()

    def _on_selection_changed(self) -> None:
        items = self._table.selectedItems()
        if not items:
            self._detail_panel.clear()
            self._right_pane.hide()
            return
        row = items[0].row()
        visible = self.visible_investments()
        if row >= len(visible):
            self._detail_panel.clear()
            self._right_pane.hide()
            return
        self._right_pane.setCurrentIndex(0)
        self._detail_panel.show_investment(visible[row])
        self._right_pane.show()

    def _on_panel_close_requested(self) -> None:
        self._table.clearSelection()
        self._right_pane.setCurrentIndex(0)
        self._add_panel.reset()
        self._right_pane.hide()

    def _on_investment_deleted(self, investment_id: uuid.UUID) -> None:
        if self.projection_cache is not None:
            self.projection_cache = [
                p for p in self.projection_cache if p.investment.id != investment_id
            ]
        self.refresh_table()
        self.statusBar().showMessage("Investment deleted.", 4000)

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
        # Keep menu action and filter-row checkbox in sync without re-triggering.
        self._hide_matured_action.blockSignals(True)
        self._hide_matured_action.setChecked(checked)
        self._hide_matured_action.blockSignals(False)
        self._hide_matured_cb.blockSignals(True)
        self._hide_matured_cb.setChecked(checked)
        self._hide_matured_cb.blockSignals(False)
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
            self, "Import Statement",
            dirs[0] if dirs else "",
            "Statement files (*.xlsx *.txt)",
        )
        if not path_str:
            return

        self._set_busy(True)
        self._status_label.setText(f"Loading {Path(path_str).name}…")

        self._worker = _ImportWorker(Path(path_str), self._session_factory)
        self._worker.finished.connect(self._on_import_done)
        self._worker.error.connect(self._on_import_error)
        self._worker.start()

    _BROKER_DISPLAY = {
        Broker.XP:  "XP",
        Broker.BTG: "BTG Pactual",
        Broker.BB:  "Banco do Brasil",
    }

    def _on_import_done(self, payload) -> None:
        broker, result = payload
        self._set_busy(False)
        broker_display = self._BROKER_DISPLAY[broker]
        self._status_label.setText(
            f"Loaded {result.inserted + result.skipped} investments "
            f"({result.inserted} new, {result.skipped} unchanged)."
        )
        QMessageBox.information(
            self,
            "Import complete",
            f"{broker_display} statement imported — "
            f"{result.inserted} new, {result.skipped} unchanged.",
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

    def _on_add_investment_clicked(self) -> None:
        self._table.clearSelection()
        self._add_panel.reset()
        self._right_pane.setCurrentIndex(1)
        self._right_pane.show()

    def _on_add_saved(self, investment_id: uuid.UUID) -> None:
        self._right_pane.setCurrentIndex(0)
        self.refresh_table()
        visible = self.visible_investments()
        for i, inv in enumerate(visible):
            if inv.id == investment_id:
                self._table.selectRow(i)
                return

    # ── Startup helpers ───────────────────────────────────────────────────────

    def _set_startup_tab(self) -> None:
        self._tabs.setCurrentIndex(1 if not self._investments else 0)

    # ── Curve Inspector ───────────────────────────────────────────────────────

    def _open_curve_inspector(self, series: str) -> None:
        curve = {
            SERIES_CDI:  self._cdi_curve,
            SERIES_IPCA: self._ipca_curve,
            SERIES_PRE:  self._pre_curve,
        }[series]
        w = CurveInspectorWindow(
            series=series,
            curve=curve,
            fetch_result=self._fetch_result,
            parent=self,
        )
        w.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        w.show()

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

        def _title(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setProperty("role", "panelTitle")
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
    app.setStyleSheet(make_stylesheet())
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
