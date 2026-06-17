# JustFixed — Project Structure Reference

Generated 2026-05-30 from the actual repo tree and file contents.
Do not trust any earlier snapshot; verify with the files directly if in doubt.

---

## 1. Top-level layout

```
JustFixed/
├── alembic/            SQLAlchemy-Alembic migration environment + version scripts
├── assets/             Application icon (icon.ico) and icon-gen README
├── docs/               Design and reference docs (this file lives here)
├── installer/          InnoSetup script (justfixed.iss) for Windows installer
├── src/justfixed/      The package — all application code
├── tests/              Pytest suite, mirroring src/justfixed/ layer by layer
├── tools/              Developer scripts: publish_curves.py, generate_placeholder_icon.py
├── alembic.ini         Alembic configuration
├── build.py            PyInstaller build helper
├── justfixed.spec      PyInstaller spec file
└── pyproject.toml      Package metadata, dependencies
```

---

## 2. The `src/justfixed/` package — layer by layer

### `domain/`
Pure value/entity types. No I/O, no database imports.

| File | Purpose | Public symbols |
|------|---------|----------------|
| `investment.py` | Single fixed-income purchase entity | `InvestmentSource` (enum), `Investment` (dataclass) |
| `issuer.py` | Issuing institution entity | `IssuerKind` (enum), `Issuer` (dataclass), `_normalize_cnpj` |
| `money.py` | Decimal-safe monetary amount | `Money` (dataclass; factory methods `from_reais`, `zero`) |
| `product.py` | Product taxonomy + coupon rules | `ProductType` (enum), `CouponFrequency` (enum), `TaxTreatment` (enum), `ProductRule` (dataclass), `rules_for` |
| `rates.py` | Typed rate sum-type | `Rate` (alias), `Prefixed`, `PostFixedCDI`, `PostFixedIPCA`, `PostFixedCDIPlusSpread` (dataclasses), `_format_brazilian_percent` |

### `engine/`
Pure functions over domain types. No I/O except `fetcher.py` (HTTP) and `seed.py` (DB via repository).

| File | Purpose | Public symbols |
|------|---------|----------------|
| `accrual.py` | Day-count accrual for each rate type | `accrue` |
| `back_solve.py` | Reverse-solve max principal under FGC cap | `BackSolveResult`, `max_principal_under_fgc` |
| `calendar.py` | ANBIMA holiday calendar, business-day arithmetic | `business_days_between`, `is_business_day`, `add_business_days`, `next_business_day` |
| `cashflow.py` | Coupon schedule generation | `CashFlowKind` (enum), `CashFlow` (dataclass), `coupon_dates`, `schedule` |
| `conglomerate_report.py` | Build conglomerate aggregation view | `ConglomerateStatus`, `ConglomerateDetailRow`, `ConglomerateSection`, `ConglomerateReport`, `build_conglomerate_report`, `build_conglomerate_report_from_projections` |
| `curve.py` | CDI/IPCA/Pre yield-curve data types | `CurveVertex`, `Curve` |
| `fetcher.py` | HTTP fetch + local cache for curve/seed JSON | `FetchResult`, `fetch_curves`, `fetch_seed_data`, `parse_curve_payload` |
| `fgc.py` | FGC concentration check | `ExposureStatus`, `InvestmentExposure`, `ConglomerateExposure`, `FGCReport`, `fgc_concentration_report`, `fgc_concentration_report_from_projections` |
| `projection.py` | Project investment value to maturity | `ProjectionResult`, `project` |
| `seed.py` | One-time DB seed on empty database | `load_seed_if_empty` |
| `tax.py` | Brazilian regressive IR tax computation | `TaxResult`, `regressive_rate_for`, `compute_ir` |

### `importers/`
Three-layer pipeline (parser → mapper → loader) for three brokers. Each broker has its own `.py` (parser), `_mapper.py` (mapper), `_loader.py` (loader).

