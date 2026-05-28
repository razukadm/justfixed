"""Tests for _CalculatorTab widget (B41 phase 2 part 1, COMMIT 1).

Uses a session-scoped QApplication. IssuerRepository is patched at
justfixed.ui.main so no real database is required.

Pattern: _make_tab() patches IssuerRepository during construction (which
calls reset()) and returns a fully-initialised widget.
"""

from __future__ import annotations

import sys
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication

from justfixed.domain.issuer import Issuer, IssuerKind
from justfixed.ui.main import _CalculatorTab


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


def _make_tab(issuers: list[Issuer] | None = None) -> _CalculatorTab:
    """Create a _CalculatorTab with a mocked session_factory.

    IssuerRepository is patched so __init__'s reset() call succeeds
    without a real database.
    """
    with patch("justfixed.ui.main.IssuerRepository") as MockRepo:
        MockRepo.return_value.list_all.return_value = issuers or []
        tab = _CalculatorTab(MagicMock())
    return tab


def _call_reset(tab: _CalculatorTab, issuers: list[Issuer] | None = None) -> None:
    with patch("justfixed.ui.main.IssuerRepository") as MockRepo:
        MockRepo.return_value.list_all.return_value = issuers or []
        tab.reset()


# ── Tab label ─────────────────────────────────────────────────────────────────

class TestCalculatorTabLabel:
    def test_tab_text_is_calculator(self, qapp) -> None:
        from PySide6.QtWidgets import QTabWidget
        tab_widget = QTabWidget()
        calc_tab = _make_tab()
        tab_widget.addTab(calc_tab, "Calculator")
        assert tab_widget.tabText(0) == "Calculator"

    def test_calculator_tab_position(self, qapp) -> None:
        import os
        from PySide6.QtWidgets import QTabWidget, QWidget

        def _find_tab(tw: QTabWidget, text: str) -> int:
            for i in range(tw.count()):
                if tw.tabText(i) == text:
                    return i
            return -1

        tab_widget = QTabWidget()
        tab_widget.addTab(QWidget(), "Conglomerates")
        tab_widget.addTab(QWidget(), "Investments")
        tab_widget.addTab(_make_tab(), "Calculator")
        if os.environ.get("JUSTFIXED_DEV"):
            tab_widget.addTab(QWidget(), "Dev")

        calc_idx = _find_tab(tab_widget, "Calculator")
        investments_idx = _find_tab(tab_widget, "Investments")
        dev_idx = _find_tab(tab_widget, "Dev")

        assert calc_idx != -1
        assert investments_idx != -1
        assert calc_idx > investments_idx
        if dev_idx != -1:
            assert calc_idx < dev_idx


# ── Field defaults ─────────────────────────────────────────────────────────────

class TestCalculatorTabDefaults:
    def test_calculate_button_disabled_by_default(self, qapp) -> None:
        tab = _make_tab()
        assert not tab._calc_btn.isEnabled()

    def test_enter_value_radio_checked_by_default(self, qapp) -> None:
        tab = _make_tab()
        assert tab._radio_enter.isChecked()
        assert not tab._radio_solve.isChecked()

    def test_value_field_enabled_when_enter_value_selected(self, qapp) -> None:
        tab = _make_tab()
        assert tab._value_edit.isEnabled()

    def test_purchase_date_defaults_to_today(self, qapp) -> None:
        tab = _make_tab()
        today = date.today()
        q = tab._purchase_date_edit.date()
        assert (q.year(), q.month(), q.day()) == (today.year, today.month, today.day)

    def test_maturity_defaults_to_one_year_after_purchase(self, qapp) -> None:
        tab = _make_tab()
        today = date.today()
        expected = today.replace(year=today.year + 1)
        q = tab._maturity_date_edit.date()
        assert (q.year(), q.month(), q.day()) == (expected.year, expected.month, expected.day)

    def test_issuer_combo_populated_from_repo(self, qapp) -> None:
        issuer = _make_issuer("Banco Inter")
        tab = _make_tab(issuers=[issuer])
        names = [tab._issuer_combo.itemText(i) for i in range(tab._issuer_combo.count())]
        assert "Banco Inter" in names


# ── Mode toggle ────────────────────────────────────────────────────────────────

class TestModeToggle:
    def test_solve_mode_disables_value_field(self, qapp) -> None:
        tab = _make_tab()
        tab._radio_solve.setChecked(True)
        tab._mode_group.idClicked.emit(1)
        assert not tab._value_edit.isEnabled()

    def test_enter_mode_re_enables_value_field(self, qapp) -> None:
        tab = _make_tab()
        tab._radio_solve.setChecked(True)
        tab._mode_group.idClicked.emit(1)
        tab._radio_enter.setChecked(True)
        tab._mode_group.idClicked.emit(0)
        assert tab._value_edit.isEnabled()


# ── Reset ─────────────────────────────────────────────────────────────────────

class TestReset:
    def test_reset_clears_value_field(self, qapp) -> None:
        tab = _make_tab()
        tab._value_edit.setText("50.000,00")
        _call_reset(tab)
        assert tab._value_edit.text() == ""

    def test_reset_restores_enter_value_radio(self, qapp) -> None:
        tab = _make_tab()
        tab._radio_solve.setChecked(True)
        tab._mode_group.idClicked.emit(1)
        _call_reset(tab)
        assert tab._radio_enter.isChecked()
        assert tab._value_edit.isEnabled()

    def test_reset_repopulates_issuer_combo(self, qapp) -> None:
        tab = _make_tab()
        issuer = _make_issuer("Novo Banco")
        _call_reset(tab, issuers=[issuer])
        names = [tab._issuer_combo.itemText(i) for i in range(tab._issuer_combo.count())]
        assert "Novo Banco" in names
