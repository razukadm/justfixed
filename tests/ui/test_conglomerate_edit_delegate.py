"""Tests for ConglomerateEditDelegate — validation and save logic.

Uses a session-scoped QApplication so Qt objects can be instantiated
without a running event loop. Editor, model, and index are mocked;
no real database or window is created.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, call, patch

import pytest
from PySide6.QtWidgets import QApplication

from justfixed.domain.issuer import Issuer, UNVERIFIED_CONGLOMERATE_PREFIX
from justfixed.ui.main import ConglomerateEditDelegate


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


@pytest.fixture
def delegate(qapp):
    return ConglomerateEditDelegate(MagicMock(), MagicMock())


def _mock_editor(text: str) -> MagicMock:
    editor = MagicMock()
    editor.text.return_value = text
    return editor


# ---------- Validation ----------


class TestConglomerateEditDelegateValidation:
    def test_rejects_empty_string(self, delegate) -> None:
        delegate.setModelData(_mock_editor(""), MagicMock(), MagicMock())

        delegate._session_factory.assert_not_called()
        status_bar = delegate._main_window.statusBar.return_value
        status_bar.showMessage.assert_called_once()
        msg, timeout = status_bar.showMessage.call_args[0]
        assert "empty" in msg.lower()
        assert timeout == 4000

    def test_rejects_over_100_chars(self, delegate) -> None:
        delegate.setModelData(_mock_editor("x" * 101), MagicMock(), MagicMock())

        delegate._session_factory.assert_not_called()
        status_bar = delegate._main_window.statusBar.return_value
        status_bar.showMessage.assert_called_once()
        msg, timeout = status_bar.showMessage.call_args[0]
        assert "100" in msg
        assert timeout == 4000

    def test_rejects_unverified_prefix(self, delegate) -> None:
        delegate.setModelData(
            _mock_editor(f"{UNVERIFIED_CONGLOMERATE_PREFIX}Foo Bank"),
            MagicMock(),
            MagicMock(),
        )

        delegate._session_factory.assert_not_called()
        status_bar = delegate._main_window.statusBar.return_value
        status_bar.showMessage.assert_called_once()
        msg, timeout = status_bar.showMessage.call_args[0]
        assert "[unverified]" in msg
        assert timeout == 4000


# ---------- Save ----------


def _make_inv(name: str = "Foo", conglomerate: str = "[unverified] Foo") -> MagicMock:
    inv = MagicMock()
    inv.issuer.name = name
    inv.issuer.conglomerate = conglomerate
    return inv


class TestConglomerateEditDelegateSave:
    def test_accept_writes_to_both_repos_in_order(self, delegate) -> None:
        inv = _make_inv()
        delegate._main_window._visible_investments.return_value = [inv]
        index = MagicMock()
        index.row.return_value = 0

        manager = MagicMock()
        with patch("justfixed.ui.main.IssuerRepository") as MockIssuerRepo, \
             patch("justfixed.ui.main.CurationMemoryRepository") as MockCurationRepo:
            manager.attach_mock(MockIssuerRepo.return_value.save, "issuer_save")
            manager.attach_mock(MockCurationRepo.return_value.set, "curation_set")

            delegate.setModelData(_mock_editor("New Conglomerate"), MagicMock(), index)

        manager.assert_has_calls([
            call.issuer_save(inv.issuer),
            call.curation_set(Issuer.normalize_name("Foo"), "New Conglomerate"),
        ])

    def test_issuer_save_failure_aborts_curation_write(self, delegate) -> None:
        inv = _make_inv()
        delegate._main_window._visible_investments.return_value = [inv]
        index = MagicMock()
        index.row.return_value = 0

        with patch("justfixed.ui.main.IssuerRepository") as MockIssuerRepo, \
             patch("justfixed.ui.main.CurationMemoryRepository") as MockCurationRepo:
            MockIssuerRepo.return_value.save.side_effect = Exception("DB error")

            delegate.setModelData(_mock_editor("New Conglomerate"), MagicMock(), index)

            MockCurationRepo.return_value.set.assert_not_called()

        assert inv.issuer.conglomerate == "[unverified] Foo"
        status_bar = delegate._main_window.statusBar.return_value
        status_bar.showMessage.assert_called_once()
        msg, _ = status_bar.showMessage.call_args[0]
        assert "unchanged" in msg.lower()

    def test_curation_failure_does_not_rollback_issuer_save(self, delegate) -> None:
        inv = _make_inv()
        delegate._main_window._visible_investments.return_value = [inv]
        index = MagicMock()
        index.row.return_value = 0

        with patch("justfixed.ui.main.IssuerRepository") as MockIssuerRepo, \
             patch("justfixed.ui.main.CurationMemoryRepository") as MockCurationRepo, \
             patch("justfixed.ui.main.logging") as mock_logging:
            MockCurationRepo.return_value.set.side_effect = Exception("Curation error")

            delegate.setModelData(_mock_editor("New Conglomerate"), MagicMock(), index)

            MockIssuerRepo.return_value.save.assert_called_once()

        assert inv.issuer.conglomerate == "New Conglomerate"
        mock_logging.warning.assert_called_once()
        delegate._main_window._refresh_table.assert_called_once()