| File | Purpose | Public symbols |
|------|---------|----------------|
| `detection.py` | Auto-detect broker from file; dispatch to correct loader | `Broker` (enum), `detect_broker`, `load_statement` |
| `loader_types.py` | Shared loader return type | `LoadResult` |
| `_kind_catalog.py` | Classify issuer kind from name | `classify_issuer_kind` |
| `_parsing_utils.py` | Shared percent-parsing utility | `_parse_brazilian_percent_to_fraction` |
| `_provenance.py` | Map import source to custodian string | `custodian_for_source` |
| `xp.py` | XP XLSX parser (file → `XPRow` list) | `XPRow`, `read_renda_fixa_rows` |
| `xp_mapper.py` | XP strings → typed domain values | `ParsedXPRow`, `parse_row`, `parse_brazilian_money`, `parse_brazilian_date`, `parse_rate`, `parse_product_and_coupon`, `parse_issuer_name` |
| `xp_loader.py` | XP typed values → persisted investments | `load_xp_statement` |
| `btg.py` | BTG XLSX parser | `BTGRow`, `read_renda_fixa_rows` |
| `btg_mapper.py` | BTG strings → typed domain values | `ParsedBTGRow`, `parse_row`, `parse_btg_datetime_string`, `parse_btg_decimal`, `parse_btg_rate`, `parse_btg_product` |
| `btg_loader.py` | BTG typed values → persisted | `load_btg_statement` |
| `bb.py` | BB fixed-width .txt parser | `BBRow`, `read_lca_rows` |
| `bb_mapper.py` | BB strings → typed domain values | `ParsedBBRow`, `parse_row`, `parse_taxa` |
| `bb_loader.py` | BB typed values → persisted | `load_bb_statement` |

### `persistence/`
SQLAlchemy models, mappers, repositories, and Alembic migration runner.

| File | Purpose | Public symbols |
|------|---------|----------------|
| `database.py` | Engine/session factory; default DB URL | `Base`, `default_database_url`, `make_engine`, `make_session_factory`, `session_scope` |
| `models.py` | SQLAlchemy ORM table definitions | `IssuerRow`, `InvestmentRow`, `CurationMemoryRow` |
| `mappers.py` | Convert between domain objects and ORM rows | `issuer_to_row`, `issuer_from_row`, `investment_to_row`, `investment_from_row` |
| `migrations.py` | Apply Alembic migrations programmatically | `run_migrations` |
| `repositories.py` | All DB access (only public persistence API) | `IssuerRepository`, `InvestmentRepository`, `CurationMemoryRepository` |

### `exports/`

| File | Purpose | Public symbols |
|------|---------|----------------|
| `calendar.py` | Generate iCalendar (.ics) for maturity dates | `export_maturity_calendar` |
| `xlsx.py` | Generate XLSX workbooks for the Investments and Conglomerates tabs | `export_investments_xlsx`, `export_conglomerates_xlsx` |

### `ui/`
PySide6 single-window application.

| File | Purpose | Public symbols |
|------|---------|----------------|
| `main.py` | Entire UI — all tabs, panels, workers, MainWindow (~3954 lines; see §3) | see §3 |
| `curve_inspector.py` | Pop-up curve viewer with chart + vertices table + cross-check (~533 lines) | `CurveInspectorWindow` |
| `manage_reference_data.py` | Modal reference-data management dialog (issuers, conglomerates, custodians) | `ManageReferenceDataDialog` |
| `theme.py` | Design tokens — frozen COLORS and FONTS dataclasses (~119 lines) | `Colors`, `Fonts`, `COLORS`, `FONTS` |
| `qss.py` | Global stylesheet factory applied once to QApplication (~369 lines) | `make_stylesheet` |
| `widgets/panel.py` | Reusable titled/bordered content frame | `Panel` |
| `widgets/provenance_callout.py` | Reusable curve provenance callout frame | `ProvenanceCallout` |

---

## 3. `ui/main.py` — deep map

**File stats:** 3954 lines. The only source of global constants used across the UI is this file's module-level block (lines 1–155). (§3 symbol line numbers are approximate and drift as the file grows.)

### 3a. Module-level constants (UI work reference)

