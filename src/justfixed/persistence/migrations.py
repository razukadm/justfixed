"""SQLite PRAGMA user_version migration runner.

This is the project's first migration seam. Each version step is a
(target_version, migrate_fn) pair; run_migrations applies them in order,
skipping any step already satisfied by the current user_version.

To add a future migration, append a new (N, _migrate_{N-1}_to_{N}) tuple
to _MIGRATIONS and define the corresponding function.

Crash-safety does NOT rely on transactional DDL — SQLite does not
reliably roll back ALTER TABLE on failure. Instead, each step must be
written to be idempotent under re-run: if the process dies after a
schema change but before `PRAGMA user_version` is bumped, the next
launch re-runs the same step, so the step must tolerate already-applied
changes (e.g. _migrate_0_to_1 checks for the custodian column before
ALTER, and its backfill UPDATEs are guarded by `custodian IS NULL`).
Any future step MUST follow this rule — guard every operation so a
re-run is a no-op.
"""
from __future__ import annotations

from typing import Callable

from sqlalchemy import Engine, text

from justfixed.persistence.mappers import CUSTODIAN_BY_SOURCE


def _get_user_version(engine: Engine) -> int:
    with engine.connect() as conn:
        return conn.execute(text("PRAGMA user_version")).scalar()


def _migrate_0_to_1(conn) -> None:
    """Add custodian column and backfill from import provenance (B42)."""
    # Only ALTER if the column is absent — a fresh DB created by create_all
    # after the model change already has it; an old DB does not.
    existing_cols = {
        row[1]
        for row in conn.execute(text("PRAGMA table_info(investments)"))
    }
    if "custodian" not in existing_cols:
        conn.execute(text("ALTER TABLE investments ADD COLUMN custodian VARCHAR"))

    # Backfill rows that have a known broker provenance.
    # Manual rows (and any unknown source) are left NULL — None = unset.
    for source, custodian in CUSTODIAN_BY_SOURCE.items():
        if custodian is not None:
            conn.execute(
                text(
                    "UPDATE investments"
                    " SET custodian = :c"
                    " WHERE source = :s AND custodian IS NULL"
                ),
                {"c": custodian, "s": source},
            )


def _migrate_1_to_2(conn) -> None:
    """Add broker_value_amount and broker_value_currency columns (B10 Slice 1).

    Pre-existing rows correctly get NULL — there is no past broker value to
    recover. No backfill needed.
    """
    existing_cols = {
        row[1]
        for row in conn.execute(text("PRAGMA table_info(investments)"))
    }
    if "broker_value_amount" not in existing_cols:
        conn.execute(text("ALTER TABLE investments ADD COLUMN broker_value_amount NUMERIC"))
    if "broker_value_currency" not in existing_cols:
        conn.execute(text("ALTER TABLE investments ADD COLUMN broker_value_currency VARCHAR"))


# Ordered list of (target_version, migrate_fn). Apply in sequence; skip
# any step already satisfied by the current user_version.
_MIGRATIONS: list[tuple[int, Callable]] = [
    (1, _migrate_0_to_1),
    (2, _migrate_1_to_2),
]


def run_migrations(engine: Engine) -> None:
    """Apply any pending migrations to the database.

    Safe to call on every startup: each step is idempotent and skipped
    when user_version already meets or exceeds the target.
    """
    current = _get_user_version(engine)

    for target_version, migrate_fn in _MIGRATIONS:
        if current >= target_version:
            continue
        with engine.begin() as conn:
            migrate_fn(conn)
            # PRAGMA user_version = N requires a literal integer; no bind params.
            conn.execute(text(f"PRAGMA user_version = {target_version}"))
        current = target_version
