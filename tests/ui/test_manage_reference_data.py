"""Tests for ManageReferenceDataDialog and MainWindow._open_manage_reference_data.

Uses two patterns:
 * Real-dialog / real-DB: constructs ManageReferenceDataDialog with repos backed
   by an in-memory SQLite database so table content and delete flows are verifiable.
 * MagicMock self: tests MainWindow._open_manage_reference_data without
   instantiating a real MainWindow.
"""

from __future__ import annotations

import sys
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import (
    QApplication,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
)

from justfixed.domain.investment import Investment
from justfixed.domain.issuer import Issuer, IssuerKind, UNVERIFIED_CONGLOMERATE_PREFIX
from justfixed.domain.money import Money
from justfixed.domain.product import ProductType
from justfixed.domain.rates import PostFixedCDI
from justfixed.persistence.database import Base, make_engine, make_session_factory
from justfixed.persistence.repositories import InvestmentRepository, IssuerRepository
from justfixed.ui.main import MainWindow
from justfixed.ui.manage_reference_data import ManageReferenceDataDialog


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


@pytest.fixture
def factory():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    f = make_session_factory(engine)
    yield f
    engine.dispose()


@pytest.fixture
def issuer_repo(factory):
    return IssuerRepository(factory)


@pytest.fixture
def investment_repo(factory):
    return InvestmentRepository(factory)


def _make_issuer(name: str, conglomerate: str = "Some Group") -> Issuer:
    return Issuer.create(name, conglomerate, IssuerKind.COMMERCIAL_BANK)


def _make_investment(issuer: Issuer, *, purchase_date=date(2024, 1, 1),
                     maturity_date=date(2026, 1, 1)) -> Investment:
    return Investment.create(
        product=ProductType.CDB,
        issuer=issuer,
        principal=Money.from_reais("10000"),
        rate=PostFixedCDI.from_percent("110"),
        purchase_date=purchase_date,
        maturity_date=maturity_date,
    )


def _make_dialog(issuer_repo, investment_repo, qapp) -> ManageReferenceDataDialog:
    return ManageReferenceDataDialog(issuer_repo, investment_repo)


# ── Tab structure ─────────────────────────────────────────────────────────────


class TestDialogTabStructure:
    def test_three_tabs_in_order(self, qapp, issuer_repo, investment_repo) -> None:
        dlg = _make_dialog(issuer_repo, investment_repo, qapp)
        assert dlg._tabs.count() == 3
        assert dlg._tabs.tabText(0) == "Issuers"
        assert dlg._tabs.tabText(1) == "Conglomerates"
        assert dlg._tabs.tabText(2) == "Custodians"

    def test_conglomerates_tab_has_table(
        self, qapp, issuer_repo, investment_repo
    ) -> None:
        dlg = _make_dialog(issuer_repo, investment_repo, qapp)
        assert isinstance(dlg._conglomerates_table, QTableWidget)

    def test_custodians_tab_has_placeholder_label(
        self, qapp, issuer_repo, investment_repo
    ) -> None:
        dlg = _make_dialog(issuer_repo, investment_repo, qapp)
        widget = dlg._tabs.widget(2)
        labels = widget.findChildren(QLabel)
        assert any("soon" in lbl.text().lower() or "coming" in lbl.text().lower()
                   for lbl in labels)


# ── Issuers table content ─────────────────────────────────────────────────────


class TestIssuersTableContent:
    def test_lists_all_issuers_including_orphan(
        self, qapp, issuer_repo, investment_repo
    ) -> None:
        a = _make_issuer("Banco Alpha")
        b = _make_issuer("Banco Beta")   # orphan — no investments
        issuer_repo.save(a)
        issuer_repo.save(b)
        inv = _make_investment(a)
        investment_repo.save(inv)

        dlg = _make_dialog(issuer_repo, investment_repo, qapp)
        table = dlg._issuers_table
        row_count = table.rowCount()
        names = {table.item(r, 0).text() for r in range(row_count)}
        assert "Banco Alpha" in names
        assert "Banco Beta" in names

    def test_investment_count_shown_per_row(
        self, qapp, issuer_repo, investment_repo
    ) -> None:
        a = _make_issuer("Banco Alpha")
        b = _make_issuer("Banco Beta")
        issuer_repo.save(a)
        issuer_repo.save(b)
        investment_repo.save(
            _make_investment(a, purchase_date=date(2024, 1, 1), maturity_date=date(2026, 1, 1))
        )
        investment_repo.save(
            _make_investment(a, purchase_date=date(2024, 2, 1), maturity_date=date(2026, 2, 1))
        )

        dlg = _make_dialog(issuer_repo, investment_repo, qapp)
        table = dlg._issuers_table

        counts_by_name: dict[str, str] = {}
        for r in range(table.rowCount()):
            name = table.item(r, 0).text()
            count = table.item(r, 3).text()
            counts_by_name[name] = count

        assert counts_by_name["Banco Alpha"] == "2"
        assert counts_by_name["Banco Beta"] == "0"


