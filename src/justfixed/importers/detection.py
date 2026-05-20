"""Broker detection and unified statement dispatch.

Identifies a statement file's broker by structural sheet-name fingerprint
and routes it to the correct loader.

Adding a future broker N requires exactly three changes:
  1. A Broker.N enum member here.
  2. A fingerprint case in detect_broker.
  3. A dispatch case in load_statement.
No other module needs to change.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

import openpyxl
from sqlalchemy.orm import Session, sessionmaker

from justfixed.importers.btg_loader import load_btg_statement
from justfixed.importers.xp_loader import LoadResult, load_xp_statement


class Broker(Enum):
    """Which broker produced a statement file (i.e. which file format).

    This is an importer concept, deliberately separate from
    domain.InvestmentSource. InvestmentSource answers "who created this
    investment row" and includes MANUAL, which is not a broker and can
    never be a detection result. Broker answers "what statement format
    is this file" and is only meaningful during the import pipeline.
    """

    XP  = "xp"
    BTG = "btg"


# Sheet-name fingerprints — one per broker. Mutually exclusive in practice
# (confirmed against synthetic and real fixtures). Stored here as the single
# source of truth so detect_broker and any future tooling stay in sync.
_XP_FINGERPRINT  = "Sua carteira"
_BTG_FINGERPRINT = "Renda Fixa"


def detect_broker(path: Path) -> Broker:
    """Identify which broker produced the statement at *path*.

    Opens the workbook read-only to inspect sheet names only; no cell
    data is read. The workbook is closed before returning.

    Detection fingerprints:
      - Sheet named "Renda Fixa" present  -> Broker.BTG
      - Sheet named "Sua carteira" present -> Broker.XP
      - Both present                       -> ValueError (ambiguous file)
      - Neither present                    -> ValueError (unrecognized format)

    Args:
        path: Filesystem path to an .xlsx statement file.

    Returns:
        The detected Broker.

    Raises:
        FileNotFoundError: If *path* does not exist (propagated from openpyxl).
        ValueError: If the sheet names do not match any known broker, or
                    if the file matches more than one broker (ambiguous).
    """
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        sheet_names = wb.sheetnames
    finally:
        wb.close()

    has_btg = _BTG_FINGERPRINT in sheet_names
    has_xp  = _XP_FINGERPRINT  in sheet_names

    if has_btg and has_xp:
        raise ValueError(
            f"Ambiguous statement format: {path.name} matches both XP "
            f"({_XP_FINGERPRINT!r}) and BTG ({_BTG_FINGERPRINT!r}) fingerprints. "
            f"Sheets found: {sheet_names}."
        )
    if has_btg:
        return Broker.BTG
    if has_xp:
        return Broker.XP
    raise ValueError(
        f"Unrecognized statement format: {path.name} has sheets "
        f"{sheet_names} — expected an XP or BTG statement."
    )


def load_statement(
    path: Path, session_factory: sessionmaker[Session]
) -> tuple[Broker, LoadResult]:
    """Detect broker, then load the statement into the database.

    This is the single place in the codebase that maps a Broker to its
    loader function. Callers that want to display which broker was detected
    alongside import counts should use this function rather than calling
    detect_broker + load_*_statement separately (which would open the
    workbook twice).

    Args:
        path: Filesystem path to an .xlsx statement file.
        session_factory: SQLAlchemy session factory bound to the target
                         database engine.

    Returns:
        A (Broker, LoadResult) tuple: the detected broker and a summary
        of what was inserted vs. skipped.

    Raises:
        FileNotFoundError: If *path* does not exist.
        ValueError: If the file format is unrecognized or ambiguous.
        ValueError: If any row fails parsing (propagated from the loader).
        sqlalchemy.exc.IntegrityError: If a database constraint is violated.
    """
    broker = detect_broker(path)
    if broker is Broker.XP:
        result = load_xp_statement(path, session_factory)
    else:
        result = load_btg_statement(path, session_factory)
    return broker, result
