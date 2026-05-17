"""Tests for MainWindow projection cache infrastructure (B' UI session 2, stage B).

Uses the "real method, MagicMock self" pattern: the actual MainWindow methods
are called with a MagicMock stand-in for self. All attribute assignments land
on the mock and are directly assertable. No Qt window is instantiated, so
no QApplication or database setup is needed.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, call, patch

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from justfixed.domain.issuer import IssuerKind
from justfixed.domain.money import Money
from justfixed.engine.fgc import ExposureStatus
from justfixed.ui.main import ConglomerateEditDelegate, MainWindow, compute_totals


class TestProjectionCachePopulation:
    def test_project_done_populates_cache(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock.projection_cache = None
        self_mock._ts_label = MagicMock()
        fake_results = []
        fake_fgc = MagicMock()
        fake_fgc.conglomerates = []

        MainWindow._on_project_done(self_mock, fake_results, fake_fgc)

        assert self_mock.projection_cache is fake_results


class TestProjectionCacheInvalidation:
    def test_import_done_clears_cache(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock.projection_cache = [MagicMock()]
        self_mock._status_label = MagicMock()
        self_mock._ts_label = MagicMock()
        fake_result = MagicMock()
        fake_result.inserted = 3
        fake_result.skipped = 0

        MainWindow._on_import_done(self_mock, fake_result)

        assert self_mock.projection_cache is None

    def test_clear_db_clears_cache(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock.projection_cache = [MagicMock()]
        self_mock._investments = [MagicMock()]  # non-empty so dialog appears
        self_mock._repo = MagicMock()
        self_mock._repo.delete_all.return_value = (1, 0)
        self_mock._status_label = MagicMock()
        self_mock._ts_label = MagicMock()

        with patch("justfixed.ui.main.QMessageBox.question",
                   return_value=QMessageBox.StandardButton.Yes):
            MainWindow._on_clear_db_clicked(self_mock)

        assert self_mock.projection_cache is None


class TestRefreshTableCacheAwareness:
    def _make_self_mock(self) -> MagicMock:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._repo = MagicMock()
        self_mock._table = MagicMock()
        self_mock._stack = MagicMock()
        return self_mock

    def test_refresh_table_with_cache_uses_fgc_report(self) -> None:
        self_mock = self._make_self_mock()
        inv_id = uuid.uuid4()
        fake_inv = MagicMock()
        fake_inv.id = inv_id
        self_mock.visible_investments.return_value = [fake_inv]

        fake_inv_exposure = MagicMock()
        fake_inv_exposure.investment_id = inv_id
        fake_conglomerate = MagicMock()
        fake_conglomerate.current_status = ExposureStatus.APPROACHING
        fake_conglomerate.investments = [fake_inv_exposure]
        fake_report = MagicMock()
        fake_report.conglomerates = [fake_conglomerate]

        self_mock.projection_cache = [MagicMock()]

        with patch("justfixed.ui.main.fgc_concentration_report_from_projections",
                   return_value=fake_report) as mock_fgc_func:
            MainWindow.refresh_table(self_mock)

        mock_fgc_func.assert_called_once_with(self_mock.projection_cache)
        self_mock._populate_row.assert_called_once_with(
            0, fake_inv,
            current_value=None,
            projected_value=None,
            fgc_status=ExposureStatus.APPROACHING,
            highlight=False,
        )

    def test_refresh_table_without_cache_passes_none_fgc_status(self) -> None:
        self_mock = self._make_self_mock()
        fake_inv = MagicMock()
        self_mock.visible_investments.return_value = [fake_inv]
        self_mock.projection_cache = None

        MainWindow.refresh_table(self_mock)

        self_mock._populate_row.assert_called_once_with(
            0, fake_inv,
            current_value=None,
            projected_value=None,
            fgc_status=None,
            highlight=False,
        )

    def test_refresh_table_populates_current_and_projected_from_cache(self) -> None:
        self_mock = self._make_self_mock()
        inv_id = uuid.uuid4()

        fake_inv = MagicMock()
        fake_inv.id = inv_id
        fake_inv.issuer.conglomerate = "Banco X S.A."

        other_inv = MagicMock()
        other_inv.id = uuid.uuid4()
        other_inv.issuer.conglomerate = "Banco Y S.A."

        self_mock.visible_investments.return_value = [fake_inv, other_inv]

        fake_proj = MagicMock()
        fake_proj.investment.id = inv_id
        fake_proj.current_value = MagicMock(name="current_value")
        fake_proj.gross_at_maturity = MagicMock(name="gross_at_maturity")

        fake_report = MagicMock()
        fake_report.conglomerates = []
        self_mock.projection_cache = [fake_proj]

        with patch("justfixed.ui.main.fgc_concentration_report_from_projections",
                   return_value=fake_report):
            MainWindow.refresh_table(self_mock)

        calls = self_mock._populate_row.call_args_list
        assert calls[0] == call(
            0, fake_inv,
            current_value=fake_proj.current_value,
            projected_value=fake_proj.gross_at_maturity,
            fgc_status=None,
            highlight=False,
        )
        assert calls[1] == call(
            1, other_inv,
            current_value=None,
            projected_value=None,
            fgc_status=None,
            highlight=False,
        )


class TestRefreshTableHighlight:
    def _make_self_mock(self) -> MagicMock:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._repo = MagicMock()
        self_mock._table = MagicMock()
        self_mock._stack = MagicMock()
        self_mock.projection_cache = None
        return self_mock

    def test_refresh_table_highlights_matching_issuer_rows(self) -> None:
        self_mock = self._make_self_mock()
        matching_id = uuid.uuid4()

        matching_inv = MagicMock()
        matching_inv.issuer.id = matching_id
        matching_inv.issuer.conglomerate = "Banco A S.A."

        other_inv = MagicMock()
        other_inv.issuer.id = uuid.uuid4()
        other_inv.issuer.conglomerate = "Banco B S.A."

        self_mock.visible_investments.return_value = [matching_inv, other_inv]

        MainWindow.refresh_table(self_mock, highlight_issuer_id=matching_id)

        calls = self_mock._populate_row.call_args_list
        assert calls[0] == call(0, matching_inv, current_value=None, projected_value=None,
                                fgc_status=None, highlight=True)
        assert calls[1] == call(1, other_inv, current_value=None, projected_value=None,
                                fgc_status=None, highlight=False)

    def test_refresh_table_no_highlight_when_id_is_none(self) -> None:
        self_mock = self._make_self_mock()
        fake_inv = MagicMock()
        self_mock.visible_investments.return_value = [fake_inv]

        MainWindow.refresh_table(self_mock)

        self_mock._populate_row.assert_called_once_with(
            0, fake_inv,
            current_value=None,
            projected_value=None,
            fgc_status=None,
            highlight=False,
        )


class TestTriggerConglomerateHighlight:
    def test_trigger_highlight_cancels_existing_timer(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        old_timer = MagicMock(spec=QTimer)
        self_mock._highlight_timer = old_timer

        with patch("justfixed.ui.main.QTimer"):
            MainWindow.trigger_conglomerate_highlight(self_mock, uuid.uuid4())

        old_timer.stop.assert_called_once()

    def test_trigger_highlight_calls_refresh_with_id(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._highlight_timer = None
        issuer_id = uuid.uuid4()

        with patch("justfixed.ui.main.QTimer"):
            MainWindow.trigger_conglomerate_highlight(self_mock, issuer_id)

        self_mock.refresh_table.assert_called_once_with(highlight_issuer_id=issuer_id)

    def test_trigger_highlight_schedules_clear_after_3000ms(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._highlight_timer = None

        with patch("justfixed.ui.main.QTimer") as MockQTimer:
            mock_timer = MagicMock(spec=QTimer)
            MockQTimer.return_value = mock_timer
            MainWindow.trigger_conglomerate_highlight(self_mock, uuid.uuid4())

        mock_timer.setSingleShot.assert_called_once_with(True)
        mock_timer.setInterval.assert_called_once_with(3000)
        mock_timer.start.assert_called_once()


class TestRefreshTableScrollPreservation:
    def test_refresh_table_preserves_scroll_position(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._repo = MagicMock()
        self_mock._table = MagicMock()
        self_mock._stack = MagicMock()
        self_mock.projection_cache = None
        self_mock.visible_investments.return_value = []
        self_mock._table.verticalScrollBar.return_value.value.return_value = 150

        MainWindow.refresh_table(self_mock)

        self_mock._table.verticalScrollBar.return_value.setValue.assert_called_once_with(150)


def _make_inv(issuer_name: str, conglomerate: str, days_to_maturity: int) -> MagicMock:
    inv = MagicMock()
    inv.issuer.name = issuer_name
    inv.issuer.conglomerate = conglomerate
    inv.maturity_date = date.today() + timedelta(days=days_to_maturity)
    return inv


class TestVisibleInvestmentsFilter:
    def _make_self(self, investments: list, *, hide_matured: bool = False,
                   filter_issuer: str | None = None,
                   filter_conglomerate: str | None = None) -> MagicMock:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._investments = investments
        self_mock._hide_matured = hide_matured
        self_mock._filter_issuer = filter_issuer
        self_mock._filter_conglomerate = filter_conglomerate
        return self_mock

    def test_no_filters_returns_all_sorted_by_maturity(self) -> None:
        inv_a = _make_inv("Bank A", "Group A", 60)
        inv_b = _make_inv("Bank B", "Group B", 30)
        self_mock = self._make_self([inv_a, inv_b])

        result = MainWindow.visible_investments(self_mock)

        assert result == [inv_b, inv_a]

    def test_filter_issuer_excludes_non_matching(self) -> None:
        inv_a = _make_inv("Bank A", "Group A", 30)
        inv_b = _make_inv("Bank B", "Group B", 60)
        self_mock = self._make_self([inv_a, inv_b], filter_issuer="Bank A")

        result = MainWindow.visible_investments(self_mock)

        assert result == [inv_a]

    def test_filter_conglomerate_excludes_non_matching(self) -> None:
        inv_a = _make_inv("Bank A", "Group A", 30)
        inv_b = _make_inv("Bank B", "Group A", 60)
        inv_c = _make_inv("Bank C", "Group B", 45)
        self_mock = self._make_self([inv_a, inv_b, inv_c], filter_conglomerate="Group A")

        result = MainWindow.visible_investments(self_mock)

        assert result == [inv_a, inv_b]

    def test_issuer_and_conglomerate_filters_are_anded(self) -> None:
        inv_a = _make_inv("Bank A", "Group A", 30)
        inv_b = _make_inv("Bank B", "Group A", 60)
        self_mock = self._make_self([inv_a, inv_b],
                                    filter_issuer="Bank A", filter_conglomerate="Group A")

        result = MainWindow.visible_investments(self_mock)

        assert result == [inv_a]

    def test_hide_matured_excludes_past_maturity(self) -> None:
        active = _make_inv("Bank A", "Group A", 30)
        matured = _make_inv("Bank B", "Group B", -1)
        self_mock = self._make_self([active, matured], hide_matured=True)

        result = MainWindow.visible_investments(self_mock)

        assert result == [active]

    def test_filter_issuer_none_does_not_filter(self) -> None:
        inv_a = _make_inv("Bank A", "Group A", 10)
        inv_b = _make_inv("Bank B", "Group B", 20)
        self_mock = self._make_self([inv_a, inv_b], filter_issuer=None)

        result = MainWindow.visible_investments(self_mock)

        assert result == [inv_a, inv_b]

    def test_result_sorted_ascending_by_maturity_date(self) -> None:
        inv_c = _make_inv("Bank C", "Group C", 90)
        inv_a = _make_inv("Bank A", "Group A", 10)
        inv_b = _make_inv("Bank B", "Group B", 50)
        self_mock = self._make_self([inv_c, inv_a, inv_b])

        result = MainWindow.visible_investments(self_mock)

        assert result == [inv_a, inv_b, inv_c]


class TestFilterHandlers:
    def test_issuer_handler_sets_filter_and_calls_refresh(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._filter_issuer = None

        MainWindow._on_issuer_filter_changed(self_mock, "Bank A")

        assert self_mock._filter_issuer == "Bank A"
        self_mock.refresh_table.assert_called_once_with()

    def test_issuer_handler_clears_filter_on_all(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._filter_issuer = "Bank A"

        MainWindow._on_issuer_filter_changed(self_mock, "All")

        assert self_mock._filter_issuer is None
        self_mock.refresh_table.assert_called_once_with()

    def test_conglomerate_handler_sets_filter_and_calls_refresh(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._filter_conglomerate = None

        MainWindow._on_conglomerate_filter_changed(self_mock, "Group A")

        assert self_mock._filter_conglomerate == "Group A"
        self_mock.refresh_table.assert_called_once_with()

    def test_conglomerate_handler_clears_filter_on_all(self) -> None:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._filter_conglomerate = "Group A"

        MainWindow._on_conglomerate_filter_changed(self_mock, "All")

        assert self_mock._filter_conglomerate is None
        self_mock.refresh_table.assert_called_once_with()


# ── compute_totals helpers ────────────────────────────────────────────────────

def _brl(amount: str) -> Money:
    return Money(Decimal(amount), "BRL")


def _make_investment(principal: Money) -> MagicMock:
    inv = MagicMock()
    inv.id = uuid.uuid4()
    inv.principal = principal
    return inv


def _make_projection(inv: MagicMock, current: Money, gross: Money) -> MagicMock:
    proj = MagicMock()
    proj.investment.id = inv.id
    proj.current_value = current
    proj.gross_at_maturity = gross
    return proj


class TestComputeTotals:
    def test_empty_investments_no_cache(self) -> None:
        result = compute_totals([], None)

        assert result["principal_total"] == Money.zero()
        assert result["current_value_total"] is None
        assert result["projected_total"] is None
        assert result["row_count"] == 0

    def test_empty_investments_with_cache(self) -> None:
        some_proj = MagicMock()
        result = compute_totals([], [some_proj])

        assert result["principal_total"] == Money.zero()
        assert result["current_value_total"] == Money.zero()
        assert result["projected_total"] == Money.zero()
        assert result["row_count"] == 0

    def test_investments_no_cache_returns_principal_only(self) -> None:
        inv_a = _make_investment(_brl("100.00"))
        inv_b = _make_investment(_brl("250.00"))

        result = compute_totals([inv_a, inv_b], None)

        assert result["principal_total"] == _brl("350.00")
        assert result["current_value_total"] is None
        assert result["projected_total"] is None
        assert result["row_count"] == 2

    def test_all_investments_in_cache_sums_projections(self) -> None:
        inv_a = _make_investment(_brl("100.00"))
        inv_b = _make_investment(_brl("250.00"))
        proj_a = _make_projection(inv_a, _brl("110.00"), _brl("130.00"))
        proj_b = _make_projection(inv_b, _brl("260.00"), _brl("300.00"))

        result = compute_totals([inv_a, inv_b], [proj_a, proj_b])

        assert result["principal_total"] == _brl("350.00")
        assert result["current_value_total"] == _brl("370.00")
        assert result["projected_total"] == _brl("430.00")
        assert result["row_count"] == 2

    def test_partial_cache_returns_none_for_projected(self) -> None:
        inv_a = _make_investment(_brl("100.00"))
        inv_b = _make_investment(_brl("250.00"))
        proj_a = _make_projection(inv_a, _brl("110.00"), _brl("130.00"))

        result = compute_totals([inv_a, inv_b], [proj_a])

        assert result["principal_total"] == _brl("350.00")
        assert result["current_value_total"] is None
        assert result["projected_total"] is None
        assert result["row_count"] == 2


class TestUpdateTotals:
    def _make_self_mock(self) -> MagicMock:
        self_mock = MagicMock(spec=MainWindow)
        self_mock._filter_issuer = None
        self_mock._filter_conglomerate = None
        self_mock.projection_cache = None
        self_mock._principal_label = MagicMock()
        self_mock._current_label = MagicMock()
        self_mock._projected_label = MagicMock()
        self_mock._rows_label = MagicMock()
        return self_mock

    def test_update_totals_with_full_cache(self) -> None:
        self_mock = self._make_self_mock()
        fake_inv = MagicMock()
        self_mock.visible_investments.return_value = [fake_inv, fake_inv]

        totals = {
            "principal_total": _brl("350.00"),
            "current_value_total": _brl("370.00"),
            "projected_total": _brl("430.00"),
            "row_count": 2,
        }
        with patch("justfixed.ui.main.compute_totals", return_value=totals):
            MainWindow._update_totals(self_mock)

        self_mock._principal_label.setText.assert_called_once_with("Principal: R$ 350,00")
        self_mock._current_label.setText.assert_called_once_with("Current: R$ 370,00")
        self_mock._projected_label.setText.assert_called_once_with("Projected: R$ 430,00")
        self_mock._rows_label.setText.assert_called_once_with("Rows: 2")

    def test_update_totals_no_cache_shows_dash_for_projected(self) -> None:
        self_mock = self._make_self_mock()
        fake_inv = MagicMock()
        self_mock.visible_investments.return_value = [fake_inv]

        totals = {
            "principal_total": _brl("100.00"),
            "current_value_total": None,
            "projected_total": None,
            "row_count": 1,
        }
        with patch("justfixed.ui.main.compute_totals", return_value=totals):
            MainWindow._update_totals(self_mock)

        self_mock._principal_label.setText.assert_called_once_with("Principal: R$ 100,00")
        self_mock._current_label.setText.assert_called_once_with("Current: —")
        self_mock._projected_label.setText.assert_called_once_with("Projected: —")
        self_mock._rows_label.setText.assert_called_once_with("Rows: 1")

    def test_update_totals_with_filter_shows_m_of_n(self) -> None:
        self_mock = self._make_self_mock()
        self_mock._filter_issuer = "BMG"

        def visible_side_effect(*, apply_filter: bool = True):
            return [MagicMock()] if apply_filter else [MagicMock(), MagicMock(), MagicMock()]

        self_mock.visible_investments.side_effect = visible_side_effect

        totals = {
            "principal_total": _brl("100.00"),
            "current_value_total": None,
            "projected_total": None,
            "row_count": 1,
        }
        with patch("justfixed.ui.main.compute_totals", return_value=totals):
            MainWindow._update_totals(self_mock)

        self_mock._rows_label.setText.assert_called_once_with("Rows: 1 of 3")


# ── Integration test helpers ──────────────────────────────────────────────────

def _make_integration_projection(inv: MagicMock, current: Money, gross: Money) -> MagicMock:
    proj = MagicMock()
    proj.investment = inv         # same Python reference — mutations propagate
    proj.as_of = date.today()    # real date required by fgc_concentration_report_from_projections
    proj.current_value = current
    proj.gross_at_maturity = gross
    return proj


def _make_integration_self_mock(
    investments: list,
    projection_cache: list | None = None,
    filter_issuer: str | None = None,
    filter_conglomerate: str | None = None,
) -> MagicMock:
    self_mock = MagicMock(spec=MainWindow)

    self_mock._investments = investments
    self_mock._hide_matured = False
    self_mock._filter_issuer = filter_issuer
    self_mock._filter_conglomerate = filter_conglomerate
    self_mock._has_projected = False
    self_mock.projection_cache = projection_cache
    self_mock._highlight_timer = None
    self_mock._worker = None

    self_mock._table = MagicMock()
    self_mock._stack = MagicMock()
    self_mock._issuer_combo = MagicMock()
    self_mock._conglomerate_combo = MagicMock()
    self_mock._principal_label = MagicMock()
    self_mock._current_label = MagicMock()
    self_mock._projected_label = MagicMock()
    self_mock._rows_label = MagicMock()

    self_mock._repo = MagicMock()
    self_mock._repo.list_all.return_value = investments

    self_mock.visible_investments.side_effect = (
        lambda *, apply_filter=True:
        MainWindow.visible_investments(self_mock, apply_filter=apply_filter)
    )
    self_mock._update_totals.side_effect = (
        lambda: MainWindow._update_totals(self_mock)
    )
    self_mock._populate_filter_dropdowns.side_effect = (
        lambda: MainWindow._populate_filter_dropdowns(self_mock)
    )
    self_mock.refresh_table.side_effect = (
        lambda highlight_issuer_id=None:
        MainWindow.refresh_table(self_mock, highlight_issuer_id=highlight_issuer_id)
    )

    return self_mock


class TestCurationRoundtripIntegration:
    def test_edit_conglomerate_propagates_through_save_and_refresh(self) -> None:
        inv1 = MagicMock()
        inv1.id = uuid.uuid4()
        inv1.issuer.id = uuid.uuid4()
        inv1.issuer.name = "Bank Alpha"
        inv1.issuer.conglomerate = "[unverified] Bank Alpha"
        inv1.issuer.kind = IssuerKind.COMMERCIAL_BANK
        inv1.maturity_date = date.today() + timedelta(days=30)
        inv1.purchase_date = date.today() - timedelta(days=30)
        inv1.product = MagicMock()
        inv1.principal = _brl("10000.00")

        inv2 = MagicMock()
        inv2.id = uuid.uuid4()
        inv2.issuer.id = uuid.uuid4()
        inv2.issuer.name = "Bank Alpha"
        inv2.issuer.conglomerate = "[unverified] Bank Alpha"
        inv2.issuer.kind = IssuerKind.COMMERCIAL_BANK
        inv2.maturity_date = date.today() + timedelta(days=60)
        inv2.purchase_date = date.today() - timedelta(days=60)
        inv2.product = MagicMock()
        inv2.principal = _brl("5000.00")

        proj1 = _make_integration_projection(inv1, _brl("10500.00"), _brl("11000.00"))
        proj2 = _make_integration_projection(inv2, _brl("5200.00"), _brl("5500.00"))

        investments = [inv1, inv2]
        self_mock = _make_integration_self_mock(investments, projection_cache=[proj1, proj2])

        # Phase 1 — baseline refresh
        MainWindow.refresh_table(self_mock)

        calls = self_mock._populate_row.call_args_list
        assert len(calls) == 2
        assert calls[0].kwargs["fgc_status"] == ExposureStatus.UNDER
        assert calls[1].kwargs["fgc_status"] == ExposureStatus.UNDER

        expected_principal = inv1.principal + inv2.principal
        self_mock._principal_label.setText.assert_called_with(
            f"Principal: {expected_principal.to_display()}"
        )

        # Phase 2 — delegate save
        delegate = ConglomerateEditDelegate(self_mock, MagicMock())
        editor = MagicMock()
        editor.text.return_value = "Alpha Banking Group"
        index = MagicMock()
        index.row.return_value = 0  # inv1 comes first (shorter maturity)

        with patch("justfixed.ui.main.IssuerRepository") as MockIssuerRepo, \
             patch("justfixed.ui.main.CurationMemoryRepository") as MockCurationRepo:
            delegate.setModelData(editor, MagicMock(), index)

        MockIssuerRepo.return_value.save.assert_called_once_with(inv1.issuer)
        MockCurationRepo.return_value.set.assert_called_once()
        assert inv1.issuer.conglomerate == "Alpha Banking Group"
        self_mock.trigger_conglomerate_highlight.assert_called_once_with(inv1.issuer.id)

        # Phase 3 — post-edit refresh: mutation propagates through projection cache
        self_mock._populate_row.reset_mock()
        self_mock._principal_label.reset_mock()

        MainWindow.refresh_table(self_mock)

        calls = self_mock._populate_row.call_args_list
        assert len(calls) == 2
        # FGC now groups inv1 under "Alpha Banking Group" via the shared reference;
        # exposure amounts unchanged, both conglomerates remain UNDER
        assert calls[0].kwargs["fgc_status"] == ExposureStatus.UNDER
        assert calls[1].kwargs["fgc_status"] == ExposureStatus.UNDER

        self_mock._principal_label.setText.assert_called_with(
            f"Principal: {expected_principal.to_display()}"
        )


class TestFilterTotalsIntegration:
    def test_filter_narrows_visible_and_totals_with_cache(self) -> None:
        inv1 = MagicMock()
        inv1.id = uuid.uuid4()
        inv1.issuer.name = "Bank A"
        inv1.issuer.conglomerate = "Group X"
        inv1.issuer.kind = IssuerKind.COMMERCIAL_BANK
        inv1.maturity_date = date.today() + timedelta(days=10)
        inv1.purchase_date = date.today() - timedelta(days=10)
        inv1.product = MagicMock()
        inv1.principal = _brl("10000.00")

        inv2 = MagicMock()
        inv2.id = uuid.uuid4()
        inv2.issuer.name = "Bank A"
        inv2.issuer.conglomerate = "Group Y"
        inv2.issuer.kind = IssuerKind.COMMERCIAL_BANK
        inv2.maturity_date = date.today() + timedelta(days=20)
        inv2.purchase_date = date.today() - timedelta(days=20)
        inv2.product = MagicMock()
        inv2.principal = _brl("15000.00")

        inv3 = MagicMock()
        inv3.id = uuid.uuid4()
        inv3.issuer.name = "Bank B"
        inv3.issuer.conglomerate = "Group X"
        inv3.issuer.kind = IssuerKind.COMMERCIAL_BANK
        inv3.maturity_date = date.today() + timedelta(days=30)
        inv3.purchase_date = date.today() - timedelta(days=30)
        inv3.product = MagicMock()
        inv3.principal = _brl("20000.00")

        inv4 = MagicMock()
        inv4.id = uuid.uuid4()
        inv4.issuer.name = "Bank B"
        inv4.issuer.conglomerate = "Group Y"
        inv4.issuer.kind = IssuerKind.COMMERCIAL_BANK
        inv4.maturity_date = date.today() + timedelta(days=40)
        inv4.purchase_date = date.today() - timedelta(days=40)
        inv4.product = MagicMock()
        inv4.principal = _brl("25000.00")

        proj1 = _make_integration_projection(inv1, _brl("10100.00"), _brl("10500.00"))
        proj2 = _make_integration_projection(inv2, _brl("15200.00"), _brl("15800.00"))
        proj3 = _make_integration_projection(inv3, _brl("20300.00"), _brl("21000.00"))
        proj4 = _make_integration_projection(inv4, _brl("25400.00"), _brl("26000.00"))

        investments = [inv1, inv2, inv3, inv4]
        self_mock = _make_integration_self_mock(
            investments, projection_cache=[proj1, proj2, proj3, proj4]
        )

        # Phase 1 — baseline: all four investments visible
        MainWindow.refresh_table(self_mock)

        assert self_mock._populate_row.call_count == 4
        expected_all_principal = (
            inv1.principal + inv2.principal + inv3.principal + inv4.principal
        )
        expected_all_current = (
            proj1.current_value + proj2.current_value
            + proj3.current_value + proj4.current_value
        )
        self_mock._principal_label.setText.assert_called_with(
            f"Principal: {expected_all_principal.to_display()}"
        )
        self_mock._current_label.setText.assert_called_with(
            f"Current: {expected_all_current.to_display()}"
        )
        self_mock._rows_label.setText.assert_called_with("Rows: 4")

        # Phase 2 — issuer filter: Bank A only (inv1 + inv2)
        self_mock._populate_row.reset_mock()
        self_mock._principal_label.reset_mock()
        self_mock._current_label.reset_mock()
        self_mock._rows_label.reset_mock()

        MainWindow._on_issuer_filter_changed(self_mock, "Bank A")

        assert self_mock._populate_row.call_count == 2
        expected_bank_a_principal = inv1.principal + inv2.principal
        expected_bank_a_current = proj1.current_value + proj2.current_value
        self_mock._principal_label.setText.assert_called_with(
            f"Principal: {expected_bank_a_principal.to_display()}"
        )
        self_mock._current_label.setText.assert_called_with(
            f"Current: {expected_bank_a_current.to_display()}"
        )
        self_mock._rows_label.setText.assert_called_with("Rows: 2 of 4")

        # Phase 3 — AND conglomerate filter: Bank A ∩ Group X = inv1 only
        self_mock._populate_row.reset_mock()
        self_mock._principal_label.reset_mock()
        self_mock._current_label.reset_mock()
        self_mock._rows_label.reset_mock()

        MainWindow._on_conglomerate_filter_changed(self_mock, "Group X")

        assert self_mock._populate_row.call_count == 1
        self_mock._principal_label.setText.assert_called_with(
            f"Principal: {inv1.principal.to_display()}"
        )
        self_mock._current_label.setText.assert_called_with(
            f"Current: {proj1.current_value.to_display()}"
        )
        self_mock._rows_label.setText.assert_called_with("Rows: 1 of 4")

        # Phase 4 — clear issuer filter; conglomerate "Group X" still active
        # visible = inv1 (Bank A, Group X) + inv3 (Bank B, Group X) = 2
        self_mock._populate_row.reset_mock()
        self_mock._rows_label.reset_mock()

        MainWindow._on_issuer_filter_changed(self_mock, "All")

        assert self_mock._populate_row.call_count == 2
        self_mock._rows_label.setText.assert_called_with("Rows: 2 of 4")

        # Phase 5 — clear conglomerate filter; both filters None, all four visible
        self_mock._populate_row.reset_mock()
        self_mock._rows_label.reset_mock()

        MainWindow._on_conglomerate_filter_changed(self_mock, "All")

        assert self_mock._populate_row.call_count == 4
        self_mock._rows_label.setText.assert_called_with("Rows: 4")
