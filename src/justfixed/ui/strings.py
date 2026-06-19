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

    # ── Investments table headers ──────────────────────────────────────────────
    COL_ISSUER: str = "Emissor"
    COL_CONGLOMERATE: str = "Conglomerado"
    COL_PRODUCT: str = "Produto"
    COL_TYPE: str = "Tipo"
    COL_RATE: str = "Taxa"
    COL_PRINCIPAL: str = "Principal"
    COL_MATURITY: str = "Vencimento"
    COL_CURRENT: str = "Atual"
    COL_PROJECTED: str = "Projetado"
    COL_FGC: str = "FGC"

    # ── Toolbar buttons ────────────────────────────────────────────────────────
    BTN_IMPORT: str = "Importar extrato…"
    BTN_ADD: str = "Adicionar investimento…"
    BTN_PROJECT: str = "Projetar para hoje"
    BTN_EXPORT_CAL: str = "Exportar calendário…"

    # ── Status bar ─────────────────────────────────────────────────────────────
    STATUS_READY: str = "Pronto."
    STATUS_LOADING: str = "Carregando {name}…"
    STATUS_LOADED: str = "{total} investimentos carregados ({new} novos, {unchanged} inalterados)."
    STATUS_DELETED: str = "Investimento excluído."

    # ── Footer summary ─────────────────────────────────────────────────────────
    SUMMARY_PRINCIPAL: str = "Principal: {value}"
    SUMMARY_CURRENT: str = "Atual: {value}"
    SUMMARY_PROJECTED: str = "Projetado: {value}"
    ROWS: str = "Linhas: {n}"
    ROWS_FILTERED: str = "Linhas: {n} de {total}"
    ROWS_ACTIVE_MATURED: str = "{active} ativos · {matured} vencidos"

    # ── Empty states ───────────────────────────────────────────────────────────
    EMPTY_INVESTMENTS: str = "Nenhum investimento ainda.\nImporte um extrato, ou adicione um investimento manualmente."
    EMPTY_CONG_DISPLAY: str = "Nenhum investimento para exibir."
    PROJ_EMPTY: str = 'Nenhuma projeção ainda. Clique em "{btn}" para calcular.'

    # ── Field labels (detail panel + add panel; colon added at call site) ───────
    FIELD_ISSUER: str = "Emissor"
    FIELD_CONGLOMERATE: str = "Conglomerado"
    FIELD_CUSTODIAN: str = "Custodiante"
    FIELD_PRODUCT: str = "Produto"
    FIELD_PRINCIPAL: str = "Principal"
    FIELD_RATE: str = "Taxa"
    FIELD_PURCHASE_DATE: str = "Data de compra"
    FIELD_ISSUE_DATE: str = "Data de emissão"
    FIELD_MATURITY_DATE: str = "Data de vencimento"
    FIELD_COUPON: str = "Cupom"
    FIELD_DESCRIPTION: str = "Descrição"
    FIELD_CURRENT_VALUE: str = "Valor atual"

    # ── Add-investment panel ────────────────────────────────────────────────────
    ADD_TITLE: str = "Adicionar investimento"
    ADD_SAVE: str = "Salvar investimento"
    ADD_CANCEL: str = "Cancelar"
    ADD_NAME: str = "Nome:"
    ADD_TYPE: str = "Tipo:"
    PH_ISSUER_NAME: str = "Nome do emissor"
    PH_OPTIONAL: str = "(opcional)"
    PH_PRINCIPAL_EXAMPLE: str = "ex. 10.000,00"
    PH_DESCRIPTION: str = "Nota opcional"
    PH_CONGLOMERATE: str = "Conglomerado (deixe em branco para marcar como não verificado)"

    # ── Detail panel ────────────────────────────────────────────────────────────
    DETAIL_NO_SELECTION: str = "Nenhum investimento selecionado."
    DETAIL_DELETE: str = "Excluir investimento"
    DETAIL_IMPORTED_NOTICE: str = "Importado — apenas descrição e valor atual são editáveis."

    # ── Projection breakdown ─────────────────────────────────────────────────────
    PROJ_TITLE: str = "Projeção"
    PROJ_AS_OF: str = "em {date}"
    PROJ_CURRENT: str = "Valor atual"
    PROJ_GROSS: str = "Bruto no vencimento"
    PROJ_GAIN: str = "Rendimento"
    PROJ_TAX: str = "IR"
    PROJ_NET: str = "Líquido no vencimento"

    # ── Filter row ──────────────────────────────────────────────────────────────
    FILTER_ALL: str = "Todos"
    FILTER_UNSET: str = "(sem custodiante)"
    CB_HIDE_MATURED: str = "Ocultar vencidos"

    # ── Conglomerate accordion columns ──────────────────────────────────────────
    COL_NEXT_MATURITY: str = "Próx. vencimento"
    COL_PROJECTED_BALANCE: str = "Saldo projetado"
    CONG_PROJECT_PROMPT: str = 'Clique em "{btn}" para preencher.'

    # ── FGC status / badges ─────────────────────────────────────────────────────
    FGC_UNDER: str = "ABAIXO"
    FGC_APPROACHING: str = "PRÓXIMO"
    FGC_OVER: str = "ACIMA"
    FGC_NA: str = "N/A"
    FGC_NA_TESOURO: str = "N/A — Tesouro"
    FGC_PAID: str = "PAGO"

    # ── Mock marker ─────────────────────────────────────────────────────────────
    MOCK_BADGE: str = "SIMULADO"

    # ── Conglomerate edit-delegate validation ───────────────────────────────────
    DLG_INVALID_CONG_TITLE: str = "Conglomerado inválido"
    DLG_CONG_EMPTY: str = "O conglomerado não pode ficar vazio. Insira um valor."
    DLG_CONG_TOO_LONG: str = "Conglomerado muito longo. Insira no máximo 100 caracteres."
    DLG_CONG_RESERVED: str = "O prefixo de não verificado é reservado para uso do sistema. Insira o nome do conglomerado sem ele."


STR = Strings()