| Name | Line | Value / purpose |
|------|------|----------------|
| `_COL_ISSUER` | 127 | 0 — column index |
| `_COL_CONGLOMERATE` | 128 | 1 |
| `_COL_PRODUCT` | 129 | 2 |
| `_COL_TYPE` | 130 | 3 |
| `_COL_RATE` | 131 | 4 |
| `_COL_PRINCIPAL` | 132 | 5 |
| `_COL_MATURITY` | 133 | 6 |
| `_COL_CURRENT` | 134 | 7 |
| `_COL_PROJECTED` | 135 | 8 |
| `_COL_FGC` | 136 | 9 |
| `_NCOLS` | 137 | 10 — total column count |
| `_HEADERS` | 139–142 | `["Issuer", "Conglomerate", "Product", "Type", "Rate", "Principal", "Maturity", "Current", "Projected", "FGC"]` |
| `_BADGE_STYLE` | 148–153 | `dict[str, (label, color)]` — keyed by `ExposureStatus.value` / `ConglomerateStatus.value` |
| `_HIGHLIGHT_COLOR` | 182 | `QColor(COLORS.HIGHLIGHT_ROW)` — freshly-imported row tint |
| `_MONO_FONT` | 183 | `QFont(FONTS.MONO_FAMILY, FONTS.MONO_SIZE)` — Consolas 10pt |
| `_MATURED_COLOR` | 184 | `QColor(COLORS.INK_3)` — whole-row mute for matured rows + PAID text |
| `_CUSTODIAN_UNSET` | 2003 | `object()` sentinel — distinguishes "no custodian filter" (None) from "filter for NULL custodian" |

### 3b. Where the stylesheet is applied

`main()` → line **3730**: `app.setStyleSheet(make_stylesheet())` — applied once to the `QApplication` instance before `MainWindow` is shown.

### 3c. Top-level classes and module-level functions

| Name | Lines | Description |
|------|-------|-------------|
| `_make_fgc_badge` | 173–180 | Returns a styled QLabel for FGC status (used in conglomerate accordion) |
| `_format_type` | 187–193 | Rate → short type string ("Pré", "CDI+", "IPCA+", "CDI") |
| `_format_rate_short` | 196–206 | Rate → compact rate string for accordion rows |
| `_format_rate` | 209–227 | Rate → full rate string for investments table; resolves CDI % from curve |
| `_is_matured` | 232–234 | Returns True if investment's maturity_date ≤ today |
| `compute_totals` | 237–294 | Aggregate principal / current / projected totals from a list + optional projection cache |
| `_make_cong_detail_header` | 299–320 | Build QWidget for conglomerate detail header row |
| `_make_cong_detail_row` | 323–371 | Build QWidget for a single conglomerate detail row; mock rows get left-border tint |
| `_row_is_mock` | 374–383 | Test whether a detail row matches the active Calculator mock |
| `_make_drawdown_header` | 394–414 | Build QWidget for Calculator drawdown table header |
| `_make_drawdown_row` | 417–489 | Build QWidget for a Calculator drawdown table row (including peak row variant) |
| `_pct_to_display` | 713–715 | Format Decimal percent for display (Calculator) |
| `_parse_rate_percent` | 718–733 | Parse percent string from Calculator form field |
| `_ImportWorker` | 494–507 | QThread that runs `load_statement` off the UI thread |
| `_ProjectWorker` | 510–534 | QThread that runs `project` for all investments off the UI thread |
| `_EditableField` | 539–708 | Inline click-to-edit widget (label ↔ line-edit toggle); used in `InvestmentDetailPanel` |
| `_RateEditor` | 745–821 | Composite rate-entry widget (type selector + value field + suffix label); used in Calculator and Add Investment |
| `InvestmentDetailPanel` | 826–1156 | Right-side detail panel: editable fields, projection section, delete button |
| `_CalculatorTab` | 1161–1992 | Calculator tab widget: enter-value and back-solve modes, FGC drawdown preview |
| `_AddInvestmentPanel` | 2006–2306 | Manual investment entry form (source=MANUAL) |
| `ConglomerateEditDelegate` | 2311–2413 | QStyledItemDelegate for inline conglomerate column editing in investments table |
| `_ActiveMock` | 2419–2430 | Named-tuple-style dataclass holding the Calculator's synthetic investment + projection for mock-row display |
| `MainWindow` | 2435–3723 | The application's single QMainWindow — see §3d |
| `main` | 3728–3743 | Entry point: creates QApplication, applies stylesheet, builds MainWindow |

