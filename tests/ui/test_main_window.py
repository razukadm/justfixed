"""Tests for MainWindow projection cache infrastructure (B' UI session 2, stage B).

Uses the "real method, MagicMock self" pattern: the actual MainWindow methods
are called with a MagicMock stand-in for self. All attribute assignments land
on the mock and are directly assertable. No Qt window is instantiated, so
no QApplication or database setup is needed.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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
        )
