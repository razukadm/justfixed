"""Tests for design tokens (theme.py) and global stylesheet (qss.py)."""

from __future__ import annotations

import pytest

from justfixed.ui.theme import COLORS, FONTS, Colors, Fonts


class TestColors:
    def test_singleton_is_frozen(self) -> None:
        with pytest.raises(AttributeError):
            COLORS.INK = "#000000"  # type: ignore[misc]

    def test_ink_primary_text(self) -> None:
        assert COLORS.INK == "#1a1a1a"

    def test_ink_matches_curve_inspector(self) -> None:
        # curve_inspector._INK and main.py toolbar button text both use this value.
        assert COLORS.INK == "#1a1a1a"

    def test_warn_matches_curve_inspector(self) -> None:
        # curve_inspector._WARN and the "approaching" FGC badge both use #e67e22.
        assert COLORS.WARN == "#e67e22"

    def test_fgc_na_matches_treasury_badge(self) -> None:
        assert COLORS.FGC_NA == "#aaaaaa"

    def test_danger_red(self) -> None:
        assert COLORS.DANGER == "#e74c3c"

    def test_panel_white(self) -> None:
        assert COLORS.PANEL == "#ffffff"

    def test_toolbar_btn_pressed_is_also_border_colour(self) -> None:
        # Same #4cae6a value was used as both pressed-state bg and border.
        assert COLORS.TOOLBAR_BTN_PRESSED == "#4cae6a"

    def test_detail_row_odd_matches_detail_header_bg(self) -> None:
        # #f0f0f0 is shared between the detail header and odd detail rows.
        assert COLORS.DETAIL_ROW_ODD == COLORS.DETAIL_HEADER_BG

    def test_highlight_row(self) -> None:
        assert COLORS.HIGHLIGHT_ROW == "#FFF8DC"

    def test_fgc_over_is_red(self) -> None:
        assert COLORS.FGC_OVER == "#e74c3c"

    def test_fgc_over_equals_danger_today(self) -> None:
        # Intentional split: same value, separate tokens for divergence-safety.
        assert COLORS.FGC_OVER == COLORS.DANGER

    def test_error_text_is_dark_red(self) -> None:
        assert COLORS.ERROR_TEXT == "#c0392b"

    def test_error_text_equals_danger_hover_today(self) -> None:
        # Intentional split: same value, separate tokens for divergence-safety.
        assert COLORS.ERROR_TEXT == COLORS.DANGER_HOVER

    def test_secondary_hover(self) -> None:
        assert COLORS.SECONDARY_HOVER == "#eefbf3"

    def test_secondary_border_uses_rule(self) -> None:
        # The secondary button border reuses RULE (#d9d6cf) — no duplicate token.
        assert COLORS.RULE == "#d9d6cf"


class TestFonts:
    def test_singleton_is_frozen(self) -> None:
        with pytest.raises(AttributeError):
            FONTS.UI_FAMILY = "Arial"  # type: ignore[misc]

    def test_ui_family(self) -> None:
        assert FONTS.UI_FAMILY == "Segoe UI"

    def test_mono_family(self) -> None:
        assert FONTS.MONO_FAMILY == "Consolas"

    def test_sizes(self) -> None:
        assert FONTS.UI_SIZE_SM == 8
        assert FONTS.UI_SIZE_MD == 9
        assert FONTS.MONO_SIZE == 10


