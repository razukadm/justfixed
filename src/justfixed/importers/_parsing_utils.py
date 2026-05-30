"""Shared low-level parsing helpers for the importer mappers.

Both xp_mapper and btg_mapper parse identical Brazilian percent strings;
this module provides the canonical implementation so neither mapper reaches
into the other's internals.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation


# Brazilian percent: same number format as money, with a trailing "%".
_PERCENT_RE = re.compile(
    r"""^\s*
        (\d{1,3}(?:\.\d{3})*)   # integer part with optional thousands
        (?:,(\d+))?             # optional decimal part
        \s*%\s*$""",
    re.VERBOSE,
)


def _parse_brazilian_percent_to_fraction(text: str) -> Decimal:
    """Parse '95,50%' into Decimal('0.955'). Internal helper for rate parsing.

    Raises:
        ValueError: If the string is not a well-formed Brazilian percent.
    """
    match = _PERCENT_RE.match(text)
    if not match:
        raise ValueError(f"Not a valid Brazilian percent string: {text!r}")

    integer_part, decimal_part = match.groups()
    integer_clean = integer_part.replace(".", "")
    decimal_clean = decimal_part if decimal_part is not None else "00"
    combined = f"{integer_clean}.{decimal_clean}"

    try:
        percent = Decimal(combined)
    except InvalidOperation as e:  # pragma: no cover
        raise ValueError(f"Could not parse percent from {text!r}: {e}")

    return percent / Decimal("100")
