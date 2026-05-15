"""Tests for MainWindow projection cache infrastructure (B' UI session 2, stage B).

Uses the "real method, MagicMock self" pattern: the actual MainWindow methods
are called with a MagicMock stand-in for self. All attribute assignments land
on the mock and are directly assertable. No Qt window is instantiated, so
no QApplication or database setup is needed.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QMessageBox

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
