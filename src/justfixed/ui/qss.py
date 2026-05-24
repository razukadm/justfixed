"""Global Qt stylesheet for the JustFixed UI.

Applied once to QApplication in main(). Individual widgets opt-in via
setProperty("role", ...) or setObjectName() selectors — no inline
setStyleSheet calls in main.py.
"""

from __future__ import annotations

from justfixed.ui.theme import COLORS


def make_stylesheet() -> str:
    c = COLORS
    return f"""
/* ── Toolbar action buttons ─────────────────────────────────────── */
QPushButton[role="toolbar"] {{
    background-color: {c.TOOLBAR_BTN};
    border: 1px solid {c.TOOLBAR_BTN_PRESSED};
    border-radius: 4px;
    padding: 6px 12px;
    color: {c.INK};
}}
QPushButton[role="toolbar"]:hover {{
    background-color: {c.TOOLBAR_BTN_HOVER};
}}
QPushButton[role="toolbar"]:pressed {{
    background-color: {c.TOOLBAR_BTN_PRESSED};
}}
QPushButton[role="toolbar"]:disabled {{
    background-color: {c.TOOLBAR_BTN_DISABLED_BG};
    color: {c.INK_3};
}}

/* ── Danger (delete) button ─────────────────────────────────────── */
QPushButton[role="danger"] {{
    background-color: {c.DANGER};
    color: white;
    border: none;
    border-radius: 4px;
    padding: 6px 12px;
}}
QPushButton[role="danger"]:hover {{
    background-color: {c.DANGER_HOVER};
}}
QPushButton[role="danger"]:pressed {{
    background-color: {c.DANGER_PRESSED};
}}
QPushButton[role="danger"]:disabled {{
    background-color: {c.DANGER_DISABLED_BG};
    color: {c.INK_3};
}}

/* ── Panel title labels ─────────────────────────────────────────── */
QLabel[role="panelTitle"] {{
    font-weight: bold;
}}

/* ── Info / source banner ───────────────────────────────────────── */
QLabel[role="infoBanner"] {{
    background: {c.SOURCE_BANNER_BG};
    color: {c.SOURCE_BANNER_FG};
    padding: 4px 8px;
    border-radius: 4px;
}}

/* ── Error label ────────────────────────────────────────────────── */
QLabel[role="error"] {{
    background: {c.ERROR_BG};
    color: {c.ERROR_TEXT};
    padding: 4px 8px;
    border-radius: 4px;
}}

/* ── Field labels (left-column form labels) ─────────────────────── */
QLabel[role="fieldLabel"] {{
    color: {c.FIELD_LABEL_FG};
}}

/* ── Sub-labels (new-issuer inline fields) ──────────────────────── */
QLabel[role="subLabel"] {{
    color: {c.INK_3};
}}

/* ── FGC badge colours ──────────────────────────────────────────── */
QLabel[fgcStatus="under"]       {{ color: {c.FGC_UNDER}; }}
QLabel[fgcStatus="approaching"] {{ color: {c.WARN}; }}
QLabel[fgcStatus="over"]        {{ color: {c.FGC_OVER}; }}
QLabel[fgcStatus="not_fgc"]     {{ color: {c.FGC_NA}; }}

/* ── Conglomerate accordion: summary header ─────────────────────── */
QWidget#congHeader {{
    background-color: {c.CONG_HEADER_BG};
    border-bottom: 1px solid {c.CONG_ROW_BORDER};
}}
QWidget#congHeader QLabel {{
    font-weight: bold;
}}

/* ── Conglomerate accordion: summary data rows ──────────────────── */
QWidget[congRowParity="even"] {{
    background-color: {c.PANEL};
    border-bottom: 1px solid {c.CONG_ROW_BORDER};
}}
QWidget[congRowParity="odd"] {{
    background-color: {c.CONG_ROW_ODD};
    border-bottom: 1px solid {c.CONG_ROW_BORDER};
}}

/* ── Conglomerate accordion: detail header ──────────────────────── */
QWidget#detailHeader {{
    background-color: {c.DETAIL_HEADER_BG};
    border-bottom: 1px solid {c.CONG_ROW_BORDER};
}}
QWidget#detailHeader QLabel {{
    font-weight: bold;
}}

/* ── Conglomerate accordion: detail data rows ───────────────────── */
QWidget[detailRowParity="even"] {{
    background-color: {c.DETAIL_ROW_EVEN};
    border-bottom: 1px solid {c.DETAIL_ROW_BORDER};
}}
QWidget[detailRowParity="odd"] {{
    background-color: {c.DETAIL_ROW_ODD};
    border-bottom: 1px solid {c.DETAIL_ROW_BORDER};
}}

/* ── Secondary (outlined) button ────────────────────────────────── */
QPushButton[role="secondary"] {{
    background-color: {c.PANEL};
    border: 1px solid {c.RULE};
    border-radius: 4px;
    padding: 6px 12px;
    color: {c.INK};
}}
QPushButton[role="secondary"]:hover {{
    background-color: {c.SECONDARY_HOVER};
}}
QPushButton[role="secondary"]:pressed {{
    background-color: {c.PANEL_2};
}}
QPushButton[role="secondary"]:disabled {{
    color: {c.INK_3};
}}
"""
