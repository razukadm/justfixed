"""Tests for MainWindow projection cache infrastructure (B' UI session 2, stage B).

Uses the "real method, MagicMock self" pattern: the actual MainWindow methods
are called with a MagicMock stand-in for self. All attribute assignments land
on the mock and are directly assertable. No Qt window is instantiated, so
no QApplication or database setup is needed.
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, call, patch

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QMessageBox, QPushButton

from justfixed.domain.issuer import IssuerKind
from justfixed.importers.detection import Broker
from justfixed.domain.money import Money
from justfixed.domain.rates import Prefixed, PostFixedCDI, PostFixedCDIPlusSpread, PostFixedIPCA
from justfixed.engine.curve import Curve, CurveVertex
from justfixed.engine.fgc import ExposureStatus
from justfixed.engine.projection import ProjectionResult
from justfixed.engine.tax import TaxResult
from PySide6.QtWidgets import QPlainTextEdit, QScrollArea

from PySide6.QtCore import Qt

from justfixed.ui.main import (
    _ActiveMock, _AddInvestmentPanel, _CalculatorTab, _COL_FGC, _COL_PRINCIPAL,
    _ASSUMED_CDI, _ASSUMED_IPCA, _CUSTODIAN_UNSET,
    ConglomerateEditDelegate, InvestmentDetailPanel, MainWindow,
    compute_totals, _format_type, _format_rate, _is_matured,
)


class TestIsMatured:
    def test_past_maturity_is_matured(self) -> None:
        inv = MagicMock()
        inv.maturity_date = date.today() - timedelta(days=1)
        assert _is_matured(inv) is True

    def test_today_maturity_is_matured(self) -> None:
        inv = MagicMock()
        inv.maturity_date = date.today()
        assert _is_matured(inv) is True

    def test_future_maturity_is_not_matured(self) -> None:
        inv = MagicMock()
        inv.maturity_date = date.today() + timedelta(days=1)
        assert _is_matured(inv) is False


class TestProjectionCachePopulation:
    def test_project_done_populates_cache(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock.projection_cache = None
        self_mock._ts_label = MagicMock()
        self_mock._detail_panel = MagicMock()
        fake_results = []

        MainWindow._on_project_done(self_mock, fake_results)

        assert self_mock.projection_cache is fake_results


class TestProjectionCacheInvalidation:
    def test_import_done_clears_cache(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock.projection_cache = [MagicMock()]
        self_mock._status_label = MagicMock()
        self_mock._ts_label = MagicMock()
        self_mock._expanded_conglomerates = set()
        fake_result = MagicMock()
        fake_result.inserted = 3
        fake_result.skipped = 0

        with patch("justfixed.ui.main.QMessageBox.information"):
            MainWindow._on_import_done(self_mock, (Broker.BTG, fake_result))

        assert self_mock.projection_cache is None

    def test_import_done_shows_broker_in_information_dialog(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock.projection_cache = None
        self_mock._status_label = MagicMock()
        self_mock._ts_label = MagicMock()
        self_mock._expanded_conglomerates = set()
        self_mock._BROKER_DISPLAY = MainWindow._BROKER_DISPLAY
        fake_result = MagicMock()
        fake_result.inserted = 2
        fake_result.skipped = 0

        with patch("justfixed.ui.main.QMessageBox.information") as mock_info:
            MainWindow._on_import_done(self_mock, (Broker.BTG, fake_result))

        mock_info.assert_called_once()
        _, title, body = mock_info.call_args.args
        assert title == "Import complete"
        assert "BTG Pactual" in body

    def test_import_done_xp_shows_xp_in_dialog(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock.projection_cache = None
        self_mock._status_label = MagicMock()
        self_mock._ts_label = MagicMock()
        self_mock._expanded_conglomerates = set()
        self_mock._BROKER_DISPLAY = MainWindow._BROKER_DISPLAY
        fake_result = MagicMock()
        fake_result.inserted = 1
        fake_result.skipped = 0

        with patch("justfixed.ui.main.QMessageBox.information") as mock_info:
            MainWindow._on_import_done(self_mock, (Broker.XP, fake_result))

        _, _title, body = mock_info.call_args.args
        assert "XP" in body

    def test_clear_db_clears_cache(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock.projection_cache = [MagicMock()]
        self_mock._investments = [MagicMock()]  # non-empty so dialog appears
        self_mock._repo = MagicMock()
        self_mock._repo.delete_all.return_value = (1, 0)
        self_mock._status_label = MagicMock()
        self_mock._ts_label = MagicMock()
        self_mock._expanded_conglomerates = set()

        with patch("justfixed.ui.main.QMessageBox.question",
                   return_value=QMessageBox.StandardButton.Yes):
            MainWindow._on_clear_db_clicked(self_mock)

        assert self_mock.projection_cache is None


class TestRefreshTableCacheAwareness:
    def _make_self_mock(self) -> MagicMock:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._repo = MagicMock()
        self_mock._table = MagicMock()
        self_mock._stack = MagicMock()
        self_mock._fgc_status_by_id.side_effect = (
            lambda: MainWindow._fgc_status_by_id(self_mock)
        )
        return self_mock

    def test_refresh_table_with_cache_uses_fgc_report(self) -> None:
        self_mock = self._make_self_mock()
        inv_id = uuid.uuid4()
        fake_inv = MagicMock()
        fake_inv.id = inv_id
        self_mock.visible_investments.return_value = [fake_inv]

        fake_inv_exposure = MagicMock()
        fake_inv_exposure.investment_id = inv_id
        fake_conglomerate = MagicMock()
        fake_conglomerate.current_status = ExposureStatus.APPROACHING
        fake_conglomerate.investments = [fake_inv_exposure]
        fake_report = MagicMock()
        fake_report.conglomerates = [fake_conglomerate]

        self_mock.projection_cache = [MagicMock()]

        with patch("justfixed.ui.main.fgc_concentration_report_from_projections",
                   return_value=fake_report) as mock_fgc_func:
            MainWindow.refresh_table(self_mock)

        mock_fgc_func.assert_called_once_with(self_mock.projection_cache)
        self_mock._populate_row.assert_called_once_with(
            0, fake_inv,
            current_value=None,
            projected_value=None,
            fgc_status=ExposureStatus.APPROACHING,
            highlight=False,
        )

    def test_refresh_table_without_cache_passes_none_fgc_status(self) -> None:
        self_mock = self._make_self_mock()
        fake_inv = MagicMock()
        self_mock.visible_investments.return_value = [fake_inv]
        self_mock.projection_cache = None

        MainWindow.refresh_table(self_mock)

        self_mock._populate_row.assert_called_once_with(
            0, fake_inv,
            current_value=None,
            projected_value=None,
            fgc_status=None,
            highlight=False,
        )

    def test_refresh_table_populates_current_and_projected_from_cache(self) -> None:
        self_mock = self._make_self_mock()
        inv_id = uuid.uuid4()

        fake_inv = MagicMock()
        fake_inv.id = inv_id
        fake_inv.issuer.conglomerate = "Banco X S.A."

        other_inv = MagicMock()
        other_inv.id = uuid.uuid4()
        other_inv.issuer.conglomerate = "Banco Y S.A."

        self_mock.visible_investments.return_value = [fake_inv, other_inv]

        _zero = Money.from_reais("0")
        fake_current = Money.from_reais("10500.00")
        fake_gross = Money.from_reais("11000.00")
        fake_proj = ProjectionResult(
            investment=fake_inv,
            as_of=date.today(),
            current_value=fake_current,
            cash_flows=[],
            gross_at_maturity=fake_gross,
            tax_breakdown=TaxResult(
                gross=fake_gross,
                gain=_zero,
                tax_rate=Decimal("0"),
                tax_amount=_zero,
                net=fake_gross,
            ),
            net_at_maturity=fake_gross,
        )

        fake_report = MagicMock()
        fake_report.conglomerates = []
        self_mock._repo.list_all.return_value = [fake_inv, other_inv]
        self_mock.projection_cache = [fake_proj]

        with patch("justfixed.ui.main.fgc_concentration_report_from_projections",
                   return_value=fake_report):
            MainWindow.refresh_table(self_mock)

        calls = self_mock._populate_row.call_args_list
        assert calls[0] == call(
            0, fake_inv,
            current_value=fake_current,
            projected_value=fake_gross,
            fgc_status=None,
            highlight=False,
        )
        assert calls[1] == call(
            1, other_inv,
            current_value=None,
            projected_value=None,
            fgc_status=None,
            highlight=False,
        )


class TestRefreshTableHighlight:
    def _make_self_mock(self) -> MagicMock:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._repo = MagicMock()
        self_mock._table = MagicMock()
        self_mock._stack = MagicMock()
        self_mock.projection_cache = None
        self_mock._fgc_status_by_id.side_effect = (
            lambda: MainWindow._fgc_status_by_id(self_mock)
        )
        return self_mock

    def test_refresh_table_highlights_matching_issuer_rows(self) -> None:
        self_mock = self._make_self_mock()
        matching_id = uuid.uuid4()

        matching_inv = MagicMock()
        matching_inv.issuer.id = matching_id
        matching_inv.issuer.conglomerate = "Banco A S.A."

        other_inv = MagicMock()
        other_inv.issuer.id = uuid.uuid4()
        other_inv.issuer.conglomerate = "Banco B S.A."

        self_mock.visible_investments.return_value = [matching_inv, other_inv]

        MainWindow.refresh_table(self_mock, highlight_issuer_id=matching_id)

        calls = self_mock._populate_row.call_args_list
        assert calls[0] == call(0, matching_inv, current_value=None, projected_value=None,
                                fgc_status=None, highlight=True)
        assert calls[1] == call(1, other_inv, current_value=None, projected_value=None,
                                fgc_status=None, highlight=False)

    def test_refresh_table_no_highlight_when_id_is_none(self) -> None:
        self_mock = self._make_self_mock()
        fake_inv = MagicMock()
        self_mock.visible_investments.return_value = [fake_inv]

        MainWindow.refresh_table(self_mock)

        self_mock._populate_row.assert_called_once_with(
            0, fake_inv,
            current_value=None,
            projected_value=None,
            fgc_status=None,
            highlight=False,
        )


class TestTriggerConglomerateHighlight:
    def test_trigger_highlight_cancels_existing_timer(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        old_timer = MagicMock(spec=QTimer)
        self_mock._highlight_timer = old_timer

        with patch("justfixed.ui.main.QTimer"):
            MainWindow.trigger_conglomerate_highlight(self_mock, uuid.uuid4())

        old_timer.stop.assert_called_once()

    def test_trigger_highlight_calls_refresh_with_id(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._highlight_timer = None
        issuer_id = uuid.uuid4()

        with patch("justfixed.ui.main.QTimer"):
            MainWindow.trigger_conglomerate_highlight(self_mock, issuer_id)

        self_mock.refresh_table.assert_called_once_with(highlight_issuer_id=issuer_id)

    def test_trigger_highlight_schedules_clear_after_3000ms(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._highlight_timer = None

        with patch("justfixed.ui.main.QTimer") as MockQTimer:
            mock_timer = MagicMock(spec=QTimer)
            MockQTimer.return_value = mock_timer
            MainWindow.trigger_conglomerate_highlight(self_mock, uuid.uuid4())

        mock_timer.setSingleShot.assert_called_once_with(True)
        mock_timer.setInterval.assert_called_once_with(3000)
        mock_timer.start.assert_called_once()


class TestRefreshTableScrollPreservation:
    def test_refresh_table_preserves_scroll_position(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._repo = MagicMock()
        self_mock._table = MagicMock()
        self_mock._stack = MagicMock()
        self_mock.projection_cache = None
        self_mock.visible_investments.return_value = []
        self_mock._table.verticalScrollBar.return_value.value.return_value = 150

        MainWindow.refresh_table(self_mock)

        self_mock._table.verticalScrollBar.return_value.setValue.assert_called_once_with(150)


def _make_inv(issuer_name: str, conglomerate: str, days_to_maturity: int) -> MagicMock:
    inv = MagicMock()
    inv.issuer.name = issuer_name
    inv.issuer.conglomerate = conglomerate
    inv.maturity_date = date.today() + timedelta(days=days_to_maturity)
    return inv


class TestVisibleInvestmentsFilter:
    def _make_self(self, investments: list, *, hide_matured: bool = False,
                   filter_issuer: str | None = None,
                   filter_conglomerate: str | None = None,
                   filter_custodian=None) -> MagicMock:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._investments = investments
        self_mock._hide_matured = hide_matured
        self_mock._filter_issuer = filter_issuer
        self_mock._filter_conglomerate = filter_conglomerate
        self_mock._filter_custodian = filter_custodian
        return self_mock

    def test_no_filters_returns_all_sorted_by_maturity(self) -> None:
        inv_a = _make_inv("Bank A", "Group A", 60)
        inv_b = _make_inv("Bank B", "Group B", 30)
        self_mock = self._make_self([inv_a, inv_b])

        result = MainWindow.visible_investments(self_mock)

        assert result == [inv_b, inv_a]

    def test_filter_issuer_excludes_non_matching(self) -> None:
        inv_a = _make_inv("Bank A", "Group A", 30)
        inv_b = _make_inv("Bank B", "Group B", 60)
        self_mock = self._make_self([inv_a, inv_b], filter_issuer="Bank A")

        result = MainWindow.visible_investments(self_mock)

        assert result == [inv_a]

    def test_filter_conglomerate_excludes_non_matching(self) -> None:
        inv_a = _make_inv("Bank A", "Group A", 30)
        inv_b = _make_inv("Bank B", "Group A", 60)
        inv_c = _make_inv("Bank C", "Group B", 45)
        self_mock = self._make_self([inv_a, inv_b, inv_c], filter_conglomerate="Group A")

        result = MainWindow.visible_investments(self_mock)

        assert result == [inv_a, inv_b]

    def test_issuer_and_conglomerate_filters_are_anded(self) -> None:
        inv_a = _make_inv("Bank A", "Group A", 30)
        inv_b = _make_inv("Bank B", "Group A", 60)
        self_mock = self._make_self([inv_a, inv_b],
                                    filter_issuer="Bank A", filter_conglomerate="Group A")

        result = MainWindow.visible_investments(self_mock)

        assert result == [inv_a]

    def test_hide_matured_excludes_past_maturity(self) -> None:
        active = _make_inv("Bank A", "Group A", 30)
        matured = _make_inv("Bank B", "Group B", -1)
        self_mock = self._make_self([active, matured], hide_matured=True)

        result = MainWindow.visible_investments(self_mock)

        assert result == [active]

    def test_filter_issuer_none_does_not_filter(self) -> None:
        inv_a = _make_inv("Bank A", "Group A", 10)
        inv_b = _make_inv("Bank B", "Group B", 20)
        self_mock = self._make_self([inv_a, inv_b], filter_issuer=None)

        result = MainWindow.visible_investments(self_mock)

        assert result == [inv_a, inv_b]

    def test_result_sorted_ascending_by_maturity_date(self) -> None:
        inv_c = _make_inv("Bank C", "Group C", 90)
        inv_a = _make_inv("Bank A", "Group A", 10)
        inv_b = _make_inv("Bank B", "Group B", 50)
        self_mock = self._make_self([inv_c, inv_a, inv_b])

        result = MainWindow.visible_investments(self_mock)

        assert result == [inv_a, inv_b, inv_c]


class TestFilterHandlers:
    def test_issuer_handler_sets_filter_and_calls_refresh(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._filter_issuer = None

        MainWindow._on_issuer_filter_changed(self_mock, "Bank A")

        assert self_mock._filter_issuer == "Bank A"
        self_mock.refresh_table.assert_called_once_with()

    def test_issuer_handler_clears_filter_on_all(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._filter_issuer = "Bank A"

        MainWindow._on_issuer_filter_changed(self_mock, "All")

        assert self_mock._filter_issuer is None
        self_mock.refresh_table.assert_called_once_with()

    def test_conglomerate_handler_sets_filter_and_calls_refresh(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._filter_conglomerate = None

        MainWindow._on_conglomerate_filter_changed(self_mock, "Group A")

        assert self_mock._filter_conglomerate == "Group A"
        self_mock.refresh_table.assert_called_once_with()

    def test_conglomerate_handler_clears_filter_on_all(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._filter_conglomerate = "Group A"

        MainWindow._on_conglomerate_filter_changed(self_mock, "All")

        assert self_mock._filter_conglomerate is None
        self_mock.refresh_table.assert_called_once_with()


# ── compute_totals helpers ────────────────────────────────────────────────────

def _brl(amount: str) -> Money:
    return Money(Decimal(amount), "BRL")


def _make_investment(principal: Money) -> MagicMock:
    inv = MagicMock()
    inv.id = uuid.uuid4()
    inv.principal = principal
    return inv


def _make_projection(inv: MagicMock, current: Money, gross: Money) -> MagicMock:
    proj = MagicMock()
    proj.investment.id = inv.id
    proj.current_value = current
    proj.gross_at_maturity = gross
    return proj


class TestComputeTotals:
    def test_empty_investments_no_cache(self) -> None:
        result = compute_totals([], None)

        assert result["principal_total"] == Money.zero()
        assert result["current_value_total"] is None
        assert result["projected_total"] is None
        assert result["row_count"] == 0

    def test_empty_investments_with_cache(self) -> None:
        some_proj = MagicMock()
        result = compute_totals([], [some_proj])

        assert result["principal_total"] == Money.zero()
        assert result["current_value_total"] == Money.zero()
        assert result["projected_total"] == Money.zero()
        assert result["row_count"] == 0

    def test_investments_no_cache_returns_principal_only(self) -> None:
        inv_a = _make_investment(_brl("100.00"))
        inv_b = _make_investment(_brl("250.00"))

        result = compute_totals([inv_a, inv_b], None)

        assert result["principal_total"] == _brl("350.00")
        assert result["current_value_total"] is None
        assert result["projected_total"] is None
        assert result["row_count"] == 2

    def test_all_investments_in_cache_sums_projections(self) -> None:
        inv_a = _make_investment(_brl("100.00"))
        inv_b = _make_investment(_brl("250.00"))
        proj_a = _make_projection(inv_a, _brl("110.00"), _brl("130.00"))
        proj_b = _make_projection(inv_b, _brl("260.00"), _brl("300.00"))

        result = compute_totals([inv_a, inv_b], [proj_a, proj_b])

        assert result["principal_total"] == _brl("350.00")
        assert result["current_value_total"] == _brl("370.00")
        assert result["projected_total"] == _brl("430.00")
        assert result["row_count"] == 2

    def test_partial_cache_returns_none_for_projected(self) -> None:
        inv_a = _make_investment(_brl("100.00"))
        inv_b = _make_investment(_brl("250.00"))
        proj_a = _make_projection(inv_a, _brl("110.00"), _brl("130.00"))

        result = compute_totals([inv_a, inv_b], [proj_a])

        assert result["principal_total"] == _brl("350.00")
        assert result["current_value_total"] is None
        assert result["projected_total"] is None
        assert result["row_count"] == 2


class TestUpdateTotals:
    def _make_self_mock(self) -> MagicMock:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._filter_issuer = None
        self_mock._filter_conglomerate = None
        self_mock.projection_cache = None
        self_mock._principal_label = MagicMock()
        self_mock._current_label = MagicMock()
        self_mock._projected_label = MagicMock()
        self_mock._rows_label = MagicMock()
        return self_mock

    def _active_inv(self) -> MagicMock:
        inv = MagicMock()
        inv.maturity_date = date.today() + timedelta(days=365)
        return inv

    def test_update_totals_with_full_cache(self) -> None:
        self_mock = self._make_self_mock()
        fake_inv = self._active_inv()
        self_mock.visible_investments.return_value = [fake_inv, fake_inv]

        totals = {
            "principal_total": _brl("350.00"),
            "current_value_total": _brl("370.00"),
            "projected_total": _brl("430.00"),
            "row_count": 2,
        }
        with patch("justfixed.ui.main.compute_totals", return_value=totals):
            MainWindow._update_totals(self_mock)

        self_mock._principal_label.setText.assert_called_once_with("Principal: R$ 350,00")
        self_mock._current_label.setText.assert_called_once_with("Current: R$ 370,00")
        self_mock._projected_label.setText.assert_called_once_with("Projected: R$ 430,00")
        self_mock._rows_label.setText.assert_called_once_with("Rows: 2")

    def test_update_totals_no_cache_shows_dash_for_projected(self) -> None:
        self_mock = self._make_self_mock()
        fake_inv = self._active_inv()
        self_mock.visible_investments.return_value = [fake_inv]

        totals = {
            "principal_total": _brl("100.00"),
            "current_value_total": None,
            "projected_total": None,
            "row_count": 1,
        }
        with patch("justfixed.ui.main.compute_totals", return_value=totals):
            MainWindow._update_totals(self_mock)

        self_mock._principal_label.setText.assert_called_once_with("Principal: R$ 100,00")
        self_mock._current_label.setText.assert_called_once_with("Current: —")
        self_mock._projected_label.setText.assert_called_once_with("Projected: —")
        self_mock._rows_label.setText.assert_called_once_with("Rows: 1")

    def test_update_totals_with_filter_shows_m_of_n(self) -> None:
        self_mock = self._make_self_mock()
        self_mock._filter_issuer = "BMG"
        future = date.today() + timedelta(days=365)

        def _active():
            inv = MagicMock()
            inv.maturity_date = future
            return inv

        def visible_side_effect(*, apply_filter: bool = True):
            return [_active()] if apply_filter else [_active(), _active(), _active()]

        self_mock.visible_investments.side_effect = visible_side_effect

        totals = {
            "principal_total": _brl("100.00"),
            "current_value_total": None,
            "projected_total": None,
            "row_count": 1,
        }
        with patch("justfixed.ui.main.compute_totals", return_value=totals):
            MainWindow._update_totals(self_mock)

        self_mock._rows_label.setText.assert_called_once_with("Rows: 1 of 3")


class TestUpdateTotalsMatured:
    """_update_totals always excludes matured rows from sums regardless of toggle,
    and shows 'N active · M matured' when matured rows are visible."""

    def _make_self_mock(self, *, hide_matured: bool, filter_issuer=None) -> MagicMock:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._hide_matured = hide_matured
        self_mock._filter_issuer = filter_issuer
        self_mock._filter_conglomerate = None
        self_mock.projection_cache = None
        self_mock._principal_label = MagicMock()
        self_mock._current_label = MagicMock()
        self_mock._projected_label = MagicMock()
        self_mock._rows_label = MagicMock()
        return self_mock

    def _active_inv(self) -> MagicMock:
        inv = MagicMock()
        inv.maturity_date = date.today() + timedelta(days=365)
        return inv

    def _matured_inv(self) -> MagicMock:
        inv = MagicMock()
        inv.maturity_date = date.today() - timedelta(days=1)
        return inv

    def test_toggle_on_no_matured_rows_pill_shows_n(self) -> None:
        self_mock = self._make_self_mock(hide_matured=True)
        self_mock.visible_investments.return_value = [self._active_inv()]
        totals_stub = {
            "principal_total": _brl("100.00"),
            "current_value_total": None,
            "projected_total": None,
            "row_count": 1,
        }
        with patch("justfixed.ui.main.compute_totals", return_value=totals_stub):
            MainWindow._update_totals(self_mock)
        self_mock._rows_label.setText.assert_called_once_with("Rows: 1")

    def test_toggle_on_compute_totals_receives_only_active(self) -> None:
        self_mock = self._make_self_mock(hide_matured=True)
        active = self._active_inv()
        self_mock.visible_investments.return_value = [active]
        with patch("justfixed.ui.main.compute_totals") as mock_ct:
            mock_ct.return_value = {
                "principal_total": _brl("100.00"),
                "current_value_total": None,
                "projected_total": None,
                "row_count": 1,
            }
            MainWindow._update_totals(self_mock)
        passed = mock_ct.call_args[0][0]
        assert all(not _is_matured(inv) for inv in passed)

    def test_toggle_off_matured_excluded_from_compute_totals(self) -> None:
        self_mock = self._make_self_mock(hide_matured=False)
        active = self._active_inv()
        matured = self._matured_inv()
        self_mock.visible_investments.return_value = [active, matured]
        with patch("justfixed.ui.main.compute_totals") as mock_ct:
            mock_ct.return_value = {
                "principal_total": _brl("100.00"),
                "current_value_total": None,
                "projected_total": None,
                "row_count": 1,
            }
            MainWindow._update_totals(self_mock)
        passed = mock_ct.call_args[0][0]
        assert len(passed) == 1
        assert not _is_matured(passed[0])

    def test_toggle_off_with_matured_pill_shows_split(self) -> None:
        self_mock = self._make_self_mock(hide_matured=False)
        self_mock.visible_investments.return_value = [
            self._active_inv(), self._active_inv(), self._matured_inv(),
        ]
        totals_stub = {
            "principal_total": _brl("200.00"),
            "current_value_total": None,
            "projected_total": None,
            "row_count": 2,
        }
        with patch("justfixed.ui.main.compute_totals", return_value=totals_stub):
            MainWindow._update_totals(self_mock)
        self_mock._rows_label.setText.assert_called_once_with("2 active · 1 matured")

    def test_toggle_off_no_matured_pill_shows_n(self) -> None:
        self_mock = self._make_self_mock(hide_matured=False)
        self_mock.visible_investments.return_value = [self._active_inv()]
        totals_stub = {
            "principal_total": _brl("100.00"),
            "current_value_total": None,
            "projected_total": None,
            "row_count": 1,
        }
        with patch("justfixed.ui.main.compute_totals", return_value=totals_stub):
            MainWindow._update_totals(self_mock)
        self_mock._rows_label.setText.assert_called_once_with("Rows: 1")


# ── Integration test helpers ──────────────────────────────────────────────────

def _make_integration_projection(inv: MagicMock, current: Money, gross: Money) -> ProjectionResult:
    _zero = Money.from_reais("0")
    return ProjectionResult(
        investment=inv,
        as_of=date.today(),
        current_value=current,
        cash_flows=[],
        gross_at_maturity=gross,
        tax_breakdown=TaxResult(
            gross=gross,
            gain=_zero,
            tax_rate=Decimal("0"),
            tax_amount=_zero,
            net=gross,
        ),
        net_at_maturity=gross,
    )


def _make_integration_self_mock(
    investments: list,
    projection_cache: list | None = None,
    filter_issuer: str | None = None,
    filter_conglomerate: str | None = None,
) -> MagicMock:
    self_mock = MagicMock(spec=MainWindow)

    self_mock._investments = investments
    self_mock._hide_matured = False
    self_mock._filter_issuer = filter_issuer
    self_mock._filter_conglomerate = filter_conglomerate
    self_mock._has_projected = False
    self_mock.projection_cache = projection_cache
    self_mock._highlight_timer = None
    self_mock._worker = None

    self_mock._table = MagicMock()
    self_mock._stack = MagicMock()
    self_mock._issuer_combo = MagicMock()
    self_mock._conglomerate_combo = MagicMock()
    self_mock._custodian_combo = MagicMock()
    self_mock._filter_custodian = None
    self_mock._principal_label = MagicMock()
    self_mock._current_label = MagicMock()
    self_mock._projected_label = MagicMock()
    self_mock._rows_label = MagicMock()

    self_mock._repo = MagicMock()
    self_mock._repo.list_all.return_value = investments

    self_mock.visible_investments.side_effect = (
        lambda *, apply_filter=True:
        MainWindow.visible_investments(self_mock, apply_filter=apply_filter)
    )
    self_mock._update_totals.side_effect = (
        lambda: MainWindow._update_totals(self_mock)
    )
    self_mock._populate_filter_dropdowns.side_effect = (
        lambda: MainWindow._populate_filter_dropdowns(self_mock)
    )
    self_mock.refresh_table.side_effect = (
        lambda highlight_issuer_id=None:
        MainWindow.refresh_table(self_mock, highlight_issuer_id=highlight_issuer_id)
    )
    self_mock._fgc_status_by_id.side_effect = (
        lambda: MainWindow._fgc_status_by_id(self_mock)
    )

    return self_mock


class TestCurationRoundtripIntegration:
    def test_edit_conglomerate_propagates_through_save_and_refresh(self) -> None:
        inv1 = MagicMock()
        inv1.id = uuid.uuid4()
        inv1.issuer.id = uuid.uuid4()
        inv1.issuer.name = "Bank Alpha"
        inv1.issuer.conglomerate = "[unverified] Bank Alpha"
        inv1.issuer.kind = IssuerKind.COMMERCIAL_BANK
        inv1.maturity_date = date.today() + timedelta(days=30)
        inv1.purchase_date = date.today() - timedelta(days=30)
        inv1.product = MagicMock()
        inv1.principal = _brl("10000.00")

        inv2 = MagicMock()
        inv2.id = uuid.uuid4()
        inv2.issuer.id = uuid.uuid4()
        inv2.issuer.name = "Bank Alpha"
        inv2.issuer.conglomerate = "[unverified] Bank Alpha"
        inv2.issuer.kind = IssuerKind.COMMERCIAL_BANK
        inv2.maturity_date = date.today() + timedelta(days=60)
        inv2.purchase_date = date.today() - timedelta(days=60)
        inv2.product = MagicMock()
        inv2.principal = _brl("5000.00")

        proj1 = _make_integration_projection(inv1, _brl("10500.00"), _brl("11000.00"))
        proj2 = _make_integration_projection(inv2, _brl("5200.00"), _brl("5500.00"))

        investments = [inv1, inv2]
        self_mock = _make_integration_self_mock(investments, projection_cache=[proj1, proj2])

        # Phase 1 — baseline refresh
        MainWindow.refresh_table(self_mock)

        calls = self_mock._populate_row.call_args_list
        assert len(calls) == 2
        assert calls[0].kwargs["fgc_status"] == ExposureStatus.UNDER
        assert calls[1].kwargs["fgc_status"] == ExposureStatus.UNDER

        expected_principal = inv1.principal + inv2.principal
        self_mock._principal_label.setText.assert_called_with(
            f"Principal: {expected_principal.to_display()}"
        )

        # Phase 2 — delegate save
        delegate = ConglomerateEditDelegate(self_mock, MagicMock())
        editor = MagicMock()
        editor.text.return_value = "Alpha Banking Group"
        index = MagicMock()
        index.row.return_value = 0  # inv1 comes first (shorter maturity)

        with patch("justfixed.ui.main.IssuerRepository") as MockIssuerRepo, \
             patch("justfixed.ui.main.CurationMemoryRepository") as MockCurationRepo:
            delegate.setModelData(editor, MagicMock(), index)

        MockIssuerRepo.return_value.save.assert_called_once_with(inv1.issuer)
        MockCurationRepo.return_value.set.assert_called_once()
        assert inv1.issuer.conglomerate == "Alpha Banking Group"
        self_mock.trigger_conglomerate_highlight.assert_called_once_with(inv1.issuer.id)

        # Phase 3 — post-edit refresh: mutation propagates through projection cache
        self_mock._populate_row.reset_mock()
        self_mock._principal_label.reset_mock()

        MainWindow.refresh_table(self_mock)

        calls = self_mock._populate_row.call_args_list
        assert len(calls) == 2
        # FGC now groups inv1 under "Alpha Banking Group" via the shared reference;
        # exposure amounts unchanged, both conglomerates remain UNDER
        assert calls[0].kwargs["fgc_status"] == ExposureStatus.UNDER
        assert calls[1].kwargs["fgc_status"] == ExposureStatus.UNDER

        self_mock._principal_label.setText.assert_called_with(
            f"Principal: {expected_principal.to_display()}"
        )


class TestFilterTotalsIntegration:
    def test_filter_narrows_visible_and_totals_with_cache(self) -> None:
        inv1 = MagicMock()
        inv1.id = uuid.uuid4()
        inv1.issuer.name = "Bank A"
        inv1.issuer.conglomerate = "Group X"
        inv1.issuer.kind = IssuerKind.COMMERCIAL_BANK
        inv1.maturity_date = date.today() + timedelta(days=10)
        inv1.purchase_date = date.today() - timedelta(days=10)
        inv1.product = MagicMock()
        inv1.principal = _brl("10000.00")

        inv2 = MagicMock()
        inv2.id = uuid.uuid4()
        inv2.issuer.name = "Bank A"
        inv2.issuer.conglomerate = "Group Y"
        inv2.issuer.kind = IssuerKind.COMMERCIAL_BANK
        inv2.maturity_date = date.today() + timedelta(days=20)
        inv2.purchase_date = date.today() - timedelta(days=20)
        inv2.product = MagicMock()
        inv2.principal = _brl("15000.00")

        inv3 = MagicMock()
        inv3.id = uuid.uuid4()
        inv3.issuer.name = "Bank B"
        inv3.issuer.conglomerate = "Group X"
        inv3.issuer.kind = IssuerKind.COMMERCIAL_BANK
        inv3.maturity_date = date.today() + timedelta(days=30)
        inv3.purchase_date = date.today() - timedelta(days=30)
        inv3.product = MagicMock()
        inv3.principal = _brl("20000.00")

        inv4 = MagicMock()
        inv4.id = uuid.uuid4()
        inv4.issuer.name = "Bank B"
        inv4.issuer.conglomerate = "Group Y"
        inv4.issuer.kind = IssuerKind.COMMERCIAL_BANK
        inv4.maturity_date = date.today() + timedelta(days=40)
        inv4.purchase_date = date.today() - timedelta(days=40)
        inv4.product = MagicMock()
        inv4.principal = _brl("25000.00")

        proj1 = _make_integration_projection(inv1, _brl("10100.00"), _brl("10500.00"))
        proj2 = _make_integration_projection(inv2, _brl("15200.00"), _brl("15800.00"))
        proj3 = _make_integration_projection(inv3, _brl("20300.00"), _brl("21000.00"))
        proj4 = _make_integration_projection(inv4, _brl("25400.00"), _brl("26000.00"))

        investments = [inv1, inv2, inv3, inv4]
        self_mock = _make_integration_self_mock(
            investments, projection_cache=[proj1, proj2, proj3, proj4]
        )

        # Phase 1 — baseline: all four investments visible
        MainWindow.refresh_table(self_mock)

        assert self_mock._populate_row.call_count == 4
        expected_all_principal = (
            inv1.principal + inv2.principal + inv3.principal + inv4.principal
        )
        expected_all_current = (
            proj1.current_value + proj2.current_value
            + proj3.current_value + proj4.current_value
        )
        self_mock._principal_label.setText.assert_called_with(
            f"Principal: {expected_all_principal.to_display()}"
        )
        self_mock._current_label.setText.assert_called_with(
            f"Current: {expected_all_current.to_display()}"
        )
        self_mock._rows_label.setText.assert_called_with("Rows: 4")

        # Phase 2 — issuer filter: Bank A only (inv1 + inv2)
        self_mock._populate_row.reset_mock()
        self_mock._principal_label.reset_mock()
        self_mock._current_label.reset_mock()
        self_mock._rows_label.reset_mock()

        MainWindow._on_issuer_filter_changed(self_mock, "Bank A")

        assert self_mock._populate_row.call_count == 2
        expected_bank_a_principal = inv1.principal + inv2.principal
        expected_bank_a_current = proj1.current_value + proj2.current_value
        self_mock._principal_label.setText.assert_called_with(
            f"Principal: {expected_bank_a_principal.to_display()}"
        )
        self_mock._current_label.setText.assert_called_with(
            f"Current: {expected_bank_a_current.to_display()}"
        )
        self_mock._rows_label.setText.assert_called_with("Rows: 2 of 4")

        # Phase 3 — AND conglomerate filter: Bank A ∩ Group X = inv1 only
        self_mock._populate_row.reset_mock()
        self_mock._principal_label.reset_mock()
        self_mock._current_label.reset_mock()
        self_mock._rows_label.reset_mock()

        MainWindow._on_conglomerate_filter_changed(self_mock, "Group X")

        assert self_mock._populate_row.call_count == 1
        self_mock._principal_label.setText.assert_called_with(
            f"Principal: {inv1.principal.to_display()}"
        )
        self_mock._current_label.setText.assert_called_with(
            f"Current: {proj1.current_value.to_display()}"
        )
        self_mock._rows_label.setText.assert_called_with("Rows: 1 of 4")

        # Phase 4 — clear issuer filter; conglomerate "Group X" still active
        # visible = inv1 (Bank A, Group X) + inv3 (Bank B, Group X) = 2
        self_mock._populate_row.reset_mock()
        self_mock._rows_label.reset_mock()

        MainWindow._on_issuer_filter_changed(self_mock, "All")

        assert self_mock._populate_row.call_count == 2
        self_mock._rows_label.setText.assert_called_with("Rows: 2 of 4")

        # Phase 5 — clear conglomerate filter; both filters None, all four visible
        self_mock._populate_row.reset_mock()
        self_mock._rows_label.reset_mock()

        MainWindow._on_conglomerate_filter_changed(self_mock, "All")

        assert self_mock._populate_row.call_count == 4
        self_mock._rows_label.setText.assert_called_with("Rows: 4")


def _make_curve(anchor_str: str = "2026-05-15") -> Curve:
    return Curve(
        anchor=date.fromisoformat(anchor_str),
        vertices=(CurveVertex(business_days=252, rate=Decimal("0.144")),),
    )


# ── _update_curve_label ───────────────────────────────────────────────────────

class TestUpdateCurveLabel:
    def _mock(self) -> MagicMock:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._curve_label = MagicMock()
        return self_mock

    def test_live_with_vertices_shows_anchor(self) -> None:
        self_mock = self._mock()
        MainWindow._update_curve_label(self_mock, "live", _make_curve())
        self_mock._curve_label.setText.assert_called_once_with("Curve: live (2026-05-15)")

    def test_unavailable_shows_unavailable(self) -> None:
        self_mock = self._mock()
        MainWindow._update_curve_label(self_mock, "unavailable", None)
        self_mock._curve_label.setText.assert_called_once_with("Curve: unavailable")

    def test_live_no_curve_shows_no_data(self) -> None:
        self_mock = self._mock()
        MainWindow._update_curve_label(self_mock, "live", None)
        self_mock._curve_label.setText.assert_called_once_with("Curve: live (no data)")

    def test_manual_with_curve_shows_manual(self) -> None:
        self_mock = self._mock()
        MainWindow._update_curve_label(self_mock, "manual", _make_curve())
        self_mock._curve_label.setText.assert_called_once_with("Curve: manual (2026-05-15)")


# ── _on_load_curve_from_file_clicked (B30) ────────────────────────────────────

class TestLoadCurveFromFile:
    _VALID_PAYLOAD = {
        "cdi": {
            "anchor": "2026-05-15",
            "vertices": [{"business_days": 252, "rate": 0.144}],
        }
    }

    def test_valid_json_updates_cdi_curve_and_reprojects(self, tmp_path) -> None:
        json_file = tmp_path / "latest.json"
        json_file.write_text(json.dumps(self._VALID_PAYLOAD), encoding="utf-8")
        self_mock = MagicMock(spec=MainWindow)
        self_mock._curve_source = "live"

        with patch("justfixed.ui.main.QFileDialog.getOpenFileName",
                   return_value=(str(json_file), "")), \
             patch("justfixed.ui.main.QStandardPaths.standardLocations",
                   return_value=[""]):
            MainWindow._on_load_curve_from_file_clicked(self_mock)

        assert self_mock._cdi_curve is not None
        assert self_mock._curve_source == "manual"
        self_mock._update_curve_label.assert_called_once()
        self_mock._on_project_clicked.assert_called_once()

    def test_cancel_is_no_op(self) -> None:
        self_mock = MagicMock(spec=MainWindow)

        with patch("justfixed.ui.main.QFileDialog.getOpenFileName",
                   return_value=("", "")), \
             patch("justfixed.ui.main.QStandardPaths.standardLocations",
                   return_value=[""]):
            MainWindow._on_load_curve_from_file_clicked(self_mock)

        self_mock._on_project_clicked.assert_not_called()

    def test_invalid_json_shows_warning_no_reproject(self, tmp_path) -> None:
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not valid json {{ ", encoding="utf-8")
        self_mock = MagicMock(spec=MainWindow)

        with patch("justfixed.ui.main.QFileDialog.getOpenFileName",
                   return_value=(str(bad_file), "")), \
             patch("justfixed.ui.main.QStandardPaths.standardLocations",
                   return_value=[""]), \
             patch("justfixed.ui.main.QMessageBox.warning") as mock_warn:
            MainWindow._on_load_curve_from_file_clicked(self_mock)

        mock_warn.assert_called_once()
        self_mock._on_project_clicked.assert_not_called()

    def test_no_cdi_section_shows_warning_no_reproject(self, tmp_path) -> None:
        json_file = tmp_path / "empty.json"
        json_file.write_text(json.dumps({"as_of": "2026-05-15"}), encoding="utf-8")
        self_mock = MagicMock(spec=MainWindow)

        with patch("justfixed.ui.main.QFileDialog.getOpenFileName",
                   return_value=(str(json_file), "")), \
             patch("justfixed.ui.main.QStandardPaths.standardLocations",
                   return_value=[""]), \
             patch("justfixed.ui.main.QMessageBox.warning") as mock_warn:
            MainWindow._on_load_curve_from_file_clicked(self_mock)

        mock_warn.assert_called_once()
        self_mock._on_project_clicked.assert_not_called()


# ── _format_type (B27) ────────────────────────────────────────────────────────

class TestFormatType:
    def test_prefixed(self) -> None:
        assert _format_type(Prefixed.from_percent("12.5")) == "Pré"

    def test_post_fixed_cdi(self) -> None:
        assert _format_type(PostFixedCDI.from_percent("112")) == "Pós"

    def test_post_fixed_cdi_plus_spread(self) -> None:
        assert _format_type(PostFixedCDIPlusSpread.from_percent("2.05")) == "Pós+"

    def test_post_fixed_ipca(self) -> None:
        assert _format_type(PostFixedIPCA.from_percent("6")) == "IPCA+"


# ── _format_rate (B27) ────────────────────────────────────────────────────────

def _make_curve_13() -> Curve:
    return Curve(
        anchor=date(2026, 5, 15),
        vertices=(CurveVertex(business_days=252, rate=Decimal("0.13")),),
    )


class TestFormatRate:
    _MATURITY = date(2027, 5, 15)

    def test_prefixed_no_parenthetical(self) -> None:
        # Prefixed: just the percent, no "a.a." suffix, no parens
        rate = Prefixed.from_percent("12.5")
        assert _format_rate(rate, None, self._MATURITY) == "12,50%"

    def test_post_fixed_cdi_with_curve(self) -> None:
        # effective = 1.12 × 0.13 = 0.1456 → 14,56%
        rate = PostFixedCDI.from_percent("112")
        result = _format_rate(rate, _make_curve_13(), self._MATURITY)
        assert result == "112,00% do CDI (14,56%)"

    def test_post_fixed_cdi_without_curve(self) -> None:
        # effective = 1.12 × 0.144 (_ASSUMED_CDI) = 0.16128 → 16,13%
        rate = PostFixedCDI.from_percent("112")
        result = _format_rate(rate, None, self._MATURITY)
        assert result == "112,00% do CDI (16,13%)"

    def test_post_fixed_cdi_plus_spread_with_curve(self) -> None:
        # effective = 0.13 + 0.0205 + (0.13 × 0.0205) = 0.153165 → 15,32%
        rate = PostFixedCDIPlusSpread.from_percent("2.05")
        result = _format_rate(rate, _make_curve_13(), self._MATURITY)
        assert result == "CDI + 2,05% (15,32%)"

    def test_post_fixed_cdi_plus_spread_without_curve(self) -> None:
        # effective = 0.144 + 0.0205 + (0.144 × 0.0205) = 0.167452 → 16,75%
        rate = PostFixedCDIPlusSpread.from_percent("2.05")
        result = _format_rate(rate, None, self._MATURITY)
        assert result == "CDI + 2,05% (16,75%)"

    def test_post_fixed_ipca(self) -> None:
        # effective = 0.0414 + 0.06 + (0.0414 × 0.06) = 0.103884 → 10,39%
        rate = PostFixedIPCA.from_percent("6")
        result = _format_rate(rate, None, self._MATURITY)
        assert result == "IPCA + 6,00% (10,39%)"

    def test_post_fixed_ipca_curve_not_used(self) -> None:
        # IPCA effective rate uses _ASSUMED_IPCA regardless of curve presence
        rate = PostFixedIPCA.from_percent("6")
        with_curve = _format_rate(rate, _make_curve_13(), self._MATURITY)
        without_curve = _format_rate(rate, None, self._MATURITY)
        assert with_curve == without_curve

    def test_format_rate_honors_assumed_ipca_kwarg(self) -> None:
        # assumed_ipca=0.08 (8%) with spread=6%:
        # effective = 0.08 + 0.06 + (0.08 × 0.06) = 0.1448 → 14,48%
        # default (0.0414) gives 10,39% — the two must differ.
        rate = PostFixedIPCA.from_percent("6")
        result_alt = _format_rate(rate, None, self._MATURITY, assumed_ipca=Decimal("0.08"))
        result_default = _format_rate(rate, None, self._MATURITY)
        assert result_alt != result_default
        assert result_alt == "IPCA + 6,00% (14,48%)"


# ── Startup tab selection ─────────────────────────────────────────────────────

class TestStartupTabSelection:
    def test_opens_investments_tab_when_db_empty(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._investments = []
        self_mock._tabs = MagicMock()

        MainWindow._set_startup_tab(self_mock)

        self_mock._tabs.setCurrentIndex.assert_called_once_with(1)

    def test_opens_conglomerates_tab_when_investments_present(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._investments = [MagicMock()]
        self_mock._tabs = MagicMock()

        MainWindow._set_startup_tab(self_mock)

        self_mock._tabs.setCurrentIndex.assert_called_once_with(0)


# ── Empty-state widget wiring ─────────────────────────────────────────────────

@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


class TestEmptyStateButtonWiring:
    def test_empty_state_import_button_wired_to_import_handler(self, qapp) -> None:
        self_mock = MagicMock(spec=MainWindow)

        MainWindow._build_empty_state_widget(self_mock)

        self_mock._empty_import_btn.click()
        self_mock._on_import_clicked.assert_called_once()

    def test_empty_state_add_button_wired_to_add_handler(self, qapp) -> None:
        self_mock = MagicMock(spec=MainWindow)

        MainWindow._build_empty_state_widget(self_mock)

        self_mock._empty_add_btn.click()
        self_mock._on_add_investment_clicked.assert_called_once()


# ── Custodian B42 ─────────────────────────────────────────────────────────────


def _inv_with_custodian(custodian, days: int = 30) -> MagicMock:
    inv = MagicMock()
    inv.custodian = custodian
    inv.maturity_date = date.today() + timedelta(days=days)
    inv.issuer.name = "Bank"
    inv.issuer.conglomerate = "Group"
    return inv


class TestDistinctCustodians:
    def test_returns_sorted_distinct_non_none(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._investments = [
            _inv_with_custodian("XP"),
            _inv_with_custodian("BTG Pactual"),
            _inv_with_custodian("XP"),   # duplicate — deduplicated
            _inv_with_custodian(None),   # excluded
        ]
        assert MainWindow._distinct_custodians(self_mock) == ["BTG Pactual", "XP"]

    def test_empty_investments_returns_empty(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._investments = []
        assert MainWindow._distinct_custodians(self_mock) == []

    def test_all_none_returns_empty(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._investments = [_inv_with_custodian(None), _inv_with_custodian(None)]
        assert MainWindow._distinct_custodians(self_mock) == []


class TestCustodianFilterHandler:
    def test_value_text_sets_filter_and_refreshes(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._filter_custodian = None
        MainWindow._on_custodian_filter_changed(self_mock, "XP")
        assert self_mock._filter_custodian == "XP"
        self_mock.refresh_table.assert_called_once_with()

    def test_all_clears_filter(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._filter_custodian = "XP"
        MainWindow._on_custodian_filter_changed(self_mock, "All")
        assert self_mock._filter_custodian is None
        self_mock.refresh_table.assert_called_once_with()

    def test_unset_text_sets_sentinel(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._filter_custodian = None
        MainWindow._on_custodian_filter_changed(self_mock, "(unset)")
        assert self_mock._filter_custodian is _CUSTODIAN_UNSET
        self_mock.refresh_table.assert_called_once_with()


class TestVisibleInvestmentsCustodianFilter:
    def _self_mock(self, investments, *, filter_custodian=None) -> MagicMock:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._investments = investments
        self_mock._hide_matured = False
        self_mock._filter_issuer = None
        self_mock._filter_conglomerate = None
        self_mock._filter_custodian = filter_custodian
        return self_mock

    def test_no_filter_shows_all(self) -> None:
        inv_xp = _inv_with_custodian("XP", 10)
        inv_null = _inv_with_custodian(None, 20)
        result = MainWindow.visible_investments(self._self_mock([inv_xp, inv_null]))
        assert set(result) == {inv_xp, inv_null}

    def test_value_filter_shows_matching_only(self) -> None:
        inv_xp = _inv_with_custodian("XP", 10)
        inv_btg = _inv_with_custodian("BTG Pactual", 20)
        result = MainWindow.visible_investments(
            self._self_mock([inv_xp, inv_btg], filter_custodian="XP")
        )
        assert result == [inv_xp]

    def test_unset_filter_shows_only_null_custodian(self) -> None:
        inv_xp = _inv_with_custodian("XP", 10)
        inv_null = _inv_with_custodian(None, 20)
        result = MainWindow.visible_investments(
            self._self_mock([inv_xp, inv_null], filter_custodian=_CUSTODIAN_UNSET)
        )
        assert result == [inv_null]


class TestDetailPanelCustodianConfig:
    def test_custodian_in_field_keys(self) -> None:
        keys = [key for _, key in InvestmentDetailPanel._FIELD_KEYS]
        assert "custodian" in keys

    def test_custodian_after_conglomerate_before_product(self) -> None:
        keys = [key for _, key in InvestmentDetailPanel._FIELD_KEYS]
        ci = keys.index("custodian")
        assert keys[ci - 1] == "conglomerate"
        assert keys[ci + 1] == "product"

    def test_custodian_label_is_custodian(self) -> None:
        labels = {key: label for label, key in InvestmentDetailPanel._FIELD_KEYS}
        assert labels["custodian"] == "Custodian"

    def test_custodian_editable_for_manual(self) -> None:
        assert "custodian" in InvestmentDetailPanel._EDITABLE_FOR_MANUAL

    def test_custodian_not_editable_for_import(self) -> None:
        assert "custodian" not in InvestmentDetailPanel._EDITABLE_FOR_IMPORT


class TestDetailPanelFormatFieldCustodian:
    def test_real_custodian_value_formatted_verbatim(self) -> None:
        self_mock = MagicMock(spec=InvestmentDetailPanel)
        inv = MagicMock()
        inv.custodian = "BTG Pactual"
        assert InvestmentDetailPanel._format_field(self_mock, "custodian", inv) == "BTG Pactual"

    def test_none_custodian_formats_as_em_dash(self) -> None:
        self_mock = MagicMock(spec=InvestmentDetailPanel)
        inv = MagicMock()
        inv.custodian = None
        assert InvestmentDetailPanel._format_field(self_mock, "custodian", inv) == "—"


class TestSelectionHandlers:
    def test_on_selection_changed_empty_clears_and_hides_panel(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._table = MagicMock()
        self_mock._detail_panel = MagicMock()
        self_mock._right_pane = MagicMock()
        self_mock._table.selectedItems.return_value = []
        MainWindow._on_selection_changed(self_mock)
        self_mock._detail_panel.clear.assert_called_once()
        self_mock._right_pane.hide.assert_called_once()

    def test_on_selection_changed_with_row_shows_investment(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._table = MagicMock()
        self_mock._detail_panel = MagicMock()
        self_mock._right_pane = MagicMock()
        inv = MagicMock()
        item = MagicMock()
        item.row.return_value = 0
        self_mock._table.selectedItems.return_value = [item]
        self_mock.visible_investments.return_value = [inv]
        MainWindow._on_selection_changed(self_mock)
        self_mock._detail_panel.show_investment.assert_called_once_with(inv)
        self_mock._right_pane.show.assert_called_once()

    def test_on_panel_close_requested_clears_table_selection(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._table = MagicMock()
        self_mock._right_pane = MagicMock()
        self_mock._add_panel = MagicMock()
        MainWindow._on_panel_close_requested(self_mock)
        self_mock._table.clearSelection.assert_called_once()

    def test_on_panel_close_requested_resets_stack_and_hides_pane(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._table = MagicMock()
        self_mock._right_pane = MagicMock()
        self_mock._add_panel = MagicMock()
        MainWindow._on_panel_close_requested(self_mock)
        self_mock._right_pane.setCurrentIndex.assert_called_once_with(0)
        self_mock._right_pane.hide.assert_called_once()

    def test_on_panel_close_requested_resets_add_panel(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._table = MagicMock()
        self_mock._right_pane = MagicMock()
        self_mock._add_panel = MagicMock()
        MainWindow._on_panel_close_requested(self_mock)
        self_mock._add_panel.reset.assert_called_once()


class TestAddPanelCloseButton:
    def test_header_close_button_emits_cancelled(self, qapp) -> None:
        panel = _AddInvestmentPanel(MagicMock(), MagicMock())
        received: list[bool] = []
        panel.cancelled.connect(lambda: received.append(True))
        panel._close_btn.click()
        assert received == [True]


class TestRestoreSelection:
    def test_none_selected_id_is_noop(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._table = MagicMock()
        self_mock._detail_panel = MagicMock()
        MainWindow._restore_selection(self_mock, None, [])
        self_mock._table.selectRow.assert_not_called()
        self_mock._detail_panel.clear.assert_not_called()

    def test_matching_investment_calls_select_row(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._table = MagicMock()
        self_mock._detail_panel = MagicMock()
        inv = MagicMock()
        inv.id = uuid.uuid4()
        MainWindow._restore_selection(self_mock, inv.id, [inv])
        self_mock._table.selectRow.assert_called_once_with(0)

    def test_missing_investment_clears_panel(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._table = MagicMock()
        self_mock._detail_panel = MagicMock()
        self_mock._right_pane = MagicMock()
        inv = MagicMock()
        inv.id = uuid.uuid4()
        other_id = uuid.uuid4()
        MainWindow._restore_selection(self_mock, other_id, [inv])
        self_mock._detail_panel.clear.assert_called_once()
        self_mock._right_pane.hide.assert_called_once()


class TestInvestmentDeleted:
    def test_evicts_matching_cache_entry_and_refreshes(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        inv_id = uuid.uuid4()
        other_id = uuid.uuid4()
        proj_keep = MagicMock()
        proj_keep.investment.id = other_id
        proj_evict = MagicMock()
        proj_evict.investment.id = inv_id
        self_mock.projection_cache = [proj_evict, proj_keep]

        MainWindow._on_investment_deleted(self_mock, inv_id)

        assert self_mock.projection_cache == [proj_keep]
        self_mock.refresh_table.assert_called_once()

    def test_leaves_other_cache_entries_intact(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        inv_id = uuid.uuid4()
        proj_a = MagicMock()
        proj_a.investment.id = uuid.uuid4()
        proj_b = MagicMock()
        proj_b.investment.id = uuid.uuid4()
        self_mock.projection_cache = [proj_a, proj_b]

        MainWindow._on_investment_deleted(self_mock, inv_id)

        assert self_mock.projection_cache == [proj_a, proj_b]

    def test_no_crash_when_cache_is_none(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock.projection_cache = None

        MainWindow._on_investment_deleted(self_mock, uuid.uuid4())

        self_mock.refresh_table.assert_called_once()
        assert self_mock.projection_cache is None


# ── B41 phase 2.4a: active_mock state on MainWindow ───────────────────────────

class TestActiveMock:
    """Tests a-c: set_active_mock and clear_active_mock on MainWindow."""

    def _make_self(self) -> MagicMock:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._expanded_conglomerates = set()
        return self_mock

    def test_set_active_mock_stores_synth_and_projection(self) -> None:
        # a — set_active_mock sets self.active_mock with correct fields
        self_mock = self._make_self()
        synth_inv = MagicMock()
        synth_inv.issuer.conglomerate = "Test Cong"
        projection = MagicMock()

        MainWindow.set_active_mock(self_mock, synth_inv, projection)

        assert self_mock.active_mock is not None
        assert isinstance(self_mock.active_mock, _ActiveMock)
        assert self_mock.active_mock.synth_investment is synth_inv
        assert self_mock.active_mock.projection is projection

    def test_set_active_mock_triggers_refresh(self) -> None:
        # a — set_active_mock calls _refresh_conglomerates
        self_mock = self._make_self()
        synth_inv = MagicMock()
        synth_inv.issuer.conglomerate = "Test Cong"

        MainWindow.set_active_mock(self_mock, synth_inv, MagicMock())

        self_mock._refresh_conglomerates.assert_called_once()

    def test_set_active_mock_expands_conglomerate_before_refresh(self) -> None:
        # b — conglomerate in _expanded_conglomerates BEFORE refresh fires
        self_mock = self._make_self()
        synth_inv = MagicMock()
        synth_inv.issuer.conglomerate = "Test Cong"

        expanded_at_refresh: list[bool] = []

        def _capture_refresh():
            expanded_at_refresh.append("Test Cong" in self_mock._expanded_conglomerates)

        self_mock._refresh_conglomerates.side_effect = _capture_refresh

        MainWindow.set_active_mock(self_mock, synth_inv, MagicMock())

        assert expanded_at_refresh == [True]  # expanded before the refresh call

    def test_clear_active_mock_sets_none(self) -> None:
        # c — clear_active_mock nulls the attribute
        self_mock = self._make_self()
        self_mock.active_mock = MagicMock()

        MainWindow.clear_active_mock(self_mock)

        assert self_mock.active_mock is None

    def test_clear_active_mock_triggers_refresh(self) -> None:
        # c — clear_active_mock calls _refresh_conglomerates
        self_mock = self._make_self()
        self_mock.active_mock = MagicMock()

        MainWindow.clear_active_mock(self_mock)

        self_mock._refresh_conglomerates.assert_called_once()


# ── B41 phase 2.4b-i: mock splice into _refresh_conglomerates ─────────────────

class TestRefreshConglomeratesMockSplice:
    """Tests a-c from the 2.4b-i spec."""

    def _make_self(self, proj, *, inv_id, active_mock=None):
        self_mock = MagicMock(spec=MainWindow)
        self_mock._cong_layout = MagicMock()
        self_mock._cong_section_widgets = {}
        fake_inv = MagicMock()
        fake_inv.id = inv_id
        self_mock.projection_cache = [proj]
        self_mock.visible_investments.return_value = [fake_inv]
        self_mock.active_mock = active_mock
        return self_mock

    def test_no_mock_passes_only_cache_projections(self) -> None:
        # a: active_mock=None — build_conglomerate_report_from_projections
        # receives exactly the filtered cache projections, nothing more.
        inv_id = uuid.uuid4()
        fake_proj = MagicMock()
        fake_proj.investment.id = inv_id

        self_mock = self._make_self(fake_proj, inv_id=inv_id, active_mock=None)
        fake_report = MagicMock()
        fake_report.sections = []

        with patch("justfixed.ui.main.build_conglomerate_report_from_projections",
                   return_value=fake_report) as mock_build:
            MainWindow._refresh_conglomerates(self_mock)

        mock_build.assert_called_once()
        passed = mock_build.call_args.args[0]
        assert passed == [fake_proj]

    def test_with_mock_appends_mock_projection(self) -> None:
        # b: active_mock set — mock's projection is appended after cache projections.
        inv_id = uuid.uuid4()
        fake_proj = MagicMock()
        fake_proj.investment.id = inv_id

        mock_proj = MagicMock()
        active_mock = _ActiveMock(synth_investment=MagicMock(), projection=mock_proj)

        self_mock = self._make_self(fake_proj, inv_id=inv_id, active_mock=active_mock)
        fake_report = MagicMock()
        fake_report.sections = []

        with patch("justfixed.ui.main.build_conglomerate_report_from_projections",
                   return_value=fake_report) as mock_build:
            MainWindow._refresh_conglomerates(self_mock)

        mock_build.assert_called_once()
        passed = mock_build.call_args.args[0]
        assert fake_proj in passed
        assert mock_proj in passed
        assert passed[-1] is mock_proj  # mock appended last

    def test_investments_tab_fgc_report_excludes_mock(self) -> None:
        # c: refresh_table builds the FGC concentration report from
        # projection_cache only — active_mock.projection is NOT included.
        self_mock = MagicMock(spec=MainWindow)
        self_mock._repo = MagicMock()
        self_mock._table = MagicMock()
        self_mock._stack = MagicMock()
        fake_proj = MagicMock()
        self_mock.projection_cache = [fake_proj]
        self_mock.visible_investments.return_value = []
        self_mock.active_mock = MagicMock()  # mock IS set
        self_mock._fgc_status_by_id.side_effect = (
            lambda: MainWindow._fgc_status_by_id(self_mock)
        )

        fake_fgc_report = MagicMock()
        fake_fgc_report.conglomerates = []

        with patch("justfixed.ui.main.fgc_concentration_report_from_projections",
                   return_value=fake_fgc_report) as mock_fgc:
            MainWindow.refresh_table(self_mock)

        # FGC report built from projection_cache only — no mock injected
        mock_fgc.assert_called_once_with(self_mock.projection_cache)


# ── Dev tab runbook (B35) ─────────────────────────────────────────────────────

class TestDevTabRunbook:
    """Verify the Publishing-curves runbook in the Dev tab.

    Uses the real _build_dev_tab method with a bare MagicMock so the
    QWidget tree is actually constructed.  Requires a QApplication (qapp
    fixture from above).
    """

    @pytest.fixture
    def dev_tab(self, qapp):
        self_mock = MagicMock()
        self_mock._seed_loaded_count = 0
        return MainWindow._build_dev_tab(self_mock)

    def test_returns_scroll_area(self, dev_tab) -> None:
        assert isinstance(dev_tab, QScrollArea)

    def test_scroll_area_widget_resizable(self, dev_tab) -> None:
        assert dev_tab.widgetResizable() is True

    def test_scroll_area_no_frame(self, dev_tab) -> None:
        from PySide6.QtWidgets import QFrame
        assert dev_tab.frameShape() == QFrame.Shape.NoFrame

    def test_runbook_title_present(self, dev_tab) -> None:
        labels = dev_tab.findChildren(QLabel)
        assert any(lbl.text() == "Publishing curves" for lbl in labels)

    def test_three_copy_buttons(self, dev_tab) -> None:
        buttons = dev_tab.findChildren(QPushButton)
        copy_btns = [b for b in buttons if b.text() == "Copy"]
        assert len(copy_btns) == 3

    def test_three_command_displays(self, dev_tab) -> None:
        displays = dev_tab.findChildren(QPlainTextEdit)
        assert len(displays) == 3

    def test_curve_labels_set_as_instance_attrs(self, qapp) -> None:
        self_mock = MagicMock()
        self_mock._seed_loaded_count = 0
        MainWindow._build_dev_tab(self_mock)
        assert isinstance(self_mock._dev_cdi_label, QLabel)
        assert isinstance(self_mock._dev_pre_label, QLabel)
        assert isinstance(self_mock._dev_ipca_label, QLabel)

    def test_copy_handler_clipboard_only_no_subprocess(self, dev_tab) -> None:
        """Copy button writes to clipboard only — no subprocess or QProcess."""
        import subprocess
        from PySide6.QtCore import QProcess

        buttons = dev_tab.findChildren(QPushButton)
        copy_btns = [b for b in buttons if b.text() == "Copy"]
        assert copy_btns, "no Copy buttons found"

        mock_board = MagicMock()
        with patch("subprocess.run") as mock_run, \
             patch("subprocess.Popen") as mock_popen, \
             patch.object(QProcess, "start") as mock_qprocess, \
             patch("justfixed.ui.main.QApplication.clipboard",
                   return_value=mock_board):
            copy_btns[0].click()

        mock_run.assert_not_called()
        mock_popen.assert_not_called()
        mock_qprocess.assert_not_called()
        mock_board.setText.assert_called_once()

    def test_cmd_1b_text_matches_dev_routine(self, dev_tab) -> None:
        displays = dev_tab.findChildren(QPlainTextEdit)
        all_text = "\n---\n".join(d.toPlainText() for d in displays)
        assert "publish_curves.py" in all_text
        assert "--as-of" in all_text
        assert "--commit" in all_text

    def test_cmd_1c_text_matches_dev_routine(self, dev_tab) -> None:
        displays = dev_tab.findChildren(QPlainTextEdit)
        all_text = "\n---\n".join(d.toPlainText() for d in displays)
        assert "show --stat HEAD" in all_text
        assert "curves/latest.json" in all_text

    def test_cmd_1d_text_matches_dev_routine(self, dev_tab) -> None:
        displays = dev_tab.findChildren(QPlainTextEdit)
        all_text = "\n---\n".join(d.toPlainText() for d in displays)
        assert "justfixed-data push" in all_text
        assert "status -sb" in all_text


# ── _CalculatorTab assumption delegation ──────────────────────────────────────

class TestCalculatorTabAssumptionDelegation:
    """_assumed_cdi/_assumed_ipca must read live from the owning MainWindow,
    even after QTabWidget.addTab reparents the widget away from that window."""

    @pytest.fixture
    def session_factory(self):
        from justfixed.persistence.database import Base, make_engine, make_session_factory
        engine = make_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        return make_session_factory(engine)

    def test_reads_from_owner_after_reparenting(self, qapp, session_factory) -> None:
        from PySide6.QtWidgets import QTabWidget, QWidget
        # Simulate the production scenario: a stub "MainWindow" carries the
        # assumptions; addTab forces Qt to reparent the widget, so self.parent()
        # no longer points at the stub.
        parent = QWidget()
        parent._assumed_ipca = Decimal("0.20")  # type: ignore[attr-defined]
        calc = _CalculatorTab(session_factory=session_factory, parent=parent)

        tabs = QTabWidget()
        tabs.addTab(calc, "Calc")  # reparents calc — self.parent() now ≠ parent

        # The stored _main_window reference must still resolve correctly.
        assert calc._assumed_ipca == Decimal("0.20")

        # Mutation is reflected live — not a captured copy.
        parent._assumed_ipca = Decimal("0.05")  # type: ignore[attr-defined]
        assert calc._assumed_ipca == Decimal("0.05")

    def test_falls_back_to_module_default_when_unowned(self, qapp, session_factory) -> None:
        calc = _CalculatorTab(session_factory=session_factory, parent=None)
        assert calc._assumed_ipca == _ASSUMED_IPCA

    def test_reset_reaches_owner_after_reparenting(self, qapp, session_factory) -> None:
        from PySide6.QtWidgets import QTabWidget, QWidget

        class _StubWin(QWidget):
            def __init__(self) -> None:
                super().__init__()
                self.cleared = 0
            def clear_active_mock(self) -> None:
                self.cleared += 1

        stub = _StubWin()
        calc = _CalculatorTab(session_factory=session_factory, parent=stub)
        tabs = QTabWidget()
        tabs.addTab(calc, "Calc")          # reparents calc; self.parent() != stub now
        before = stub.cleared
        calc.reset()
        # With the old self.parent(), reset() hits the stacked widget and never
        # calls clear_active_mock; the stored _main_window reference fixes that.
        assert stub.cleared == before + 1


# ── Projection assumption editor (Dev tab) ────────────────────────────────────

class TestProjectionAssumptionEditor:
    def _fake(self):
        m = MagicMock()
        m._assumed_cdi = _ASSUMED_CDI
        m._assumed_ipca = _ASSUMED_IPCA
        m._dev_cdi_input = QLineEdit()
        m._dev_ipca_input = QLineEdit()
        return m

    def test_apply_updates_single_source(self, qapp) -> None:
        m = self._fake()
        m._dev_cdi_input.setText("20,00")
        m._dev_ipca_input.setText("8,00")
        MainWindow._on_apply_assumptions_clicked(m)
        assert m._assumed_cdi == Decimal("0.20")
        assert m._assumed_ipca == Decimal("0.08")

    def test_apply_rejects_invalid_input(self, qapp) -> None:
        m = self._fake()
        m._dev_cdi_input.setText("1.5")   # period not allowed → ValueError
        m._dev_ipca_input.setText("8,00")
        MainWindow._on_apply_assumptions_clicked(m)
        assert m._assumed_cdi == _ASSUMED_CDI    # unchanged on bad input
        assert m._assumed_ipca == _ASSUMED_IPCA

    def test_reset_restores_defaults(self, qapp) -> None:
        m = self._fake()
        m._assumed_cdi = Decimal("0.30")
        m._assumed_ipca = Decimal("0.10")
        MainWindow._on_reset_assumptions_clicked(m)
        assert m._assumed_cdi == _ASSUMED_CDI
        assert m._assumed_ipca == _ASSUMED_IPCA


# ── Investments table smoke (commit 2 of global styling) ─────────────────────

def _make_smoke_investment(*, maturity_offset_days: int):
    from justfixed.domain.investment import Investment
    from justfixed.domain.issuer import Issuer, IssuerKind
    from justfixed.domain.money import Money
    from justfixed.domain.product import ProductType
    from justfixed.domain.rates import Prefixed
    issuer = Issuer.create("Banco Smoke", "Smoke Group", IssuerKind.COMMERCIAL_BANK)
    return Investment(
        product=ProductType.CDB,
        issuer=issuer,
        principal=Money.from_reais("10000"),
        rate=Prefixed.from_percent("12"),
        purchase_date=date(2022, 1, 3),
        maturity_date=date.today() + timedelta(days=maturity_offset_days),
    )


class TestInvestmentsTableSmoke:
    """Construction smoke: objectName, widget props, and row population do not raise."""

    def _make_window(self):
        with patch("justfixed.ui.main.default_database_url", return_value="sqlite:///:memory:"), \
             patch("justfixed.ui.main.run_migrations"), \
             patch("justfixed.ui.main.fetch_seed_data", return_value={}), \
             patch("justfixed.ui.main.load_seed_if_empty", return_value=0):
            return MainWindow()

    def test_table_objectname(self, qapp) -> None:
        win = self._make_window()
        try:
            assert win._table.objectName() == "investmentsTable"
        finally:
            win.close()

    def test_table_alternating_rows_enabled(self, qapp) -> None:
        win = self._make_window()
        try:
            assert win._table.alternatingRowColors() is True
        finally:
            win.close()

    def test_table_grid_hidden(self, qapp) -> None:
        win = self._make_window()
        try:
            assert win._table.showGrid() is False
        finally:
            win.close()

    def test_populate_active_row_no_exception(self, qapp) -> None:
        win = self._make_window()
        try:
            inv = _make_smoke_investment(maturity_offset_days=365)
            win._table.setRowCount(1)
            win._populate_row(0, inv, current_value=None, projected_value=None, fgc_status=None)
        finally:
            win.close()

    def test_populate_paid_row_no_exception(self, qapp) -> None:
        """PAID path (matured row, hide_matured=False) runs without exception."""
        win = self._make_window()
        try:
            win._hide_matured = False
            inv = _make_smoke_investment(maturity_offset_days=-1)
            win._table.setRowCount(1)
            win._populate_row(0, inv, current_value=None, projected_value=None, fgc_status=None)
        finally:
            win.close()

    def test_stylesheet_applied_no_exception(self, qapp) -> None:
        from justfixed.ui.qss import make_stylesheet
        win = self._make_window()
        try:
            win.setStyleSheet(make_stylesheet())
        finally:
            win.close()

    def test_table_row_height_is_26(self, qapp) -> None:
        # IN-3: row density pinned to 26px via setDefaultSectionSize.
        win = self._make_window()
        try:
            assert win._table.verticalHeader().defaultSectionSize() == 26
        finally:
            win.close()

    def test_cong_project_button_has_toolbar_role(self, qapp) -> None:
        # CG-6: Conglomerates "Project as of today" is now green (toolbar), not secondary.
        win = self._make_window()
        try:
            assert win._cong_project_btn.property("role") == "toolbar"
        finally:
            win.close()

    def test_investments_project_button_still_has_toolbar_role(self, qapp) -> None:
        # Regression: Investments tab Project button was already toolbar; must stay.
        win = self._make_window()
        try:
            assert win._project_btn.property("role") == "toolbar"
        finally:
            win.close()

    def test_export_button_has_toolbar_role(self, qapp) -> None:
        win = self._make_window()
        try:
            assert win._export_btn.property("role") == "toolbar"
        finally:
            win.close()

    def test_project_and_export_not_in_top_toolbar(self, qapp) -> None:
        # Relocation: Project and Export moved below the table — they must NOT
        # share a parent widget with the Import and Add buttons.
        win = self._make_window()
        try:
            assert win._project_btn.parentWidget() is not win._import_btn.parentWidget()
            assert win._export_btn.parentWidget() is not win._import_btn.parentWidget()
        finally:
            win.close()

    def test_project_and_export_share_parent(self, qapp) -> None:
        # Both below-table buttons live in the same layout container.
        win = self._make_window()
        try:
            assert win._project_btn.parentWidget() is win._export_btn.parentWidget()
        finally:
            win.close()

    def test_totals_strip_objectname(self, qapp) -> None:
        # IN-5: wrapper widget exists and carries the QSS objectName.
        from PySide6.QtWidgets import QWidget
        win = self._make_window()
        try:
            strip = win.findChild(QWidget, "totalsStrip")
            assert strip is not None
        finally:
            win.close()

    def test_table_horizontal_scroll_as_needed(self, qapp) -> None:
        # IN-6: table scrolls horizontally instead of crushing columns.
        win = self._make_window()
        try:
            assert win._table.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
        finally:
            win.close()

    def test_table_minimum_section_size(self, qapp) -> None:
        # IN-6: columns won't shrink below 60px; prevents mid-word header truncation.
        win = self._make_window()
        try:
            assert win._table.horizontalHeader().minimumSectionSize() == 60
        finally:
            win.close()

    def test_table_inactive_selection_color_is_selection_bg(self, qapp) -> None:
        # IN-1: inactive palette group Highlight == SELECTION_BG so selection
        # looks identical whether or not the table has keyboard focus.
        from PySide6.QtGui import QPalette, QColor
        from justfixed.ui.theme import COLORS
        win = self._make_window()
        try:
            pal = win._table.palette()
            assert pal.color(
                QPalette.ColorGroup.Inactive, QPalette.ColorRole.Highlight
            ) == QColor(COLORS.SELECTION_BG)
        finally:
            win.close()

    def test_table_active_selection_color_is_selection_bg(self, qapp) -> None:
        from PySide6.QtGui import QPalette, QColor
        from justfixed.ui.theme import COLORS
        win = self._make_window()
        try:
            pal = win._table.palette()
            assert pal.color(
                QPalette.ColorGroup.Active, QPalette.ColorRole.Highlight
            ) == QColor(COLORS.SELECTION_BG)
        finally:
            win.close()

    def test_highlight_row_cream_still_used_for_import_flash(self, qapp) -> None:
        # Import-flash (_HIGHLIGHT_COLOR) must remain cream, not the selection blue.
        from PySide6.QtGui import QColor
        from justfixed.ui.main import _HIGHLIGHT_COLOR
        from justfixed.ui.theme import COLORS
        assert _HIGHLIGHT_COLOR == QColor(COLORS.HIGHLIGHT_ROW)
        assert _HIGHLIGHT_COLOR != QColor(COLORS.SELECTION_BG)


# ── Investments table alignment (commit 3a: left-align) ──────────────────────

class TestInvestmentsTableAlignment:
    """Left-align for data columns; center for FGC — in both cells and headers."""

    def _make_window(self):
        with patch("justfixed.ui.main.default_database_url", return_value="sqlite:///:memory:"), \
             patch("justfixed.ui.main.run_migrations"), \
             patch("justfixed.ui.main.fetch_seed_data", return_value={}), \
             patch("justfixed.ui.main.load_seed_if_empty", return_value=0):
            return MainWindow()

    def test_mono_cell_is_left_aligned(self, qapp) -> None:
        win = self._make_window()
        try:
            inv = _make_smoke_investment(maturity_offset_days=365)
            win._table.setRowCount(1)
            win._populate_row(0, inv, current_value=None, projected_value=None, fgc_status=None)
            from justfixed.ui.main import _COL_PRINCIPAL
            item = win._table.item(0, _COL_PRINCIPAL)
            assert item is not None
            assert Qt.AlignmentFlag.AlignLeft in Qt.Alignment(item.textAlignment())
            assert Qt.AlignmentFlag.AlignRight not in Qt.Alignment(item.textAlignment())
        finally:
            win.close()

    def test_paid_cell_is_left_aligned(self, qapp) -> None:
        win = self._make_window()
        try:
            win._hide_matured = False
            inv = _make_smoke_investment(maturity_offset_days=-1)
            win._table.setRowCount(1)
            win._populate_row(0, inv, current_value=None, projected_value=None, fgc_status=None)
            from justfixed.ui.main import _COL_CURRENT
            item = win._table.item(0, _COL_CURRENT)
            assert item is not None
            assert item.text() == "PAID"
            assert Qt.AlignmentFlag.AlignLeft in Qt.Alignment(item.textAlignment())
            assert Qt.AlignmentFlag.AlignRight not in Qt.Alignment(item.textAlignment())
        finally:
            win.close()

    def test_fgc_cell_is_center_aligned(self, qapp) -> None:
        win = self._make_window()
        try:
            inv = _make_smoke_investment(maturity_offset_days=365)
            win._table.setRowCount(1)
            win._populate_row(0, inv, current_value=None, projected_value=None, fgc_status=None)
            item = win._table.item(0, _COL_FGC)
            assert item is not None
            assert Qt.AlignmentFlag.AlignCenter in Qt.Alignment(item.textAlignment())
        finally:
            win.close()

    def test_data_column_header_is_left_aligned(self, qapp) -> None:
        win = self._make_window()
        try:
            hdr_item = win._table.horizontalHeaderItem(_COL_PRINCIPAL)
            assert hdr_item is not None
            assert Qt.AlignmentFlag.AlignLeft in Qt.Alignment(hdr_item.textAlignment())
            assert Qt.AlignmentFlag.AlignRight not in Qt.Alignment(hdr_item.textAlignment())
        finally:
            win.close()

    def test_fgc_column_header_is_center_aligned(self, qapp) -> None:
        win = self._make_window()
        try:
            hdr_item = win._table.horizontalHeaderItem(_COL_FGC)
            assert hdr_item is not None
            assert Qt.AlignmentFlag.AlignCenter in Qt.Alignment(hdr_item.textAlignment())
        finally:
            win.close()

    def test_paid_row_fgc_badge_is_greyed(self, qapp) -> None:
        """FIX 2: matured PAID row — FGC badge foreground == _MATURED_COLOR."""
        from justfixed.ui.main import _MATURED_COLOR
        win = self._make_window()
        try:
            win._hide_matured = False
            inv = _make_smoke_investment(maturity_offset_days=-1)
            win._table.setRowCount(1)
            win._populate_row(0, inv, current_value=None, projected_value=None, fgc_status=None)
            fgc_item = win._table.item(0, _COL_FGC)
            assert fgc_item is not None
            assert fgc_item.foreground().color() == _MATURED_COLOR
        finally:
            win.close()

    def test_active_row_fgc_badge_keeps_status_color(self, qapp) -> None:
        """FIX 2 regression: non-matured row FGC keeps its own foreground, not _MATURED_COLOR."""
        from PySide6.QtGui import QColor
        from justfixed.engine.fgc import ExposureStatus
        from justfixed.ui.main import _MATURED_COLOR, COLORS
        win = self._make_window()
        try:
            inv = _make_smoke_investment(maturity_offset_days=365)
            win._table.setRowCount(1)
            win._populate_row(0, inv, current_value=None, projected_value=None,
                              fgc_status=ExposureStatus.UNDER)
            fgc_item = win._table.item(0, _COL_FGC)
            assert fgc_item is not None
            assert fgc_item.foreground().color() != _MATURED_COLOR
            assert fgc_item.foreground().color() == QColor(COLORS.FGC_UNDER)
        finally:
            win.close()


# ---------------------------------------------------------------------------
# Detail panel: broker_reported_value provenance (B10 Slice 1)
# ---------------------------------------------------------------------------


class TestRefreshProjection:
    """refresh_projection current-value provenance: user-edited "(edited)" >
    broker-reported "(broker)" > computed (unmarked)."""

    def _make_self_mock(self, broker_reported_value=None, user_edited_value=None):
        self_mock = MagicMock()

        inv = MagicMock()
        inv.broker_reported_value = broker_reported_value
        inv.user_edited_value = user_edited_value
        self_mock._current_inv = inv

        proj = MagicMock()
        proj.investment.id = inv.id
        proj.current_value.to_display.return_value = "R$ 10.200,00"
        proj.gross_at_maturity.to_display.return_value = "R$ 11.000,00"
        proj.net_at_maturity.to_display.return_value = "R$ 10.800,00"
        proj.tax_breakdown.tax_rate = Decimal("0.15")
        proj.tax_breakdown.gain.to_display.return_value = "R$ 800,00"
        proj.tax_breakdown.tax_amount.to_display.return_value = "R$ 200,00"
        proj.as_of = date(2026, 6, 11)

        self_mock._main_window.projection_cache = [proj]
        return self_mock

    def test_shows_broker_value_with_provenance_when_present(self) -> None:
        broker_money = Money.from_reais("10500")
        self_mock = self._make_self_mock(broker_reported_value=broker_money)

        InvestmentDetailPanel.refresh_projection(self_mock)

        text = self_mock._proj_current_lbl.setText.call_args[0][0]
        assert broker_money.to_display() in text
        assert "(broker)" in text

    def test_shows_computed_value_unmarked_when_no_broker_value(self) -> None:
        self_mock = self._make_self_mock(broker_reported_value=None)

        InvestmentDetailPanel.refresh_projection(self_mock)

        text = self_mock._proj_current_lbl.setText.call_args[0][0]
        assert "R$ 10.200,00" in text
        assert "(estimated)" not in text
        assert "(broker)" not in text

    def test_user_edited_value_takes_priority_over_broker(self) -> None:
        user_money = Money.from_reais("10600")
        broker_money = Money.from_reais("10500")
        self_mock = self._make_self_mock(
            user_edited_value=user_money,
            broker_reported_value=broker_money,
        )

        InvestmentDetailPanel.refresh_projection(self_mock)

        text = self_mock._proj_current_lbl.setText.call_args[0][0]
        assert user_money.to_display() in text
        assert "(edited)" in text
        assert "(broker)" not in text

    def test_shows_user_edited_value_when_broker_absent(self) -> None:
        user_money = Money.from_reais("10600")
        self_mock = self._make_self_mock(
            user_edited_value=user_money,
            broker_reported_value=None,
        )

        InvestmentDetailPanel.refresh_projection(self_mock)

        text = self_mock._proj_current_lbl.setText.call_args[0][0]
        assert user_money.to_display() in text
        assert "(edited)" in text

    def test_falls_back_to_broker_when_user_edited_cleared(self) -> None:
        broker_money = Money.from_reais("10500")
        self_mock = self._make_self_mock(
            user_edited_value=None,
            broker_reported_value=broker_money,
        )

        InvestmentDetailPanel.refresh_projection(self_mock)

        text = self_mock._proj_current_lbl.setText.call_args[0][0]
        assert broker_money.to_display() in text
        assert "(broker)" in text
        assert "(edited)" not in text


class TestProjectionCacheRepair:
    def test_cache_repaired_after_conglomerate_rename(self) -> None:
        inv = MagicMock()
        inv.id = uuid.uuid4()
        inv.issuer.id = uuid.uuid4()
        inv.issuer.name = "Banco Exemplo"
        inv.issuer.conglomerate = "Old Group"
        inv.issuer.kind = IssuerKind.COMMERCIAL_BANK
        inv.maturity_date = date.today() + timedelta(days=30)
        inv.purchase_date = date.today() - timedelta(days=30)
        inv.product = MagicMock()
        inv.principal = _brl("10000.00")

        proj = _make_integration_projection(inv, _brl("10100.00"), _brl("10500.00"))
        self_mock = _make_integration_self_mock([inv], projection_cache=[proj])

        inv.issuer.conglomerate = "New Group"

        MainWindow.refresh_table(self_mock)

        assert len(self_mock.projection_cache) == 1
        repaired = self_mock.projection_cache[0]
        assert repaired.investment.issuer.conglomerate == "New Group"
        assert repaired.current_value == _brl("10100.00")
        assert repaired.gross_at_maturity == _brl("10500.00")

    def test_cache_entry_dropped_when_investment_deleted(self) -> None:
        inv1 = MagicMock()
        inv1.id = uuid.uuid4()
        inv1.issuer.id = uuid.uuid4()
        inv1.issuer.conglomerate = "Group A"
        inv1.issuer.kind = IssuerKind.COMMERCIAL_BANK
        inv1.maturity_date = date.today() + timedelta(days=30)
        inv1.purchase_date = date.today() - timedelta(days=30)
        inv1.product = MagicMock()
        inv1.principal = _brl("10000.00")

        inv2 = MagicMock()
        inv2.id = uuid.uuid4()
        inv2.issuer.id = uuid.uuid4()
        inv2.issuer.conglomerate = "Group B"
        inv2.issuer.kind = IssuerKind.COMMERCIAL_BANK
        inv2.maturity_date = date.today() + timedelta(days=60)
        inv2.purchase_date = date.today() - timedelta(days=60)
        inv2.product = MagicMock()
        inv2.principal = _brl("20000.00")

        proj1 = _make_integration_projection(inv1, _brl("10100.00"), _brl("10500.00"))
        proj2 = _make_integration_projection(inv2, _brl("20200.00"), _brl("21000.00"))

        self_mock = _make_integration_self_mock([inv1, inv2], projection_cache=[proj1, proj2])

        self_mock._repo.list_all.return_value = [inv2]

        MainWindow.refresh_table(self_mock)

        assert len(self_mock.projection_cache) == 1
        assert self_mock.projection_cache[0].investment is inv2
