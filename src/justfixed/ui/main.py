"""PySide6 main window for JustFixed — Milestone A′."""

from __future__ import annotations

import logging
import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import QDate, QLocale, QStandardPaths, QStringListModel, Qt, QThread, Signal
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QApplication,
    QCompleter,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from justfixed.domain.issuer import Issuer, IssuerKind, UNVERIFIED_CONGLOMERATE_PREFIX
from justfixed.domain.money import Money
from justfixed.domain.product import rules_for
from justfixed.engine.fgc import ExposureStatus, FGCReport, fgc_concentration_report
from justfixed.engine.projection import project
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
_COL_PRINCIPAL    = 3
_COL_MATURITY     = 4
_COL_CURRENT      = 5
_COL_PROJECTED    = 6
_COL_FGC          = 7
_NCOLS            = 8

_HEADERS = [
    "Issuer", "Conglomerate", "Product",
    "Principal", "Maturity", "Current value", "Projected value", "FGC",
]

_PT_BR = QLocale(QLocale.Language.Portuguese, QLocale.Country.Brazil)

_FGC_COLORS: dict[ExposureStatus, tuple[QColor, str]] = {
    ExposureStatus.UNDER:       (QColor("#2ecc71"), "● UNDER"),
    ExposureStatus.APPROACHING: (QColor("#e67e22"), "● APPROACHING"),
    ExposureStatus.OVER:        (QColor("#e74c3c"), "● OVER"),
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
    finished = Signal(object, object)  # list[ProjectionResult], FGCReport
    error    = Signal(str)

    def __init__(self, investments: list) -> None:
        super().__init__()
        self._investments = investments

    def run(self) -> None:
        try:
            today = date.today()
            results = [
                project(inv, as_of=today, assumed_cdi=_ASSUMED_CDI, assumed_ipca=_ASSUMED_IPCA)
                for inv in self._investments
            ]
            fgc_report = fgc_concentration_report(
                self._investments, as_of=today, assumed_cdi=_ASSUMED_CDI, assumed_ipca=_ASSUMED_IPCA
            )
            self.finished.emit(results, fgc_report)
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

        if text.startswith(UNVERIFIED_CONGLOMERATE_PREFIX):
            QMessageBox.warning(
                self._main_window,
                "Invalid conglomerate",
                "The [unverified] prefix is reserved for system use. "
                "Please enter the conglomerate name without it.",
            )
            return

        visible = self._main_window._visible_investments()
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

        self._main_window._refresh_table()

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

        # Loaded investments — only mutated by _refresh_table(), never by
        # error handlers, so a failed import/project leaves the previous
        # list intact and _set_busy(False) re-enables buttons correctly.
        self._investments: list = []
        self._hide_matured: bool = True
        self._has_projected: bool = False
        self._worker: QThread | None = None  # keeps worker alive during run

        self._build_ui()
        self._refresh_table()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
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

        # Middle — table or empty-state label (swapped via QStackedWidget)
        self._stack = QStackedWidget()

        self._table = QTableWidget(0, _NCOLS)
        self._table.setHorizontalHeaderLabels(_HEADERS)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.verticalHeader().setVisible(False)
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

        self.setStatusBar(QStatusBar())

        # Menu bar — File (Clear DB when JUSTFIXED_DEV set) + View
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("File")
        if os.environ.get("JUSTFIXED_DEV"):
            clear_db_action = QAction("Clear Database…", self)
            clear_db_action.triggered.connect(self._on_clear_db_clicked)
            file_menu.addAction(clear_db_action)
        view_menu = menu_bar.addMenu("View")
        self._hide_matured_action = QAction("Hide matured investments", self)
        self._hide_matured_action.setCheckable(True)
        self._hide_matured_action.setChecked(True)
        self._hide_matured_action.triggered.connect(self._on_hide_matured_toggled)
        view_menu.addAction(self._hide_matured_action)

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
            self._export_btn.setEnabled(False)
        else:
            self._update_button_states()

    # ── Table ─────────────────────────────────────────────────────────────────

    def _refresh_table(self) -> None:
        """Reload all investments from DB and repopulate the table."""
        self._investments = self._repo.list_all()
        visible = self._visible_investments()
        self._table.setRowCount(len(visible))
        for row, inv in enumerate(visible):
            self._populate_row(row, inv, current_value=None, projected_value=None, fgc_status=None)
        self._stack.setCurrentIndex(0 if self._investments else 1)
        self._update_button_states()

    def _visible_investments(self) -> list:
        if not self._hide_matured:
            return self._investments
        today = date.today()
        return [i for i in self._investments if i.maturity_date > today]

    def _populate_row(
        self,
        row: int,
        inv,
        *,
        current_value: Money | None,
        projected_value: Money | None,
        fgc_status: ExposureStatus | None,
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
            color, label = _FGC_COLORS[fgc_status]
            badge = QTableWidgetItem(label)
            badge.setForeground(color)
        badge.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._table.setItem(row, _COL_FGC, badge)

    def _cell(self, row: int, col: int, text: str) -> None:
        self._table.setItem(row, col, QTableWidgetItem(text))

    def _update_button_states(self) -> None:
        today = date.today()
        self._project_btn.setEnabled(bool(self._investments))
        self._export_btn.setEnabled(
            any(inv.maturity_date >= today for inv in self._investments)
        )

    def _on_hide_matured_toggled(self, checked: bool) -> None:
        self._hide_matured = checked
        self._refresh_table()
        if self._has_projected:
            self._on_project_clicked()

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
        self._has_projected = False
        self._refresh_table()
        self.statusBar().showMessage(f"Cleared {deleted_investments} investments.", 6000)

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
        self._has_projected = False
        self._refresh_table()

    def _on_import_error(self, message: str) -> None:
        # _investments unchanged — failed import did not reach _refresh_table().
        self._set_busy(False)
        self._status_label.setText("Ready.")
        QMessageBox.critical(self, "Import failed", message)

    # ── Project ───────────────────────────────────────────────────────────────

    def _on_project_clicked(self) -> None:
        self._set_busy(True)

        self._worker = _ProjectWorker(self._visible_investments())
        self._worker.finished.connect(self._on_project_done)
        self._worker.error.connect(self._on_project_error)
        self._worker.start()

    def _on_project_done(self, results: list, fgc_report: FGCReport) -> None:
        self._set_busy(False)
        status_map = {
            c.conglomerate_name: c.current_status
            for c in fgc_report.conglomerates
        }
        for row, result in enumerate(results):
            inv = result.investment
            self._populate_row(
                row, inv,
                current_value=result.current_value,
                projected_value=result.net_at_maturity,
                fgc_status=status_map.get(inv.issuer.conglomerate),
            )
        self.statusBar().showMessage(
            f"Projected {len(results)} investments as of {date.today():%d/%m/%Y}.", 6000
        )
        self._has_projected = True

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
                self._visible_investments(), as_of=date.today(), assumed_cdi=_ASSUMED_CDI, assumed_ipca=_ASSUMED_IPCA
            )
            Path(path_str).write_bytes(ics)
            self.statusBar().showMessage(f"Calendar exported to {path_str}.", 8000)
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