### 3d. `InvestmentDetailPanel` (826–1156) — key methods

| Method | Line | Description |
|--------|------|-------------|
| `__init__` | 868 | Builds form rows (_EditableField for issuer/product/rate/principal/purchase/maturity/custodian), delete button, projection section |
| `show_investment` | 942 | Populate all fields from an Investment; called on table selection change |
| `clear` | 1000 | Reset panel to empty state |
| `_build_projection_section` | 1012 | Build the projection sub-panel (Panel widget) |
| `refresh_projection` | 1063 | Re-run projection for current investment and update display |
| `_on_delete_clicked` | 1093 | Confirm dialog → delete investment → emit `investment_deleted` signal |
| `_save_field` | 1119 | Validate + persist a single editable field; return error string or "" |
| `_format_field` | 1132 | Format an investment field for display in the label view |
| `_set_error` | 1150 | Show/hide inline error label |

### 3e. `_CalculatorTab` (1161–1992) — key methods

| Method | Line | Description |
|--------|------|-------------|
| `__init__` | 1168 | Full form layout: mode radio buttons, issuer combo, rate editor, date fields, result area |
| `reset` | 1287 | Clear form inputs and result area |
| `_populate_issuer_combo` | 1332 | Reload issuer list from DB into combo box |
| `_on_mode_changed` | 1356 | Switch between "Enter Value" and "Solve" modes |
| `_on_calculate_clicked` | 1394 | Dispatch to `_run_enter_value_calculation` or `_run_solve_calculation` |
| `_run_enter_value_calculation` | 1400 | Compute projection for a given principal; build result card + FGC pill + drawdown panel |
| `_run_solve_calculation` | 1550 | Back-solve max principal; build solve result card + drawdown panel |
| `_build_solve_result_card` | 1675 | Build the Panel showing solved principal + FGC metrics |
| `_build_drawdown_panel` | 1765 | Build the drawdown table panel (header + rows, with mock/peak styling) |
| `_show_solve_panels` | 1866 | Place solve result card and drawdown panel into the result area |
| `_build_result_card` | 1890 | Build the Panel showing enter-value result (current + projected + FGC pill) |
| `_show_result_card` | 1981 | Place result card into the result area |

### 3f. `_AddInvestmentPanel` (2006–2306) — key methods

| Method | Line | Description |
|--------|------|-------------|
| `__init__` | 2017 | Builds entry form; title, error label, form rows, save button |
| `_build_form` | 2081 | Full form layout: issuer combo + new-issuer inline sub-form, product, rate, dates, principal, custodian |
| `reset` | 2180 | Clear all form fields and collapse new-issuer sub-form |
| `_populate_issuer_combo` | 2205 | Reload issuer list from DB |
| `_on_save_clicked` | 2220 | Validate form → create Investment + optional new Issuer → persist → emit `investment_saved` |
| `_resolve_issuer` | 2271 | Return existing Issuer from combo or create a new one from inline sub-form |

### 3g. `ConglomerateEditDelegate` (2311–2413) — key methods

| Method | Line | Description |
|--------|------|-------------|
| `__init__` | 2320 | Store references to MainWindow and session_factory |
| `createEditor` | 2325 | Build inline QLineEdit with autocomplete from existing conglomerate names |
| `setModelData` | 2356 | Persist edited conglomerate to DB and update curation memory; trigger highlight |

### 3h. `MainWindow` (2435–3723) — key methods

#### Construction
| Method | Line | Description |
|--------|------|-------------|
| `__init__` | 2436 | Open DB, run migrations, seed on first run, build full UI |
| `_build_ui` | 2504 | Assemble QTabWidget (Conglomerates, Investments, Calculator, Dev); all toolbar/filter/table layout |
| `_build_empty_state_widget` | 2725 | Build the "no investments yet" empty-state placeholder shown in the stack |
| `_build_dev_tab` | 3434 | Build the Dev tab (curve status + publishing runbook + seed info) |

