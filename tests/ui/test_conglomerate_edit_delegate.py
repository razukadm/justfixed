"""Tests for ConglomerateEditDelegate — validation and save logic.

Uses a session-scoped QApplication so Qt objects can be instantiated
without a running event loop. Editor, model, and index are mocked;
no real database or window is created.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication

from justfixed.domain.issuer import UNVERIFIED_CONGLOMERATE_PREFIX
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