class TestMakeStylesheet:
    def test_returns_non_empty_string(self) -> None:
        from justfixed.ui.qss import make_stylesheet
        sheet = make_stylesheet()
        assert isinstance(sheet, str)
        assert len(sheet) > 200

    def test_contains_toolbar_role(self) -> None:
        from justfixed.ui.qss import make_stylesheet
        assert 'role="toolbar"' in make_stylesheet()

    def test_contains_danger_role(self) -> None:
        from justfixed.ui.qss import make_stylesheet
        assert 'role="danger"' in make_stylesheet()

    def test_contains_fgc_status_selectors(self) -> None:
        from justfixed.ui.qss import make_stylesheet
        sheet = make_stylesheet()
        assert 'fgcStatus="under"' in sheet
        assert 'fgcStatus="over"' in sheet

    def test_token_values_embedded(self) -> None:
        from justfixed.ui.qss import make_stylesheet
        sheet = make_stylesheet()
        assert COLORS.TOOLBAR_BTN in sheet
        assert COLORS.DANGER in sheet
        assert COLORS.FIELD_LABEL_FG in sheet

    def test_contains_secondary_role(self) -> None:
        from justfixed.ui.qss import make_stylesheet
        assert 'role="secondary"' in make_stylesheet()

    def test_secondary_hover_in_stylesheet(self) -> None:
        from justfixed.ui.qss import make_stylesheet
        assert COLORS.SECONDARY_HOVER in make_stylesheet()

    def test_contains_status_bar(self) -> None:
        from justfixed.ui.qss import make_stylesheet
        assert "QStatusBar" in make_stylesheet()

    def test_status_bar_uses_font_tokens(self) -> None:
        from justfixed.ui.qss import make_stylesheet
        from justfixed.ui.theme import FONTS
        sheet = make_stylesheet()
        assert FONTS.UI_FAMILY in sheet
        assert str(FONTS.UI_SIZE_MD) in sheet

    # ── Base surface + typography (commit 1 of global styling) ───────────────

    def test_paper_background_in_qmainwindow_rule(self) -> None:
        from justfixed.ui.qss import make_stylesheet
        sheet = make_stylesheet()
        assert COLORS.PAPER in sheet
        assert "QMainWindow" in sheet

    def test_qdialog_gets_paper_background(self) -> None:
        from justfixed.ui.qss import make_stylesheet
        sheet = make_stylesheet()
        assert "QDialog" in sheet

    def test_base_font_family_on_qwidget(self) -> None:
        from justfixed.ui.qss import make_stylesheet
        sheet = make_stylesheet()
        # QWidget rule carries the font-family token
        assert "QWidget" in sheet
        assert FONTS.UI_FAMILY in sheet

    def test_base_font_size_uses_ui_size_md(self) -> None:
        from justfixed.ui.qss import make_stylesheet
        sheet = make_stylesheet()
        # font-size token value appears in the sheet (already true for status bar;
        # this guards the base QWidget rule carries it too)
        assert f"{FONTS.UI_SIZE_MD}pt" in sheet

    def test_h1_role_selector_present(self) -> None:
        from justfixed.ui.qss import make_stylesheet
        assert 'role="h1"' in make_stylesheet()

    def test_h2_role_selector_present(self) -> None:
        from justfixed.ui.qss import make_stylesheet
        assert 'role="h2"' in make_stylesheet()

    # ── Regression: existing rules not removed ───────────────────────────────

    def test_toolbar_role_still_present(self) -> None:
        from justfixed.ui.qss import make_stylesheet
        assert 'role="toolbar"' in make_stylesheet()

    def test_danger_role_still_present(self) -> None:
        from justfixed.ui.qss import make_stylesheet
        assert 'role="danger"' in make_stylesheet()

    def test_secondary_role_still_present(self) -> None:
        from justfixed.ui.qss import make_stylesheet
        assert 'role="secondary"' in make_stylesheet()

    def test_mock_row_rule_still_present(self) -> None:
        from justfixed.ui.qss import make_stylesheet
        assert 'rowKind="mock"' in make_stylesheet()

    def test_peak_row_rule_still_present(self) -> None:
        from justfixed.ui.qss import make_stylesheet
        assert 'rowKind="peak"' in make_stylesheet()

    def test_cong_parity_rows_still_present(self) -> None:
        from justfixed.ui.qss import make_stylesheet
        sheet = make_stylesheet()
        assert 'congRowParity="even"' in sheet
        assert 'congRowParity="odd"' in sheet

    def test_panel_title_role_still_present(self) -> None:
        from justfixed.ui.qss import make_stylesheet
        assert 'role="panelTitle"' in make_stylesheet()

    def test_qwidget_base_rule_has_no_background_property(self) -> None:
        # The QWidget base rule must carry only font/color, NOT background-color,
        # to avoid clobbering CODE_BLOCK_BG command displays and accordion rows.
        from justfixed.ui.qss import make_stylesheet
        sheet = make_stylesheet()
        # Find the QWidget block and confirm it does not set background-color.
        # Strategy: locate "QWidget {" and extract until the closing "}"
        idx = sheet.find("QWidget {")
        assert idx != -1, "QWidget base rule missing"
        end = sheet.index("}", idx)
        qwidget_block = sheet[idx:end + 1]
        assert "background" not in qwidget_block

    # ── Investments table visual pass (commit 2 of global styling) ──────────

    def test_investments_table_alternate_background_color(self) -> None:
        from justfixed.ui.qss import make_stylesheet
        sheet = make_stylesheet()
        assert "alternate-background-color" in sheet
        assert COLORS.PANEL_2 in sheet

    def test_investments_table_header_section_rule(self) -> None:
        from justfixed.ui.qss import make_stylesheet
        assert "QHeaderView::section" in make_stylesheet()

    def test_investments_table_scoped_to_objectname(self) -> None:
        from justfixed.ui.qss import make_stylesheet
        sheet = make_stylesheet()
        assert "investmentsTable" in sheet
        assert "QTableWidget#investmentsTable" in sheet

    # ── Form and control chrome (global styling commit 3) ───────────────────

    def test_form_controls_qlineedit_rule_present(self) -> None:
        from justfixed.ui.qss import make_stylesheet
        sheet = make_stylesheet()
        assert "QLineEdit {" in sheet

    def test_form_controls_qcombobox_rule_present(self) -> None:
        from justfixed.ui.qss import make_stylesheet
        assert "QComboBox {" in make_stylesheet()

    def test_form_controls_qdateedit_rule_present(self) -> None:
        from justfixed.ui.qss import make_stylesheet
        assert "QDateEdit {" in make_stylesheet()

    def test_qlineedit_error_border_regression(self) -> None:
        from justfixed.ui.qss import make_stylesheet
        assert 'QLineEdit[hasError="true"]' in make_stylesheet()

    def test_error_border_rule_after_base_qlineedit_for_cascade(self) -> None:
        # QLineEdit[hasError] and QLineEdit:focus have equal specificity;
        # the later one wins. Match the CSS rules themselves (include the
        # opening brace) to avoid matching the comment that also references
        # the selector string.
        from justfixed.ui.qss import make_stylesheet
        sheet = make_stylesheet()
        focus_idx = sheet.index("QLineEdit:focus {")
        error_idx = sheet.index('QLineEdit[hasError="true"] {')
        assert error_idx > focus_idx

    def test_form_controls_use_rule_token_for_border(self) -> None:
        from justfixed.ui.qss import make_stylesheet
        sheet = make_stylesheet()
        assert COLORS.RULE in sheet

    def test_form_controls_use_link_token_for_focus(self) -> None:
        from justfixed.ui.qss import make_stylesheet
        sheet = make_stylesheet()
        assert COLORS.LINK in sheet

    def test_checkbox_rule_present(self) -> None:
        from justfixed.ui.qss import make_stylesheet
        assert "QCheckBox {" in make_stylesheet()

    def test_radiobutton_rule_present(self) -> None:
        from justfixed.ui.qss import make_stylesheet
        assert "QRadioButton {" in make_stylesheet()

    # ── IN-5: totals strip background band ───────────────────────────────────

    def test_totals_strip_rule_present(self) -> None:
        from justfixed.ui.qss import make_stylesheet
        assert "QWidget#totalsStrip" in make_stylesheet()

    def test_totals_strip_uses_panel_2(self) -> None:
        from justfixed.ui.qss import make_stylesheet
        sheet = make_stylesheet()
        idx = sheet.index("QWidget#totalsStrip")
        block_end = sheet.index("}", idx)
        block = sheet[idx:block_end + 1]
        assert COLORS.PANEL_2 in block

    # ── CH-1: tab styling ────────────────────────────────────────────────────

    def test_tab_bar_tab_rule_present(self) -> None:
        from justfixed.ui.qss import make_stylesheet
        assert "QTabBar::tab {" in make_stylesheet()

    def test_tab_bar_tab_selected_rule_present(self) -> None:
        from justfixed.ui.qss import make_stylesheet
        assert "QTabBar::tab:selected {" in make_stylesheet()

    def test_tab_widget_pane_rule_present(self) -> None:
        from justfixed.ui.qss import make_stylesheet
        assert "QTabWidget::pane {" in make_stylesheet()

    def test_tab_bar_uses_panel_2_for_inactive(self) -> None:
        from justfixed.ui.qss import make_stylesheet
        sheet = make_stylesheet()
        idx = sheet.index("QTabBar::tab {")
        block_end = sheet.index("}", idx)
        block = sheet[idx:block_end + 1]
        assert COLORS.PANEL_2 in block

    def test_tab_bar_selected_uses_panel(self) -> None:
        from justfixed.ui.qss import make_stylesheet
        sheet = make_stylesheet()
        idx = sheet.index("QTabBar::tab:selected {")
        block_end = sheet.index("}", idx)
        block = sheet[idx:block_end + 1]
        assert COLORS.PANEL in block
