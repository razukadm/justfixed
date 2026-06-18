"""User-facing pt-BR strings for the JustFixed UI chrome (B37).

Single home for translatable UI chrome text. Single locale (pt-BR), no runtime
switching. Domain display values (money, rates, dates, product names) are pt-BR
at the domain layer and are NOT duplicated here. Computed-display mappings
(IssuerKind, FGC badges, broker names) join this module in their own slices.
Grows per B37 slice; this file currently holds the menu/tab/About surface.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Strings:
    # ── Menus ──────────────────────────────────────────────────────────────────
    MENU_FILE: str = "Arquivo"
    MENU_VIEW: str = "Exibir"
    MENU_HELP: str = "Ajuda"

    # ── Menu actions ───────────────────────────────────────────────────────────
    ACT_EXPORT_INVESTMENTS: str = "Exportar investimentos para Excel…"
    ACT_EXPORT_CONGLOMERATES: str = "Exportar conglomerados para Excel…"
    ACT_CLEAR_DB: str = "Limpar banco de dados…"
    ACT_HIDE_MATURED: str = "Ocultar investimentos vencidos"
    ACT_CURVE_CDI: str = "Curva CDI"
    ACT_CURVE_IPCA: str = "Curva IPCA-real"
    ACT_CURVE_PRE: str = "Curva Prefixado"
    ACT_MANAGE_REF_DATA: str = "Gerenciar dados de referência…"
    ACT_ABOUT: str = "Sobre o JustFixed"

    # ── Tabs ───────────────────────────────────────────────────────────────────
    TAB_INVESTMENTS: str = "Investimentos"
    TAB_CONGLOMERATES: str = "Conglomerados"
    TAB_CALCULATOR: str = "Calculadora"
    TAB_DEV: str = "Dev"

    # ── About dialog ───────────────────────────────────────────────────────────
    ABOUT_TITLE: str = "Sobre o JustFixed"
    ABOUT_VERSION: str = "Versão:"
    ABOUT_BUILD_DATE: str = "Data da build:"
    ABOUT_EXPIRES: str = "Expira em:"


STR = Strings()
