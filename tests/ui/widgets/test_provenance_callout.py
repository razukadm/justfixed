"""Tests for the ProvenanceCallout widget."""

from __future__ import annotations

import sys
from datetime import date

import pytest
from PySide6.QtWidgets import QApplication, QFrame, QLabel

from justfixed.ui.widgets.provenance_callout import ProvenanceCallout
from justfixed.ui.strings import STR


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


class TestProvenanceCallout:
    def test_is_qframe(self, qapp) -> None:
        pc = ProvenanceCallout("series label", date(2025, 1, 15))
        assert isinstance(pc, QFrame)

    def test_object_name(self, qapp) -> None:
        pc = ProvenanceCallout("series label", date(2025, 1, 15))
        assert pc.objectName() == "provenance"

    def test_asof_formatted_date(self, qapp) -> None:
        pc = ProvenanceCallout("series label", date(2025, 3, 20))
        labels = [lbl.text() for lbl in pc.findChildren(QLabel)]
        assert "2025-03-20" in labels

    def test_asof_none_shows_dash(self, qapp) -> None:
        pc = ProvenanceCallout("series label", None)
        labels = [lbl.text() for lbl in pc.findChildren(QLabel)]
        assert "—" in labels

    def test_curve_asof_label_present(self, qapp) -> None:
        pc = ProvenanceCallout("series label", date(2025, 1, 15))
        labels = [lbl.text() for lbl in pc.findChildren(QLabel)]
        assert STR.CALLOUT_ASOF in labels

    def test_set_as_of(self, qapp) -> None:
        pc = ProvenanceCallout("series label", date(2025, 1, 1))
        pc.set_as_of(date(2025, 6, 15))
        assert pc._val_asof.text() == "2025-06-15"

    def test_set_unavailable(self, qapp) -> None:
        pc = ProvenanceCallout("series label", date(2025, 1, 1))
        pc.set_unavailable()
        assert pc._val_asof.text() == "—"

    def test_set_unavailable_with_reason(self, qapp) -> None:
        pc = ProvenanceCallout("series label", date(2025, 1, 1))
        pc.set_unavailable("network error")
        assert pc._val_asof.text() == "—"

    def test_series_name_in_label(self, qapp) -> None:
        pc = ProvenanceCallout("CDI curve text", date(2025, 1, 1))
        labels = [lbl.text() for lbl in pc.findChildren(QLabel)]
        assert "CDI curve text" in labels

    def test_extra_params_accepted(self, qapp) -> None:
        from datetime import datetime
        pc = ProvenanceCallout(
            "label",
            date(2025, 1, 1),
            fetched_at=datetime(2025, 1, 1, 12, 0),
            fetch_status="fresh",
            source="justfixed-data",
        )
        assert pc.objectName() == "provenance"
