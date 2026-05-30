"""BTGRow -> typed-data mapper.

Layer 2 of the BTG importer pipeline:
- Input: BTGRow (raw strings from the XLSX, produced by btg.py).
- Output: ParsedBTGRow (typed data: Money, date, Rate, ProductType, etc.).

This module deliberately knows nothing about the database. It produces
an issuer NAME (a string), not an Issuer instance. Reconciling that
name against the database is layer 3's job.

BTG differs from XP in five concrete ways handled here:
  1. Dates arrive as "YYYY-MM-DD 00:00:00" (str(datetime)), not DD/MM/YYYY.
  2. Numeric fields arrive as Python repr ("43000", "1080.15641"), not
     Brazilian-formatted ("R$ 43.000,00") — Decimal() accepts them directly.
  3. Rate text uses "do CDI" ("89,00% do CDI"); "do" is optional in the regex.
  4. Product and issuer come from BTGRow fields, not a description string.
  5. Coupon frequency cannot be detected from observed data; always NONE.

Strict parsing philosophy: any malformed input raises ValueError with
a descriptive message. We do NOT silently fall back to defaults.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from justfixed.domain.money import Money
from justfixed.domain.product import CouponFrequency, ProductType
from justfixed.domain.rates import PostFixedCDI, Rate
from justfixed.importers.btg import BTGRow
from justfixed.importers._parsing_utils import _parse_brazilian_percent_to_fraction


# ---------- Date parsing ----------


_BTG_DATETIME_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2}) 00:00:00$")


def parse_btg_datetime_string(text: str) -> date:
    """Parse a BTG datetime string ("YYYY-MM-DD 00:00:00") into a date.

    Layer-1 coerces openpyxl datetime values via str(), producing
    "2025-09-29 00:00:00". This function inverts that transformation.

    Raises:
        ValueError: If the string does not match the expected format or
            contains invalid date components (e.g. month 13).
    """
    match = _BTG_DATETIME_RE.match(text.strip())
    if not match:
        raise ValueError(f"Not a valid BTG datetime string: {text!r}")
    year, month, day = (int(g) for g in match.groups())
    try:
        return date(year, month, day)
    except ValueError as e:
        raise ValueError(f"Invalid date components in {text!r}: {e}")


# ---------- Decimal parsing ----------


def parse_btg_decimal(text: str) -> Decimal:
    """Parse a Python numeric repr string into a Decimal.

    BTG layer-1 coerces cell values via str(int/float), producing
    "43000", "1080.15641", etc. — Python numeric representation, NOT
    Brazilian-formatted. Decimal() accepts these directly.

    Raises:
        ValueError: If the string is not a valid numeric representation
            (e.g. Brazilian "R$ 1.000,00" or garbage text), or if the
            value is non-finite ("NaN", "Infinity", "-Infinity").
    """
    try:
        result = Decimal(text)
    except InvalidOperation:
        raise ValueError(f"Not a valid numeric string: {text!r}")
    if not result.is_finite():
        raise ValueError(f"Numeric value is not finite: {text!r}")
    return result


# ---------- Rate parsing ----------


# BTG CDI-percentage format: "89,00% do CDI" or "95,00% CDI" (no "do").
_BTG_CDI_PCT_RE = re.compile(r"^(.+?%)\s*(?:do\s+)?CDI\s*$", re.IGNORECASE)


def parse_btg_rate(text: str) -> Rate:
    """Parse a BTG rate string into a Rate subclass.

    Recognized formats:
        "89,00% do CDI"  -> PostFixedCDI(0.89)
        "95,00% CDI"     -> PostFixedCDI(0.95)   ("do" is optional)

    Only PostFixedCDI is implemented. BTG's wording for Prefixed,
    CDIPlusSpread, and IPCA is unknown; unrecognized formats raise
    ValueError so the first encounter of each format is auditable and
    forces a focused follow-up commit.

    Raises:
        ValueError: If the format is not recognized or the embedded
            percent is malformed.
    """
    stripped = text.strip()
    m = _BTG_CDI_PCT_RE.match(stripped)
    if m:
        fraction = _parse_brazilian_percent_to_fraction(m.group(1))
        return PostFixedCDI(fraction)
    raise ValueError(f"Unrecognized BTG rate format: {text!r}")


# ---------- Product mapping ----------


_BTG_PRODUCT_MAP: dict[str, ProductType] = {
    "LCI": ProductType.LCI,
    "LCA": ProductType.LCA,
    "CDB": ProductType.CDB,
    "LCD": ProductType.LCD,
    "LC":  ProductType.LC,
}


def parse_btg_product(text: str) -> ProductType:
    """Map a BTG product string to a ProductType.

    Raises:
        ValueError: If the product string is not in the recognized set.
    """
    product = _BTG_PRODUCT_MAP.get(text.strip())
    if product is None:
        raise ValueError(f"Unrecognized BTG product type: {text!r}")
    return product


# ---------- Description construction ----------


_MONTHS_PT = {
    1: "JAN", 2: "FEV", 3: "MAR", 4: "ABR", 5: "MAI", 6: "JUN",
    7: "JUL", 8: "AGO", 9: "SET", 10: "OUT", 11: "NOV", 12: "DEZ",
}


def _build_description(product_str: str, issuer_name: str, maturity_date: date) -> str:
    """Construct a human-readable description for a BTG position.

    Format: "<product> <issuer> - <MMM_PT>/<YYYY>"
    Example: "LCI ASSOCIACAO DE POUPANCA E EMPRESTIMO POUPEX - SET/2027"
    """
    month_pt = _MONTHS_PT[maturity_date.month]
    return f"{product_str} {issuer_name} - {month_pt}/{maturity_date.year}"


# ---------- Composition: parse a whole BTGRow ----------


@dataclass(frozen=True, slots=True)
class ParsedBTGRow:
    """A BTGRow interpreted into typed domain values, awaiting issuer reconciliation.

    All fields have been parsed from their string forms in the original BTGRow.
    The `issuer_name` is a human-readable string ready to look up against the
    database (or to create a new Issuer with). The next pipeline layer
    (btg_loader) does that reconciliation.

    `issue_date` is parsed from emissao_date_text. BTG provides a real
    issuance date; preserving it here costs nothing. Whether btg_loader
    passes it to Investment.create is a layer-3 decision.

    `principal` is the acquisition cost (valor_compra_text), equivalent to
    XP's valor_aplicado_original.

    `coupon_frequency` is always CouponFrequency.NONE. BTG rows carry no
    coupon hint in observed data; the first coupon-paying BTG instrument
    forces a revisit of this layer.
    """

    product:          ProductType
    issuer_name:      str           # readable form, NOT normalized
    principal:        Money         # from valor_compra_text
    rate:             Rate
    purchase_date:    date          # from aquisicao_date_text
    issue_date:       date          # from emissao_date_text
    maturity_date:    date          # from vencimento_date_text
    coupon_frequency: CouponFrequency  # always NONE for now
    description:      str           # constructed, not sourced from a field


def parse_row(row: BTGRow) -> ParsedBTGRow:
    """Convert a BTGRow into a ParsedBTGRow with all fields typed.

    Composes the primitive parsers. Each parser is independent; we
    proceed in roughly the order fields appear on the output dataclass.

    Raises:
        ValueError: From any underlying parser, wrapped with a contextual
            message that identifies the offending row by issuer and ativo.
    """
    try:
        product = parse_btg_product(row.product)
        issuer_name = row.issuer_name.strip()
        principal = Money(
            amount=parse_btg_decimal(row.valor_compra_text), currency="BRL"
        )
        rate = parse_btg_rate(row.taxa_compra)
        purchase_date = parse_btg_datetime_string(row.aquisicao_date_text)
        issue_date = parse_btg_datetime_string(row.emissao_date_text)
        maturity_date = parse_btg_datetime_string(row.vencimento_date_text)
        # BTG coupon detection is unsolved — no coupon hint in observed data.
        # First coupon-paying BTG instrument forces a revisit.
        coupon_frequency = CouponFrequency.NONE
        description = _build_description(row.product, issuer_name, maturity_date)
    except ValueError as e:
        raise ValueError(
            f"Could not parse BTG row {row.issuer_name!r} / {row.ativo!r}: {e}"
        ) from e

    return ParsedBTGRow(
        product=product,
        issuer_name=issuer_name,
        principal=principal,
        rate=rate,
        purchase_date=purchase_date,
        issue_date=issue_date,
        maturity_date=maturity_date,
        coupon_frequency=coupon_frequency,
        description=description,
    )
