"""Tests for _AddInvestmentPanel widget.

Uses a session-scoped QApplication. Repositories are always mocked;
no real database or window is instantiated.

The "real widget, mocked dependencies" pattern mirrors
test_investment_detail_panel.py — _AddInvestmentPanel is constructed
with a MagicMock session_factory, and IssuerRepository /
InvestmentRepository are patched at justfixed.ui.main.*.
"""

from __future__ import annotations

import sys
import uuid
from datetime import date
from unittest.mock import MagicMock, patch, call

import pytest
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication

from justfixed.domain.investment import Investment, InvestmentSource
from justfixed.domain.issuer import Issuer, IssuerKind, UNVERIFIED_CONGLOMERATE_PREFIX
from justfixed.domain.money import Money
from justfixed.domain.product import CouponFrequency, ProductType
from justfixed.domain.rates import PostFixedCDI
from justfixed.ui.main import _AddInvestmentPanel, _NEW_ISSUER_SENTINEL


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


def _make_issuer(name: str = "Banco Inter") -> Issuer:
    return Issuer(
        name=name,
        conglomerate="Banco Inter S.A.",
        kind=IssuerKind.COMMERCIAL_BANK,
    )


def _make_panel(issuers: list[Issuer] | None = None) -> _AddInvestmentPanel:
    """Create a panel with a mocked session_factory.

    If issuers is provided, IssuerRepository.list_all returns them.
    reset() is called so the form is fully initialised.
    """
    panel = _AddInvestmentPanel(MagicMock(), MagicMock())
    _call_reset(panel, issuers or [])
    return panel


def _call_reset(panel: _AddInvestmentPanel, issuers: list[Issuer]) -> None:
    with patch("justfixed.ui.main.IssuerRepository") as MockRepo:
        MockRepo.return_value.list_all.return_value = issuers
        panel.reset()


# ── Construction ──────────────────────────────────────────────────────────────

class TestAddInvestmentPanelConstruction:
    def test_instantiates_without_error(self, qapp) -> None:
        panel = _AddInvestmentPanel(MagicMock(), MagicMock())
        assert panel is not None

    def test_error_label_hidden_by_default(self, qapp) -> None:
        panel = _AddInvestmentPanel(MagicMock(), MagicMock())
        assert panel._error_label.isHidden()

    def test_new_issuer_group_hidden_by_default(self, qapp) -> None:
        panel = _AddInvestmentPanel(MagicMock(), MagicMock())
        assert panel._new_issuer_group.isHidden()


# ── Issuer combo population ───────────────────────────────────────────────────

class TestIssuerCombo:
    def test_combo_includes_existing_issuers(self, qapp) -> None:
        issuer = _make_issuer("Banco Inter")
        panel = _make_panel(issuers=[issuer])

        names = [
            panel._issuer_combo.itemText(i)
            for i in range(panel._issuer_combo.count())
        ]
        assert "Banco Inter" in names

    def test_combo_sentinel_is_last_entry(self, qapp) -> None:
        issuer = _make_issuer("Banco Inter")
        panel = _make_panel(issuers=[issuer])

        last_data = panel._issuer_combo.itemData(panel._issuer_combo.count() - 1)
        assert last_data == _NEW_ISSUER_SENTINEL

    def test_combo_has_issuers_plus_sentinel(self, qapp) -> None:
        issuers = [_make_issuer("Alpha Bank"), _make_issuer("Beta Bank")]
        panel = _make_panel(issuers=issuers)
        # 2 real issuers + 1 sentinel
        assert panel._issuer_combo.count() == 3

    def test_empty_db_shows_only_sentinel(self, qapp) -> None:
        panel = _make_panel(issuers=[])
        assert panel._issuer_combo.count() == 1
        assert panel._issuer_combo.itemData(0) == _NEW_ISSUER_SENTINEL


# ── New-issuer sub-group visibility ──────────────────────────────────────────

