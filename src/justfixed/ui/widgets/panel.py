"""Panel — a titled, bordered content frame."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from justfixed.ui.theme import COLORS


class Panel(QFrame):
    """A QFrame with objectName 'panel_frame', a header row (title + meta), and a content area."""

    def __init__(
        self,
        title: str,
        content: QWidget | None = None,
        *,
        meta: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("panel_frame")

        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(0)

        # Header
        header = QWidget()
        header.setStyleSheet(
            f"background: {COLORS.PANEL_2}; border-bottom: 1px solid {COLORS.RULE_2}; border-radius: 0px;"
        )
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 6, 10, 6)
        header_layout.setSpacing(4)

        self._title_lbl = QLabel(title)
        self._title_lbl.setObjectName("panel_title")
        self._title_lbl.setStyleSheet(
            f"font-weight: 600; color: {COLORS.INK}; background: transparent;"
        )

        self._meta_lbl = QLabel(meta or "")
        self._meta_lbl.setObjectName("panel_meta")
        self._meta_lbl.setStyleSheet(
            f"font-family: Consolas, 'Courier New', monospace; "
            f"font-size: 11px; color: {COLORS.INK_3}; background: transparent;"
        )
        if meta is None:
            self._meta_lbl.hide()

        header_layout.addWidget(self._title_lbl)
        header_layout.addStretch()
        header_layout.addWidget(self._meta_lbl)
        self._main_layout.addWidget(header)

        self._content: QWidget | None = None
        if content is not None:
            self.set_content(content)

    @property
    def content(self) -> QWidget | None:
        return self._content

    def set_content(self, widget: QWidget) -> None:
        if self._content is not None:
            self._main_layout.removeWidget(self._content)
            self._content.setParent(None)  # type: ignore[arg-type]
        self._content = widget
        self._main_layout.addWidget(widget, 1)

    def set_meta(self, text: str | None) -> None:
        if text is None:
            self._meta_lbl.setText("")
            self._meta_lbl.hide()
        else:
            self._meta_lbl.setText(text)
            self._meta_lbl.show()

    def set_title(self, text: str) -> None:
        self._title_lbl.setText(text)
