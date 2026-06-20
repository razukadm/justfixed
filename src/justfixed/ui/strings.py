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
    FGC_AT_CAP: str = "NO LIMITE"

    # ── Mock marker ─────────────────────────────────────────────────────────────
    MOCK_BADGE: str = "SIMULADO"

    # ── Conglomerate edit-delegate validation ───────────────────────────────────
    DLG_INVALID_CONG_TITLE: str = "Conglomerado inválido"
    DLG_CONG_EMPTY: str = "O conglomerado não pode ficar vazio. Insira um valor."
    DLG_CONG_TOO_LONG: str = "Conglomerado muito longo. Insira no máximo 100 caracteres."
    DLG_CONG_RESERVED: str = "O prefixo de não verificado é reservado para uso do sistema. Insira o nome do conglomerado sem ele."

    # ── Calculator inputs ───────────────────────────────────────────────────────
    CALC_VALUE: str = "Valor"
    CALC_MODE_ENTER: str = "Inserir valor"
    CALC_MODE_SOLVE: str = "Calcular máximo sob o FGC"
    CALC_RESET: str = "Limpar"
    CALC_CALCULATE: str = "Calcular"
    CALC_PLACEHOLDER: str = "Execute um cálculo para ver os resultados."
    CALC_ERR_ISSUER: str = "Selecione um emissor."
    CALC_ERR_DATES: str = "A data de vencimento deve ser posterior à data de compra."
    CALC_ERR_AMOUNT: str = "Insira um valor positivo (ex. 50.000,00)."

    # ── Calculator result card ────────────────────────────────────────────────────
    CALC_RESULT_TITLE: str = "Resultado do cálculo"
    CALC_SOLVE_TITLE: str = "Resultado do cálculo reverso"
    CALC_MAX_PRINCIPAL: str = "Principal máximo"
    CALC_MAX_PRINCIPAL_CAPPED: str = "Principal máximo (limitado pelo FGC)"
    CALC_PROJ_AT: str = "Projetado no vencimento ({date})"
    CALC_FGC_PEAK_UTIL: str = "Pico de uso do FGC"
    CALC_STATUS_ROW: str = "Situação"
    CALC_EFF_RATE_GROSS: str = "Taxa efetiva (a.a., bruta)"
    CALC_EFF_RATE_NET: str = "Taxa efetiva (a.a.)"
    CALC_TENOR: str = "Prazo"
    CALC_TENOR_DAYS: str = "{n} dias"
    CALC_HINT_MAX_PRINCIPAL: str = "Conforme inserido. Mude para o modo Calcular para achar o máximo."
    CALC_HINT_CAPPED: str = "Posições existentes já no limite do FGC ou acima. Sem espaço para nova posição."
    CALC_HINT_GROSS: str = "Bruto, antes do IR."
    CALC_HINT_NET: str = "Líquido de IR."
    CALC_HINT_UTIL: str = "No vencimento. A verificação de saldo corrente aparece no modo Calcular."
    CALC_HINT_TESOURO: str = "Investimentos do Tesouro não são cobertos pelo FGC."
    CALC_HINT_OVER_ENTER: str = "Reduza o principal ou escolha outro emissor para ficar abaixo de R$ 250 mil."
    CALC_HINT_OVER_SOLVE: str = "Limite do FGC excedido no pico — reduza o prazo ou troque o emissor."
    CALC_HINT_APPROACHING: str = "Próximo do limite de R$ 250 mil do FGC."
    CALC_MSG_ENTER_TESOURO: str = "Projetado em {date} · {name} · Tesouro (sem FGC)"
    CALC_MSG_ENTER_FGC: str = "Projetado em {date} · {name} · FGC {status}"
    CALC_MSG_SOLVED_AT_CAP: str = "Posições de {conglomerate} já no limite do FGC."
    CALC_MSG_SOLVED: str = "Principal máximo calculado sob o FGC · limite atingido em {date}"

    # ── Calculator drawdown preview ─────────────────────────────────────────────
    CALC_DRAWDOWN_TITLE: str = "Prévia do resgate sequencial — {issuer}"
    CALC_PEAK_AT: str = "em {date}"

    # ── Manage Reference Data (chrome) ──────────────────────────────────────────
    MRD_TITLE: str = "Gerenciar dados de referência"
    MRD_TAB_ISSUERS: str = "Emissores"
    MRD_TAB_CONGLOMERATES: str = "Conglomerados"
    MRD_TAB_CUSTODIANS: str = "Custodiantes"
    MRD_COL_NAME: str = "Nome"
    MRD_COL_KIND: str = "Tipo"
    MRD_COL_NUM_INVESTMENTS: str = "Nº de investimentos"
    MRD_COL_NUM_ISSUERS: str = "Nº de emissores"
    MRD_RENAME: str = "Renomear"
    MRD_DISSOLVE: str = "Dissolver"
    MRD_CLEAR: str = "Limpar"
    MRD_DELETE: str = "Excluir"
    MRD_TIP_CANT_DELETE: str = "Não é possível excluir: {count} investimento(s) ainda usam este emissor."
    MRD_TIP_NO_CUSTODIAN: str = "Nenhum custodiante para renomear."
    MRD_TIP_ALREADY_UNSET: str = "Já está vazio."

    # ── Manage Reference Data (dialogs) ─────────────────────────────────────────
    MRD_DLG_DELETE_TITLE: str = "Excluir emissor"
    MRD_DLG_DELETE_BODY: str = "Excluir o emissor '{name}'? Esta ação não pode ser desfeita."
    MRD_DLG_RENAME_CONG_TITLE: str = "Renomear conglomerado"
    MRD_DLG_RENAME_CUST_TITLE: str = "Renomear custodiante"
    MRD_DLG_NEW_NAME: str = "Novo nome para '{old}':"
    MRD_DLG_NAME_BLANK: str = "O nome não pode ficar vazio."
    MRD_DLG_MERGE_CONG_TITLE: str = "Mesclar conglomerados"
    MRD_DLG_MERGE_CONG_BODY: str = "'{text}' já existe. Mesclar os {count} emissor(es) de '{old}' em '{text}'?"
    MRD_DLG_MERGE_CUST_TITLE: str = "Mesclar custodiantes"
    MRD_DLG_MERGE_CUST_BODY: str = "'{text}' já existe. Mesclar os {count} investimento(s) de '{old}' em '{text}'?"
    MRD_DLG_DISSOLVE_TITLE: str = "Dissolver conglomerado"
    MRD_DLG_DISSOLVE_BODY: str = "Dissolver '{name}'? Seus {count} emissor(es) deixam de ser curados e o agrupamento é removido. Esta ação não pode ser desfeita."
    MRD_DLG_CLEAR_TITLE: str = "Limpar custodiante"
    MRD_DLG_CLEAR_BODY: str = "Limpar o custodiante '{name}' de seus {count} investimento(s)? Eles ficarão sem custodiante."

    # ── Curve Inspector ─────────────────────────────────────────────────────────
    CURVE_TITLE_CDI: str = "JustFixed — Curva CDI"
    CURVE_TITLE_IPCA: str = "JustFixed — Curva IPCA-real"
    CURVE_TITLE_PRE: str = "JustFixed — Curva Prefixado"
    CURVE_PANEL_SHAPE: str = "Formato da curva"
    CURVE_PANEL_VERTICES: str = "Vértices"
    CURVE_META_VERTICES: str = "{n} vértices"
    CURVE_META_ROWS: str = "{n} linhas"
    CURVE_AXIS_DATE: str = "Data de liquidação"
    CURVE_AXIS_RATE: str = "Taxa (% a.a.)"
    CURVE_COL_SETTLES: str = "Liquida em"
    CURVE_COL_RATE: str = "Taxa a.a."
    CURVE_STATUS_UNAVAIL: str = "Curva: indisponível"
    CURVE_STATUS: str = "Curva: justfixed-data ({anchor})  ·  {n} vértices"
    CURVE_QUAL_SOURCE: str = "fonte oficial"
    CURVE_QUAL_VISUAL: str = "verificação visual rápida"
    CURVE_SOURCE_NOTE: str = "Fonte: <b>justfixed-data</b>, compilado a partir das curvas publicadas pela ANBIMA / B3."
    CURVE_VERIFY: str = "Verifique estes dados na fonte:"
    CURVE_UNAVAIL_HEADING: str = "Dados da curva indisponíveis"
    CURVE_UNAVAIL_BODY: str = "Não foi possível buscar ou carregar uma curva em cache para esta série.\nA janela não pode mostrar vértices até que os dados estejam disponíveis."

    # ── Dialogs & status messages ───────────────────────────────────────────────
    DLG_DELETE_INV_TITLE: str = "Excluir investimento"
    DLG_DELETE_INV_BODY: str = "Excluir permanentemente este investimento?\n\n{issuer}  ·  {product}\nPrincipal: {principal}  ·  Vencimento: {maturity}\n\nEsta ação não pode ser desfeita."
    DLG_IMPORT_OK_TITLE: str = "Importação concluída"
    DLG_IMPORT_OK_BODY: str = "Extrato {broker} importado — {new} novos, {unchanged} inalterados."
    DLG_IMPORT_FAIL_TITLE: str = "Falha na importação"
    DLG_PROJECTION_FAIL_TITLE: str = "Falha na projeção"
    MSG_CALENDAR_EXPORTED: str = "Calendário exportado para {path}."
    MSG_INVESTMENTS_EXPORTED: str = "Investimentos exportados para {path}."
    MSG_CONGLOMERATES_EXPORTED: str = "Conglomerados exportados para {path}."
    MSG_CURVE_EXPORTED: str = "Dados da curva exportados para {path}."
    DLG_CALENDAR_FAIL_TITLE: str = "Falha ao exportar calendário"
    DLG_EXCEL_FAIL_TITLE: str = "Falha ao exportar Excel"
    DLG_DB_ERROR_TITLE: str = "Erro de banco de dados"
    DLG_DB_ERROR_BODY: str = "O JustFixed não pôde abrir seu banco de dados e será encerrado.\n\n{exc}"

    # ── Status indicators & misc ────────────────────────────────────────────────
    STATUS_CURVE: str = "Curva: {source} ({date})"
    STATUS_CURVE_UNAVAIL: str = "Curva: indisponível"
    STATUS_CURVE_NO_DATA: str = "Curva: {source} (sem dados)"
    CURVE_SOURCE_LIVE: str = "ativa"
    CURVE_SOURCE_MANUAL: str = "manual"
    STATUS_PROJECTED_TS: str = "Projetado: {ts}"
    ERR_ISSUER_NAME_EMPTY: str = "O nome do emissor não pode ficar vazio."
    CALLOUT_ASOF: str = "DATA-BASE"
    MSG_PROJECTED_COUNT: str = "Projetados {count} investimentos em {date}."


STR = Strings()
