"""Banco do Brasil LCA statement parser — Layer 1.

Reads a fixed-width plain-text BB/SISBB terminal dump (.txt), locating
the "RESUMO DAS APLICAÇÕES LCA" section and extracting one BBRow per
application line.

Layer 1 contract:
- Input: path to a .txt file (UTF-8; latin-1 fallback for older dumps).
- Output: list[BBRow]. Every field is a raw stripped string exactly as
  it appeared in the file. No typing, no Decimal, no date parsing.
  That is Layer 2's responsibility.
- ALL rows are returned — active AND matured (SALDO "0,00"). Filtering
  matured positions is the loader's job.
- Strict parsing: missing section title or unexpected structure raises
  ValueError with a contextual message.

Column layout (0-indexed character slices on each data row).
Data rows are 100 chars wide; blank lines between rows are skipped.

  Field            Slice      Alignment  Notes
  ──────────────── ────────── ─────────  ──────────────────────────────
  numero           [0:26]     left       content at positions 1–19 (19 chars)
  data_aplicacao   [26:46]    left       content at positions 26–35 (10 chars)
  valor_emissao    [46:62]    right      content ends at position 57 (10–12 chars)
  saldo            [62:76]    right      content ends at position 73 (4–12 chars)
  taxa             [76:86]    left       content at positions 76–80 (4–5 chars)
  data_vencimento  [86:]      left       content at positions 86–95 (10 chars)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


_SECTION_ANCHOR   = "RESUMO DAS APLICAÇÕES LCA"
_COL_HEADER_TOKEN = "NÚMERO"
_TOTAL_MARKER     = "TOTAL"

_COL_NUMERO      = slice(0,  26)
_COL_DATA_APLIC  = slice(26, 46)
_COL_VALOR       = slice(46, 62)
_COL_SALDO       = slice(62, 76)
_COL_TAXA        = slice(76, 86)
_COL_DATA_VENC   = slice(86, None)

# Minimum line length: must reach the start of data_vencimento (position 86)
# and contain at least one character of it.
_MIN_DATA_ROW_LEN = 87


@dataclass(frozen=True, slots=True)
class BBRow:
    """A single LCA application from a BB statement, raw-string form.

    Every field holds the cell value after stripping surrounding whitespace.
    No further parsing is done at this layer.

    Fields
    ------
    numero           Application number (sequence identifier).
    data_aplicacao   Application date, as "dd/mm/yyyy".
    valor_emissao    Face value at issuance, Brazilian-formatted money string.
    saldo            Current gross balance; "0,00" for matured positions.
    taxa             Rate magnitude, e.g. "95,00" or "6,50".
    data_vencimento  Maturity date, as "dd/mm/yyyy".
    """

    numero:          str
    data_aplicacao:  str
    valor_emissao:   str
    saldo:           str
    taxa:            str
    data_vencimento: str


def _read_text(path: Path) -> str:
    """Read file as UTF-8; fall back to latin-1 for older SISBB dumps."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")


def _is_dashed_rule(line: str) -> bool:
    """True if the stripped line is non-empty and consists entirely of dashes."""
    s = line.strip()
    return bool(s) and s == "-" * len(s)


def _slice_row(line: str, line_no: int) -> BBRow:
    """Slice one data row into its six BBRow fields by fixed character offsets.

    Raises ValueError if the line is too short to reach the data_vencimento
    column (position 86).
    """
    if len(line) < _MIN_DATA_ROW_LEN:
        raise ValueError(
            f"Line {line_no}: data row too short ({len(line)} chars, "
            f"minimum {_MIN_DATA_ROW_LEN}). Line: {line!r}"
        )
    return BBRow(
        numero=line[_COL_NUMERO].strip(),
        data_aplicacao=line[_COL_DATA_APLIC].strip(),
        valor_emissao=line[_COL_VALOR].strip(),
        saldo=line[_COL_SALDO].strip(),
        taxa=line[_COL_TAXA].strip(),
        data_vencimento=line[_COL_DATA_VENC].strip(),
    )


def read_lca_rows(path: Path) -> list[BBRow]:
    """Extract all LCA applications from a BB SISBB statement text file.

    Parses the "RESUMO DAS APLICAÇÕES LCA" section, reading every data row
    between the post-header dashed rule and the TOTAL line. Both active
    (saldo > 0) and matured (saldo "0,00") rows are included.

    Args:
        path: Path to a BB terminal-dump .txt file.

    Returns:
        A list of BBRow objects in file order.

    Raises:
        FileNotFoundError: If the path does not exist.
        ValueError: If the section title is absent, the column-header row
            is not found, the post-header dashed rule is missing, or a
            data row is too short to slice.
    """
    text = _read_text(path)
    lines = text.splitlines()

    # Phase 1: locate the "RESUMO DAS APLICAÇÕES LCA" section title.
    anchor_idx: int | None = None
    for i, line in enumerate(lines):
        if _SECTION_ANCHOR in line:
            anchor_idx = i
            break
    if anchor_idx is None:
        raise ValueError(
            f"Section {_SECTION_ANCHOR!r} not found in {path.name!r}. "
            "Is this a Banco do Brasil LCA statement?"
        )

    # Phase 2: find the column-header row (contains "NÚMERO") after the anchor.
    header_idx: int | None = None
    for i in range(anchor_idx + 1, len(lines)):
        if _COL_HEADER_TOKEN in lines[i]:
            header_idx = i
            break
    if header_idx is None:
        raise ValueError(
            f"Column header row (containing {_COL_HEADER_TOKEN!r}) not found "
            f"after section anchor in {path.name!r}."
        )

    # Phase 3: find the dashed rule immediately following the column header.
    rule_idx: int | None = None
    for i in range(header_idx + 1, len(lines)):
        if _is_dashed_rule(lines[i]):
            rule_idx = i
            break
    if rule_idx is None:
        raise ValueError(
            f"Dashed rule after column header not found in {path.name!r}."
        )

    # Phase 4: read data rows until TOTAL or a closing dashed rule.
    rows: list[BBRow] = []
    for i in range(rule_idx + 1, len(lines)):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(_TOTAL_MARKER):
            break
        if _is_dashed_rule(line):
            break
        rows.append(_slice_row(line, i + 1))

    return rows