class TestNewIssuerSubGroup:
    def test_selecting_sentinel_reveals_sub_group(self, qapp) -> None:
        issuer = _make_issuer("Banco Inter")
        panel = _make_panel(issuers=[issuer])

        sentinel_idx = panel._issuer_combo.count() - 1
        panel._issuer_combo.setCurrentIndex(sentinel_idx)

        assert not panel._new_issuer_group.isHidden()

    def test_selecting_real_issuer_hides_sub_group(self, qapp) -> None:
        issuer = _make_issuer("Banco Inter")
        panel = _make_panel(issuers=[issuer])

        # First reveal the sub-group via sentinel
        sentinel_idx = panel._issuer_combo.count() - 1
        panel._issuer_combo.setCurrentIndex(sentinel_idx)
        assert not panel._new_issuer_group.isHidden()

        # Now select the real issuer (index 0)
        panel._issuer_combo.setCurrentIndex(0)
        assert panel._new_issuer_group.isHidden()

    def test_sub_group_hidden_when_no_issuers_and_sentinel_selected(self, qapp) -> None:
        # With an empty DB the sentinel is at index 0; sub-group should be visible.
        panel = _make_panel(issuers=[])
        assert panel._issuer_combo.currentData() == _NEW_ISSUER_SENTINEL
        assert not panel._new_issuer_group.isHidden()


# ── Save — happy path ─────────────────────────────────────────────────────────

class TestAddInvestmentPanelSave:
    def _setup_panel_for_save(self, qapp, issuer: Issuer) -> _AddInvestmentPanel:
        """Create a panel with one real issuer, valid default dates."""
        panel = _make_panel(issuers=[issuer])
        # Select the real issuer (index 0)
        panel._issuer_combo.setCurrentIndex(0)
        # Principal
        panel._principal_edit.setText("10.000,00")
        # Dates: purchase/issue = today, maturity = today+365 (set by reset())
        return panel

    def test_valid_save_persists_investment_with_source_manual(self, qapp) -> None:
        issuer = _make_issuer()
        panel = self._setup_panel_for_save(qapp, issuer)

        with patch("justfixed.ui.main.InvestmentRepository") as MockInvRepo:
            panel._on_save_clicked()

        MockInvRepo.return_value.save.assert_called_once()
        saved_inv: Investment = MockInvRepo.return_value.save.call_args[0][0]
        assert saved_inv.source == InvestmentSource.MANUAL

    def test_valid_save_emits_saved_signal_with_investment_id(self, qapp) -> None:
        issuer = _make_issuer()
        panel = self._setup_panel_for_save(qapp, issuer)

        emitted_ids: list[uuid.UUID] = []
        panel.saved.connect(lambda inv_id: emitted_ids.append(inv_id))

        with patch("justfixed.ui.main.InvestmentRepository"):
            panel._on_save_clicked()

        assert len(emitted_ids) == 1
        assert isinstance(emitted_ids[0], uuid.UUID)

    def test_valid_save_clears_error_label(self, qapp) -> None:
        issuer = _make_issuer()
        panel = self._setup_panel_for_save(qapp, issuer)
        panel._set_error("prior error")

        with patch("justfixed.ui.main.InvestmentRepository"):
            panel._on_save_clicked()

        assert panel._error_label.isHidden()

    def test_save_uses_selected_issuer(self, qapp) -> None:
        issuer = _make_issuer("Banco Inter")
        panel = self._setup_panel_for_save(qapp, issuer)

        with patch("justfixed.ui.main.InvestmentRepository") as MockInvRepo:
            panel._on_save_clicked()

        saved_inv: Investment = MockInvRepo.return_value.save.call_args[0][0]
        assert saved_inv.issuer.name == "Banco Inter"

    def test_save_uses_selected_product(self, qapp) -> None:
        issuer = _make_issuer()
        panel = self._setup_panel_for_save(qapp, issuer)
        # Select CDB (the first product in the combo, same as ProductType iteration order)
        panel._product_combo.setCurrentIndex(0)

        with patch("justfixed.ui.main.InvestmentRepository") as MockInvRepo:
            panel._on_save_clicked()

        saved_inv: Investment = MockInvRepo.return_value.save.call_args[0][0]
        assert saved_inv.product == panel._product_combo.currentData()


# ── Save — validation failures ────────────────────────────────────────────────

