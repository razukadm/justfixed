"""Tests for InvestmentDetailPanel widget and _EditableField.

Uses a session-scoped QApplication so Qt objects can be instantiated
without a running event loop. Investment data is mocked or real domain
objects as needed; no real database or window is created.
"""

from __future__ import annotations

import sys
import types
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QDate, QEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from justfixed.domain.investment import Investment, InvestmentSource
from justfixed.domain.issuer import Issuer, IssuerKind
from justfixed.domain.money import Money
from justfixed.domain.product import CouponFrequency, ProductType
from justfixed.domain.rates import PostFixedCDI, PostFixedCDIPlusSpread, PostFixedIPCA, Prefixed
from justfixed.ui.main import InvestmentDetailPanel, _EditableField, _RateEditor


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


def _mock_inv(**overrides):
    """Minimal mock investment with all fields show_investment() reads.

    The issuer is a SimpleNamespace so .name and .conglomerate are plain
    attributes with no Mock magic (avoids the Mock.name footgun).
    """
    inv = MagicMock()
    inv.issuer = types.SimpleNamespace(
        name="Banco Inter",
        conglomerate="Banco Inter S.A.",
    )
    inv.product = ProductType.CDB
    inv.principal.to_display.return_value = "R$ 10.000,00"
    inv.rate.to_display.return_value = "112,00% do CDI"
    inv.purchase_date = date(2024, 1, 15)
    inv.issue_date = date(2024, 1, 15)
    inv.maturity_date = date(2026, 1, 15)
    inv.coupon_frequency = CouponFrequency.NONE
    inv.description = ""
    inv.source = InvestmentSource.XP_IMPORT
    for k, v in overrides.items():
        setattr(inv, k, v)
    return inv


