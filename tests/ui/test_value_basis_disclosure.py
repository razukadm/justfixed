"""Tests for F-05: 'valor na curva' disclosure at point of display.

Covers:
1. String constants: STR.VALUE_BASIS_NOTE and STR.PROJ_CURRENT_TAG exact text.
2. InvestmentDetailPanel._proj_current_tag_lbl: existence, initial hidden state,
   tag text, and visibility gating (visible iff the panel shows proj.current_value).
3. Footer label (MainWindow._value_basis_note): MainWindow requires a live DB to
   instantiate and is not exercised here. Widget presence and text are verified
   by the screenshot gate (run the app, confirm the footer reads as a quiet
   disclaimer at the bottom of the Investments tab).
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication

from justfixed.domain.investment import Investment
from justfixed.domain.issuer import Issuer, IssuerKind
from justfixed.domain.money import Money
from justfixed.domain.product import CouponFrequency, ProductType
from justfixed.domain.rates import PostFixedCDI
from justfixed.engine.projection import ProjectionResult
from justfixed.engine.tax import TaxResult
from justfixed.ui.main import InvestmentDetailPanel
from justfixed.ui.strings import STR


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


# ── Investment / projection helpers ─────────────────────────────────────────────

_PURCHASE = date(2025, 1, 2)
_MATURITY = date(2026, 1, 2)


def _make_inv(**overrides) -> Investment:
    defaults: dict = dict(
        product=ProductType.CDB,
        issuer=Issuer.create("Banco Teste", "Banco Teste S.A.", IssuerKind.COMMERCIAL_BANK),
        principal=Money.from_reais("10000"),
        rate=PostFixedCDI.from_percent("110"),
        purchase_date=_PURCHASE,
        maturity_date=_MATURITY,
        coupon_frequency=CouponFrequency.NONE,
    )
    defaults.update(overrides)
    return Investment.create(**defaults)


def _make_proj(inv: Investment) -> ProjectionResult:
    return ProjectionResult(
        investment=inv,
        as_of=_MATURITY,
        current_value=Money.from_reais("11000"),
        cash_flows=[],
        gross_at_maturity=Money.from_reais("11000"),
        tax_breakdown=TaxResult(
            gross=Money.from_reais("11000"),
            gain=Money.from_reais("1000"),
            tax_rate=Decimal("0.225"),
            tax_amount=Money.from_reais("225"),
            net=Money.from_reais("10775"),
        ),
        net_at_maturity=Money.from_reais("10775"),
    )


def _panel_with_proj(inv: Investment) -> InvestmentDetailPanel:
    """Build a panel with a populated projection cache, then call show_investment."""
    main_win = MagicMock()
    main_win.projection_cache = [_make_proj(inv)]
    panel = InvestmentDetailPanel(MagicMock(), main_win)
    panel.show_investment(inv)
    return panel


# ── 1. String constants ──────────────────────────────────────────────────────────

class TestDisclosureStrings:
    def test_value_basis_note_exact_text(self) -> None:
        assert STR.VALUE_BASIS_NOTE == (
            "Valor atual = valor na curva (não marcação a mercado)"
        )

    def test_proj_current_tag_exact_text(self) -> None:
        assert STR.PROJ_CURRENT_TAG == "valor na curva"


# ── 2. Detail-panel tag widget ───────────────────────────────────────────────────

class TestProjCurrentTagLabel:
    def test_tag_label_exists(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        assert hasattr(panel, "_proj_current_tag_lbl")

    def test_tag_label_starts_hidden(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        assert panel._proj_current_tag_lbl.isHidden()

    def test_tag_label_text_matches_string(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        assert panel._proj_current_tag_lbl.text() == STR.PROJ_CURRENT_TAG


class TestTagVisibilityGating:
    def test_tag_visible_for_bare_computed_value(self, qapp) -> None:
        inv = _make_inv()
        panel = _panel_with_proj(inv)
        assert not panel._proj_current_tag_lbl.isHidden()

    def test_tag_hidden_for_user_edited_value(self, qapp) -> None:
        inv = _make_inv(user_edited_value=Money.from_reais("10500"))
        panel = _panel_with_proj(inv)
        assert panel._proj_current_tag_lbl.isHidden()

    def test_tag_hidden_for_broker_reported_value(self, qapp) -> None:
        inv = _make_inv(broker_reported_value=Money.from_reais("10200"))
        panel = _panel_with_proj(inv)
        assert panel._proj_current_tag_lbl.isHidden()

    def test_tag_hidden_after_clear(self, qapp) -> None:
        inv = _make_inv()
        panel = _panel_with_proj(inv)
        assert not panel._proj_current_tag_lbl.isHidden()  # shown after projection
        panel.clear()
        assert panel._proj_current_tag_lbl.isHidden()

    def test_tag_hidden_when_no_cache(self, qapp) -> None:
        main_win = MagicMock()
        main_win.projection_cache = None
        panel = InvestmentDetailPanel(MagicMock(), main_win)
        panel.show_investment(_make_inv())
        assert panel._proj_current_tag_lbl.isHidden()

    def test_tag_hidden_when_investment_not_in_cache(self, qapp) -> None:
        other_inv = _make_inv()
        inv = _make_inv()
        main_win = MagicMock()
        main_win.projection_cache = [_make_proj(other_inv)]
        panel = InvestmentDetailPanel(MagicMock(), main_win)
        panel.show_investment(inv)
        assert panel._proj_current_tag_lbl.isHidden()