class TestAddInvestmentPanelValidation:
    def test_maturity_before_purchase_shows_error_no_persist(self, qapp) -> None:
        issuer = _make_issuer()
        panel = _make_panel(issuers=[issuer])
        panel._issuer_combo.setCurrentIndex(0)
        panel._principal_edit.setText("10.000,00")

        # Set maturity before purchase
        today = date.today()
        panel._purchase_date_edit.setDate(QDate(today.year, today.month, today.day))
        panel._issue_date_edit.setDate(QDate(today.year, today.month, today.day))
        yesterday = QDate(today.year, today.month, today.day).addDays(-1)
        panel._maturity_date_edit.setDate(yesterday)

        with patch("justfixed.ui.main.InvestmentRepository") as MockInvRepo:
            panel._on_save_clicked()

        MockInvRepo.return_value.save.assert_not_called()
        assert not panel._error_label.isHidden()
        assert panel._error_label.text() != ""

    def test_blank_principal_shows_error_no_persist(self, qapp) -> None:
        issuer = _make_issuer()
        panel = _make_panel(issuers=[issuer])
        panel._issuer_combo.setCurrentIndex(0)
        panel._principal_edit.setText("")  # blank

        with patch("justfixed.ui.main.InvestmentRepository") as MockInvRepo:
            panel._on_save_clicked()

        MockInvRepo.return_value.save.assert_not_called()
        assert not panel._error_label.isHidden()

    def test_invalid_rate_shows_error_no_persist(self, qapp) -> None:
        issuer = _make_issuer()
        panel = _make_panel(issuers=[issuer])
        panel._issuer_combo.setCurrentIndex(0)
        panel._principal_edit.setText("10.000,00")
        panel._rate_editor._line.setText("abc")

        with patch("justfixed.ui.main.InvestmentRepository") as MockInvRepo:
            panel._on_save_clicked()

        MockInvRepo.return_value.save.assert_not_called()
        assert not panel._error_label.isHidden()


# ── New-issuer save paths ─────────────────────────────────────────────────────

class TestNewIssuerPath:
    def _select_sentinel(self, panel: _AddInvestmentPanel) -> None:
        sentinel_idx = panel._issuer_combo.count() - 1
        panel._issuer_combo.setCurrentIndex(sentinel_idx)

    def test_collision_shows_error_issuer_repo_save_not_called(self, qapp) -> None:
        existing_issuer = _make_issuer("Banco Inter")
        panel = _make_panel(issuers=[])
        self._select_sentinel(panel)
        panel._new_name_edit.setText("Banco Inter")
        panel._new_cong_edit.setText("Some Conglomerate")
        panel._principal_edit.setText("10.000,00")

        with patch("justfixed.ui.main.IssuerRepository") as MockIssuerRepo, \
             patch("justfixed.ui.main.InvestmentRepository") as MockInvRepo:
            MockIssuerRepo.return_value.find_by_normalized_name.return_value = existing_issuer
            panel._on_save_clicked()

        # find_by_normalized_name normalizes internally — _resolve_issuer must pass
        # the raw user input (the same contract the XP loader follows).
        MockIssuerRepo.return_value.find_by_normalized_name.assert_called_once_with("Banco Inter")
        MockIssuerRepo.return_value.save.assert_not_called()
        MockInvRepo.return_value.save.assert_not_called()
        assert not panel._error_label.isHidden()
        assert "already exists" in panel._error_label.text()

    def test_collision_by_different_casing_shows_error(self, qapp) -> None:
        # User types lowercase; the stored issuer has title-case name.
        # find_by_normalized_name normalizes both, so it finds the collision.
        # _resolve_issuer must pass raw input so the method can normalize it.
        existing_issuer = _make_issuer("Banco Inter")
        panel = _make_panel(issuers=[])
        self._select_sentinel(panel)
        panel._new_name_edit.setText("banco inter")  # lowercase
        panel._new_cong_edit.setText("Some Conglomerate")
        panel._principal_edit.setText("10.000,00")

        with patch("justfixed.ui.main.IssuerRepository") as MockIssuerRepo, \
             patch("justfixed.ui.main.InvestmentRepository") as MockInvRepo:
            MockIssuerRepo.return_value.find_by_normalized_name.return_value = existing_issuer
            panel._on_save_clicked()

        # Raw input "banco inter" is passed; the method normalizes it to "BANCO INTER".
        MockIssuerRepo.return_value.find_by_normalized_name.assert_called_once_with("banco inter")
        MockIssuerRepo.return_value.save.assert_not_called()
        MockInvRepo.return_value.save.assert_not_called()
        assert not panel._error_label.isHidden()
        assert "already exists" in panel._error_label.text()

    def test_fresh_name_persists_issuer_then_investment(self, qapp) -> None:
        panel = _make_panel(issuers=[])
        self._select_sentinel(panel)
        panel._new_name_edit.setText("Novo Banco S.A.")
        panel._new_cong_edit.setText("Novo Holding")
        # Set a valid kind — pick COMMERCIAL_BANK by finding it in the combo
        idx = panel._new_kind_combo.findData(IssuerKind.COMMERCIAL_BANK)
        panel._new_kind_combo.setCurrentIndex(idx)
        panel._principal_edit.setText("10.000,00")

        saved_calls: list = []

        with patch("justfixed.ui.main.IssuerRepository") as MockIssuerRepo, \
             patch("justfixed.ui.main.InvestmentRepository") as MockInvRepo:
            MockIssuerRepo.return_value.find_by_normalized_name.return_value = None
            MockIssuerRepo.return_value.save.side_effect = lambda obj: saved_calls.append(("issuer", obj))
            MockInvRepo.return_value.save.side_effect = lambda obj: saved_calls.append(("investment", obj))
            panel._on_save_clicked()

        assert len(saved_calls) == 2
        assert saved_calls[0][0] == "issuer"
        assert saved_calls[1][0] == "investment"
        saved_issuer: Issuer = saved_calls[0][1]
        assert saved_issuer.name == "Novo Banco S.A."
        assert saved_issuer.conglomerate == "Novo Holding"
        saved_inv: Investment = saved_calls[1][1]
        assert saved_inv.source == InvestmentSource.MANUAL

    def test_fresh_name_blank_conglomerate_uses_unverified_prefix(self, qapp) -> None:
        panel = _make_panel(issuers=[])
        self._select_sentinel(panel)
        panel._new_name_edit.setText("Novo Banco S.A.")
        panel._new_cong_edit.setText("")  # left blank
        idx = panel._new_kind_combo.findData(IssuerKind.COMMERCIAL_BANK)
        panel._new_kind_combo.setCurrentIndex(idx)
        panel._principal_edit.setText("10.000,00")

        with patch("justfixed.ui.main.IssuerRepository") as MockIssuerRepo, \
             patch("justfixed.ui.main.InvestmentRepository"):
            MockIssuerRepo.return_value.find_by_normalized_name.return_value = None
            panel._on_save_clicked()

        saved_issuer: Issuer = MockIssuerRepo.return_value.save.call_args[0][0]
        assert saved_issuer.conglomerate.startswith(UNVERIFIED_CONGLOMERATE_PREFIX)

    def test_blank_new_issuer_name_shows_error(self, qapp) -> None:
        panel = _make_panel(issuers=[])
        self._select_sentinel(panel)
        panel._new_name_edit.setText("")  # blank name
        panel._principal_edit.setText("10.000,00")

        with patch("justfixed.ui.main.IssuerRepository") as MockIssuerRepo, \
             patch("justfixed.ui.main.InvestmentRepository") as MockInvRepo:
            panel._on_save_clicked()

        MockIssuerRepo.return_value.save.assert_not_called()
        MockInvRepo.return_value.save.assert_not_called()
        assert not panel._error_label.isHidden()


