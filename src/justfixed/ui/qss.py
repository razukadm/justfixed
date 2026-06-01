"""Global Qt stylesheet for the JustFixed UI.

Applied once to QApplication in main(). Individual widgets opt-in via
setProperty("role", ...) or setObjectName() selectors — no inline
setStyleSheet calls in main.py.
"""

from __future__ import annotations

from justfixed.ui.theme import COLORS, FONTS


def make_stylesheet() -> str:
    c = COLORS
    f = FONTS
    return f"""
/* ── Base surface and typography ────────────────────────────────────
   Background is scoped to QMainWindow + QDialog only — NOT a blanket
   QWidget — so QPlainTextEdit code blocks (CODE_BLOCK_BG set inline),
   accordion parity rows, and role-styled buttons all keep their own
   backgrounds.  Font properties are set on QWidget with no background
   so they cascade safely to every child widget; widgets that need a
   different color (danger button, status bar, FGC badges) already carry
   more-specific selectors that override this default. */
QMainWindow {{
    background-color: {c.PAPER};
}}
QDialog {{
    background-color: {c.PAPER};
}}
QWidget {{
    font-family: '{f.UI_FAMILY}';
    font-size: {f.UI_SIZE_MD}pt;
    color: {c.INK};
}}

/* ── Type-scale heading labels ──────────────────────────────────────
   Available for use; not yet applied to existing labels (later pass). */
QLabel[role="h1"] {{
    font-size: 22pt;
    font-weight: 600;
    color: {c.INK};
}}
QLabel[role="h2"] {{
    font-size: 16pt;
    font-weight: 600;
    color: {c.INK};
}}

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

/* ── Form and control chrome ─────────────────────────────────────────
   Global rules for QLineEdit, QComboBox, QDateEdit, QCheckBox, and
   QRadioButton.  Applies to the filter row, Calculator form, Add
   Investment form, and inline table editors all at once.
   Cascade note: QLineEdit[hasError="true"] appears AFTER these base
   rules so the danger border wins on same-specificity when a field is
   both focused and in error.
   QComboBox::down-arrow and QDateEdit up/down arrow glyphs left at
   Qt default — no custom image assets available.
   QCheckBox::indicator and QRadioButton::indicator left at Qt default
   (Accept) — reliable cross-state checked rendering requires image
   assets; forcing a border-only style leaves an empty indicator.     */
QLineEdit {{
    background-color: {c.PANEL};
    border: 1px solid {c.RULE};
    border-radius: 3px;
    padding: 4px;
    color: {c.INK};
    selection-background-color: {c.CALLOUT_BG};
}}
QLineEdit:focus {{
    border-color: {c.LINK};
}}
QLineEdit:disabled {{
    background-color: {c.PANEL_2};
    color: {c.INK_3};
}}

QComboBox {{
    background-color: {c.PANEL};
    border: 1px solid {c.RULE};
    border-radius: 3px;
    padding: 4px;
    color: {c.INK};
}}
QComboBox:focus {{
    border-color: {c.LINK};
}}
QComboBox:disabled {{
    background-color: {c.PANEL_2};
    color: {c.INK_3};
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}

QDateEdit {{
    background-color: {c.PANEL};
    border: 1px solid {c.RULE};
    border-radius: 3px;
    padding: 4px;
    color: {c.INK};
}}
QDateEdit:focus {{
    border-color: {c.LINK};
}}
QDateEdit:disabled {{
    background-color: {c.PANEL_2};
    color: {c.INK_3};
}}
QDateEdit::up-button,
QDateEdit::down-button {{
    border: none;
    background-color: transparent;
    width: 16px;
}}

QCheckBox {{
    spacing: 6px;
    color: {c.INK};
}}
QCheckBox:disabled {{
    color: {c.INK_3};
}}

QRadioButton {{
    spacing: 6px;
    color: {c.INK};
}}
QRadioButton:disabled {{
    color: {c.INK_3};
}}

/* ── Calculator: field error border ─────────────────────────────────── */
QLineEdit[hasError="true"] {{
    border: 1px solid {c.DANGER};
}}

/* ── Calculator: big result value (principal line) ───────────────────── */
QLabel[calcResultBig="true"] {{
    font-size: 14pt;
    font-weight: bold;
    color: {c.INK};
}}

/* ── Status bar ─────────────────────────────────────────────────────── */
QStatusBar {{
    background-color: {c.STATUS_BAR_BG};
    font-family: '{f.UI_FAMILY}';
    font-size: {f.UI_SIZE_MD}pt;
    color: {c.INK_3};
    border-top: 1px solid {c.RULE_2};
}}

/* ── Calculator: drawdown preview — mock row (hypothetical investment) ── */
QWidget[rowKind="mock"] {{
    background-color: {c.MOCK_ROW_BG};
    border-left: 3px solid {c.MOCK_ROW_EDGE};
    border-bottom: 1px solid {c.CONG_ROW_BORDER};
}}
QLabel[badge="mock"] {{
    color: {c.MOCK_INK};
    font-weight: bold;
    padding-right: 4px;
}}

/* ── Calculator: drawdown preview — peak (cap-binds) row ────────────── */
QWidget[rowKind="peak"] {{
    background-color: {c.PEAK_ROW_BG};
    border-left: 3px solid {c.PEAK_ROW_EDGE};
    border-bottom: 1px solid {c.CONG_ROW_BORDER};
}}
QLabel[indicator="peak"] {{
    color: {c.PEAK_INDICATOR};
    font-weight: bold;
}}

/* ── Tab widget chrome (CH-1) ────────────────────────────────────────
   90% goal: branded, readable tabs.  The pane-seam between the active
   tab and the content area is accepted as a Qt rendering artefact and
   not fought.  Heavy QTabWidget frame replaced with a single RULE line.
   Hover uses PAPER (lighter than inactive PANEL_2); no extra border so
   the hover doesn't add visual weight.                                */
QTabWidget::pane {{
    border: none;
    border-top: 1px solid {c.RULE};
}}
QTabBar::tab {{
    background-color: {c.PANEL_2};
    color: {c.INK_2};
    padding: 7px 16px;
    margin-right: 2px;
    border: none;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{
    background-color: {c.PANEL};
    color: {c.INK};
    border-bottom: 2px solid {c.INK};
}}
QTabBar::tab:hover:!selected {{
    background-color: {c.PAPER};
    color: {c.INK_2};
}}

/* ── Investments totals strip ────────────────────────────────────── */
QWidget#totalsStrip {{
    background-color: {c.PANEL_2};
    border-top: 1px solid {c.RULE_2};
}}

/* ── Investments table (scoped to objectName — curve inspector untouched) ── */
QTableWidget#investmentsTable {{
    background-color: {c.PANEL};
    alternate-background-color: {c.PANEL_2};
    color: {c.INK};
    border-top: 1px solid {c.RULE};
    border-bottom: 1px solid {c.RULE};
    gridline-color: transparent;
}}
QTableWidget#investmentsTable::item {{
    border-bottom: 1px solid {c.RULE_2};
    padding: 2px 4px;
}}
QTableWidget#investmentsTable::item:selected {{
    background-color: {c.SELECTION_BG};
    color: {c.INK};
}}
QTableWidget#investmentsTable QHeaderView::section {{
    background-color: {c.PANEL_2};
    color: {c.INK_3};
    font-weight: 600;
    font-size: {f.UI_SIZE_MD}pt;
    padding: 4px 6px;
    border: none;
    border-bottom: 1px solid {c.RULE};
}}
"""
