"""Tests for InvestmentDetailPanel widget.

Uses a session-scoped QApplication so Qt objects can be instantiated
without a running event loop. Investment data is mocked; no real
database or window is created.
"""

from __future__ import annotations

import sys
import types
from datetime import date
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication

from justfixed.domain.investment import InvestmentSource
from justfixed.domain.product import CouponFrequency, ProductType
from justfixed.ui.main import InvestmentDetailPanel


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


def _mock_inv(**overrides):
    """Minimal mock investment with all fields show_investment() reads.

    The issuer is a SimpleNamespace so .name and .conglomerate are plain
    attributes with no Mock magic (avoids the Mock.name footgun).
    """
    inv = MagicMock()
    inv.issuer = types.SimpleNamespace(
        name="Banco Inter",
        conglomerate="Banco Inter S.A.",
    )
    inv.product = ProductType.CDB
    inv.principal.to_display.return_value = "R$ 10.000,00"
    inv.rate.to_display.return_value = "112,00% do CDI"
    inv.purchase_date = date(2024, 1, 15)
    inv.issue_date = date(2024, 1, 15)
    inv.maturity_date = date(2026, 1, 15)
    inv.coupon_frequency = CouponFrequency.NONE
    inv.description = ""
    inv.source = InvestmentSource.XP_IMPORT
    for k, v in overrides.items():
        setattr(inv, k, v)
    return inv


class TestInvestmentDetailPanelConstruction:
    def test_instantiates_without_error(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        assert panel is not None


class TestInvestmentDetailPanelShowInvestment:
    def test_show_investment_updates_identity_label(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        panel.show_investment(_mock_inv())
        text = panel._identity_label.text()
        assert "Banco Inter" in text
        assert "CDB" in text

    def test_clear_resets_identity_label(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        panel.show_investment(_mock_inv())
        panel.clear()
        assert panel._identity_label.text() == "No investment selected."


class TestInvestmentDetailPanelCloseSignal:
    def test_close_button_emits_closed_signal(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        slot = MagicMock()
        panel.closed.connect(slot)
        panel._close_btn.click()
        slot.assert_called_once()


class TestInvestmentDetailPanelFieldDisplay:
    def test_issuer_and_product_populated(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        panel.show_investment(_mock_inv())
        assert panel._field_values["issuer"].text() == "Banco Inter"
        assert "CDB" in panel._field_values["product"].text()

    def test_principal_and_rate_populated(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        panel.show_investment(_mock_inv())
        assert panel._field_values["principal"].text() == "R$ 10.000,00"
        assert panel._field_values["rate"].text() == "112,00% do CDI"

    def test_description_shows_dash_when_empty(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        panel.show_investment(_mock_inv(description=""))
        assert panel._field_values["description"].text() == "—"

    def test_description_shows_text_when_set(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        panel.show_investment(_mock_inv(description="Some note"))
        assert panel._field_values["description"].text() == "Some note"

    def test_clear_empties_field_values(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        panel.show_investment(_mock_inv())
        panel.clear()
        assert panel._field_values["issuer"].text() == ""


class TestInvestmentDetailPanelSourceBanner:
    def test_xp_import_banner_visible(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        panel.show_investment(_mock_inv(source=InvestmentSource.XP_IMPORT))
        assert not panel._source_banner.isHidden()

    def test_manual_banner_hidden(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        panel.show_investment(_mock_inv(source=InvestmentSource.MANUAL))
        assert panel._source_banner.isHidden()

    def test_clear_hides_banner(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        panel.show_investment(_mock_inv())
        panel.clear()
        assert panel._source_banner.isHidden()
