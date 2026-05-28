"""Tests for the active_mock visual treatment in the Conglomerates detail view.

B41 phase 2.4b-ii: _make_cong_detail_row(is_mock=True) and
_make_detail_container wiring via _row_is_mock.

These tests create real Qt widgets so they need a QApplication.
"""

from __future__ import annotations

import sys
from datetime import date
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from justfixed.domain.investment import Investment
from justfixed.domain.issuer import Issuer, IssuerKind
from justfixed.domain.money import Money
from justfixed.domain.product import ProductType
from justfixed.domain.rates import Prefixed
from justfixed.engine.conglomerate_report import (
    ConglomerateDetailRow,
    ConglomerateSection,
    ConglomerateStatus,
)
from justfixed.ui.main import (
    _ActiveMock,
    MainWindow,
    _make_cong_detail_row,
    _row_is_mock,
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


# ── Shared helpers ────────────────────────────────────────────────────────────

_PURCHASE = date(2025, 1, 2)
_MATURITY = date(2026, 1, 2)
_MOCK_PRINCIPAL = Money.from_reais("50000")
_REAL_PRINCIPAL = Money.from_reais("30000")


def _make_issuer(name: str = "Test Bank") -> Issuer:
    return Issuer.create(name, "Test Cong", IssuerKind.COMMERCIAL_BANK)


def _make_detail_row(
    issuer_name: str = "Test Bank",
    maturity: date = _MATURITY,
    principal: Money = _MOCK_PRINCIPAL,
) -> ConglomerateDetailRow:
    return ConglomerateDetailRow(
        maturity_date=maturity,
        issuer_name=issuer_name,
        product=ProductType.CDB,
        principal=principal,
        current_value=Money.from_reais("51000"),
        projected_value=Money.from_reais("55000"),
        projected_balance=Money.from_reais("55000"),
        fgc_status=ConglomerateStatus.UNDER,
    )


def _make_active_mock(
    issuer_name: str = "Test Bank",
    maturity: date = _MATURITY,
    principal: Money = _MOCK_PRINCIPAL,
) -> _ActiveMock:
    issuer = _make_issuer(issuer_name)
    synth_inv = Investment.create(
        product=ProductType.CDB,
        issuer=issuer,
        principal=principal,
        rate=Prefixed.from_percent("12"),
        purchase_date=_PURCHASE,
        maturity_date=maturity,
    )
    return _ActiveMock(synth_investment=synth_inv, projection=MagicMock())


def _make_section(rows: list[ConglomerateDetailRow]) -> ConglomerateSection:
    total_principal = sum((r.principal for r in rows), Money.zero())
    return ConglomerateSection(
        conglomerate_name="Test Cong",
        investment_count=len(rows),
        total_principal=total_principal,
        total_current_value=Money.from_reais("82000"),
        total_projected_value=Money.from_reais("90000"),
        next_maturity=rows[0].maturity_date,
        summary_fgc_status=ConglomerateStatus.UNDER,
        rows=rows,
    )


def _layout_widgets(container: QWidget) -> list[QWidget]:
    """Return the direct layout-item widgets from container's layout."""
    layout = container.layout()
    result = []
    for i in range(layout.count()):
        w = layout.itemAt(i).widget()
        if w is not None:
            result.append(w)
    return result


# ── d: mock row has rowKind="mock" ─────────────────────────────────────────────

class TestMockRowProperty:
    """d: exactly one row in the detail container has rowKind="mock"."""

    def test_mock_row_widget_has_rowkind_mock(self, qapp) -> None:
        widget = _make_cong_detail_row(_make_detail_row(), 0, is_mock=True)
        assert widget.property("rowKind") == "mock"

    def test_non_mock_row_has_no_rowkind(self, qapp) -> None:
        widget = _make_cong_detail_row(_make_detail_row(), 0, is_mock=False)
        assert widget.property("rowKind") != "mock"

    def test_detail_container_has_exactly_one_mock_row(self, qapp) -> None:
        real_row = _make_detail_row(
            issuer_name="Real Bank",
            maturity=date(2026, 6, 1),
            principal=_REAL_PRINCIPAL,
        )
        mock_row = _make_detail_row()  # matches _make_active_mock defaults

        section = _make_section([real_row, mock_row])
        active_mock = _make_active_mock()

        self_mock = MagicMock(spec=MainWindow)
        self_mock.active_mock = active_mock

        container = MainWindow._make_detail_container(self_mock, section)

        # Skip the header widget (index 0), look at the row widgets
        row_widgets = _layout_widgets(container)[1:]
        mock_rows = [w for w in row_widgets if w.property("rowKind") == "mock"]
        assert len(mock_rows) == 1


# ── e: mock row's issuer cell contains a badge="mock" QLabel ──────────────────

class TestMockBadge:
    """e: MOCK badge QLabel present and correct."""

    def test_mock_row_has_badge_label(self, qapp) -> None:
        widget = _make_cong_detail_row(_make_detail_row(), 0, is_mock=True)
        badges = [
            lbl for lbl in widget.findChildren(QLabel)
            if lbl.property("badge") == "mock"
        ]
        assert len(badges) == 1

    def test_mock_badge_text_is_MOCK(self, qapp) -> None:
        widget = _make_cong_detail_row(_make_detail_row(), 0, is_mock=True)
        badge = next(
            lbl for lbl in widget.findChildren(QLabel)
            if lbl.property("badge") == "mock"
        )
        assert badge.text() == "MOCK"

    def test_non_mock_row_has_no_badge(self, qapp) -> None:
        widget = _make_cong_detail_row(_make_detail_row(), 0, is_mock=False)
        badges = [
            lbl for lbl in widget.findChildren(QLabel)
            if lbl.property("badge") == "mock"
        ]
        assert len(badges) == 0


# ── f: non-mock rows are not styled as mock ────────────────────────────────────

class TestNonMockRowsUnaffected:
    """f: real rows in the same section keep detailRowParity, no rowKind="mock"."""

    def test_real_row_has_parity_not_mock(self, qapp) -> None:
        widget = _make_cong_detail_row(_make_detail_row(), 0, is_mock=False)
        assert widget.property("detailRowParity") in ("even", "odd")
        assert widget.property("rowKind") != "mock"

    def test_detail_container_real_rows_have_parity(self, qapp) -> None:
        real_row = _make_detail_row(
            issuer_name="Real Bank",
            maturity=date(2026, 6, 1),
            principal=_REAL_PRINCIPAL,
        )
        mock_row = _make_detail_row()

        section = _make_section([real_row, mock_row])
        active_mock = _make_active_mock()

        self_mock = MagicMock(spec=MainWindow)
        self_mock.active_mock = active_mock

        container = MainWindow._make_detail_container(self_mock, section)

        row_widgets = _layout_widgets(container)[1:]
        real_widgets = [w for w in row_widgets if w.property("rowKind") != "mock"]
        # At least the real_row widget should have a parity property
        assert all(
            w.property("detailRowParity") in ("even", "odd")
            for w in real_widgets
        )


# ── g: mock conglomerate is in _expanded_conglomerates after set_active_mock ──

class TestExpandedAfterSetMock:
    """g: set_active_mock auto-expands the mock's conglomerate."""

    def test_conglomerate_expanded(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._expanded_conglomerates = set()
        synth_inv = MagicMock()
        synth_inv.issuer.conglomerate = "Test Cong"

        MainWindow.set_active_mock(self_mock, synth_inv, MagicMock())

        assert "Test Cong" in self_mock._expanded_conglomerates


# ── h: after clear_active_mock, no mock rows in the container ─────────────────

class TestClearRemovesMockRow:
    """h: with active_mock=None, no row has rowKind="mock"."""

    def test_no_mock_rows_when_active_mock_is_none(self, qapp) -> None:
        real_row = _make_detail_row(
            issuer_name="Real Bank",
            maturity=date(2026, 6, 1),
            principal=_REAL_PRINCIPAL,
        )
        section = _make_section([real_row])

        self_mock = MagicMock(spec=MainWindow)
        self_mock.active_mock = None  # cleared

        container = MainWindow._make_detail_container(self_mock, section)

        row_widgets = _layout_widgets(container)[1:]
        mock_rows = [w for w in row_widgets if w.property("rowKind") == "mock"]
        assert len(mock_rows) == 0

    def test_clear_active_mock_then_no_mock_rows(self, qapp) -> None:
        # Build a two-row section (real + mock-matching) with mock set,
        # then rebuild with mock cleared — the mock row must be gone.
        real_row = _make_detail_row(
            issuer_name="Real Bank",
            maturity=date(2026, 6, 1),
            principal=_REAL_PRINCIPAL,
        )
        mock_row = _make_detail_row()  # matches mock defaults
        section = _make_section([real_row, mock_row])

        # With mock set
        self_mock_with = MagicMock(spec=MainWindow)
        self_mock_with.active_mock = _make_active_mock()
        container_with = MainWindow._make_detail_container(self_mock_with, section)
        rows_with = _layout_widgets(container_with)[1:]
        assert any(w.property("rowKind") == "mock" for w in rows_with)

        # With mock cleared
        self_mock_without = MagicMock(spec=MainWindow)
        self_mock_without.active_mock = None
        container_without = MainWindow._make_detail_container(self_mock_without, section)
        rows_without = _layout_widgets(container_without)[1:]
        assert not any(w.property("rowKind") == "mock" for w in rows_without)


# ── i: Investments tab boundary ───────────────────────────────────────────────

class TestInvestmentsBoundary:
    """i: active_mock.projection is NOT passed to the Investments tab FGC report."""

    def test_refresh_table_fgc_excludes_mock(self) -> None:
        from unittest.mock import patch
        self_mock = MagicMock(spec=MainWindow)
        self_mock._repo = MagicMock()
        self_mock._table = MagicMock()
        self_mock._stack = MagicMock()
        fake_proj = MagicMock()
        self_mock.projection_cache = [fake_proj]
        self_mock.visible_investments.return_value = []
        self_mock.active_mock = _make_active_mock()

        fake_fgc_report = MagicMock()
        fake_fgc_report.conglomerates = []

        with patch(
            "justfixed.ui.main.fgc_concentration_report_from_projections",
            return_value=fake_fgc_report,
        ) as mock_fgc:
            MainWindow.refresh_table(self_mock)

        # Must be called with projection_cache only, not extended with mock
        mock_fgc.assert_called_once_with(self_mock.projection_cache)
        # The mock's projection was NOT included
        mock_proj = self_mock.active_mock.projection
        assert mock_proj not in mock_fgc.call_args.args[0]
