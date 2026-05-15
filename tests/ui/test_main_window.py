"""Tests for MainWindow projection cache infrastructure (B' UI session 2, stage B).

Uses the "real method, MagicMock self" pattern: the actual MainWindow methods
are called with a MagicMock stand-in for self. All attribute assignments land
on the mock and are directly assertable. No Qt window is instantiated, so
no QApplication or database setup is needed.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, call, patch

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from justfixed.engine.fgc import ExposureStatus
from justfixed.ui.main import MainWindow


class TestProjectionCachePopulation:
    def test_project_done_populates_cache(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._projection_cache = None
        fake_results = []
        fake_fgc = MagicMock()
        fake_fgc.conglomerates = []

        MainWindow._on_project_done(self_mock, fake_results, fake_fgc)

        assert self_mock._projection_cache is fake_results


class TestProjectionCacheInvalidation:
    def test_import_done_clears_cache(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._projection_cache = [MagicMock()]
        self_mock._status_label = MagicMock()
        fake_result = MagicMock()
        fake_result.inserted = 3
        fake_result.skipped = 0

        MainWindow._on_import_done(self_mock, fake_result)

        assert self_mock._projection_cache is None

    def test_clear_db_clears_cache(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._projection_cache = [MagicMock()]
        self_mock._investments = [MagicMock()]  # non-empty so dialog appears
        self_mock._repo = MagicMock()
        self_mock._repo.delete_all.return_value = (1, 0)

        with patch("justfixed.ui.main.QMessageBox.question",
                   return_value=QMessageBox.StandardButton.Yes):
            MainWindow._on_clear_db_clicked(self_mock)

        assert self_mock._projection_cache is None


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
        self_mock._visible_investments.return_value = [fake_inv]

        fake_conglomerate = MagicMock()
        fake_conglomerate.conglomerate_name = "Banco X S.A."
        fake_conglomerate.current_status = ExposureStatus.APPROACHING
        fake_report = MagicMock()
        fake_report.conglomerates = [fake_conglomerate]

        self_mock._projection_cache = [MagicMock()]

        with patch("justfixed.ui.main.fgc_concentration_report_from_projections",
                   return_value=fake_report) as mock_fgc_func:
            MainWindow._refresh_table(self_mock)

        mock_fgc_func.assert_called_once_with(self_mock._projection_cache)
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
        self_mock._visible_investments.return_value = [fake_inv]
        self_mock._projection_cache = None

        MainWindow._refresh_table(self_mock)

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
        self_mock._projection_cache = None
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

        self_mock._visible_investments.return_value = [matching_inv, other_inv]

        MainWindow._refresh_table(self_mock, highlight_issuer_id=matching_id)

        calls = self_mock._populate_row.call_args_list
        assert calls[0] == call(0, matching_inv, current_value=None, projected_value=None,
                                fgc_status=None, highlight=True)
        assert calls[1] == call(1, other_inv, current_value=None, projected_value=None,
                                fgc_status=None, highlight=False)

    def test_refresh_table_no_highlight_when_id_is_none(self) -> None:
        self_mock = self._make_self_mock()
        fake_inv = MagicMock()
        self_mock._visible_investments.return_value = [fake_inv]

        MainWindow._refresh_table(self_mock)

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
            MainWindow._trigger_conglomerate_highlight(self_mock, uuid.uuid4())

        old_timer.stop.assert_called_once()

    def test_trigger_highlight_calls_refresh_with_id(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._highlight_timer = None
        issuer_id = uuid.uuid4()

        with patch("justfixed.ui.main.QTimer"):
            MainWindow._trigger_conglomerate_highlight(self_mock, issuer_id)

        self_mock._refresh_table.assert_called_once_with(highlight_issuer_id=issuer_id)

    def test_trigger_highlight_schedules_clear_after_3000ms(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._highlight_timer = None

        with patch("justfixed.ui.main.QTimer") as MockQTimer:
            mock_timer = MagicMock(spec=QTimer)
            MockQTimer.return_value = mock_timer
            MainWindow._trigger_conglomerate_highlight(self_mock, uuid.uuid4())

        mock_timer.setSingleShot.assert_called_once_with(True)
        mock_timer.setInterval.assert_called_once_with(3000)
        mock_timer.start.assert_called_once()


class TestRefreshTableScrollPreservation:
    def test_refresh_table_preserves_scroll_position(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._repo = MagicMock()
        self_mock._table = MagicMock()
        self_mock._stack = MagicMock()
        self_mock._projection_cache = None
        self_mock._visible_investments.return_value = []
        self_mock._table.verticalScrollBar.return_value.value.return_value = 150

        MainWindow._refresh_table(self_mock)

        self_mock._table.verticalScrollBar.return_value.setValue.assert_called_once_with(150)
