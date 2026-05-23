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
        assert FONTS.MONO_SIZE == 8


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
