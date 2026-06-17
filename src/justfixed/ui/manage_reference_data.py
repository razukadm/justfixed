"""Manage Reference Data dialog.

Modal dialog for managing issuers, conglomerates, and custodians.
Opened via View ▸ Manage Reference Data….
"""

from __future__ import annotations

from collections import Counter

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from justfixed.persistence.repositories import InvestmentRepository, IssuerRepository


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
        self.setWindowTitle("Manage Reference Data")
        self.setMinimumSize(820, 480)
        self._build_ui()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_issuers_tab(), "Issuers")
        self._tabs.addTab(self._build_placeholder_tab(), "Conglomerates")
        self._tabs.addTab(self._build_placeholder_tab(), "Custodians")
        root.addWidget(self._tabs, stretch=1)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject)
        root.addWidget(button_box)

    def _build_placeholder_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label = QLabel("Coming soon")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: #888888;")
        layout.addWidget(label)
        return widget

    def _build_issuers_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)

        self._issuers_table = QTableWidget()
        self._issuers_table.setColumnCount(5)
        self._issuers_table.setHorizontalHeaderLabels(
            ["Name", "Conglomerate", "Kind", "# Investments", ""]
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

        self._populate_issuers_table()
        return widget

    # ── Data population ───────────────────────────────────────────────────────

    def _populate_issuers_table(self) -> None:
        counts: Counter = Counter(
            inv.issuer.id for inv in self._investment_repo.list_all()
        )
        issuers = self._issuer_repo.list_all()
        self._issuers_table.setRowCount(len(issuers))
        for row, issuer in enumerate(issuers):
            count = counts.get(issuer.id, 0)
            kind_display = issuer.kind.value.replace("_", " ").title()

            self._issuers_table.setItem(row, 0, QTableWidgetItem(issuer.name))
            self._issuers_table.setItem(row, 1, QTableWidgetItem(issuer.conglomerate))
            self._issuers_table.setItem(row, 2, QTableWidgetItem(kind_display))

            count_item = QTableWidgetItem(str(count))
            count_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            self._issuers_table.setItem(row, 3, count_item)

            del_btn = QPushButton("Delete")
            if count > 0:
                del_btn.setEnabled(False)
                del_btn.setToolTip(
                    f"Can't delete: {count} investment(s) still reference this issuer."
                )
            else:
                del_btn.clicked.connect(
                    lambda checked=False, iss=issuer: self._on_delete_issuer(iss)
                )
            self._issuers_table.setCellWidget(row, 4, del_btn)

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
        self._populate_issuers_table()