# ── Delete button enabled / disabled states ───────────────────────────────────


class TestDeleteButtonState:
    def test_delete_enabled_for_orphan(
        self, qapp, issuer_repo, investment_repo
    ) -> None:
        orphan = _make_issuer("Banco Orphan")
        issuer_repo.save(orphan)

        dlg = _make_dialog(issuer_repo, investment_repo, qapp)
        table = dlg._issuers_table
        # Find the row for the orphan
        for r in range(table.rowCount()):
            if table.item(r, 0).text() == "Banco Orphan":
                btn = table.cellWidget(r, 4)
                assert isinstance(btn, QPushButton)
                assert btn.isEnabled()
                return
        pytest.fail("Orphan row not found in table")

    def test_delete_disabled_for_issuer_with_investments(
        self, qapp, issuer_repo, investment_repo
    ) -> None:
        issuer = _make_issuer("Banco Busy")
        issuer_repo.save(issuer)
        investment_repo.save(_make_investment(issuer))

        dlg = _make_dialog(issuer_repo, investment_repo, qapp)
        table = dlg._issuers_table
        for r in range(table.rowCount()):
            if table.item(r, 0).text() == "Banco Busy":
                btn = table.cellWidget(r, 4)
                assert isinstance(btn, QPushButton)
                assert not btn.isEnabled()
                assert btn.toolTip() != ""
                return
        pytest.fail("Busy issuer row not found in table")

    def test_disabled_button_tooltip_mentions_count(
        self, qapp, issuer_repo, investment_repo
    ) -> None:
        issuer = _make_issuer("Banco Busy")
        issuer_repo.save(issuer)
        investment_repo.save(_make_investment(issuer))

        dlg = _make_dialog(issuer_repo, investment_repo, qapp)
        table = dlg._issuers_table
        for r in range(table.rowCount()):
            if table.item(r, 0).text() == "Banco Busy":
                btn = table.cellWidget(r, 4)
                assert "1" in btn.toolTip()
                return
        pytest.fail("Busy issuer row not found in table")


# ── Delete action ─────────────────────────────────────────────────────────────


