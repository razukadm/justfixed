"""Tests for the database connection and session machinery."""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from justfixed.persistence.database import (
    Base,
    default_database_url,
    make_engine,
    make_session_factory,
    session_scope,
)


# ---------- Engine and session creation ----------


class TestEngineCreation:
    def test_in_memory_engine_can_be_made(self) -> None:
        engine = make_engine("sqlite:///:memory:")
        assert isinstance(engine, Engine)
        engine.dispose()

    def test_engine_executes_simple_query(self) -> None:
        engine = make_engine("sqlite:///:memory:")
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            assert result.scalar() == 1
        engine.dispose()

    def test_session_factory_yields_sessions(self) -> None:
        engine = make_engine("sqlite:///:memory:")
        factory = make_session_factory(engine)
        session = factory()
        assert isinstance(session, Session)
        session.close()
        engine.dispose()


# ---------- Foreign-key enforcement (SQLite quirk) ----------


class TestForeignKeyEnforcement:
    def test_sqlite_foreign_keys_pragma_is_on(self) -> None:
        # Without the event hook, SQLite would report 0 here.
        engine = make_engine("sqlite:///:memory:")
        with engine.connect() as conn:
            result = conn.execute(text("PRAGMA foreign_keys"))
            assert result.scalar() == 1
        engine.dispose()


# ---------- session_scope context manager ----------


class TestSessionScope:
    def test_clean_exit_commits(self) -> None:
        engine = make_engine("sqlite:///:memory:")
        factory = make_session_factory(engine)

        # Build a tiny test table directly via core SQL so we don't need
        # ORM models yet. We're testing the session machinery, not models.
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE t (n INTEGER)"))

        with session_scope(factory) as session:
            session.execute(text("INSERT INTO t (n) VALUES (1)"))
            # Implicit commit on clean exit.

        # Reopen and verify the row persisted.
        with session_scope(factory) as session:
            result = session.execute(text("SELECT n FROM t")).scalars().all()
            assert result == [1]

        engine.dispose()

    def test_exception_rolls_back(self) -> None:
        engine = make_engine("sqlite:///:memory:")
        factory = make_session_factory(engine)
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE t (n INTEGER)"))

        # Raise mid-session. The insert must NOT persist.
        with pytest.raises(RuntimeError, match="boom"):
            with session_scope(factory) as session:
                session.execute(text("INSERT INTO t (n) VALUES (42)"))
                raise RuntimeError("boom")

        with session_scope(factory) as session:
            result = session.execute(text("SELECT n FROM t")).scalars().all()
            assert result == []

        engine.dispose()


# ---------- default URL behavior ----------


class TestDefaultDatabaseUrl:
    def test_default_url_starts_with_sqlite_prefix(self) -> None:
        url = default_database_url()
        assert url.startswith("sqlite:///")

    def test_default_url_points_to_dot_justfixed(self) -> None:
        url = default_database_url()
        assert ".justfixed" in url
        assert url.endswith("justfixed.db")


# ---------- Base ----------


class TestBase:
    def test_base_has_metadata(self) -> None:
        # `metadata` is what Alembic and Base.metadata.create_all use.
        assert Base.metadata is not None