#### Conglomerate accordion
| Method | Line | Description |
|--------|------|-------------|
| `_make_summary_header` | 2856 | Build the fixed accordion header row |
| `_make_summary_row` | 2747 | Build one conglomerate summary row widget |
| `_make_section_widget` | 2803 | Build an accordion section (summary row + expandable detail container) |
| `_make_detail_container` | 2839 | Build the detail sub-list widget for an expanded accordion section |
| `_toggle_section` | 2826 | Expand/collapse a conglomerate section |
| `_refresh_conglomerates` | 2887 | Rebuild the entire conglomerate accordion from `_investments` |
| `_clear_cong_layout` | 2849 | Remove all widgets from the conglomerate scroll area |
| `set_active_mock` | 2909 | Install a Calculator mock investment into the accordion display |
| `clear_active_mock` | 2919 | Remove the Calculator mock from the accordion display |
| `trigger_conglomerate_highlight` | 3241 | Scroll Conglomerates tab to, and expand, the section for a given issuer |

#### Investments table
| Method | Line | Description |
|--------|------|-------------|
| `refresh_table` | 2954 | Reload all investments from DB; repopulate table with current projection/FGC data |
| `_update_totals` | 2996 | Recompute and display principal/current/projected totals footer |
| `_populate_filter_dropdowns` | 3038 | Rebuild issuer/conglomerate/custodian filter combos from current investments |
| `visible_investments` | 3086 | Return filter-applied, maturity-sorted investments for display |
| `_populate_row` | 3102 | Write one investment into a table row (all columns including PAID path) |
| `_cell` | 3178 | Helper — set one cell with optional mono font + right-alignment |

#### Selection and panel
| Method | Line | Description |
|--------|------|-------------|
| `_on_selection_changed` | 3211 | Show/hide InvestmentDetailPanel when table selection changes |
| `_on_panel_close_requested` | 3227 | Close InvestmentDetailPanel on user dismiss |
| `_on_investment_deleted` | 3233 | Handle investment deletion signal from panel; refresh table |
| `_capture_selected_id` | 3193 | Return UUID of currently selected investment (for selection restore after refresh) |
| `_restore_selection` | 3201 | Re-select a row by UUID after a table refresh |

#### Import / add / delete
| Method | Line | Description |
|--------|------|-------------|
| `_on_import_clicked` | 3300 | Open file picker → launch `_ImportWorker` |
| `_on_import_done` | 3327 | Handle import completion; show result dialog; refresh table |
| `_on_import_error` | 3346 | Show import error dialog |
| `_on_add_investment_clicked` | 3352 | Open `_AddInvestmentPanel` |
| `_on_add_saved` | 3358 | Handle `investment_saved` signal; refresh and highlight new row |
| `_on_clear_db_clicked` | 3271 | Confirm → wipe DB → refresh |

#### Curve / projection / export
| Method | Line | Description |
|--------|------|-------------|
| `_fetch_curve` | 3391 | Launch HTTP curve fetch in background thread |
| `_update_curve_label` | 3401 | Update curve status display after fetch |
| `_refresh_dev_tab_curves` | 3409 | Refresh Dev tab curve status rows |
| `_open_curve_inspector` | 3374 | Open `CurveInspectorWindow` for a curve series |
| `_on_load_curve_from_file_clicked` | 3647 | Load curve from local JSON file (Dev tab action) |
| `_on_project_clicked` | 3681 | Launch `_ProjectWorker` to project all investments |
| `_on_project_done` | 3692 | Store projection cache; refresh table with projection data |
| `_on_project_error` | 3702 | Show projection error |
| `_on_export_clicked` | 3708 | Export maturity calendar as .ics |

