"""Tests for the Panel widget."""

from __future__ import annotations

import sys

import pytest
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QWidget

from justfixed.ui.widgets.panel import Panel


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


class TestPanel:
    def test_is_qframe(self, qapp) -> None:
        assert isinstance(Panel("Title"), QFrame)

    def test_object_name(self, qapp) -> None:
        assert Panel("Title").objectName() == "panel_frame"

    def test_title_label_object_name(self, qapp) -> None:
        p = Panel("My Title")
        lbl = p.findChild(QLabel, "panel_title")
        assert lbl is not None
        assert lbl.text() == "My Title"

    def test_meta_label_object_name(self, qapp) -> None:
        p = Panel("Title", meta="10 rows")
        lbl = p.findChild(QLabel, "panel_meta")
        assert lbl is not None
        assert lbl.text() == "10 rows"

    def test_meta_hidden_when_none(self, qapp) -> None:
        p = Panel("Title")
        lbl = p.findChild(QLabel, "panel_meta")
        assert lbl is not None
        assert lbl.isHidden()

    def test_meta_visible_when_set(self, qapp) -> None:
        p = Panel("Title", meta="5 vertices")
        lbl = p.findChild(QLabel, "panel_meta")
        assert not lbl.isHidden()

    def test_content_property_returns_widget(self, qapp) -> None:
        content = QWidget()
        p = Panel("Title", content)
        assert p.content is content

    def test_content_none_by_default(self, qapp) -> None:
        p = Panel("Title")
        assert p.content is None

    def test_set_title(self, qapp) -> None:
        p = Panel("Old")
        p.set_title("New")
        lbl = p.findChild(QLabel, "panel_title")
        assert lbl.text() == "New"

    def test_set_meta_shows_text(self, qapp) -> None:
        p = Panel("Title")
        p.set_meta("7 vertices")
        lbl = p.findChild(QLabel, "panel_meta")
        assert lbl.text() == "7 vertices"
        assert not lbl.isHidden()

    def test_set_meta_none_hides(self, qapp) -> None:
        p = Panel("Title", meta="some")
        p.set_meta(None)
        lbl = p.findChild(QLabel, "panel_meta")
        assert lbl.isHidden()

    def test_set_content_replaces(self, qapp) -> None:
        old = QWidget()
        new = QWidget()
        p = Panel("Title", old)
        p.set_content(new)
        assert p.content is new
