"""Design tokens for the JustFixed UI — palette and typography."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Colors:
    # ── Ink (text) ─────────────────────────────────────────────────────────────
    INK: str = "#1a1a1a"           # primary text; toolbar button text
    INK_2: str = "#4a4a4a"
    INK_3: str = "#888888"         # muted / disabled / sub-labels / unverified cong

    # ── Paper (backgrounds) ────────────────────────────────────────────────────
    PAPER: str = "#fafaf7"
    PANEL: str = "#ffffff"         # panel bg; cong row even
    PANEL_2: str = "#f4f4f1"

    # ── Rules (borders) ────────────────────────────────────────────────────────
    RULE: str = "#d9d6cf"
    RULE_2: str = "#ececea"

    # ── Accent ─────────────────────────────────────────────────────────────────
    LINK: str = "#1f6feb"
    WARN: str = "#e67e22"          # approaching-FGC badge; curve_inspector warning
    CALLOUT_BG: str = "#eef4fb"
    CALLOUT_EDGE: str = "#c5dbf2"
    ACCENT: str = "#d35400"
    ROW_HOVER: str = "#fff7d6"

    # ── Curve inspector extra backgrounds ──────────────────────────────────────
    TABLE_ALT_BG: str = "#fafaf8"
    TABLE_HEADER_BG: str = "#fbfbf9"
    STATUS_BAR_BG: str = "#f7f6f3"
    UNAVAIL_BG: str = "#fdfbf6"

    # ── FGC badge colours ──────────────────────────────────────────────────────
    FGC_UNDER: str = "#2ecc71"
    FGC_NA: str = "#aaaaaa"        # not_fgc badge; treasury badge

    # ── Danger (delete button, error states, FGC-over badge) ───────────────────
    # NOTE: DANGER == FGC "over" (#e74c3c) — same red used in both contexts.
    # NOTE: DANGER_HOVER == error label text (#c0392b) — same darker red.
    DANGER: str = "#e74c3c"
    DANGER_HOVER: str = "#c0392b"
    DANGER_PRESSED: str = "#a93226"
    DANGER_DISABLED_BG: str = "#f5b7b1"

    # ── Toolbar action buttons ─────────────────────────────────────────────────
    # NOTE: TOOLBAR_BTN_PRESSED == TOOLBAR_BTN_BORDER (#4cae6a) — one value, two roles.
    TOOLBAR_BTN: str = "#58d68d"
    TOOLBAR_BTN_HOVER: str = "#6fdc9f"
    TOOLBAR_BTN_PRESSED: str = "#4cae6a"   # also used as border colour
    TOOLBAR_BTN_DISABLED_BG: str = "#c8e6c9"

    # ── Status / info banners ──────────────────────────────────────────────────
    SOURCE_BANNER_BG: str = "#fff3e0"
    SOURCE_BANNER_FG: str = "#e65100"
    ERROR_BG: str = "#fdecea"

    # ── Form chrome ────────────────────────────────────────────────────────────
    FIELD_LABEL_FG: str = "#666666"

    # ── Conglomerate accordion rows ────────────────────────────────────────────
    CONG_ROW_ODD: str = "#f5f5f5"
    CONG_ROW_BORDER: str = "#dddddd"
    CONG_HEADER_BG: str = "#eaeaea"

    # ── Conglomerate detail rows ────────────────────────────────────────────────
    DETAIL_HEADER_BG: str = "#f0f0f0"
    DETAIL_ROW_EVEN: str = "#fafafa"
    # NOTE: DETAIL_ROW_ODD == DETAIL_HEADER_BG (#f0f0f0) — same shade.
    DETAIL_ROW_ODD: str = "#f0f0f0"
    DETAIL_ROW_BORDER: str = "#eeeeee"

    # ── Investments table ──────────────────────────────────────────────────────
    HIGHLIGHT_ROW: str = "#FFF8DC"


@dataclass(frozen=True)
class Fonts:
    UI_FAMILY: str = "Segoe UI"
    UI_SIZE_SM: int = 8
    UI_SIZE_MD: int = 9
    MONO_FAMILY: str = "Consolas"
    MONO_SIZE: int = 8


COLORS = Colors()
FONTS = Fonts()