#### Misc
| Method | Line | Description |
|--------|------|-------------|
| `_set_busy` | 2935 | Enable/disable toolbar buttons during background work |
| `_on_hide_matured_toggled` | 3260 | Toggle matured-row visibility and refresh |
| `_on_issuer_filter_changed` | 3069 | Apply issuer filter and refresh |
| `_on_conglomerate_filter_changed` | 3073 | Apply conglomerate filter and refresh |
| `_on_custodian_filter_changed` | 3077 | Apply custodian filter and refresh |
| `_update_button_states` | 3185 | Enable/disable Project and Export buttons based on investment list |
| `_set_startup_tab` | 3369 | Switch to Investments tab on first import |
| `_on_about_clicked` | 2924 | Show About dialog |

---

## 4. The UI styling system

### `theme.py` — design tokens (119 lines)

Two frozen dataclasses, instantiated as module-level singletons `COLORS` and `FONTS`. These are the **single source of truth** for all color and type tokens. Any widget needing a color value must read from `COLORS`; no hex literals in QSS or widget code.

**Token groups in `Colors`:**

| Group | Tokens |
|-------|--------|
| Ink (text) | `INK`, `INK_2`, `INK_3` |
| Paper (backgrounds) | `PAPER`, `PANEL`, `PANEL_2` |
| Rules (borders) | `RULE`, `RULE_2` |
| Accent | `LINK`, `WARN`, `CALLOUT_BG`, `CALLOUT_EDGE`, `ACCENT`, `ROW_HOVER` |
| Curve inspector extras | `TABLE_ALT_BG`, `TABLE_HEADER_BG`, `STATUS_BAR_BG`, `UNAVAIL_BG` |
| FGC badges | `FGC_UNDER`, `FGC_NA`, `FGC_OVER` |
| Danger action | `DANGER`, `DANGER_HOVER`, `DANGER_PRESSED`, `DANGER_DISABLED_BG` |
| Error status | `ERROR_TEXT`, `ERROR_BG` |
| Toolbar buttons | `TOOLBAR_BTN`, `TOOLBAR_BTN_HOVER`, `TOOLBAR_BTN_PRESSED`, `TOOLBAR_BTN_DISABLED_BG` |
| Info banners | `SOURCE_BANNER_BG`, `SOURCE_BANNER_FG` |
| Form chrome | `FIELD_LABEL_FG` |
| Conglomerate accordion | `CONG_ROW_ODD`, `CONG_ROW_BORDER`, `CONG_HEADER_BG` |
| Conglomerate detail rows | `DETAIL_HEADER_BG`, `DETAIL_ROW_EVEN`, `DETAIL_ROW_ODD`, `DETAIL_ROW_BORDER` |
| Secondary button | `SECONDARY_HOVER` |
| Dev tab | `CODE_BLOCK_BG` |
| Investments table | `HIGHLIGHT_ROW` |
| Calculator mock/peak rows | `MOCK_ROW_BG`, `MOCK_ROW_EDGE`, `MOCK_INK`, `PEAK_ROW_BG`, `PEAK_ROW_EDGE`, `PEAK_INDICATOR` |

**`Fonts` tokens:** `UI_FAMILY` (Segoe UI), `UI_SIZE_SM` (8pt), `UI_SIZE_MD` (10pt), `MONO_FAMILY` (Consolas), `MONO_SIZE` (10pt).

---

### `qss.py` — global stylesheet (369 lines)

`make_stylesheet()` returns a single QSS string. It is applied once:

```python
# main.py:3730
app.setStyleSheet(make_stylesheet())
```

**Selector categories currently styled:**

