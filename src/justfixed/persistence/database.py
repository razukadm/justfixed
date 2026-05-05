"""Database connection and session management.

This module is the single source of truth for how the application talks
to its database. It exposes:

- `Base`: the declarative base class that all ORM models inherit from.
- `make_engine(url)`: factory for a SQLAlchemy engine.
- `make_session_factory(engine)`: factory for a session factory.
- `default_database_url()`: where the production database lives by default.

Tests use in-memory SQLite (sqlite:///:memory:) for speed and isolation;
production uses a file in the user's data directory.

Design choices:
- We pass the engine and session factory around explicitly rather than
  using global singletons. This makes tests trivial (each test gets a
  fresh in-memory database) and avoids the threading pitfalls of globals.
- Foreign-key constraints are enabled on every connection (SQLite has
  them off by default — a notorious pitfall).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Common base class for all ORM models.

    Every persistence model inherits from this so SQLAlchemy can
    discover all tables (e.g. for `Base.metadata.create_all(engine)`).
    """


def default_database_url() -> str:
    """Return the URL for the production database.

    The file lives under the user's home directory in a hidden
    `.justfixed/` folder. Created on first use.
    """
    data_dir = Path.home() / ".justfixed"
    data_dir.mkdir(exist_ok=True)
    db_path = data_dir / "justfixed.db"
    # SQLAlchemy URL: sqlite:///<path>. The triple slash + absolute path
    # is the SQLite convention for file-based databases.
    return f"sqlite:///{db_path}"


def make_engine(url: str, *, echo: bool = False) -> Engine:
    """Create a SQLAlchemy engine for the given database URL.

    Args:
        url: Database URL, e.g. "sqlite:///path/to.db" or
             "sqlite:///:memory:" for tests.
        echo: If True, SQLAlchemy logs every SQL statement. Useful for
              debugging; off by default.

    Returns:
        A configured Engine. Call `engine.dispose()` when done if not
        relying on process exit (rare in our case).
    """
    engine = create_engine(url, echo=echo, future=True)

    # SQLite quirk: foreign-key enforcement is disabled by default.
    # Without this, a row referencing a non-existent issuer would silently
    # succeed. Hook every new connection to enable FK constraints.
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a session factory bound to the given engine.

    Use the factory to open sessions: `session = factory()`.
    Prefer the `session_scope` context manager below for ad-hoc work.
    """
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Context manager that opens a session, commits on success,
    rolls back on exception, and always closes the session.

    Usage:
        with session_scope(factory) as session:
            session.add(some_row)
            # commit happens automatically on clean exit

    Tests and repositories should prefer this over manually managing
    sessions — it's harder to leak sessions or forget to commit.
    """
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()