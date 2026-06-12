"""Tests for the SQLite migration runner (B42)."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from justfixed.persistence.database import Base
from justfixed.persistence.migrations import run_migrations


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fresh_engine():
    """In-memory SQLite engine with a shared connection (required for in-memory DBs)."""
    return create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _user_version(engine) -> int:
    with engine.connect() as conn:
        return conn.execute(text("PRAGMA user_version")).scalar()


def _col_names(engine, table: str) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {row[1] for row in rows}


# Legacy investments table schema — identical to what was on disk before B42,
# i.e. without the custodian column. We create it directly via raw SQL so we
# don't need a legacy ORM model.
_LEGACY_INVESTMENTS_DDL = """
CREATE TABLE investments (
    id TEXT PRIMARY KEY,
    product TEXT NOT NULL,
    issuer_id TEXT NOT NULL,
    principal_amount NUMERIC NOT NULL,
    principal_currency TEXT NOT NULL DEFAULT 'BRL',
    rate_kind TEXT NOT NULL,
    rate_value NUMERIC NOT NULL,
    purchase_date TEXT NOT NULL,
    maturity_date TEXT NOT NULL,
    issue_date TEXT NOT NULL,
    coupon_frequency TEXT NOT NULL DEFAULT 'none',
    description TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'xp_import',
    created_at TEXT,
    updated_at TEXT
)
"""


def _insert_row(conn, source: str) -> str:
    """Insert a minimal investment row; returns the row id."""
    row_id = str(uuid.uuid4())
    conn.execute(
        text(
            "INSERT INTO investments"
            " (id, product, issuer_id, principal_amount, principal_currency,"
            "  rate_kind, rate_value, purchase_date, maturity_date, issue_date,"
            "  coupon_frequency, description, source)"
            " VALUES (:id, 'cdb', :iid, 10000, 'BRL',"
            "  'post_fixed_cdi', 1.10, '2024-01-15', '2026-01-15', '2024-01-15',"
            "  'none', '', :src)"
        ),
        {"id": row_id, "iid": str(uuid.uuid4()), "src": source},
    )
    return row_id


# ---------------------------------------------------------------------------
# Test: fresh DB created by create_all (already has custodian column)
# ---------------------------------------------------------------------------


class TestFreshDb:
    def test_run_migrations_on_fresh_db(self) -> None:
        engine = _make_fresh_engine()
        Base.metadata.create_all(engine)
        # Sanity: column already present from model, version starts at 0.
        assert "custodian" in _col_names(engine, "investments")
        assert _user_version(engine) == 0

        run_migrations(engine)

        assert _user_version(engine) == 2
        assert "custodian" in _col_names(engine, "investments")

    def test_no_rows_no_error(self) -> None:
        engine = _make_fresh_engine()
        Base.metadata.create_all(engine)
        run_migrations(engine)   # must not raise


# ---------------------------------------------------------------------------
# Test: simulated old DB (no custodian column, mixed sources)
# ---------------------------------------------------------------------------


class TestLegacyDb:
    def _make_legacy_engine_with_rows(self):
        engine = _make_fresh_engine()
        with engine.begin() as conn:
            conn.execute(text(_LEGACY_INVESTMENTS_DDL))
            xp_id   = _insert_row(conn, "xp_import")
            btg_id  = _insert_row(conn, "btg_import")
            bb_id   = _insert_row(conn, "bb_import")
            manual_id = _insert_row(conn, "manual")
        return engine, xp_id, btg_id, bb_id, manual_id

    def test_custodian_column_added(self) -> None:
        engine, *_ = self._make_legacy_engine_with_rows()
        assert "custodian" not in _col_names(engine, "investments")
        run_migrations(engine)
        assert "custodian" in _col_names(engine, "investments")

    def test_user_version_set_to_1(self) -> None:
        engine, *_ = self._make_legacy_engine_with_rows()
        run_migrations(engine)
        assert _user_version(engine) == 2

    def test_xp_import_backfilled(self) -> None:
        engine, xp_id, *_ = self._make_legacy_engine_with_rows()
        run_migrations(engine)
        with engine.connect() as conn:
            val = conn.execute(
                text("SELECT custodian FROM investments WHERE id = :id"),
                {"id": xp_id},
            ).scalar()
        assert val == "XP"

    def test_btg_import_backfilled(self) -> None:
        engine, _, btg_id, *_ = self._make_legacy_engine_with_rows()
        run_migrations(engine)
        with engine.connect() as conn:
            val = conn.execute(
                text("SELECT custodian FROM investments WHERE id = :id"),
                {"id": btg_id},
            ).scalar()
        assert val == "BTG Pactual"

    def test_bb_import_backfilled(self) -> None:
        engine, _, _, bb_id, _ = self._make_legacy_engine_with_rows()
        run_migrations(engine)
        with engine.connect() as conn:
            val = conn.execute(
                text("SELECT custodian FROM investments WHERE id = :id"),
                {"id": bb_id},
            ).scalar()
        assert val == "Banco do Brasil"

    def test_manual_stays_null(self) -> None:
        engine, _, _, _, manual_id = self._make_legacy_engine_with_rows()
        run_migrations(engine)
        with engine.connect() as conn:
            val = conn.execute(
                text("SELECT custodian FROM investments WHERE id = :id"),
                {"id": manual_id},
            ).scalar()
        assert val is None


# ---------------------------------------------------------------------------
# Test: idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_second_call_is_noop(self) -> None:
        engine = _make_fresh_engine()
        Base.metadata.create_all(engine)
        run_migrations(engine)
        assert _user_version(engine) == 2

        # Second call must not raise and version stays 1.
        run_migrations(engine)
        assert _user_version(engine) == 2

    def test_values_unchanged_on_second_call(self) -> None:
        engine = _make_fresh_engine()
        with engine.begin() as conn:
            conn.execute(text(_LEGACY_INVESTMENTS_DDL))
            row_id = _insert_row(conn, "xp_import")

        run_migrations(engine)
        run_migrations(engine)  # idempotent second run

        with engine.connect() as conn:
            val = conn.execute(
                text("SELECT custodian FROM investments WHERE id = :id"),
                {"id": row_id},
            ).scalar()
        assert val == "XP"


# ---------------------------------------------------------------------------
# Test: crash-window recovery (column added, user_version never bumped)
# ---------------------------------------------------------------------------


class TestCrashRecovery:
    def test_rerun_after_column_added_but_version_not_bumped(self) -> None:
        # Simulate a crash: the ALTER applied (column exists) but
        # user_version is still 0. Re-running must NOT raise
        # "duplicate column name" and must complete the backfill.
        engine = _make_fresh_engine()
        with engine.begin() as conn:
            conn.execute(text(_LEGACY_INVESTMENTS_DDL))
            row_id = _insert_row(conn, "xp_import")
            # Partial migration: column added, version left at 0.
            conn.execute(text("ALTER TABLE investments ADD COLUMN custodian VARCHAR"))
        assert _user_version(engine) == 0
        assert "custodian" in _col_names(engine, "investments")

        run_migrations(engine)  # must not raise

        assert _user_version(engine) == 2
        with engine.connect() as conn:
            val = conn.execute(
                text("SELECT custodian FROM investments WHERE id = :id"),
                {"id": row_id},
            ).scalar()
        assert val == "XP"


# ---------------------------------------------------------------------------
# Test: migration 1 → 2 (broker_value columns, B10 Slice 1)
# ---------------------------------------------------------------------------

# Schema after migration 0→1 (has custodian, no broker_value columns).
_V1_INVESTMENTS_DDL = """
CREATE TABLE investments (
    id TEXT PRIMARY KEY,
    product TEXT NOT NULL,
    issuer_id TEXT NOT NULL,
    principal_amount NUMERIC NOT NULL,
    principal_currency TEXT NOT NULL DEFAULT 'BRL',
    rate_kind TEXT NOT NULL,
    rate_value NUMERIC NOT NULL,
    purchase_date TEXT NOT NULL,
    maturity_date TEXT NOT NULL,
    issue_date TEXT NOT NULL,
    coupon_frequency TEXT NOT NULL DEFAULT 'none',
    description TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'xp_import',
    custodian VARCHAR,
    created_at TEXT,
    updated_at TEXT
)
"""


def _make_v1_engine():
    """Engine with an investments table at version-1 schema (no broker_value cols)."""
    engine = _make_fresh_engine()
    with engine.begin() as conn:
        conn.execute(text(_V1_INVESTMENTS_DDL))
        _insert_row(conn, "xp_import")
        conn.execute(text("PRAGMA user_version = 1"))
    return engine


class TestMigration1To2:
    def test_broker_value_columns_added(self) -> None:
        engine = _make_v1_engine()
        assert "broker_value_amount" not in _col_names(engine, "investments")
        assert "broker_value_currency" not in _col_names(engine, "investments")
        run_migrations(engine)
        assert "broker_value_amount" in _col_names(engine, "investments")
        assert "broker_value_currency" in _col_names(engine, "investments")

    def test_user_version_set_to_2(self) -> None:
        engine = _make_v1_engine()
        run_migrations(engine)
        assert _user_version(engine) == 2

    def test_pre_existing_rows_get_null_broker_value(self) -> None:
        engine = _make_v1_engine()
        run_migrations(engine)
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT broker_value_amount, broker_value_currency FROM investments")
            ).fetchall()
        assert all(r[0] is None and r[1] is None for r in rows)

    def test_idempotent_on_rerun(self) -> None:
        engine = _make_v1_engine()
        run_migrations(engine)
        # Second call must not raise and version stays at 2.
        run_migrations(engine)
        assert _user_version(engine) == 2
