"""Tests for the BB LCA statement loader — Layer 3 (bb_loader.py).

Fixture: synthetic_bb_statement.txt (9 rows: 5 active, 4 matured).
  Active rows (saldo > 0): indices 0-3 and 8.
  Matured rows (saldo "0,00"): indices 4-7.
  All rows issued by: "Banco do Brasil S/A".

Expected first-load counts (hand-verified):
  inserted        = 5  (4 active among first 4 + 1 at index 8)
  skipped         = 4  (4 matured)
  skipped_matured = 4
  issuers_created = 1  (created on first active row)
  issuers_reused  = 4  (reused for active rows 1-3 and 8)

Expected second-load counts (idempotency):
  inserted        = 0
  skipped         = 9  (4 matured + 5 natural-key duplicates)
  skipped_matured = 4  (matured subset unchanged)
  issuers_created = 0
  issuers_reused  = 5  (resolved per active row before idempotency check)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from justfixed.importers.bb_loader import load_bb_statement
from justfixed.importers.loader_types import LoadResult
from justfixed.persistence.database import Base, make_engine, make_session_factory

BB_FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_bb_statement.txt"


@pytest.fixture
def factory():
    """Fresh in-memory SQLite database per test, with schema created."""
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield make_session_factory(engine)
    engine.dispose()


# ── First-load counts ──────────────────────────────────────────────────────────

class TestFirstLoad:
    def test_active_rows_inserted(self, factory):
        result = load_bb_statement(BB_FIXTURE, factory)
        assert result.inserted == 5

    def test_matured_rows_skipped_matured(self, factory):
        result = load_bb_statement(BB_FIXTURE, factory)
        assert result.skipped_matured == 4

    def test_total_skipped_equals_matured_on_first_load(self, factory):
        result = load_bb_statement(BB_FIXTURE, factory)
        assert result.skipped == 4

    def test_issuer_created_once(self, factory):
        result = load_bb_statement(BB_FIXTURE, factory)
        assert result.issuers_created == 1

    def test_issuer_reused_for_remaining_active_rows(self, factory):
        result = load_bb_statement(BB_FIXTURE, factory)
        assert result.issuers_reused == 4

    def test_returns_load_result(self, factory):
        result = load_bb_statement(BB_FIXTURE, factory)
        assert isinstance(result, LoadResult)


# ── Idempotency ────────────────────────────────────────────────────────────────

class TestIdempotency:
    def test_second_load_inserts_nothing(self, factory):
        load_bb_statement(BB_FIXTURE, factory)
        result = load_bb_statement(BB_FIXTURE, factory)
        assert result.inserted == 0

    def test_second_load_skipped_includes_duplicates_and_matured(self, factory):
        """skipped = 4 matured + 5 natural-key duplicates = 9."""
        load_bb_statement(BB_FIXTURE, factory)
        result = load_bb_statement(BB_FIXTURE, factory)
        assert result.skipped == 9

    def test_second_load_skipped_matured_unchanged(self, factory):
        """Matured-row count is stable regardless of prior loads."""
        load_bb_statement(BB_FIXTURE, factory)
        result = load_bb_statement(BB_FIXTURE, factory)
        assert result.skipped_matured == 4

    def test_duplicates_not_counted_in_skipped_matured(self, factory):
        """Natural-key duplicates land in skipped only, not skipped_matured."""
        load_bb_statement(BB_FIXTURE, factory)
        result = load_bb_statement(BB_FIXTURE, factory)
        duplicate_count = result.skipped - result.skipped_matured
        assert duplicate_count == 5

    def test_second_load_issuer_all_reused(self, factory):
        load_bb_statement(BB_FIXTURE, factory)
        result = load_bb_statement(BB_FIXTURE, factory)
        assert result.issuers_created == 0
        assert result.issuers_reused == 5


# ── Error propagation ──────────────────────────────────────────────────────────

class TestErrorPropagation:
    def test_active_row_domain_error_raises(self, factory):
        """ValueError from Investment.create on an active row must propagate."""
        with patch("justfixed.importers.bb_loader.Investment.create") as mock_create:
            mock_create.side_effect = ValueError("maturity_date must be after purchase_date")
            with pytest.raises(ValueError, match="maturity_date"):
                load_bb_statement(BB_FIXTURE, factory)

    def test_file_not_found_raises(self):
        engine = make_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        factory = make_session_factory(engine)
        with pytest.raises(FileNotFoundError):
            load_bb_statement(Path("nonexistent_bb.txt"), factory)
        engine.dispose()

    def test_missing_lca_section_raises_clear_message(self, tmp_path, factory):
        """A BB .txt without the LCA section raises with a helpful message."""
        bad_txt = tmp_path / "bb_no_lca.txt"
        bad_txt.write_text(
            "SISBB - Sistema de Informações Banco do Brasil\n\nNo LCA section here.\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="not yet supported"):
            load_bb_statement(bad_txt, factory)
