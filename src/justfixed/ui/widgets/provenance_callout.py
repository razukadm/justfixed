"""ProvenanceCallout — callout frame showing series identity and curve anchor date."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from justfixed.ui.theme import COLORS


class ProvenanceCallout(QFrame):
    """Callout frame with a series label (RichText) and a CURVE AS-OF date row.

    The `fetched_at`, `fetch_status`, and `source` parameters are accepted for
    forward-compatibility but are not rendered — zero visual diff with the
    original _build_provenance output.
    """

    def __init__(
        self,
        series_name: str,
        as_of: date | None = None,
        *,
        clarifier: str | None = None,
        fetched_at: datetime | None = None,
        fetch_status: Literal["fresh", "cache hit", "stale"] | None = None,
        source: str = "justfixed-data",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("provenance")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        # Row 1: series label (rich text)
        series_lbl = QLabel()
        series_lbl.setTextFormat(Qt.TextFormat.RichText)
        series_lbl.setText(series_name)
        series_lbl.setStyleSheet(f"color: {COLORS.INK}; font-size: 13px; border: none;")
        series_lbl.setWordWrap(True)
        layout.addWidget(series_lbl)

        # Row 2: 1px divider
        divider = QWidget()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background: {COLORS.CALLOUT_EDGE};")
        layout.addWidget(divider)

        # Row 3: as-of row — uppercase label + mono date value
        asof_row = QWidget()
        asof_row.setStyleSheet("background: transparent;")
        asof_layout = QHBoxLayout(asof_row)
        asof_layout.setContentsMargins(0, 0, 0, 0)
        asof_layout.setSpacing(6)

        lbl_asof = QLabel("CURVE AS-OF")
        lbl_asof.setStyleSheet(
            f"color: {COLORS.INK_3}; font-size: 9px; letter-spacing: 0.06em; border: none;"
        )

        self._val_asof = QLabel(self._format_date(as_of))
        self._val_asof.setStyleSheet(
            f"font-family: Consolas, 'Courier New', monospace; "
            f"font-size: 9px; font-weight: 500; color: {COLORS.INK}; border: none;"
        )

        asof_layout.addWidget(lbl_asof)
        asof_layout.addWidget(self._val_asof)
        asof_layout.addStretch()
        layout.addWidget(asof_row)

    @staticmethod
    def _format_date(d: date | None) -> str:
        if d is None:
            return "—"
        return d.strftime("%Y-%m-%d")

    def set_as_of(self, d: date) -> None:
        self._val_asof.setText(d.strftime("%Y-%m-%d"))

    def set_unavailable(self, reason: str | None = None) -> None:
        self._val_asof.setText("—")