| Category | Selector(s) |
|----------|-------------|
| Base surface | `QMainWindow`, `QDialog` — `PAPER` background |
| Base typography | `QWidget` — font-family + font-size (no background) |
| Type-scale labels | `QLabel[role="h1"]`, `QLabel[role="h2"]` |
| Toolbar buttons | `QPushButton[role="toolbar"]` + `:hover`, `:pressed`, `:disabled` |
| Danger button | `QPushButton[role="danger"]` + states |
| Secondary button | `QPushButton[role="secondary"]` + states |
| Panel title | `QLabel[role="panelTitle"]` |
| Info/source banner | `QLabel[role="infoBanner"]` |
| Error label | `QLabel[role="error"]` |
| Field labels | `QLabel[role="fieldLabel"]` |
| Sub-labels | `QLabel[role="subLabel"]` |
| FGC badges | `QLabel[fgcStatus="under/approaching/over/not_fgc"]` |
| Conglomerate accordion header | `QWidget#congHeader`, `QWidget#congHeader QLabel` |
| Conglomerate accordion rows | `QWidget[congRowParity="even/odd"]` |
| Conglomerate detail header | `QWidget#detailHeader`, `QWidget#detailHeader QLabel` |
| Conglomerate detail rows | `QWidget[detailRowParity="even/odd"]` |
| Calculator error field | `QLineEdit[hasError="true"]` |
| Calculator big result | `QLabel[calcResultBig="true"]` |
| Status bar | `QStatusBar` |
| Calculator mock row | `QWidget[rowKind="mock"]`, `QLabel[badge="mock"]` |
| Calculator peak row | `QWidget[rowKind="peak"]`, `QLabel[indicator="peak"]` |
| Tabs | `QTabWidget::pane`, `QTabBar::tab` + `:selected` / `:hover:!selected` |
| Form inputs | `QLineEdit`, `QComboBox` (+ `::drop-down`), `QDateEdit` (+ `::down-button`), `QCheckBox`, `QRadioButton` + `:focus`/`:disabled` states |
| Totals strip | `QWidget#totalsStrip` |
| **Investments table** | `QTableWidget#investmentsTable` — base + alternate-bg + item borders + selection; `QTableWidget#investmentsTable QHeaderView::section` — header chrome |

**Not yet styled via QSS (known visual gap — inline setStyleSheet or Qt defaults apply):**

- Glyphs left at Qt default: `QComboBox::down-arrow`, the `QDateEdit` up/down arrows, and `QCheckBox`/`QRadioButton` `::indicator` (the input widgets themselves, and the `QComboBox::drop-down` / `QDateEdit::down-button` buttons, are styled — see the table above)
- Curve inspector: has its own `_apply_stylesheet()` method with locally-scoped inline styles (file `curve_inspector.py:284`); the vertices `QTableWidget` inside it carries `objectName="verticesTable"` but is styled by that local method, **not** by the global sheet
- `QScrollArea`, `QScrollBar` — unstyled

---

### `widgets/` — extracted reusable widgets

**`Panel`** (`widgets/panel.py`)
```python
Panel(title: str, content: QWidget | None = None, *, meta: str | None = None, parent: QWidget | None = None)
```
A `QFrame` (`objectName="panel_frame"`) with a `PANEL_2`-background header row (title + optional mono meta label on the right) and a content area below. Used in `InvestmentDetailPanel._build_projection_section`, `_CalculatorTab._build_result_card`, `CurveInspectorWindow._build_chart_panel` / `_build_table_panel`.
Key methods: `set_content(widget)`, `set_meta(text)`, `set_title(text)`.

**`ProvenanceCallout`** (`widgets/provenance_callout.py`)
```python
ProvenanceCallout(series_name: str, as_of: date | None = None, *, clarifier: str | None = None, fetched_at=None, fetch_status=None, source: str = "justfixed-data", parent=None)
```
A `QFrame` (`objectName="provenance"`) showing a rich-text series label and a "CURVE AS-OF" date row. Used in `CurveInspectorWindow`. Key methods: `set_as_of(d)`, `set_unavailable(reason)`.

---

### objectName / role= reserve list (currently in use)

These names are active in the codebase. Future widgets should reuse rather than reinvent.