class TestDeleteAction:
    def test_confirming_delete_calls_repo_and_removes_row(
        self, qapp, issuer_repo, investment_repo
    ) -> None:
        orphan = _make_issuer("Banco Orphan")
        issuer_repo.save(orphan)

        dlg = _make_dialog(issuer_repo, investment_repo, qapp)

        with patch.object(
            QMessageBox,
            "question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            dlg._on_delete_issuer(orphan)

        # Row should be gone: repo has no issuers left
        assert issuer_repo.find_by_id(orphan.id) is None
        # Table should be repopulated
        assert dlg._issuers_table.rowCount() == 0

    def test_declining_delete_does_not_call_repo(
        self, qapp, issuer_repo, investment_repo
    ) -> None:
        orphan = _make_issuer("Banco Orphan")
        issuer_repo.save(orphan)

        dlg = _make_dialog(issuer_repo, investment_repo, qapp)

        with patch.object(
            QMessageBox,
            "question",
            return_value=QMessageBox.StandardButton.No,
        ):
            dlg._on_delete_issuer(orphan)

        # Issuer must still exist
        assert issuer_repo.find_by_id(orphan.id) is not None
        # Table row still present
        assert dlg._issuers_table.rowCount() == 1


# ── MainWindow launch method ──────────────────────────────────────────────────


class TestOpenManageReferenceData:
    def test_constructs_dialog_and_calls_exec_and_refresh(self) -> None:
        # _session_factory is assigned in __init__, not a class attr, so set
        # it explicitly on the mock rather than relying on spec inference.
        self_mock = MagicMock()
        self_mock._session_factory = MagicMock()

        with patch(
            "justfixed.ui.main.ManageReferenceDataDialog"
        ) as MockDlg:
            mock_dlg_instance = MagicMock()
            MockDlg.return_value = mock_dlg_instance

            MainWindow._open_manage_reference_data(self_mock)

        assert MockDlg.call_count == 1
        args, kwargs = MockDlg.call_args
        assert isinstance(args[0], IssuerRepository)
        assert isinstance(args[1], InvestmentRepository)
        assert kwargs["parent"] is self_mock
        mock_dlg_instance.exec.assert_called_once()
        self_mock.refresh_table.assert_called_once()


# ── Conglomerates tab content ─────────────────────────────────────────────────


class TestConglomeratesTabContent:
    def test_lists_curated_conglomerates_excludes_unverified(
        self, qapp, issuer_repo, investment_repo
    ) -> None:
        curated = Issuer.create("Banco Alpha", "Curated Group", IssuerKind.COMMERCIAL_BANK)
        unverified = Issuer.create(
            "Banco Beta",
            f"{UNVERIFIED_CONGLOMERATE_PREFIX}Banco Beta",
            IssuerKind.COMMERCIAL_BANK,
        )
        issuer_repo.save(curated)
        issuer_repo.save(unverified)

        dlg = _make_dialog(issuer_repo, investment_repo, qapp)
        table = dlg._conglomerates_table
        names = {table.item(r, 0).text() for r in range(table.rowCount())}
        assert "Curated Group" in names
        assert f"{UNVERIFIED_CONGLOMERATE_PREFIX}Banco Beta" not in names

    def test_correct_issuer_and_investment_counts(
        self, qapp, issuer_repo, investment_repo
    ) -> None:
        a = Issuer.create("Banco Alpha", "Group A", IssuerKind.COMMERCIAL_BANK)
        b = Issuer.create("Banco Beta", "Group A", IssuerKind.COMMERCIAL_BANK)
        c = Issuer.create("Banco Gamma", "Group B", IssuerKind.COMMERCIAL_BANK)
        issuer_repo.save(a)
        issuer_repo.save(b)
        issuer_repo.save(c)
        investment_repo.save(
            _make_investment(a, purchase_date=date(2024, 1, 1), maturity_date=date(2026, 1, 1))
        )
        investment_repo.save(
            _make_investment(b, purchase_date=date(2024, 2, 1), maturity_date=date(2026, 2, 1))
        )
        investment_repo.save(
            _make_investment(c, purchase_date=date(2024, 3, 1), maturity_date=date(2026, 3, 1))
        )

        dlg = _make_dialog(issuer_repo, investment_repo, qapp)
        table = dlg._conglomerates_table

        data: dict[str, dict] = {}
        for r in range(table.rowCount()):
            name = table.item(r, 0).text()
            data[name] = {
                "issuers": table.item(r, 1).text(),
                "investments": table.item(r, 2).text(),
            }

        assert data["Group A"]["issuers"] == "2"
        assert data["Group A"]["investments"] == "2"
        assert data["Group B"]["issuers"] == "1"
        assert data["Group B"]["investments"] == "1"


# ── Rename conglomerate ───────────────────────────────────────────────────────


class TestRenameConglomerate:
    def test_rename_to_new_name_calls_repo_and_refreshes(
        self, qapp, issuer_repo, investment_repo
    ) -> None:
        a = Issuer.create("Banco Alpha", "Old Group", IssuerKind.COMMERCIAL_BANK)
        issuer_repo.save(a)

        dlg = _make_dialog(issuer_repo, investment_repo, qapp)

        with patch.object(QInputDialog, "getText", return_value=("New Group", True)):
            dlg._on_rename_conglomerate("Old Group")

        assert issuer_repo.find_by_id(a.id).conglomerate == "New Group"
        cong_names = {
            dlg._conglomerates_table.item(r, 0).text()
            for r in range(dlg._conglomerates_table.rowCount())
        }
        assert "Old Group" not in cong_names
        assert "New Group" in cong_names

    def test_rename_onto_existing_confirms_merge_on_yes_calls_repo(
        self, qapp, issuer_repo, investment_repo
    ) -> None:
        a = Issuer.create("Banco Alpha", "Group A", IssuerKind.COMMERCIAL_BANK)
        b = Issuer.create("Banco Beta", "Group B", IssuerKind.COMMERCIAL_BANK)
        issuer_repo.save(a)
        issuer_repo.save(b)

        dlg = _make_dialog(issuer_repo, investment_repo, qapp)

        with patch.object(QInputDialog, "getText", return_value=("Group B", True)):
            with patch.object(
                QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
            ):
                dlg._on_rename_conglomerate("Group A")

        assert issuer_repo.find_by_id(a.id).conglomerate == "Group B"
        assert dlg._conglomerates_table.rowCount() == 1
        assert dlg._conglomerates_table.item(0, 0).text() == "Group B"

    def test_rename_onto_existing_on_no_does_not_call_repo(
        self, qapp, issuer_repo, investment_repo
    ) -> None:
        a = Issuer.create("Banco Alpha", "Group A", IssuerKind.COMMERCIAL_BANK)
        b = Issuer.create("Banco Beta", "Group B", IssuerKind.COMMERCIAL_BANK)
        issuer_repo.save(a)
        issuer_repo.save(b)

        dlg = _make_dialog(issuer_repo, investment_repo, qapp)

        with patch.object(QInputDialog, "getText", return_value=("Group B", True)):
            with patch.object(
                QMessageBox, "question", return_value=QMessageBox.StandardButton.No
            ):
                dlg._on_rename_conglomerate("Group A")

        assert issuer_repo.find_by_id(a.id).conglomerate == "Group A"
        assert dlg._conglomerates_table.rowCount() == 2

    def test_rename_to_blank_does_not_call_repo(
        self, qapp, issuer_repo, investment_repo
    ) -> None:
        a = Issuer.create("Banco Alpha", "Group A", IssuerKind.COMMERCIAL_BANK)
        issuer_repo.save(a)

        dlg = _make_dialog(issuer_repo, investment_repo, qapp)

        with patch.object(QInputDialog, "getText", return_value=("", True)):
            with patch.object(QMessageBox, "warning") as mock_warn:
                dlg._on_rename_conglomerate("Group A")

        mock_warn.assert_called_once()
        assert issuer_repo.find_by_id(a.id).conglomerate == "Group A"

    def test_rename_to_whitespace_does_not_call_repo(
        self, qapp, issuer_repo, investment_repo
    ) -> None:
        a = Issuer.create("Banco Alpha", "Group A", IssuerKind.COMMERCIAL_BANK)
        issuer_repo.save(a)

        dlg = _make_dialog(issuer_repo, investment_repo, qapp)

        with patch.object(QInputDialog, "getText", return_value=("   ", True)):
            with patch.object(QMessageBox, "warning"):
                dlg._on_rename_conglomerate("Group A")

        assert issuer_repo.find_by_id(a.id).conglomerate == "Group A"

    def test_cancel_does_not_call_repo(
        self, qapp, issuer_repo, investment_repo
    ) -> None:
        a = Issuer.create("Banco Alpha", "Group A", IssuerKind.COMMERCIAL_BANK)
        issuer_repo.save(a)

        dlg = _make_dialog(issuer_repo, investment_repo, qapp)

        with patch.object(QInputDialog, "getText", return_value=("Whatever", False)):
            dlg._on_rename_conglomerate("Group A")

        assert issuer_repo.find_by_id(a.id).conglomerate == "Group A"


# ── Dissolve conglomerate ─────────────────────────────────────────────────────


class TestDissolveConglomerate:
    def test_dissolve_confirmed_calls_repo_and_row_disappears(
        self, qapp, issuer_repo, investment_repo
    ) -> None:
        a = Issuer.create("Banco Alpha", "Group A", IssuerKind.COMMERCIAL_BANK)
        issuer_repo.save(a)

        dlg = _make_dialog(issuer_repo, investment_repo, qapp)
        assert dlg._conglomerates_table.rowCount() == 1

        with patch.object(
            QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
        ):
            dlg._on_dissolve_conglomerate("Group A")

        assert dlg._conglomerates_table.rowCount() == 0
        assert issuer_repo.find_by_id(a.id).conglomerate.startswith(
            UNVERIFIED_CONGLOMERATE_PREFIX
        )

    def test_dissolve_declined_does_not_call_repo(
        self, qapp, issuer_repo, investment_repo
    ) -> None:
        a = Issuer.create("Banco Alpha", "Group A", IssuerKind.COMMERCIAL_BANK)
        issuer_repo.save(a)

        dlg = _make_dialog(issuer_repo, investment_repo, qapp)

        with patch.object(
            QMessageBox, "question", return_value=QMessageBox.StandardButton.No
        ):
            dlg._on_dissolve_conglomerate("Group A")

        assert issuer_repo.find_by_id(a.id).conglomerate == "Group A"
        assert dlg._conglomerates_table.rowCount() == 1


# ── Cross-tab consistency ─────────────────────────────────────────────────────


class TestCrossTabConsistency:
    def test_rename_updates_issuers_tab_conglomerate_column(
        self, qapp, issuer_repo, investment_repo
    ) -> None:
        a = Issuer.create("Banco Alpha", "Old Group", IssuerKind.COMMERCIAL_BANK)
        issuer_repo.save(a)

        dlg = _make_dialog(issuer_repo, investment_repo, qapp)

        with patch.object(QInputDialog, "getText", return_value=("New Group", True)):
            dlg._on_rename_conglomerate("Old Group")

        table = dlg._issuers_table
        for r in range(table.rowCount()):
            if table.item(r, 0).text() == "Banco Alpha":
                assert table.item(r, 1).text() == "New Group"
                return
        pytest.fail("Banco Alpha not found in issuers table after rename")