class TestInvestmentDetailPanelConstruction:
    def test_instantiates_without_error(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        assert panel is not None


class TestInvestmentDetailPanelShowInvestment:
    def test_show_investment_updates_identity_label(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        panel.show_investment(_mock_inv())
        text = panel._identity_label.text()
        assert "Banco Inter" in text
        assert "CDB" in text

    def test_clear_resets_identity_label(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        panel.show_investment(_mock_inv())
        panel.clear()
        assert panel._identity_label.text() == "No investment selected."


class TestInvestmentDetailPanelCloseSignal:
    def test_close_button_emits_closed_signal(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        slot = MagicMock()
        panel.closed.connect(slot)
        panel._close_btn.click()
        slot.assert_called_once()


class TestInvestmentDetailPanelFieldDisplay:
    def test_issuer_and_product_populated(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        panel.show_investment(_mock_inv())
        assert panel._field_values["issuer"].text() == "Banco Inter"
        assert "CDB" in panel._field_values["product"].text()

    def test_principal_and_rate_populated(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        panel.show_investment(_mock_inv())
        assert panel._field_values["principal"].text() == "R$ 10.000,00"
        assert panel._field_values["rate"].text() == "112,00% do CDI"

    def test_description_shows_dash_when_empty(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        panel.show_investment(_mock_inv(description=""))
        assert panel._field_values["description"].text() == "—"

    def test_description_shows_text_when_set(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        panel.show_investment(_mock_inv(description="Some note"))
        assert panel._field_values["description"].text() == "Some note"

    def test_clear_empties_field_values(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        panel.show_investment(_mock_inv())
        panel.clear()
        assert panel._field_values["issuer"].text() == ""


class TestInvestmentDetailPanelSourceBanner:
    def test_xp_import_banner_visible(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        panel.show_investment(_mock_inv(source=InvestmentSource.XP_IMPORT))
        assert not panel._source_banner.isHidden()

    def test_btg_import_banner_visible(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        panel.show_investment(_mock_inv(source=InvestmentSource.BTG_IMPORT))
        assert not panel._source_banner.isHidden()

    def test_manual_banner_hidden(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        panel.show_investment(_mock_inv(source=InvestmentSource.MANUAL))
        assert panel._source_banner.isHidden()

    def test_clear_hides_banner(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        panel.show_investment(_mock_inv())
        panel.clear()
        assert panel._source_banner.isHidden()

    def test_import_banner_text_is_broker_agnostic(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        panel.show_investment(_mock_inv(source=InvestmentSource.XP_IMPORT))
        assert "XP" not in panel._source_banner.text()
        assert "Imported" in panel._source_banner.text()


# ── Helpers for real-Investment tests ─────────────────────────────────────────

def _make_real_inv(source: InvestmentSource = InvestmentSource.MANUAL, **overrides) -> Investment:
    """Create a minimal valid Investment domain object for save-path tests."""
    issuer = Issuer(
        name="Banco Inter",
        conglomerate="Banco Inter S.A.",
        kind=IssuerKind.COMMERCIAL_BANK,
    )
    defaults: dict = {
        "product": ProductType.CDB,
        "issuer": issuer,
        "principal": Money.from_reais("10000.00"),
        "rate": PostFixedCDI.from_percent("112"),
        "purchase_date": date(2024, 1, 15),
        "maturity_date": date(2026, 1, 15),
        "issue_date": date(2024, 1, 15),
        "coupon_frequency": CouponFrequency.NONE,
        "description": "",
        "source": source,
    }
    defaults.update(overrides)
    return Investment(**defaults)


# ── _EditableField tests ───────────────────────────────────────────────────────

class TestEditableField:
    def test_non_editable_event_filter_returns_false(self, qapp) -> None:
        field = _EditableField("description", MagicMock(), MagicMock())
        field.set_value("", "—", editable=False)
        event = MagicMock()
        event.type.return_value = QEvent.Type.MouseButtonDblClick
        assert field.eventFilter(field._label, event) is False

    def test_editable_double_click_event_filter_returns_true(self, qapp) -> None:
        field = _EditableField("description", MagicMock(), MagicMock())
        field.set_value("", "—", editable=True)
        event = MagicMock()
        event.type.return_value = QEvent.Type.MouseButtonDblClick
        assert field.eventFilter(field._label, event) is True

    def test_text_returns_label_text(self, qapp) -> None:
        field = _EditableField("description", MagicMock(), MagicMock())
        field.set_value("hello", "hello display", editable=False)
        assert field.text() == "hello display"

    def test_set_value_reverts_to_view_mode(self, qapp) -> None:
        field = _EditableField("description", MagicMock(), MagicMock())
        field.set_value("old", "old text", editable=True)
        field._show_editor()  # enter edit mode
        field.set_value("new", "new text", editable=True)  # should revert
        assert field._stack.currentIndex() == 0  # label visible

    def test_successful_text_commit_updates_label_and_calls_error_fn_with_none(self, qapp) -> None:
        save_fn = MagicMock(return_value="new formatted")
        error_fn = MagicMock()
        field = _EditableField("description", save_fn, error_fn)
        field.set_value("old", "old text", editable=True)
        field._show_editor()
        field._editor.setText("new value")
        field._commit()
        save_fn.assert_called_once_with("description", "new value")
        error_fn.assert_called_with(None)
        assert field.text() == "new formatted"
        assert field._stack.currentIndex() == 0

    def test_failed_extract_calls_error_fn_save_not_called(self, qapp) -> None:
        save_fn = MagicMock()
        error_fn = MagicMock()
        field = _EditableField("principal", save_fn, error_fn)
        field.set_value(Money.from_reais("10000"), "R$ 10.000,00", editable=True)
        field._show_editor()
        field._editor.setText("not a money string")
        field._commit()
        save_fn.assert_not_called()
        error_fn.assert_called_once()
        msg = error_fn.call_args[0][0]
        assert msg is not None

    def test_failed_save_shows_error_label_stays_in_editor(self, qapp) -> None:
        save_fn = MagicMock(side_effect=ValueError("maturity before issue"))
        error_fn = MagicMock()
        field = _EditableField("description", save_fn, error_fn)
        field.set_value("old", "old text", editable=True)
        field._show_editor()
        field._editor.setText("new value")
        field._commit()
        error_fn.assert_called_with("maturity before issue")
        assert field.text() == "old text"
        assert field._stack.currentIndex() == 1  # editor still visible

    def test_date_field_extracts_python_date(self, qapp) -> None:
        save_fn = MagicMock(return_value="15/06/2026")
        field = _EditableField("maturity_date", save_fn, MagicMock())
        field.set_value(date(2026, 1, 15), "15/01/2026", editable=True)
        field._show_editor()
        field._editor.setDate(QDate(2026, 6, 15))
        field._commit()
        typed = save_fn.call_args[0][1]
        assert typed == date(2026, 6, 15)

    def test_combo_field_extracts_coupon_frequency(self, qapp) -> None:
        save_fn = MagicMock(return_value="Mensal")
        field = _EditableField("coupon_frequency", save_fn, MagicMock())
        field.set_value(CouponFrequency.NONE, "Nenhum", editable=True)
        field._show_editor()
        idx = field._editor.findData(CouponFrequency.MONTHLY)
        field._editor.setCurrentIndex(idx)
        field._commit()
        typed = save_fn.call_args[0][1]
        assert typed == CouponFrequency.MONTHLY


# ── Panel save-path tests ──────────────────────────────────────────────────────

class TestInvestmentDetailPanelSave:
    def test_successful_description_edit_saves_and_refreshes(self, qapp) -> None:
        main_window = MagicMock()
        panel = InvestmentDetailPanel(MagicMock(), main_window)
        inv = _make_real_inv()
        panel.show_investment(inv)

        with patch("justfixed.ui.main.InvestmentRepository") as MockRepo:
            panel._save_field("description", "a new note")

        MockRepo.return_value.save.assert_called_once()
        main_window.refresh_table.assert_called_once()
        assert panel._current_inv.description == "a new note"

    def test_invalid_maturity_date_rejected_error_shown_nothing_saved(self, qapp) -> None:
        main_window = MagicMock()
        panel = InvestmentDetailPanel(MagicMock(), main_window)
        inv = _make_real_inv(source=InvestmentSource.MANUAL)
        panel.show_investment(inv)

        maturity_field = panel._field_values["maturity_date"]
        maturity_field._show_editor()
        maturity_field._editor.setDate(QDate(2023, 1, 1))  # before issue_date

        with patch("justfixed.ui.main.InvestmentRepository") as MockRepo:
            maturity_field._commit()

        MockRepo.return_value.save.assert_not_called()
        assert not panel._error_label.isHidden()
        assert panel._error_label.text() != ""

    def test_error_label_hidden_by_default(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        assert panel._error_label.isHidden()

    def test_set_error_shows_message(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        panel._set_error("Something went wrong")
        assert not panel._error_label.isHidden()
        assert "Something went wrong" in panel._error_label.text()

    def test_set_error_none_clears_and_hides(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        panel._set_error("prior error")
        panel._set_error(None)
        assert panel._error_label.isHidden()

    def test_error_cleared_on_row_switch(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        panel._set_error("some error")
        panel.show_investment(_mock_inv())
        assert panel._error_label.isHidden()

    def test_error_cleared_on_clear(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        panel._set_error("some error")
        panel.clear()
        assert panel._error_label.isHidden()

    def test_manual_investment_has_seven_editable_fields(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        inv = _make_real_inv(source=InvestmentSource.MANUAL)
        panel.show_investment(inv)

        expected_editable = {
            "principal", "rate", "purchase_date", "issue_date",
            "maturity_date", "coupon_frequency", "description",
        }
        for key, field in panel._field_values.items():
            if key in expected_editable:
                assert field._editable, f"Expected {key!r} to be editable for MANUAL"
            else:
                assert not field._editable, f"Expected {key!r} to be non-editable for MANUAL"

    def test_xp_import_exposes_only_description(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        inv = _make_real_inv(source=InvestmentSource.XP_IMPORT)
        panel.show_investment(inv)

        for key, field in panel._field_values.items():
            if key == "description":
                assert field._editable, "description should be editable for XP_IMPORT"
            else:
                assert not field._editable, f"{key!r} should not be editable for XP_IMPORT"

    def test_btg_import_exposes_only_description(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        inv = _make_real_inv(source=InvestmentSource.BTG_IMPORT)
        panel.show_investment(inv)

        for key, field in panel._field_values.items():
            if key == "description":
                assert field._editable, "description should be editable for BTG_IMPORT"
            else:
                assert not field._editable, f"{key!r} should not be editable for BTG_IMPORT"

    def test_save_returns_formatted_string(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        inv = _make_real_inv()
        panel.show_investment(inv)

        with patch("justfixed.ui.main.InvestmentRepository"):
            result = panel._save_field("description", "my note")

        assert result == "my note"

    def test_save_empty_description_returns_dash(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        inv = _make_real_inv(description="existing")
        panel.show_investment(inv)

        with patch("justfixed.ui.main.InvestmentRepository"):
            result = panel._save_field("description", "")

        assert result == "—"

    def test_fields_revert_to_label_on_row_switch(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        inv = _make_real_inv(source=InvestmentSource.MANUAL)
        panel.show_investment(inv)

        desc_field = panel._field_values["description"]
        desc_field._show_editor()
        assert desc_field._stack.currentIndex() == 1  # editor active

        panel.show_investment(_make_real_inv())  # row switch
        assert desc_field._stack.currentIndex() == 0  # reverted to label

    # ── Re-entrancy regression tests ───────────────────────────────────────────

    def test_same_id_show_investment_does_not_disturb_field_in_editor_mode(self, qapp) -> None:
        # Regression: refresh_table calls show_investment with the same investment
        # (same id, updated object). The set_value loop must NOT run — it would
        # reset a field that is mid-commit on the call stack.
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        inv = _make_real_inv(source=InvestmentSource.MANUAL)
        panel.show_investment(inv)

        desc_field = panel._field_values["description"]
        desc_field._show_editor()
        assert desc_field._stack.currentIndex() == 1  # editor is open

        # Simulate the re-entrant call: same id, slightly different object
        updated_inv = _make_real_inv(source=InvestmentSource.MANUAL, description="saved")
        # Give it the same UUID so show_investment treats it as a same-id refresh
        import dataclasses
        updated_inv = dataclasses.replace(updated_inv, id=inv.id)

        panel.show_investment(updated_inv)

        # Editor must still be open — the set_value loop was skipped
        assert desc_field._stack.currentIndex() == 1
        # Panel adopts the new object
        assert panel._current_inv.description == "saved"

    def test_save_field_reentrancy_via_refresh_table_leaves_saved_value(self, qapp) -> None:
        # Regression: _save_field calls refresh_table, which (via selectRow →
        # itemSelectionChanged → _on_selection_changed) calls show_investment
        # with the updated investment. Without the same-id guard, show_investment
        # would reset the field mid-commit, clobbering the saved value.
        import dataclasses

        inv = _make_real_inv(source=InvestmentSource.MANUAL)

        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        panel.show_investment(inv)

        desc_field = panel._field_values["description"]
        desc_field._show_editor()
        desc_field._editor.setText("edited note")

        # Capture the distinct mapper-reconstructed instance that fake_refresh_table
        # passes; populated inside the side_effect so we can assert on it after.
        distinct_inv_holder: list = []

        def fake_refresh_table():
            # Mirrors what refresh_table does: passes a mapper-reconstructed
            # instance — same id as _current_inv but a distinct Python object.
            # Using panel._current_inv.id (set by _save_field before this fires)
            # ensures we pin id-equality, not object-identity.
            distinct = dataclasses.replace(
                _make_real_inv(source=InvestmentSource.MANUAL, description="edited note"),
                id=panel._current_inv.id,
            )
            distinct_inv_holder.append(distinct)
            panel.show_investment(distinct)

        panel._main_window.refresh_table.side_effect = fake_refresh_table

        with patch("justfixed.ui.main.InvestmentRepository"):
            desc_field._commit()

        # After commit: label shows the saved description
        assert desc_field.text() == "edited note"
        # Field is back in view mode (commit completed)
        assert desc_field._stack.currentIndex() == 0
        # Panel adopted the distinct mapper-reconstructed instance, not the
        # intermediate object _save_field set — confirms same-id-distinct-object
        # adoption, not a trivial is-identity pass.
        assert panel._current_inv is distinct_inv_holder[0]


# ── Delete tests ─────────────────────────────────────────────────────────────

class TestInvestmentDetailPanelDelete:
    def test_delete_button_exists(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        assert hasattr(panel, "_delete_btn")

    def test_delete_button_disabled_before_investment_shown(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        assert not panel._delete_btn.isEnabled()

    def test_delete_button_enabled_after_show_investment(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        panel.show_investment(_mock_inv())
        assert panel._delete_btn.isEnabled()

    def test_delete_button_disabled_after_clear(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        panel.show_investment(_mock_inv())
        panel.clear()
        assert not panel._delete_btn.isEnabled()

    def test_confirm_calls_repo_delete_and_emits_signal(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        inv = _make_real_inv()
        panel.show_investment(inv)

        deleted_ids: list = []
        panel.investment_deleted.connect(lambda uid: deleted_ids.append(uid))

        with patch("justfixed.ui.main.InvestmentRepository") as MockRepo:
            with patch(
                "justfixed.ui.main.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ):
                panel._on_delete_clicked()

        MockRepo.return_value.delete.assert_called_once_with(inv.id)
        assert deleted_ids == [inv.id]

    def test_cancel_does_nothing(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        inv = _make_real_inv()
        panel.show_investment(inv)

        deleted_ids: list = []
        panel.investment_deleted.connect(lambda uid: deleted_ids.append(uid))

        with patch("justfixed.ui.main.InvestmentRepository") as MockRepo:
            with patch(
                "justfixed.ui.main.QMessageBox.question",
                return_value=QMessageBox.StandardButton.No,
            ):
                panel._on_delete_clicked()

        MockRepo.return_value.delete.assert_not_called()
        assert deleted_ids == []

    def test_no_op_when_no_investment_shown(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())

        with patch("justfixed.ui.main.InvestmentRepository") as MockRepo:
            with patch("justfixed.ui.main.QMessageBox.question") as mock_dlg:
                panel._on_delete_clicked()

        mock_dlg.assert_not_called()
        MockRepo.return_value.delete.assert_not_called()


# ── _RateEditor tests ─────────────────────────────────────────────────────────

class TestRateEditor:
    def test_set_rate_cdi_percent_round_trip(self, qapp) -> None:
        editor = _RateEditor()
        rate = PostFixedCDI.from_percent("112")
        editor.set_rate(rate)
        result = editor.get_rate()
        assert isinstance(result, PostFixedCDI)
        assert result == PostFixedCDI.from_percent("112")

    def test_set_rate_cdi_plus_spread_round_trip(self, qapp) -> None:
        editor = _RateEditor()
        rate = PostFixedCDIPlusSpread.from_percent("2.05")
        editor.set_rate(rate)
        result = editor.get_rate()
        assert isinstance(result, PostFixedCDIPlusSpread)
        assert result == PostFixedCDIPlusSpread.from_percent("2.05")

    def test_set_rate_ipca_plus_round_trip(self, qapp) -> None:
        editor = _RateEditor()
        rate = PostFixedIPCA.from_percent("5.5")
        editor.set_rate(rate)
        result = editor.get_rate()
        assert isinstance(result, PostFixedIPCA)
        assert result == PostFixedIPCA.from_percent("5.5")

    def test_set_rate_prefixed_round_trip(self, qapp) -> None:
        editor = _RateEditor()
        rate = Prefixed.from_percent("12")
        editor.set_rate(rate)
        result = editor.get_rate()
        assert isinstance(result, Prefixed)
        assert result == Prefixed.from_percent("12")

    def test_type_change_cdi_to_prefixed(self, qapp) -> None:
        editor = _RateEditor()
        editor.set_rate(PostFixedCDI.from_percent("112"))
        # Switch combo to Prefixed (index 3)
        idx = editor._combo.findData("prefixed")
        editor._combo.setCurrentIndex(idx)
        result = editor.get_rate()
        assert isinstance(result, Prefixed)
        assert result == Prefixed.from_percent("112")

    def test_comma_decimal_parsed(self, qapp) -> None:
        editor = _RateEditor()
        editor.set_rate(PostFixedCDI.from_percent("112"))
        editor._line.setText("112,50")
        result = editor.get_rate()
        assert isinstance(result, PostFixedCDI)
        assert result == PostFixedCDI.from_percent("112.50")

    def test_dot_decimal_rejected(self, qapp) -> None:
        editor = _RateEditor()
        editor.set_rate(PostFixedCDI.from_percent("112"))
        editor._line.setText("112.50")
        with pytest.raises(ValueError):
            editor.get_rate()

    def test_garbage_raises_value_error(self, qapp) -> None:
        editor = _RateEditor()
        editor.set_rate(PostFixedCDI.from_percent("112"))
        editor._line.setText("abc")
        with pytest.raises(ValueError):
            editor.get_rate()


# ── Panel rate integration tests ──────────────────────────────────────────────

class TestInvestmentDetailPanelRate:
    def test_manual_exposes_rate_as_editable(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        inv = _make_real_inv(source=InvestmentSource.MANUAL)
        panel.show_investment(inv)
        assert panel._field_values["rate"]._editable

    def test_import_does_not_expose_rate(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        inv = _make_real_inv(source=InvestmentSource.XP_IMPORT)
        panel.show_investment(inv)
        assert not panel._field_values["rate"]._editable

    def test_rate_save_updates_panel_label(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        inv = _make_real_inv(source=InvestmentSource.MANUAL)
        panel.show_investment(inv)

        new_rate = PostFixedCDI.from_percent("100")
        with patch("justfixed.ui.main.InvestmentRepository"):
            result = panel._save_field("rate", new_rate)

        assert result == new_rate.to_display()
        assert panel._current_inv.rate == new_rate

    def test_rate_invalid_shows_error(self, qapp) -> None:
        panel = InvestmentDetailPanel(MagicMock(), MagicMock())
        inv = _make_real_inv(source=InvestmentSource.MANUAL)
        panel.show_investment(inv)

        rate_field = panel._field_values["rate"]
        rate_field._show_editor()
        rate_field._editor._line.setText("abc")

        with patch("justfixed.ui.main.InvestmentRepository") as MockRepo:
            rate_field._commit()

        MockRepo.return_value.save.assert_not_called()
        assert not panel._error_label.isHidden()
