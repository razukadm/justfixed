"""Broker detection and unified statement dispatch.

Identifies a statement file's broker by file extension and structural
fingerprint, then routes it to the correct loader.

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

from justfixed.importers.bb_loader import load_bb_statement
from justfixed.importers.btg_loader import load_btg_statement
from justfixed.importers.loader_types import LoadResult
from justfixed.importers.xp_loader import load_xp_statement


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
    BB  = "bb"


# Sheet-name fingerprints for XLSX brokers. Mutually exclusive in practice
# (confirmed against synthetic and real fixtures). Stored here as the single
# source of truth so detect_broker and any future tooling stay in sync.
_XP_FINGERPRINT  = "Sua carteira"
_BTG_FINGERPRINT = "Renda Fixa"

# BB SISBB plain-text fingerprint: a header line containing both tokens.
# Using two terms rather than the full exact string for encoding robustness.
_BB_FINGERPRINT_SISBB = "SISBB"
_BB_FINGERPRINT_BB    = "Banco do Brasil"


def _read_text_for_detection(path: Path) -> str:
    """Read a text file as UTF-8 with latin-1 fallback (matches bb._read_text)."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")


def detect_broker(path: Path) -> Broker:
    """Identify which broker produced the statement at *path*.

    Branches on file extension first:
      .xlsx — opens the workbook read-only to inspect sheet names only;
              no cell data is read. The workbook is closed before returning.
      .txt  — reads as text (UTF-8 / latin-1 fallback) and checks for the
              SISBB header line containing both 'SISBB' and 'Banco do Brasil'.
      other — raises ValueError.

    Detection fingerprints:
      .xlsx, sheet "Renda Fixa"       → Broker.BTG
      .xlsx, sheet "Sua carteira"     → Broker.XP
      .xlsx, both sheets              → ValueError (ambiguous)
      .xlsx, neither sheet            → ValueError (unrecognized)
      .txt,  SISBB header found       → Broker.BB
      .txt,  no SISBB header          → ValueError (unrecognized .txt)
      other extension                 → ValueError

    Args:
        path: Filesystem path to a statement file (.xlsx or .txt).

    Returns:
        The detected Broker.

    Raises:
        FileNotFoundError: If *path* does not exist.
        ValueError: If the format is unrecognized, ambiguous, or the
                    extension is not .xlsx or .txt.
    """
    suffix = path.suffix.lower()

    if suffix == ".txt":
        text = _read_text_for_detection(path)
        for line in text.splitlines():
            if _BB_FINGERPRINT_SISBB in line and _BB_FINGERPRINT_BB in line:
                return Broker.BB
        raise ValueError(
            f"Unrecognized .txt statement: {path.name!r} does not contain "
            f"the SISBB header (expected a line with {_BB_FINGERPRINT_SISBB!r} "
            f"and {_BB_FINGERPRINT_BB!r}). Is this a Banco do Brasil statement?"
        )

    if suffix == ".xlsx":
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

    raise ValueError(
        f"Unrecognized file type: {path.name!r} (extension {path.suffix!r}). "
        f"Expected .xlsx (XP or BTG) or .txt (Banco do Brasil)."
    )


def load_statement(
    path: Path, session_factory: sessionmaker[Session]
) -> tuple[Broker, LoadResult]:
    """Detect broker, then load the statement into the database.

    This is the single place in the codebase that maps a Broker to its
    loader function. Callers that want to display which broker was detected
    alongside import counts should use this function rather than calling
    detect_broker + load_*_statement separately.

    Args:
        path: Filesystem path to a statement file (.xlsx or .txt).
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
    elif broker is Broker.BTG:
        result = load_btg_statement(path, session_factory)
    elif broker is Broker.BB:
        result = load_bb_statement(path, session_factory)
    else:
        raise ValueError(f"No loader for broker {broker!r}")
    return broker, result
