"""Banco do Brasil LCA statement mapper — Layer 2.

Maps a BBRow (six raw strings from bb.read_lca_rows) to a ParsedBBRow
(typed domain values: date, Money, Rate).

Layer 2 contract:
- Input:  BBRow (raw strings, Layer 1 output).
- Output: ParsedBBRow (typed: date, Money, Rate, ProductType).
- Database-free: no Issuer construction, no persistence objects.
  Those are Layer 3's job.
- Strict parsing: any malformed field raises ValueError with context.
  No silent defaults.

Reuse: parse_brazilian_money and parse_brazilian_date are imported
from xp_mapper — they handle the same Brazilian number/date formats.

Rate classification:
  The BB TAXA column carries a bare number with no label. The rate type
  is inferred from the number's magnitude via the _RATE_BANDS table.
  See that constant for the thresholds and the ARCHITECTURE.md rate-rule
  note about why PostFixedCDI and PostFixedCDIPlusSpread must not be
  swapped (~700bp difference).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from justfixed.domain.money import Money
from justfixed.domain.product import ProductType
from justfixed.domain.rates import (
    PostFixedCDI,
    PostFixedCDIPlusSpread,
    PostFixedIPCA,
    Prefixed,
    Rate,
)
from justfixed.importers.bb import BBRow
from justfixed.importers.xp_mapper import parse_brazilian_date, parse_brazilian_money

_log = logging.getLogger(__name__)


# ---------- Taxa magnitude parsing ----------

# Bare Brazilian decimal: "95,00", "12,50", "1,85"
# No R$ prefix, no % suffix — just digits with optional thousands dots and comma decimal.
_TAXA_RE = re.compile(
    r"""^\s*(\d{1,3}(?:\.\d{3})*)(?:,(\d+))?\s*$""",
    re.VERBOSE,
)


def _parse_taxa_magnitude(text: str) -> Decimal:
    """Parse a raw BB taxa string to its numeric magnitude as a Decimal.

    "95,00" → Decimal("95.00")
    "1,85"  → Decimal("1.85")

    Raises:
        ValueError: If the string is not a well-formed positive number.
    """
    match = _TAXA_RE.match(text)
    if not match:
        raise ValueError(f"Not a valid taxa value: {text!r}")
    integer_part, decimal_part = match.groups()
    integer_clean = integer_part.replace(".", "")
    decimal_clean = decimal_part if decimal_part is not None else "0"
    try:
        return Decimal(f"{integer_clean}.{decimal_clean}")
    except InvalidOperation as exc:  # pragma: no cover — regex guards this
        raise ValueError(f"Could not parse taxa from {text!r}: {exc}") from exc


# ---------- Rate classification ----------

# Magnitude bands for the BB TAXA column.  Single source of truth for all
# thresholds — change the numbers here and the classifier picks them up.
#
# Each entry: (threshold, rate_class, strict)
#   strict=True  → band matches when value is STRICTLY GREATER than threshold
#   strict=False → band matches when value is >= threshold
# Entries are checked top-to-bottom; first match wins.
#
# Resulting bands:
#   val > 50  → PostFixedCDI         (e.g. "95,00" = 95% of CDI)
#   9 ≤ val ≤ 50 → Prefixed          (e.g. "12,50" = 12.5% a.a. prefixed)
#   3 ≤ val < 9  → PostFixedIPCA     (e.g. "6,50"  = IPCA + 6.5%)
#   0 < val < 3  → PostFixedCDIPlusSpread  (e.g. "1,85" = CDI + 1.85%)
_RATE_BANDS: tuple[tuple[Decimal, type, bool], ...] = (
    (Decimal("50"), PostFixedCDI,           True),   # val > 50
    (Decimal("9"),  Prefixed,               False),  # 9 ≤ val ≤ 50
    (Decimal("3"),  PostFixedIPCA,          False),  # 3 ≤ val < 9
    (Decimal("0"),  PostFixedCDIPlusSpread, True),   # 0 < val < 3
)


def _classify_taxa(value: Decimal) -> Rate:
    """Map a taxa magnitude (Decimal, percent units) to the correct typed Rate.

    Logs each classification at DEBUG level for import audit trails.

    Raises:
        ValueError: If value is zero, negative, or no band matches.
    """
    if value <= 0:
        raise ValueError(
            f"taxa must be a positive number, got {value!r}. "
            "Zero and negative values are not valid LCA rates."
        )
    for threshold, rate_class, strict in _RATE_BANDS:
        meets = value > threshold if strict else value >= threshold
        if meets:
            rate = rate_class.from_percent(value)
            _log.debug(
                "taxa %s classified as %s (threshold=%s, strict=%s)",
                value, rate_class.__name__, threshold, strict,
            )
            return rate
    # Unreachable: the (0, CDIPlusSpread, True) band catches all positives.
    raise ValueError(  # pragma: no cover
        f"No rate band matched for taxa {value!r}"
    )


def parse_taxa(text: str) -> Rate:
    """Parse a raw BB taxa string into the appropriate typed Rate.

    "95,00" → PostFixedCDI          (95% of CDI)
    "12,50" → Prefixed              (12.5% a.a.)
    "6,50"  → PostFixedIPCA         (IPCA + 6.5%)
    "1,85"  → PostFixedCDIPlusSpread (CDI + 1.85%)

    Raises:
        ValueError: If the string is not a well-formed positive number.
    """
    magnitude = _parse_taxa_magnitude(text)
    return _classify_taxa(magnitude)


# ---------- Composition ----------


@dataclass(frozen=True, slots=True)
class ParsedBBRow:
    """A BBRow interpreted into typed domain values, awaiting issuer reconciliation.

    Fields
    ------
    numero           Application identifier (raw string; not an integer).
    data_aplicacao   Purchase / application date.
    data_vencimento  Maturity date.
    valor_emissao    Principal at issuance.
    saldo            Current gross balance; Money zero for matured positions.
    rate             Rate, classified from the taxa magnitude band.
    product          Always ProductType.LCA for BB LCA statements.
    """

    numero: str
    data_aplicacao: date
    data_vencimento: date
    valor_emissao: Money
    saldo: Money
    rate: Rate
    product: ProductType


def parse_row(row: BBRow) -> ParsedBBRow:
    """Convert a BBRow into a ParsedBBRow with all fields typed.

    Composes the primitive parsers.  On any parse failure, re-raises with
    a contextual message that identifies the offending row by numero.

    Raises:
        ValueError: From any underlying parser, wrapped with the row's numero.
    """
    try:
        data_aplic = parse_brazilian_date(row.data_aplicacao)
        data_venc = parse_brazilian_date(row.data_vencimento)
        valor = parse_brazilian_money(row.valor_emissao)
        saldo = parse_brazilian_money(row.saldo)
        rate = parse_taxa(row.taxa)
    except ValueError as exc:
        raise ValueError(
            f"Could not parse BB row {row.numero!r}: {exc}"
        ) from exc

    return ParsedBBRow(
        numero=row.numero,
        data_aplicacao=data_aplic,
        data_vencimento=data_venc,
        valor_emissao=valor,
        saldo=saldo,
        rate=rate,
        product=ProductType.LCA,
    )
