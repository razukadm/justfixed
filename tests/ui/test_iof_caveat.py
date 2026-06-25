"""Tests for the IOF caveat tag in the detail panel (R4 Part 2a).

Verifies that _proj_iof_lbl is shown when the valuation date is within
30 calendar days of purchase, and hidden otherwise.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
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


_PURCHASE = date(2025, 6, 1)
_MATURITY = date(2026, 6, 1)


def _make_inv(**overrides) -> Investment:
    defaults: dict = dict(
        product=ProductType.CDB,
        issuer=Issuer.create("Banco IOF", "Banco IOF S.A.", IssuerKind.COMMERCIAL_BANK),
        principal=Money.from_reais("10000"),
        rate=PostFixedCDI.from_percent("110"),
        purchase_date=_PURCHASE,
        maturity_date=_MATURITY,
        coupon_frequency=CouponFrequency.NONE,
    )
    defaults.update(overrides)
    return Investment.create(**defaults)


def _make_proj(inv: Investment, *, as_of: date) -> ProjectionResult:
    return ProjectionResult(
        investment=inv,
        as_of=as_of,
        current_value=Money.from_reais("10050"),
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


def _panel_with_proj(inv: Investment, *, as_of: date) -> InvestmentDetailPanel:
    main_win = MagicMock()
    main_win.projection_cache = [_make_proj(inv, as_of=as_of)]
    panel = InvestmentDetailPanel(MagicMock(), main_win)
    panel.show_investment(inv)
    return panel


# ── 1. String constant ───────────────────────────────────────────────────────────

class TestIOFCaveatString:
    def test_proj_iof_caveat_exact_text(self) -> None:
        assert STR.PROJ_IOF_CAVEAT == "IOF não considerado (resgate < 30 dias)"


# ── 2. Widget existence and initial state ────────────────────────────────────────

class TestIOFLabelWidget:
    def test_iof_lbl_exists(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        assert hasattr(panel, "_proj_iof_lbl")

    def test_iof_lbl_starts_hidden(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        assert panel._proj_iof_lbl.isHidden()

    def test_iof_lbl_text_matches_string(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        assert panel._proj_iof_lbl.text() == STR.PROJ_IOF_CAVEAT


# ── 3–5. Visibility gating ───────────────────────────────────────────────────────

class TestIOFLabelVisibility:
    def test_visible_when_within_30_days(self, qapp) -> None:
        # 15 days after purchase → < 30 → tag visible
        inv = _make_inv()
        as_of = _PURCHASE + timedelta(days=15)
        panel = _panel_with_proj(inv, as_of=as_of)
        assert not panel._proj_iof_lbl.isHidden()

    def test_hidden_when_60_days_after_purchase(self, qapp) -> None:
        inv = _make_inv()
        as_of = _PURCHASE + timedelta(days=60)
        panel = _panel_with_proj(inv, as_of=as_of)
        assert panel._proj_iof_lbl.isHidden()

    def test_hidden_at_exactly_30_days(self, qapp) -> None:
        # Strict < 30: at exactly 30 days the tag must be hidden
        inv = _make_inv()
        as_of = _PURCHASE + timedelta(days=30)
        panel = _panel_with_proj(inv, as_of=as_of)
        assert panel._proj_iof_lbl.isHidden()

    def test_visible_at_29_days(self, qapp) -> None:
        inv = _make_inv()
        as_of = _PURCHASE + timedelta(days=29)
        panel = _panel_with_proj(inv, as_of=as_of)
        assert not panel._proj_iof_lbl.isHidden()

    def test_hidden_after_clear(self, qapp) -> None:
        inv = _make_inv()
        as_of = _PURCHASE + timedelta(days=5)
        panel = _panel_with_proj(inv, as_of=as_of)
        assert not panel._proj_iof_lbl.isHidden()  # shown first
        panel.clear()
        assert panel._proj_iof_lbl.isHidden()

    def test_hidden_when_no_cache(self, qapp) -> None:
        main_win = MagicMock()
        main_win.projection_cache = None
        panel = InvestmentDetailPanel(MagicMock(), main_win)
        panel.show_investment(_make_inv())
        assert panel._proj_iof_lbl.isHidden()

    def test_hidden_when_investment_not_in_cache(self, qapp) -> None:
        other_inv = _make_inv()
        inv = _make_inv()
        main_win = MagicMock()
        main_win.projection_cache = [_make_proj(other_inv, as_of=_PURCHASE + timedelta(days=5))]
        panel = InvestmentDetailPanel(MagicMock(), main_win)
        panel.show_investment(inv)
        assert panel._proj_iof_lbl.isHidden()
