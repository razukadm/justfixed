"""XPRow → typed-data mapper.

Layer 2 of the importer pipeline:
- Input: XPRow (raw strings from the XLSX).
- Output: ParsedXPRow (typed data: Money, date, Rate, ProductType, etc.).

This module deliberately knows nothing about the database. It produces
an issuer NAME (a string), not an Issuer instance. Reconciling that
name against the database is layer 3's job.

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
from justfixed.domain.rates import (
    PostFixedCDI,
    PostFixedCDIPlusSpread,
    PostFixedIPCA,
    Prefixed,
    Rate,
)
from justfixed.importers.xp import XPRow


# ---------- Brazilian number parsing ----------


# Brazilian money: optional "R$", thousands separator ".", decimal ",".
# Examples: "R$ 45.000,00", "45.000,00", "1.234,56", "0,01".
_MONEY_RE = re.compile(
    r"""^\s*
        (?:R\$)?\s*       # optional R$ prefix with optional space after
        (-?)\s*           # optional sign (rare but possible for losses)
        (\d{1,3}          # leading digit group, 1-3 digits
        (?:\.\d{3})*)     # zero or more thousands groups (.123)
        (?:,(\d+))?       # optional decimal part (,XX or ,XXXXXXXX)
        \s*$""",
    re.VERBOSE,
)


def parse_brazilian_money(text: str) -> Money:
    """Parse a Brazilian-formatted money string into a Money (BRL).

    Accepts: "R$ 45.000,00", "45.000,00", "1.234,56", "0,01", "100".
    Rejects: empty, US-formatted ("1,234.56"), garbled, non-numeric.

    Raises:
        ValueError: If the string is not well-formed Brazilian money.
    """
    match = _MONEY_RE.match(text)
    if not match:
        raise ValueError(f"Not a valid Brazilian money string: {text!r}")

    sign, integer_part, decimal_part = match.groups()
    integer_clean = integer_part.replace(".", "")  # strip thousands separators
    decimal_clean = decimal_part if decimal_part is not None else "00"
    combined = f"{sign}{integer_clean}.{decimal_clean}"

    try:
        amount = Decimal(combined)
    except InvalidOperation as e:  # pragma: no cover - regex should prevent
        raise ValueError(f"Could not parse amount from {text!r}: {e}")

    return Money(amount=amount, currency="BRL")


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


# ---------- Date parsing ----------


_DATE_RE = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*$")


def parse_brazilian_date(text: str) -> date:
    """Parse a Brazilian-formatted date string (DD/MM/YYYY) into a date.

    Raises:
        ValueError: If the string is not a well-formed DD/MM/YYYY date.
    """
    match = _DATE_RE.match(text)
    if not match:
        raise ValueError(f"Not a valid DD/MM/YYYY date: {text!r}")

    day, month, year = (int(g) for g in match.groups())
    try:
        return date(year, month, day)
    except ValueError as e:
        raise ValueError(f"Invalid date components in {text!r}: {e}")


# ---------- Rate parsing ----------


# Recognized rate text formats (in priority order):
#   "95,50% CDI"      → PostFixedCDI(0.955)
#   "CDI +2,05%"      → PostFixedCDIPlusSpread(0.0205)
#   "IPC-A +7,31%"    → PostFixedIPCA(0.0731)
#   "+12,00%"         → Prefixed(0.12)


def parse_rate(text: str) -> Rate:
    """Parse an XP rate description into the appropriate Rate subclass.

    Recognized formats:
        "95,50% CDI"   → PostFixedCDI
        "CDI +2,05%"   → PostFixedCDIPlusSpread
        "IPC-A +7,31%" → PostFixedIPCA
        "+12,00%"      → Prefixed

    Raises:
        ValueError: If the format is not recognized or the embedded
            percent is malformed.
    """
    stripped = text.strip()

    # "% CDI" form: "95,50% CDI"
    cdi_pct_match = re.match(r"^(.+?%)\s*CDI\s*$", stripped, re.IGNORECASE)
    if cdi_pct_match:
        fraction = _parse_brazilian_percent_to_fraction(cdi_pct_match.group(1))
        return PostFixedCDI(fraction)

    # "CDI +X%" form: "CDI +2,05%"
    cdi_plus_match = re.match(r"^CDI\s*\+\s*(.+?%)\s*$", stripped, re.IGNORECASE)
    if cdi_plus_match:
        fraction = _parse_brazilian_percent_to_fraction(cdi_plus_match.group(1))
        return PostFixedCDIPlusSpread(fraction)

    # "IPC-A +X%" form: "IPC-A +7,31%". XP writes IPC-A; we treat as IPCA.
    ipca_match = re.match(r"^IPC-?A\s*\+\s*(.+?%)\s*$", stripped, re.IGNORECASE)
    if ipca_match:
        fraction = _parse_brazilian_percent_to_fraction(ipca_match.group(1))
        return PostFixedIPCA(fraction)

    # "+X%" form: "+12,00%" (or just "12,00%" — accept both for robustness)
    pre_match = re.match(r"^\+?\s*(.+?%)\s*$", stripped)
    if pre_match:
        fraction = _parse_brazilian_percent_to_fraction(pre_match.group(1))
        return Prefixed(fraction)

    raise ValueError(f"Unrecognized rate format: {text!r}")


# ---------- Product and coupon detection ----------


# Description format examples:
#   "LCI CEF - ABR/2027"
#   "LCA BANCO BV S/A - JURO MENSAL - MAR/2029"
#   "CDB BMG - JUL/2027"
#   "NTN-B - AGO/2040"


_PRODUCT_PREFIX_MAP: dict[str, ProductType] = {
    "LCI": ProductType.LCI,
    "LCA": ProductType.LCA,
    "LCD": ProductType.LCD,  # rare in XP, but possible
    "LC":  ProductType.LC,   # also rare
    "CDB": ProductType.CDB,
}


def parse_product_and_coupon(
    description: str,
) -> tuple[ProductType, CouponFrequency]:
    """Identify the ProductType and CouponFrequency from a description.

    Recognized prefixes (anchored at start, case-sensitive):
        LCI, LCA, LCD, LC, CDB → corresponding ProductType.
        NTN-B → ProductType.TESOURO_IPCA (Tesouro IPCA+).

    Coupon frequency detection (case-insensitive, substring):
        "JURO MENSAL"    → MONTHLY
        "JURO SEMESTRAL" → SEMI_ANNUAL
        otherwise        → NONE (bullet)

    Raises:
        ValueError: If no recognized product prefix is found.
    """
    desc = description.strip()

    # NTN-B is the only Tesouro product format we see in XP statements.
    if desc.startswith("NTN-B"):
        product = ProductType.TESOURO_IPCA
    else:
        # Try each prefix, longest first so "LCI " wins over "LC ".
        product = None
        for prefix in sorted(_PRODUCT_PREFIX_MAP, key=len, reverse=True):
            if desc.startswith(prefix + " "):
                product = _PRODUCT_PREFIX_MAP[prefix]
                break
        if product is None:
            raise ValueError(
                f"Cannot identify product type from description: {description!r}"
            )

    # Coupon detection (case-insensitive).
    upper = desc.upper()
    if "JURO MENSAL" in upper:
        coupon = CouponFrequency.MONTHLY
    elif "JURO SEMESTRAL" in upper:
        coupon = CouponFrequency.SEMI_ANNUAL
    else:
        coupon = CouponFrequency.NONE

    return product, coupon


# ---------- Issuer name extraction ----------


# Maturity hints embedded in descriptions: " - MMM/YYYY".
_MATURITY_HINT_RE = re.compile(
    r"\s+-\s+(?:JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)/\d{4}\s*$",
    re.IGNORECASE,
)

# "JURO MENSAL"/"JURO SEMESTRAL" markers may be embedded mid-description.
_COUPON_HINT_RE = re.compile(
    r"\s+-\s+JURO\s+(?:MENSAL|SEMESTRAL)\b",
    re.IGNORECASE,
)


def parse_issuer_name(description: str) -> str:
    """Extract a normalized issuer name from a description.

    Strips:
      - The product prefix ("LCI ", "LCA ", "CDB ", etc., or "NTN-B")
      - The maturity hint suffix (" - ABR/2027")
      - Any " - JURO MENSAL" / " - JURO SEMESTRAL" markers in the middle

    Examples:
      "LCI CEF - ABR/2027"                            → "CEF"
      "LCA BANCO COOPERATIVO SICOOB - MAI/2030"       → "BANCO COOPERATIVO SICOOB"
      "LCA BANCO BV S/A - JURO MENSAL - MAR/2029"     → "BANCO BV S/A"
      "NTN-B - AGO/2040"                              → "Tesouro Nacional"

    Raises:
        ValueError: If the description doesn't contain a recognized prefix.
    """
    desc = description.strip()

    # Tesouro is the special case: NTN-B has no issuer name in its description.
    if desc.startswith("NTN-B"):
        return "Tesouro Nacional"

    # Strip the product prefix.
    remaining: str | None = None
    for prefix in sorted(_PRODUCT_PREFIX_MAP, key=len, reverse=True):
        if desc.startswith(prefix + " "):
            remaining = desc[len(prefix) + 1 :]
            break
    if remaining is None:
        raise ValueError(
            f"Cannot extract issuer from description: {description!r}"
        )

    # Strip maturity hint and coupon hint.
    remaining = _MATURITY_HINT_RE.sub("", remaining)
    remaining = _COUPON_HINT_RE.sub("", remaining)

    return remaining.strip()


# ---------- Composition: parse a whole XPRow ----------


@dataclass(frozen=True, slots=True)
class ParsedXPRow:
    """An XPRow interpreted into typed domain values, awaiting issuer reconciliation.

    All fields have been parsed from their string forms in the original XPRow.
    The `issuer_name` is a normalized string ready to look up against the
    database (or to create a new Issuer with). The next pipeline layer
    (xp_loader) does that reconciliation.

    `principal` here is set to the ACQUISITION COST (`valor_aplicado_original`
    on the XP statement), not the current adjusted cost basis. That's the
    right input for our Investment.principal — it's what was paid at purchase.
    """

    product: ProductType
    issuer_name: str
    principal: Money
    rate: Rate
    purchase_date: date
    maturity_date: date
    coupon_frequency: CouponFrequency
    description: str  # original description preserved for trace/debugging


def parse_row(row: XPRow) -> ParsedXPRow:
    """Convert an XPRow into a ParsedXPRow with all fields typed.

    Composes the five primitive parsers. The order doesn't matter
    semantically (each parser is independent), but we proceed roughly
    in document order.

    Raises:
        ValueError: From any of the underlying parsers, with a wrapped
            message that identifies the offending row by description.
    """
    try:
        product, coupon = parse_product_and_coupon(row.description)
        issuer_name = parse_issuer_name(row.description)
        principal = parse_brazilian_money(row.valor_original)
        rate = parse_rate(row.rate_text)
        purchase_dt = parse_brazilian_date(row.purchase_date_text)
        maturity_dt = parse_brazilian_date(row.maturity_date_text)
    except ValueError as e:
        # Re-raise with a contextual message so import errors are
        # debuggable from the position description.
        raise ValueError(
            f"Could not parse XP row {row.description!r}: {e}"
        ) from e

    return ParsedXPRow(
        product=product,
        issuer_name=issuer_name,
        principal=principal,
        rate=rate,
        purchase_date=purchase_dt,
        maturity_date=maturity_dt,
        coupon_frequency=coupon,
        description=row.description,
    )