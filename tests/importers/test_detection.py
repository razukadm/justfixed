"""Tests for broker detection and unified statement dispatch."""

from __future__ import annotations

from pathlib import Path

import openpyxl
import pytest

from justfixed.importers.detection import Broker, detect_broker, load_statement
from justfixed.importers.xp_loader import LoadResult
from justfixed.persistence.database import Base, make_engine, make_session_factory


FIXTURES = Path(__file__).parent / "fixtures"
XP_FIXTURE  = FIXTURES / "synthetic_xp_statement.xlsx"
BTG_FIXTURE = FIXTURES / "synthetic_btg_statement.xlsx"


# ---------- Fixtures ----------


@pytest.fixture
def factory():
    """Fresh in-memory SQLite database per test, with schema created."""
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield make_session_factory(engine)
    engine.dispose()


# ---------- detect_broker ----------


class TestDetectBroker:
    def test_xp_fixture_detected_as_xp(self) -> None:
        assert detect_broker(XP_FIXTURE) == Broker.XP

    def test_btg_fixture_detected_as_btg(self) -> None:
        assert detect_broker(BTG_FIXTURE) == Broker.BTG

    def test_unrecognized_file_raises_value_error(self, tmp_path: Path) -> None:
        unknown = tmp_path / "unknown_statement.xlsx"
        wb = openpyxl.Workbook()
        wb.active.title = "Sheet1"
        wb.save(unknown)

        with pytest.raises(ValueError, match="unknown_statement.xlsx"):
            detect_broker(unknown)

    def test_unrecognized_error_message_names_sheets(self, tmp_path: Path) -> None:
        unknown = tmp_path / "mystery.xlsx"
        wb = openpyxl.Workbook()
        wb.active.title = "Sheet1"
        wb.save(unknown)

        with pytest.raises(ValueError, match="Sheet1"):
            detect_broker(unknown)

    def test_nonexistent_path_raises_file_not_found(self, tmp_path: Path) -> None:
        missing = tmp_path / "does_not_exist.xlsx"
        with pytest.raises(FileNotFoundError):
            detect_broker(missing)

    def test_ambiguous_file_raises_value_error(self, tmp_path: Path) -> None:
        ambiguous = tmp_path / "ambiguous.xlsx"
        wb = openpyxl.Workbook()
        wb.active.title = "Sua carteira"
        wb.create_sheet("Renda Fixa")
        wb.save(ambiguous)

        with pytest.raises(ValueError, match="Ambiguous"):
            detect_broker(ambiguous)


# ---------- load_statement ----------


class TestLoadStatement:
    def test_xp_fixture_returns_xp_broker_and_load_result(
        self, factory
    ) -> None:
        broker, result = load_statement(XP_FIXTURE, factory)

        assert broker == Broker.XP
        assert isinstance(result, LoadResult)
        assert result.inserted >= 1
        assert result.skipped == 0

    def test_btg_fixture_returns_btg_broker_and_load_result(
        self, factory
    ) -> None:
        broker, result = load_statement(BTG_FIXTURE, factory)

        assert broker == Broker.BTG
        assert isinstance(result, LoadResult)
        assert result.inserted == 2
        assert result.skipped == 0

    def test_xp_load_statement_is_idempotent(self, factory) -> None:
        load_statement(XP_FIXTURE, factory)
        broker, result = load_statement(XP_FIXTURE, factory)

        assert broker == Broker.XP
        assert result.inserted == 0
        assert result.skipped >= 1

    def test_btg_load_statement_is_idempotent(self, factory) -> None:
        load_statement(BTG_FIXTURE, factory)
        broker, result = load_statement(BTG_FIXTURE, factory)

        assert broker == Broker.BTG
        assert result.inserted == 0
        assert result.skipped == 2
