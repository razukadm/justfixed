"""Tests for MainWindow projection cache infrastructure (B' UI session 2, stage B).

Uses the "real method, MagicMock self" pattern: the actual MainWindow methods
are called with a MagicMock stand-in for self. All attribute assignments land
on the mock and are directly assertable. No Qt window is instantiated, so
no QApplication or database setup is needed.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from unittest.mock import MagicMock, call, patch

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from justfixed.engine.fgc import ExposureStatus
from justfixed.ui.main import MainWindow


class TestProjectionCachePopulation:
    def test_project_done_populates_cache(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock.projection_cache = None
        fake_results = []
        fake_fgc = MagicMock()
        fake_fgc.conglomerates = []

        MainWindow._on_project_done(self_mock, fake_results, fake_fgc)

        assert self_mock.projection_cache is fake_results


class TestProjectionCacheInvalidation:
    def test_import_done_clears_cache(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock.projection_cache = [MagicMock()]
        self_mock._status_label = MagicMock()
        fake_result = MagicMock()
        fake_result.inserted = 3
        fake_result.skipped = 0

        MainWindow._on_import_done(self_mock, fake_result)

        assert self_mock.projection_cache is None

    def test_clear_db_clears_cache(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock.projection_cache = [MagicMock()]
        self_mock._investments = [MagicMock()]  # non-empty so dialog appears
        self_mock._repo = MagicMock()
        self_mock._repo.delete_all.return_value = (1, 0)

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
        return self_mock

    def test_refresh_table_with_cache_uses_fgc_report(self) -> None:
        self_mock = self._make_self_mock()
        fake_inv = MagicMock()
        fake_inv.issuer.conglomerate = "Banco X S.A."
        self_mock.visible_investments.return_value = [fake_inv]

        fake_conglomerate = MagicMock()
        fake_conglomerate.conglomerate_name = "Banco X S.A."
        fake_conglomerate.current_status = ExposureStatus.APPROACHING
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


class TestRefreshTableHighlight:
    def _make_self_mock(self) -> MagicMock:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._repo = MagicMock()
        self_mock._table = MagicMock()
        self_mock._stack = MagicMock()
        self_mock.projection_cache = None
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
                   filter_conglomerate: str | None = None) -> MagicMock:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._investments = investments
        self_mock._hide_matured = hide_matured
        self_mock._filter_issuer = filter_issuer
        self_mock._filter_conglomerate = filter_conglomerate
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
