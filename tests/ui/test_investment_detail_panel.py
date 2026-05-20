"""Tests for InvestmentDetailPanel widget.

Uses a session-scoped QApplication so Qt objects can be instantiated
without a running event loop. Investment data is mocked; no real
database or window is created.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication

from justfixed.domain.product import ProductType
from justfixed.ui.main import InvestmentDetailPanel


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


class TestInvestmentDetailPanelConstruction:
    def test_instantiates_without_error(self, qapp) -> None:
        panel = InvestmentDetailPanel()
        assert panel is not None


class TestInvestmentDetailPanelShowInvestment:
    def test_show_investment_updates_identity_label(self, qapp) -> None:
        panel = InvestmentDetailPanel()
        inv = MagicMock()
        inv.issuer.name = "Banco Inter"
        inv.product = ProductType.CDB
        panel.show_investment(inv)
        text = panel._identity_label.text()
        assert "Banco Inter" in text
        assert "CDB" in text

    def test_clear_resets_identity_label(self, qapp) -> None:
        panel = InvestmentDetailPanel()
        inv = MagicMock()
        inv.issuer.name = "Banco Inter"
        inv.product = ProductType.CDB
        panel.show_investment(inv)
        panel.clear()
        assert panel._identity_label.text() == "No investment selected."


class TestInvestmentDetailPanelCloseSignal:
    def test_close_button_emits_closed_signal(self, qapp) -> None:
        panel = InvestmentDetailPanel()
        slot = MagicMock()
        panel.closed.connect(slot)
        panel._close_btn.click()
        slot.assert_called_once()
