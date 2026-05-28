"""Tests for _CalculatorTab widget (B41 phase 2).

Two test patterns:

* Mocked-repo pattern (_make_tab): patches IssuerRepository so no real
  database is needed. Used for structural/default/reset tests.

* Real-DB pattern (_make_real_factory + _CalculatorTab(factory)): uses an
  in-memory SQLite database. Used for Calculate wiring tests (A–F) where
  InvestmentRepository must return real holdings.
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication, QWidget

from justfixed.domain.investment import Investment
from justfixed.domain.issuer import Issuer, IssuerKind
from justfixed.domain.money import Money
from justfixed.domain.product import ProductType
from justfixed.domain.rates import Prefixed, _format_brazilian_percent
from justfixed.engine import back_solve as _back_solve
from justfixed.engine.calendar import business_days_between
from justfixed.engine.projection import project
from justfixed.persistence.database import Base, make_engine, make_session_factory
from justfixed.persistence.repositories import InvestmentRepository, IssuerRepository
from justfixed.ui.main import _ActiveMock, _CalculatorTab


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


def _make_issuer(name: str = "Banco Inter") -> Issuer:
    return Issuer(
        name=name,
        conglomerate="Banco Inter S.A.",
        kind=IssuerKind.COMMERCIAL_BANK,
    )


def _make_tab(issuers: list[Issuer] | None = None) -> _CalculatorTab:
    """Create a _CalculatorTab with a mocked session_factory.

    IssuerRepository is patched so __init__'s reset() call succeeds
    without a real database.
    """
    with patch("justfixed.ui.main.IssuerRepository") as MockRepo:
        MockRepo.return_value.list_all.return_value = issuers or []
        tab = _CalculatorTab(MagicMock())
    return tab


def _call_reset(tab: _CalculatorTab, issuers: list[Issuer] | None = None) -> None:
    with patch("justfixed.ui.main.IssuerRepository") as MockRepo:
        MockRepo.return_value.list_all.return_value = issuers or []
        tab.reset()


# ── Tab label ─────────────────────────────────────────────────────────────────

class TestCalculatorTabLabel:
    def test_tab_text_is_calculator(self, qapp) -> None:
        from PySide6.QtWidgets import QTabWidget
        tab_widget = QTabWidget()
        calc_tab = _make_tab()
        tab_widget.addTab(calc_tab, "Calculator")
        assert tab_widget.tabText(0) == "Calculator"

    def test_calculator_tab_position(self, qapp) -> None:
        import os
        from PySide6.QtWidgets import QTabWidget, QWidget

        def _find_tab(tw: QTabWidget, text: str) -> int:
            for i in range(tw.count()):
                if tw.tabText(i) == text:
                    return i
            return -1

        tab_widget = QTabWidget()
        tab_widget.addTab(QWidget(), "Conglomerates")
        tab_widget.addTab(QWidget(), "Investments")
        tab_widget.addTab(_make_tab(), "Calculator")
        if os.environ.get("JUSTFIXED_DEV"):
            tab_widget.addTab(QWidget(), "Dev")

        calc_idx = _find_tab(tab_widget, "Calculator")
        investments_idx = _find_tab(tab_widget, "Investments")
        dev_idx = _find_tab(tab_widget, "Dev")

        assert calc_idx != -1
        assert investments_idx != -1
        assert calc_idx > investments_idx
        if dev_idx != -1:
            assert calc_idx < dev_idx


# ── Field defaults ─────────────────────────────────────────────────────────────

class TestCalculatorTabDefaults:
    def test_calculate_button_disabled_by_default(self, qapp) -> None:
        tab = _make_tab()
        assert not tab._calc_btn.isEnabled()

    def test_enter_value_radio_checked_by_default(self, qapp) -> None:
        tab = _make_tab()
        assert tab._radio_enter.isChecked()
        assert not tab._radio_solve.isChecked()

    def test_value_field_enabled_when_enter_value_selected(self, qapp) -> None:
        tab = _make_tab()
        assert tab._value_edit.isEnabled()

    def test_purchase_date_defaults_to_today(self, qapp) -> None:
        tab = _make_tab()
        today = date.today()
        q = tab._purchase_date_edit.date()
        assert (q.year(), q.month(), q.day()) == (today.year, today.month, today.day)

    def test_maturity_defaults_to_one_year_after_purchase(self, qapp) -> None:
        tab = _make_tab()
        today = date.today()
        expected = today.replace(year=today.year + 1)
        q = tab._maturity_date_edit.date()
        assert (q.year(), q.month(), q.day()) == (expected.year, expected.month, expected.day)

    def test_issuer_combo_populated_from_repo(self, qapp) -> None:
        issuer = _make_issuer("Banco Inter")
        tab = _make_tab(issuers=[issuer])
        names = [tab._issuer_combo.itemText(i) for i in range(tab._issuer_combo.count())]
        assert "Banco Inter" in names


# ── Mode toggle ────────────────────────────────────────────────────────────────

class TestModeToggle:
    def test_solve_mode_disables_value_field(self, qapp) -> None:
        tab = _make_tab()
        tab._radio_solve.setChecked(True)
        tab._mode_group.idClicked.emit(1)
        assert not tab._value_edit.isEnabled()

    def test_enter_mode_re_enables_value_field(self, qapp) -> None:
        tab = _make_tab()
        tab._radio_solve.setChecked(True)
        tab._mode_group.idClicked.emit(1)
        tab._radio_enter.setChecked(True)
        tab._mode_group.idClicked.emit(0)
        assert tab._value_edit.isEnabled()


# ── Reset ─────────────────────────────────────────────────────────────────────

class TestReset:
    def test_reset_clears_value_field(self, qapp) -> None:
        tab = _make_tab()
        tab._value_edit.setText("50.000,00")
        _call_reset(tab)
        assert tab._value_edit.text() == ""

    def test_reset_restores_enter_value_radio(self, qapp) -> None:
        tab = _make_tab()
        tab._radio_solve.setChecked(True)
        tab._mode_group.idClicked.emit(1)
        _call_reset(tab)
        assert tab._radio_enter.isChecked()
        assert tab._value_edit.isEnabled()

    def test_reset_repopulates_issuer_combo(self, qapp) -> None:
        tab = _make_tab()
        issuer = _make_issuer("Novo Banco")
        _call_reset(tab, issuers=[issuer])
        names = [tab._issuer_combo.itemText(i) for i in range(tab._issuer_combo.count())]
        assert "Novo Banco" in names


# ── Real-DB helpers ────────────────────────────────────────────────────────────

_ASSUMED_CDI  = Decimal("0.144")
_ASSUMED_IPCA = Decimal("0.0414")

_PURCHASE = date(2024, 1, 2)
_MATURITY = date(2025, 1, 2)   # 366 calendar days (2024 is a leap year), 253 bdays


def _make_real_factory():
    """Fresh in-memory SQLite database with all tables created."""
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)


def _save_issuer(factory, name="Test Issuer", conglomerate="Test Cong",
                 kind=IssuerKind.COMMERCIAL_BANK) -> Issuer:
    issuer = Issuer.create(name, conglomerate, kind)
    IssuerRepository(factory).save(issuer)
    return issuer


def _set_form(tab, *, issuer_idx=0, product_type=ProductType.CDB,
              rate=None, purchase=_PURCHASE, maturity=_MATURITY,
              value="50.000,00") -> None:
    """Populate all Calculator form fields for a deterministic Calculate run."""
    if rate is None:
        rate = Prefixed.from_percent("14")
    tab._issuer_combo.setCurrentIndex(issuer_idx)
    for i in range(tab._product_combo.count()):
        if tab._product_combo.itemData(i) == product_type:
            tab._product_combo.setCurrentIndex(i)
            break
    tab._rate_editor.set_rate(rate)
    tab._purchase_date_edit.setDate(QDate(purchase.year, purchase.month, purchase.day))
    tab._maturity_date_edit.setDate(QDate(maturity.year, maturity.month, maturity.day))
    tab._value_edit.setText(value)


# ── Test A: valid Enter-value input, all six result lines ──────────────────────

class TestCalculateResultLines:
    """A: valid Enter-value run with no existing holdings. Tests each line."""

    def _run(self, qapp):
        factory = _make_real_factory()
        _save_issuer(factory)
        tab = _CalculatorTab(factory)
        _set_form(tab)
        tab._on_calculate_clicked()
        return tab

    def test_principal_line(self, qapp) -> None:
        tab = self._run(qapp)
        assert tab._res_principal_lbl is not None
        assert tab._res_principal_lbl.text() == "R$ 50.000,00"

    def test_projected_line(self, qapp) -> None:
        tab = self._run(qapp)
        assert tab._res_projected_lbl is not None
        assert tab._res_projected_lbl.text() == "R$ 55.799,46"

    def test_fgc_utilization_line(self, qapp) -> None:
        tab = self._run(qapp)
        assert tab._res_fgc_util_lbl is not None
        assert tab._res_fgc_util_lbl.text() == "R$ 57.029,65 / R$ 250.000,00"

    def test_status_under(self, qapp) -> None:
        tab = self._run(qapp)
        assert tab._res_status_pill is not None
        assert tab._res_status_pill.text() == "UNDER"
        assert tab._res_status_pill.property("fgcStatus") == "under"

    def test_effective_rate(self, qapp) -> None:
        tab = self._run(qapp)
        assert tab._res_effective_rate_lbl is not None
        # Derive expected value from the projection, same formula as implementation.
        issuer = Issuer.create("Test Issuer", "Test Cong", IssuerKind.COMMERCIAL_BANK)
        inv = Investment.create(
            product=ProductType.CDB, issuer=issuer,
            principal=Money.from_reais("50000"),
            rate=Prefixed.from_percent("14"),
            purchase_date=_PURCHASE, maturity_date=_MATURITY,
        )
        proj = project(inv, as_of=_MATURITY,
                       assumed_cdi=_ASSUMED_CDI, assumed_ipca=_ASSUMED_IPCA)
        bdays = business_days_between(_PURCHASE, _MATURITY)
        years_252 = Decimal(bdays) / Decimal("252")
        eff = (proj.net_at_maturity.amount / Decimal("50000")) ** (
            Decimal("1") / years_252
        ) - Decimal("1")
        expected = _format_brazilian_percent(eff * Decimal("100"))
        assert tab._res_effective_rate_lbl.text() == expected

    def test_tenor_line(self, qapp) -> None:
        tab = self._run(qapp)
        assert tab._res_tenor_lbl is not None
        assert tab._res_tenor_lbl.text() == "366 days"

    def test_result_card_shown(self, qapp) -> None:
        tab = self._run(qapp)
        assert tab._result_stack.currentIndex() == 1
        assert tab._result_panel is not None


# ── Test B: FGC OVER scenario ──────────────────────────────────────────────────

class TestCalculateFGCOver:
    """B: existing holdings push the conglomerate over the FGC cap."""

    def test_status_over(self, qapp) -> None:
        factory = _make_real_factory()
        issuer = _save_issuer(factory)

        # Existing holding: large enough to push total over R$250k alongside the mock
        existing = Investment.create(
            product=ProductType.CDB, issuer=issuer,
            principal=Money.from_reais("200000"),
            rate=Prefixed.from_percent("5"),
            purchase_date=date(2023, 1, 2), maturity_date=date(2026, 1, 2),
        )
        InvestmentRepository(factory).save(existing)

        tab = _CalculatorTab(factory)
        _set_form(tab)
        tab._on_calculate_clicked()

        assert tab._res_status_pill is not None
        assert tab._res_status_pill.text() == "OVER"
        assert tab._res_status_pill.property("fgcStatus") == "over"


# ── Test C: Tesouro issuer ─────────────────────────────────────────────────────

class TestCalculateTesouro:
    """C: Treasury issuer — FGC shows N/A."""

    def test_status_not_fgc(self, qapp) -> None:
        factory = _make_real_factory()
        issuer = _save_issuer(
            factory, "Tesouro Nacional", "Tesouro Nacional", IssuerKind.TREASURY
        )

        tab = _CalculatorTab(factory)
        # TESOURO_PREFIXADO is not shown in the FGC-only product combo by default;
        # add it here so the Investment.create() call can succeed with a TREASURY issuer.
        tab._product_combo.addItem("Tesouro Prefixado", ProductType.TESOURO_PREFIXADO)
        _set_form(tab, product_type=ProductType.TESOURO_PREFIXADO)
        tab._on_calculate_clicked()

        assert tab._res_status_pill is not None
        assert tab._res_status_pill.text() == "N/A — Tesouro"
        assert tab._res_status_pill.property("fgcStatus") == "not_fgc"
        assert tab._res_fgc_util_lbl is not None
        assert tab._res_fgc_util_lbl.text() == "N/A"


# ── Test D: validation failures ────────────────────────────────────────────────

class TestValidationFailures:
    """D: each validation rule has its own inline error; result card stays cleared."""

    def _tab_with_issuer(self, qapp):
        factory = _make_real_factory()
        _save_issuer(factory)
        return _CalculatorTab(factory)

    def test_empty_principal_shows_error(self, qapp) -> None:
        tab = self._tab_with_issuer(qapp)
        _set_form(tab, value="")
        tab._on_calculate_clicked()
        # isVisible() requires a realized window; isHidden() checks the widget's own flag.
        assert not tab._value_err_wrap.isHidden()
        assert tab._result_stack.currentIndex() == 0  # placeholder preserved

    def test_negative_principal_shows_error(self, qapp) -> None:
        tab = self._tab_with_issuer(qapp)
        _set_form(tab, value="-1,00")
        tab._on_calculate_clicked()
        assert not tab._value_err_wrap.isHidden()
        assert tab._result_stack.currentIndex() == 0

    def test_maturity_equals_purchase_shows_error(self, qapp) -> None:
        tab = self._tab_with_issuer(qapp)
        _set_form(tab, purchase=date(2024, 6, 1), maturity=date(2024, 6, 1))
        tab._on_calculate_clicked()
        assert not tab._maturity_err_wrap.isHidden()
        assert tab._result_stack.currentIndex() == 0

    def test_maturity_before_purchase_shows_error(self, qapp) -> None:
        tab = self._tab_with_issuer(qapp)
        _set_form(tab, purchase=date(2024, 6, 2), maturity=date(2024, 6, 1))
        tab._on_calculate_clicked()
        assert not tab._maturity_err_wrap.isHidden()
        assert tab._result_stack.currentIndex() == 0


# ── Test E: reset clears result card ──────────────────────────────────────────

class TestResetClearsResult:
    """E: reset after a successful calculation restores the placeholder."""

    def test_reset_restores_placeholder(self, qapp) -> None:
        factory = _make_real_factory()
        _save_issuer(factory)
        tab = _CalculatorTab(factory)
        _set_form(tab)
        tab._on_calculate_clicked()
        assert tab._result_stack.currentIndex() == 1  # result card visible

        with patch("justfixed.ui.main.IssuerRepository") as MockRepo:
            MockRepo.return_value.list_all.return_value = []
            tab.reset()

        assert tab._result_stack.currentIndex() == 0  # placeholder restored
        assert tab._result_panel is None


# ── Test F: Solve mode result card ────────────────────────────────────────────

class TestSolveMode:
    """F: Calculate in Solve mode shows a real back-solve result card."""

    def _run(self, qapp, existing: list[Investment] | None = None):
        factory = _make_real_factory()
        issuer = _save_issuer(factory)
        if existing:
            for inv in existing:
                InvestmentRepository(factory).save(inv)
        tab = _CalculatorTab(factory)
        _set_form(tab)
        tab._radio_solve.setChecked(True)
        tab._mode_group.idClicked.emit(1)
        tab._on_calculate_clicked()
        return tab, issuer

    def _expected(self, issuer: Issuer) -> _back_solve.BackSolveResult:
        return _back_solve.max_principal_under_fgc(
            issuer_name=issuer.name,
            product=ProductType.CDB,
            rate=Prefixed.from_percent("14"),
            purchase_date=_PURCHASE,
            maturity_date=_MATURITY,
            existing_holdings=[],
            assumed_cdi=_ASSUMED_CDI,
            assumed_ipca=_ASSUMED_IPCA,
        )

    def test_solve_shows_result_panel(self, qapp) -> None:
        tab, _ = self._run(qapp)
        assert tab._result_stack.currentIndex() == 1
        assert tab._result_panel is not None

    def test_max_principal_line(self, qapp) -> None:
        tab, issuer = self._run(qapp)
        result = self._expected(issuer)
        assert tab._res_principal_lbl is not None
        assert tab._res_principal_lbl.text() == Money(result.max_principal).to_display()

    def test_projected_gross_line(self, qapp) -> None:
        tab, issuer = self._run(qapp)
        result = self._expected(issuer)
        assert tab._res_projected_lbl is not None
        assert tab._res_projected_lbl.text() == Money(result.projected_at_maturity).to_display()

    def test_status_at_cap_no_holdings(self, qapp) -> None:
        # Solve mode maximizes principal up to the FGC cap, so peak_utilization
        # is always ≥ 0.99 → AT CAP when no existing holdings consume the limit.
        tab, _ = self._run(qapp)
        assert tab._res_status_pill is not None
        assert tab._res_status_pill.text() == "AT CAP"
        assert tab._res_status_pill.property("fgcStatus") == "under"

    def test_effective_rate_is_gross(self, qapp) -> None:
        tab, issuer = self._run(qapp)
        result = self._expected(issuer)
        bdays = business_days_between(_PURCHASE, _MATURITY)
        years_252 = Decimal(bdays) / Decimal("252")
        eff = (result.projected_at_maturity / result.max_principal) ** (
            Decimal("1") / years_252
        ) - Decimal("1")
        expected = _format_brazilian_percent(eff * Decimal("100"))
        assert tab._res_effective_rate_lbl is not None
        assert tab._res_effective_rate_lbl.text() == expected

    def test_solve_max_principal_zero_when_existing_at_cap(self, qapp) -> None:
        # Existing holding fills the full FGC cap at the same issuer, overlapping
        # the mock window. back_solve returns max_principal == 0.
        factory = _make_real_factory()
        issuer = _save_issuer(factory)
        existing = Investment.create(
            product=ProductType.CDB,
            issuer=issuer,
            principal=Money.from_reais("250000"),
            rate=Prefixed.from_percent("5"),
            purchase_date=date(2023, 6, 1),
            maturity_date=date(2026, 6, 1),  # overlaps _PURCHASE.._MATURITY
        )
        InvestmentRepository(factory).save(existing)

        tab = _CalculatorTab(factory)
        _set_form(tab)
        tab._radio_solve.setChecked(True)
        tab._mode_group.idClicked.emit(1)
        tab._on_calculate_clicked()

        assert tab._res_principal_lbl is not None
        assert tab._res_principal_lbl.text() == "R$ 0,00"
        assert tab._res_status_pill is not None
        assert tab._res_status_pill.text() == "OVER"
        # Effective rate line is omitted when principal is zero.
        assert tab._res_effective_rate_lbl is None


# ── Test G: Treasury disables Solve radio ─────────────────────────────────────

class TestSolveTreasuryDisable:
    """G: Selecting a Treasury issuer disables the Solve radio button."""

    def test_treasury_disables_solve_radio(self, qapp) -> None:
        factory = _make_real_factory()
        _save_issuer(factory, "Tesouro Nacional", "Tesouro Nacional", IssuerKind.TREASURY)
        tab = _CalculatorTab(factory)
        assert not tab._radio_solve.isEnabled()

    def test_non_treasury_enables_solve_radio(self, qapp) -> None:
        factory = _make_real_factory()
        _save_issuer(factory)  # COMMERCIAL_BANK
        tab = _CalculatorTab(factory)
        assert tab._radio_solve.isEnabled()

    def test_switching_to_treasury_disables_solve(self, qapp) -> None:
        factory = _make_real_factory()
        _save_issuer(factory, "Banco Inter", "Banco Inter S.A.", IssuerKind.COMMERCIAL_BANK)
        _save_issuer(factory, "Tesouro Nacional", "Tesouro Nacional", IssuerKind.TREASURY)
        tab = _CalculatorTab(factory)
        # Find Treasury index
        treasury_idx = next(
            i for i in range(tab._issuer_combo.count())
            if tab._issuer_combo.itemText(i) == "Tesouro Nacional"
        )
        tab._issuer_combo.setCurrentIndex(treasury_idx)
        assert not tab._radio_solve.isEnabled()


# ── Test H: Drawdown preview panel ───────────────────────────────────────────

class TestDrawdownPanel:
    """H: Drawdown preview card rendered during Solve mode."""

    def _run_solve(self, qapp, factory=None) -> _CalculatorTab:
        """Run a Solve calculation on a factory that already has exactly one issuer."""
        tab = _CalculatorTab(factory)
        _set_form(tab)
        tab._radio_solve.setChecked(True)
        tab._mode_group.idClicked.emit(1)
        tab._on_calculate_clicked()
        return tab

    def test_drawdown_panel_shown(self, qapp) -> None:
        factory = _make_real_factory()
        _save_issuer(factory)
        tab = self._run_solve(qapp, factory)
        assert tab._drawdown_panel is not None

    def test_mock_row_has_mock_kind(self, qapp) -> None:
        factory = _make_real_factory()
        _save_issuer(factory)
        tab = self._run_solve(qapp, factory)
        assert tab._drawdown_rows
        mock_rows = [w for w in tab._drawdown_rows if w.property("rowKind") == "mock"]
        assert len(mock_rows) == 1

    def test_overlapping_holding_appears(self, qapp) -> None:
        # An existing holding that overlaps the mock window should appear as a row.
        factory = _make_real_factory()
        issuer = _save_issuer(factory)
        overlapping = Investment.create(
            product=ProductType.CDB, issuer=issuer,
            principal=Money.from_reais("5000"),
            rate=Prefixed.from_percent("12"),
            purchase_date=date(2023, 6, 1),
            maturity_date=date(2024, 6, 1),  # overlaps _PURCHASE (2024-01-02).._MATURITY (2025-01-02)
        )
        InvestmentRepository(factory).save(overlapping)
        tab = self._run_solve(qapp, factory)
        # Should have: 1 existing row + 1 mock row
        assert len(tab._drawdown_rows) == 2
        existing_rows = [w for w in tab._drawdown_rows if w.property("rowKind") != "mock"]
        assert len(existing_rows) == 1

    def test_non_overlapping_excluded(self, qapp) -> None:
        # An existing holding whose window does not overlap the mock window is excluded.
        factory = _make_real_factory()
        issuer = _save_issuer(factory)
        outside = Investment.create(
            product=ProductType.CDB, issuer=issuer,
            principal=Money.from_reais("1000"),
            rate=Prefixed.from_percent("10"),
            purchase_date=date(2022, 1, 2),
            maturity_date=date(2023, 12, 31),  # matures before _PURCHASE (2024-01-02)
        )
        InvestmentRepository(factory).save(outside)
        tab = self._run_solve(qapp, factory)
        # Only the mock row — the outside holding is excluded.
        assert len(tab._drawdown_rows) == 1
        assert tab._drawdown_rows[0].property("rowKind") == "mock"

    def test_drawdown_peak_balance_real_when_principal_zero(self, qapp) -> None:
        # When max_principal == 0 (existing already at cap), the peak-row balance
        # shows the real running balance — not the cap stamp (R$ 250.000,00).
        factory = _make_real_factory()
        issuer = _save_issuer(factory)
        at_cap = Investment.create(
            product=ProductType.CDB, issuer=issuer,
            principal=Money.from_reais("250000"),
            rate=Prefixed.from_percent("5"),
            purchase_date=_PURCHASE,
            maturity_date=_MATURITY,
        )
        InvestmentRepository(factory).save(at_cap)

        tab = self._run_solve(qapp, factory)

        assert tab._res_principal_lbl is not None
        assert tab._res_principal_lbl.text() == "R$ 0,00"

        peak_rows = [w for w in tab._drawdown_rows if w.property("rowKind") == "peak"]
        assert len(peak_rows) == 1
        bal_lbl = peak_rows[0].layout().itemAt(6).widget()
        assert bal_lbl is not None

        proj = project(
            at_cap, as_of=_MATURITY,
            assumed_cdi=_ASSUMED_CDI, assumed_ipca=_ASSUMED_IPCA,
        )
        expected_prefix = proj.current_value.to_display()
        assert bal_lbl.text().startswith(expected_prefix)


# ── Test I: Tesouro exclusion from drawdown ───────────────────────────────────

class TestDrawdownTesouroExcluded:
    """I: Treasury holdings are excluded from the drawdown preview."""

    def test_treasury_holding_not_in_drawdown(self, qapp) -> None:
        factory = _make_real_factory()
        issuer = _save_issuer(factory)
        treasury_issuer = _save_issuer(
            factory, "Tesouro Nacional", "Tesouro Nacional", IssuerKind.TREASURY
        )
        treasury_inv = Investment.create(
            product=ProductType.TESOURO_PREFIXADO, issuer=treasury_issuer,
            principal=Money.from_reais("10000"),
            rate=Prefixed.from_percent("13"),
            purchase_date=date(2024, 1, 2),
            maturity_date=date(2025, 6, 1),  # overlaps the mock window
        )
        InvestmentRepository(factory).save(treasury_inv)

        tab = _CalculatorTab(factory)
        _set_form(tab)
        tab._radio_solve.setChecked(True)
        tab._mode_group.idClicked.emit(1)
        tab._on_calculate_clicked()

        # Only the mock row — Treasury is excluded by kind filter.
        assert tab._drawdown_rows is not None
        assert len(tab._drawdown_rows) == 1
        assert tab._drawdown_rows[0].property("rowKind") == "mock"


# ── B41 phase 2.4a: Calculator → MainWindow set/clear_active_mock wiring ──────

class _FakeMainWindow(QWidget):
    """Minimal QWidget parent stub for Calculator cross-tab wiring tests.

    Implements the set/clear_active_mock interface that the Calculator
    calls via parent(). statusBar() stub silences the showMessage call.
    """

    def __init__(self):
        super().__init__()
        self.active_mock = None
        self._set_calls = 0
        self._clear_calls = 0

    def set_active_mock(self, synth_inv, projection):
        self.active_mock = _ActiveMock(
            synth_investment=synth_inv,
            projection=projection,
        )
        self._set_calls += 1

    def clear_active_mock(self):
        self.active_mock = None
        self._clear_calls += 1

    def statusBar(self):
        sb = MagicMock()
        return sb


class TestCrossTabMockWiring:
    """d/e/f: Calculator wires set/clear_active_mock to the parent window."""

    def _make_tab_and_win(self) -> tuple[_CalculatorTab, _FakeMainWindow]:
        factory = _make_real_factory()
        _save_issuer(factory)
        fake_win = _FakeMainWindow()
        tab = _CalculatorTab(factory, fake_win)
        return tab, fake_win

    def test_enter_value_success_calls_set_active_mock(self, qapp) -> None:
        # d: successful Enter-value calculation wires into set_active_mock
        tab, fake_win = self._make_tab_and_win()
        set_calls_before = fake_win._set_calls
        _set_form(tab)
        tab._on_calculate_clicked()
        assert fake_win._set_calls == set_calls_before + 1
        assert fake_win.active_mock is not None
        assert fake_win.active_mock.synth_investment is not None
        assert fake_win.active_mock.projection is not None

    def test_reset_calls_clear_active_mock(self, qapp) -> None:
        # e: reset() calls clear_active_mock (after setting it via calculate)
        tab, fake_win = self._make_tab_and_win()
        _set_form(tab)
        tab._on_calculate_clicked()
        assert fake_win.active_mock is not None
        clear_calls_before = fake_win._clear_calls
        tab.reset()
        assert fake_win._clear_calls == clear_calls_before + 1
        assert fake_win.active_mock is None

    def test_solve_max_principal_zero_no_set_active_mock(self, qapp) -> None:
        # f: degenerate case — existing holdings fill the cap, max_principal==0,
        # set_active_mock must NOT be called
        factory = _make_real_factory()
        issuer = _save_issuer(factory)
        existing = Investment.create(
            product=ProductType.CDB,
            issuer=issuer,
            principal=Money.from_reais("250000"),
            rate=Prefixed.from_percent("5"),
            purchase_date=date(2023, 6, 1),
            maturity_date=date(2026, 6, 1),
        )
        InvestmentRepository(factory).save(existing)
        fake_win = _FakeMainWindow()
        tab = _CalculatorTab(factory, fake_win)
        _set_form(tab)
        tab._radio_solve.setChecked(True)
        tab._mode_group.idClicked.emit(1)
        set_calls_before = fake_win._set_calls
        tab._on_calculate_clicked()
        assert fake_win._set_calls == set_calls_before  # no new call
        assert fake_win.active_mock is None