**`setObjectName` values:**
- `"investmentsTable"` — the investments `QTableWidget` (main.py:2584; QSS-scoped)
- `"totalsStrip"` — investments-tab totals strip container (main.py:2653; QSS-scoped)
- `"congHeader"` — conglomerate accordion summary header row widget (main.py:2858)
- `"detailHeader"` — conglomerate detail header row widget (main.py:301, 396)
- `"panel_frame"` — `Panel` widget frame (widgets/panel.py:28)
- `"panel_title"` — `Panel` title label (widgets/panel.py:44)
- `"panel_meta"` — `Panel` meta label (widgets/panel.py:50)
- `"provenance"` — `ProvenanceCallout` frame (widgets/provenance_callout.py:40)
- `"CurveInspectorWindow"` — curve inspector window (curve_inspector.py:270)
- `"verticesTable"` — curve inspector vertices table (curve_inspector.py:421; styled by the inspector's local `_apply_stylesheet`, not the global sheet)
- `"crosscheck"` — curve inspector cross-check frame (curve_inspector.py:458)
- `"CurveStatusBar"` — curve inspector status bar label (curve_inspector.py:497)

**`setProperty("role", ...)` values:**
- `"toolbar"` — green action buttons (Import, Add, Project, Export)
- `"secondary"` — outlined utility buttons (Conglomerate Project, empty-state buttons, Dev copy buttons)
- `"danger"` — red delete button
- `"panelTitle"` — bold panel heading labels
- `"infoBanner"` — source/info banner labels
- `"error"` — error message labels
- `"fieldLabel"` — left-column form field labels
- `"subLabel"` — smaller sub-labels in new-issuer inline sub-form
- `"emptyState"` — empty-state placeholder widget (selector not yet in QSS)
- `"h1"`, `"h2"` — type-scale heading labels (in QSS but not yet applied to any widget)

**Other `setProperty` keys:**
- `"fgcStatus"` → `"under"/"approaching"/"over"/"not_fgc"` — FGC badge labels
- `"congRowParity"` → `"even"/"odd"` — conglomerate accordion row alternating background
- `"detailRowParity"` → `"even"/"odd"` — conglomerate detail row alternating background
- `"rowKind"` → `"mock"/"peak"` — Calculator drawdown preview special rows
- `"badge"` → `"mock"` — mock-row badge label
- `"indicator"` → `"peak"` — peak-row indicator label
- `"hasError"` → `"true"/"false"` — Calculator form field error border
- `"calcResultBig"` → `"true"` — Calculator principal result large label

---

## 5. Design system reference

### Claude Design bundle (external, frozen)

The Claude Design visual reference bundle lives **outside this repo** at:
```
C:\Projects\justfixed-design\justfixed\
```

**It is a FROZEN snapshot as of 2026-05-24.** Key facts:

- It is a **design reference only**, not a live backlog or second source of truth.
- Its file names (`investments_tab.py`, `detail_panel.py`, `theme.py`, etc.) **do NOT match this repo's file structure**. The UI is consolidated in `src/justfixed/ui/main.py`; there is no `investments_tab.py` or `detail_panel.py` in this repo. Future sessions must not mistake bundle file names for real repo paths.
- Consult it for visual intent (spacing, color choices, typography hierarchy), not for code organization or symbol names.

### Shipped vs remaining visual work

**Shipped (as of 2026-05-30):**
- B43 Foundations: COLORS/FONTS token dataclasses, `make_stylesheet()` global QSS, base surface + typography rules (global-styling commit 1)
- Investments table visual pass: `setAlternatingRowColors`, `setShowGrid(False)`, right-aligned numeric columns, PAID right-alignment, `QTableWidget#investmentsTable` QSS block with header chrome (global-styling commit 2)
- Tab styling (`QTabWidget`/`QTabBar`) and form-input chrome (`QLineEdit`/`QComboBox`/`QDateEdit`/`QCheckBox`/`QRadioButton`)
- Mono-numeric column formatting throughout investments table
- PAID treatment (matured row mute to INK_3)
- Calculator tab (full enter-value + back-solve UI with FGC drawdown)
- Curve bi-directional chart↔table highlight in `CurveInspectorWindow`
- Dev tab publishing runbook (display-only, copy buttons)

**Known remaining visual gap:**
- Form-input glyphs (`QComboBox` arrow, `QDateEdit` arrows, `QCheckBox`/`QRadioButton` indicators) left at Qt default
- Table density: row height and padding not yet tuned against design spec
- Curve inspector: vertices table still styled by its own `_apply_stylesheet`, not yet migrated to the global QSS / COLORS tokens