# ── Reset ─────────────────────────────────────────────────────────────────────

class TestReset:
    def test_reset_clears_error(self, qapp) -> None:
        panel = _AddInvestmentPanel(MagicMock(), MagicMock())
        panel._set_error("prior error")
        _call_reset(panel, [])
        assert panel._error_label.isHidden()

    def test_reset_repopulates_issuer_combo(self, qapp) -> None:
        panel = _AddInvestmentPanel(MagicMock(), MagicMock())
        _call_reset(panel, [])
        assert panel._issuer_combo.count() == 1  # only sentinel

        issuer = _make_issuer("New Issuer")
        _call_reset(panel, [issuer])
        assert panel._issuer_combo.count() == 2  # issuer + sentinel

    def test_reset_clears_principal(self, qapp) -> None:
        panel = _make_panel(issuers=[])
        panel._principal_edit.setText("99.999,00")
        _call_reset(panel, [])
        assert panel._principal_edit.text() == ""

    def test_reset_clears_description(self, qapp) -> None:
        panel = _make_panel(issuers=[])
        panel._description_edit.setText("old note")
        _call_reset(panel, [])
        assert panel._description_edit.text() == ""

    def test_cancelled_signal_emitted_on_cancel_click(self, qapp) -> None:
        panel = _make_panel(issuers=[])
        fired: list = []
        panel.cancelled.connect(lambda: fired.append(True))
        panel._cancel_btn.click()
        assert fired == [True]


# ── CA-4: Save button has toolbar role ───────────────────────────────────────

class TestSaveButtonRole:
    """CA-4: Save is the primary commit action → green toolbar accent."""

    def test_save_button_has_toolbar_role(self, qapp) -> None:
        panel = _make_panel(issuers=[])
        assert panel._save_btn.property("role") == "toolbar"

    def test_cancel_button_has_danger_role(self, qapp) -> None:
        panel = _make_panel(issuers=[])
        assert panel._cancel_btn.property("role") == "danger"
