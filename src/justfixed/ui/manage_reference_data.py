"""Manage Reference Data dialog.

Modal dialog for managing issuers, conglomerates, and custodians.
Opened via View ▸ Manage Reference Data….
"""

from __future__ import annotations

from collections import Counter, defaultdict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QInputDialog,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from justfixed.domain.issuer import UNVERIFIED_CONGLOMERATE_PREFIX, display_issuer_kind
from justfixed.persistence.repositories import InvestmentRepository, IssuerRepository
from justfixed.ui.strings import STR


class ManageReferenceDataDialog(QDialog):
    """Modal dialog for managing issuers, conglomerates, and custodians."""

    def __init__(
        self,
        issuer_repo: IssuerRepository,
        investment_repo: InvestmentRepository,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._issuer_repo = issuer_repo
        self._investment_repo = investment_repo
        self.setWindowTitle(STR.MRD_TITLE)
        self.setMinimumSize(820, 480)
        self._build_ui()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_issuers_tab(), STR.MRD_TAB_ISSUERS)
        self._tabs.addTab(self._build_conglomerates_tab(), STR.MRD_TAB_CONGLOMERATES)
        self._tabs.addTab(self._build_custodians_tab(), STR.MRD_TAB_CUSTODIANS)
        root.addWidget(self._tabs, stretch=1)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject)
        root.addWidget(button_box)

        # All three tables now exist — safe to populate in one pass.
        self._refresh_all()

    def _build_issuers_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)

        self._issuers_table = QTableWidget()
        self._issuers_table.setColumnCount(5)
        self._issuers_table.setHorizontalHeaderLabels(
            [STR.MRD_COL_NAME, STR.COL_CONGLOMERATE, STR.MRD_COL_KIND, STR.MRD_COL_NUM_INVESTMENTS, ""]
        )
        hh = self._issuers_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self._issuers_table.setColumnWidth(4, 80)
        self._issuers_table.verticalHeader().setVisible(False)
        self._issuers_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._issuers_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self._issuers_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        layout.addWidget(self._issuers_table)
        # Populate deferred — _build_ui calls _refresh_all after both tables exist.
        return widget

    def _build_conglomerates_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)

        self._conglomerates_table = QTableWidget()
        self._conglomerates_table.setColumnCount(5)
        self._conglomerates_table.setHorizontalHeaderLabels(
            [STR.COL_CONGLOMERATE, STR.MRD_COL_NUM_ISSUERS, STR.MRD_COL_NUM_INVESTMENTS, STR.MRD_RENAME, STR.MRD_DISSOLVE]
        )
        hh = self._conglomerates_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self._conglomerates_table.setColumnWidth(3, 80)
        self._conglomerates_table.setColumnWidth(4, 80)
        self._conglomerates_table.verticalHeader().setVisible(False)
        self._conglomerates_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self._conglomerates_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self._conglomerates_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        layout.addWidget(self._conglomerates_table)
        # Populate deferred — _build_ui calls _refresh_all after all tables exist.
        return widget

    def _build_custodians_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)

        self._custodians_table = QTableWidget()
        self._custodians_table.setColumnCount(4)
        self._custodians_table.setHorizontalHeaderLabels(
            [STR.FIELD_CUSTODIAN, STR.MRD_COL_NUM_INVESTMENTS, STR.MRD_RENAME, STR.MRD_CLEAR]
        )
        hh = self._custodians_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self._custodians_table.setColumnWidth(2, 80)
        self._custodians_table.setColumnWidth(3, 80)
        self._custodians_table.verticalHeader().setVisible(False)
        self._custodians_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self._custodians_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self._custodians_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        layout.addWidget(self._custodians_table)
        # Populate deferred — _build_ui calls _refresh_all after all tables exist.
        return widget

    # ── Data population ───────────────────────────────────────────────────────

    def _refresh_all(self) -> None:
        """Repopulate all live tabs. Called after any mutation."""
        self._populate_issuers_table()
        self._populate_conglomerates_table()
        self._populate_custodians_table()

    def _populate_issuers_table(self) -> None:
        counts: Counter = Counter(
            inv.issuer.id for inv in self._investment_repo.list_all()
        )
        issuers = self._issuer_repo.list_all()
        self._issuers_table.setRowCount(len(issuers))
        for row, issuer in enumerate(issuers):
            count = counts.get(issuer.id, 0)
            kind_display = display_issuer_kind(issuer.kind)

            self._issuers_table.setItem(row, 0, QTableWidgetItem(issuer.name))
            self._issuers_table.setItem(row, 1, QTableWidgetItem(issuer.conglomerate))
            self._issuers_table.setItem(row, 2, QTableWidgetItem(kind_display))

            count_item = QTableWidgetItem(str(count))
            count_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            self._issuers_table.setItem(row, 3, count_item)

            del_btn = QPushButton(STR.MRD_DELETE)
            if count > 0:
                del_btn.setEnabled(False)
                del_btn.setToolTip(STR.MRD_TIP_CANT_DELETE.format(count=count))
            else:
                del_btn.clicked.connect(
                    lambda checked=False, iss=issuer: self._on_delete_issuer(iss)
                )
            self._issuers_table.setCellWidget(row, 4, del_btn)

    def _populate_conglomerates_table(self) -> None:
        issuers = self._issuer_repo.list_all()
        investments = self._investment_repo.list_all()

        issuer_counts: dict[str, int] = defaultdict(int)
        for iss in issuers:
            if not iss.conglomerate.startswith(UNVERIFIED_CONGLOMERATE_PREFIX):
                issuer_counts[iss.conglomerate] += 1

        inv_counts: dict[str, int] = defaultdict(int)
        for inv in investments:
            cong = inv.issuer.conglomerate
            if not cong.startswith(UNVERIFIED_CONGLOMERATE_PREFIX):
                inv_counts[cong] += 1

        conglomerates = sorted(issuer_counts.keys())
        self._conglomerates_table.setRowCount(len(conglomerates))
        for row, cong in enumerate(conglomerates):
            self._conglomerates_table.setItem(row, 0, QTableWidgetItem(cong))

            issuer_count_item = QTableWidgetItem(str(issuer_counts[cong]))
            issuer_count_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            self._conglomerates_table.setItem(row, 1, issuer_count_item)

            inv_count_item = QTableWidgetItem(str(inv_counts.get(cong, 0)))
            inv_count_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            self._conglomerates_table.setItem(row, 2, inv_count_item)

            rename_btn = QPushButton(STR.MRD_RENAME)
            rename_btn.clicked.connect(
                lambda checked=False, c=cong: self._on_rename_conglomerate(c)
            )
            self._conglomerates_table.setCellWidget(row, 3, rename_btn)

            dissolve_btn = QPushButton(STR.MRD_DISSOLVE)
            dissolve_btn.clicked.connect(
                lambda checked=False, c=cong: self._on_dissolve_conglomerate(c)
            )
            self._conglomerates_table.setCellWidget(row, 4, dissolve_btn)

    def _populate_custodians_table(self) -> None:
        investments = self._investment_repo.list_all()

        counts: dict[str, int] = defaultdict(int)
        unset_count = 0
        for inv in investments:
            if inv.custodian is None:
                unset_count += 1
            else:
                counts[inv.custodian] += 1

        custodians = sorted(counts.keys())
        total_rows = len(custodians) + (1 if unset_count > 0 else 0)
        self._custodians_table.setRowCount(total_rows)

        for row, cust in enumerate(custodians):
            self._custodians_table.setItem(row, 0, QTableWidgetItem(cust))

            count_item = QTableWidgetItem(str(counts[cust]))
            count_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            self._custodians_table.setItem(row, 1, count_item)

            rename_btn = QPushButton(STR.MRD_RENAME)
            rename_btn.clicked.connect(
                lambda checked=False, c=cust: self._on_rename_custodian(c)
            )
            self._custodians_table.setCellWidget(row, 2, rename_btn)

            clear_btn = QPushButton(STR.MRD_CLEAR)
            clear_btn.clicked.connect(
                lambda checked=False, c=cust: self._on_clear_custodian(c)
            )
            self._custodians_table.setCellWidget(row, 3, clear_btn)

        if unset_count > 0:
            row = len(custodians)
            self._custodians_table.setItem(row, 0, QTableWidgetItem("—"))

            count_item = QTableWidgetItem(str(unset_count))
            count_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            self._custodians_table.setItem(row, 1, count_item)

            rename_btn = QPushButton(STR.MRD_RENAME)
            rename_btn.setEnabled(False)
            rename_btn.setToolTip(STR.MRD_TIP_NO_CUSTODIAN)
            self._custodians_table.setCellWidget(row, 2, rename_btn)

            clear_btn = QPushButton(STR.MRD_CLEAR)
            clear_btn.setEnabled(False)
            clear_btn.setToolTip(STR.MRD_TIP_ALREADY_UNSET)
            self._custodians_table.setCellWidget(row, 3, clear_btn)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _on_delete_issuer(self, issuer) -> None:
        reply = QMessageBox.question(
            self,
            "Delete Issuer",
            f"Delete issuer '{issuer.name}'? This can't be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._issuer_repo.delete(issuer.id)
        self._refresh_all()

    def _on_rename_conglomerate(self, old: str) -> None:
        text, ok = QInputDialog.getText(
            self, "Rename Conglomerate", f"New name for '{old}':", text=old
        )
        if not ok:
            return
        text = text.strip()
        if not text:
            QMessageBox.warning(self, "Rename Conglomerate", "Name can't be blank.")
            return
        if text == old:
            return
        issuers = self._issuer_repo.list_all()
        all_conglomerates = {iss.conglomerate for iss in issuers}
        if text in all_conglomerates:
            old_count = sum(1 for iss in issuers if iss.conglomerate == old)
            reply = QMessageBox.question(
                self,
                "Merge Conglomerates",
                f"'{text}' already exists. Merge the {old_count} issuer(s) from "
                f"'{old}' into '{text}'?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self._issuer_repo.rename_conglomerate(old, text)
        self._refresh_all()

    def _on_dissolve_conglomerate(self, name: str) -> None:
        issuers = self._issuer_repo.list_all()
        count = sum(1 for iss in issuers if iss.conglomerate == name)
        reply = QMessageBox.question(
            self,
            "Dissolve Conglomerate",
            f"Dissolve '{name}'? Its {count} issuer(s) revert to uncurated and "
            f"the grouping is removed. This can't be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._issuer_repo.dissolve_conglomerate(name)
        self._refresh_all()

    def _on_rename_custodian(self, old: str) -> None:
        text, ok = QInputDialog.getText(
            self, "Rename Custodian", f"New name for '{old}':", text=old
        )
        if not ok:
            return
        text = text.strip()
        if not text:
            QMessageBox.warning(self, "Rename Custodian", "Name can't be blank.")
            return
        if text == old:
            return
        investments = self._investment_repo.list_all()
        existing = {inv.custodian for inv in investments if inv.custodian is not None}
        if text in existing:
            old_count = sum(1 for inv in investments if inv.custodian == old)
            reply = QMessageBox.question(
                self,
                "Merge Custodians",
                f"'{text}' already exists. Merge the {old_count} investment(s) from "
                f"'{old}' into '{text}'?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self._investment_repo.rename_custodian(old, text)
        self._refresh_all()

    def _on_clear_custodian(self, name: str) -> None:
        investments = self._investment_repo.list_all()
        count = sum(1 for inv in investments if inv.custodian == name)
        reply = QMessageBox.question(
            self,
            "Clear Custodian",
            f"Clear custodian '{name}' from its {count} investment(s)? "
            f"They'll show no custodian.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._investment_repo.clear_custodian(name)
        self._refresh_all()
