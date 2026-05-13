"""Product taxonomy and rules for Brazilian fixed-income products.

Defines the supported product types in MVP scope and the metadata
each one carries: which issuer kind it requires, whether it's FGC-
covered, whether interest is IR-exempt for individuals, and which
coupon frequencies are allowed.

Adding a new product requires:
  1. Adding a ProductType enum value.
  2. Adding a ProductRule entry to PRODUCT_RULES.
  3. Updating any match statements in the engine (the type checker
     will flag missing branches if the engine uses exhaustive match).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from justfixed.domain.issuer import IssuerKind


class ProductType(Enum):
    """All MVP-supported fixed-income product types."""

    CDB = "cdb"
    LCI = "lci"
    LCA = "lca"
    LC = "lc"
    LCD = "lcd"
    TESOURO_SELIC = "tesouro_selic"
    TESOURO_PREFIXADO = "tesouro_prefixado"
    TESOURO_IPCA = "tesouro_ipca"


class CouponFrequency(Enum):
    """How often a product pays coupons (juros) before maturity."""

    NONE = "none"           # bullet: principal + interest at maturity
    MONTHLY = "monthly"     # interest paid every month
    SEMI_ANNUAL = "semi_annual"  # interest paid every 6 months


class TaxTreatment(Enum):
    """How interest income is taxed for individuals (PF)."""

    IR_REGRESSIVE = "ir_regressive"  # 22.5% / 20% / 17.5% / 15% by holding days
    IR_EXEMPT = "ir_exempt"           # no IR for PF


@dataclass(frozen=True, slots=True)
class ProductRule:
    """Static metadata for one ProductType.

    Used by both validation (Investment.__post_init__) and the engine
    (tax computation, FGC concentration). Single source of truth.
    """

    allowed_issuer_kinds: frozenset[IssuerKind]
    fgc_covered: bool
    tax_treatment: TaxTreatment
    allowed_coupons: frozenset[CouponFrequency]
    minimum_term_days: int = 0  # 0 means no enforced minimum
    display_name: str = ""


# Single source of truth for product rules.
# Note: minimum_term_days reflects regulatory minimums we want to enforce
# at the domain level; it is not a market-typical-term.
PRODUCT_RULES: dict[ProductType, ProductRule] = {
    ProductType.CDB: ProductRule(
        allowed_issuer_kinds=frozenset({IssuerKind.COMMERCIAL_BANK}),
        fgc_covered=True,
        tax_treatment=TaxTreatment.IR_REGRESSIVE,
        allowed_coupons=frozenset(CouponFrequency),  # any
        display_name="CDB",
    ),
    ProductType.LCI: ProductRule(
        allowed_issuer_kinds=frozenset({IssuerKind.COMMERCIAL_BANK}),
        fgc_covered=True,
        tax_treatment=TaxTreatment.IR_EXEMPT,
        allowed_coupons=frozenset({CouponFrequency.NONE}),
        display_name="LCI",
    ),
    ProductType.LCA: ProductRule(
        allowed_issuer_kinds=frozenset({IssuerKind.COMMERCIAL_BANK, IssuerKind.DEVELOPMENT_BANK}),
        fgc_covered=True,
        tax_treatment=TaxTreatment.IR_EXEMPT,
        # LCAs are commonly issued with monthly coupons in the Brazilian
        # market (juros mensais), and semi-annual variants exist too.
        # Allow any frequency; we trust the broker's reported value.
        # Note: LCI is more conservative (NONE only) until real-world
        # data shows otherwise — same audit-when-it-crashes discipline.
        allowed_coupons=frozenset(CouponFrequency),
        display_name="LCA",
    ),
    ProductType.LC: ProductRule(
        allowed_issuer_kinds=frozenset({IssuerKind.COMMERCIAL_BANK}),
        fgc_covered=True,
        tax_treatment=TaxTreatment.IR_REGRESSIVE,
        allowed_coupons=frozenset(CouponFrequency),
        display_name="Letra de Câmbio",
    ),
    ProductType.LCD: ProductRule(
        allowed_issuer_kinds=frozenset({IssuerKind.DEVELOPMENT_BANK}),
        fgc_covered=True,
        tax_treatment=TaxTreatment.IR_EXEMPT,
        allowed_coupons=frozenset({CouponFrequency.NONE}),
        minimum_term_days=365,  # 12 months minimum (per regulation)
        display_name="LCD",
    ),
    ProductType.TESOURO_SELIC: ProductRule(
        allowed_issuer_kinds=frozenset({IssuerKind.TREASURY}),
        fgc_covered=False,
        tax_treatment=TaxTreatment.IR_REGRESSIVE,
        allowed_coupons=frozenset({CouponFrequency.NONE}),
        display_name="Tesouro Selic",
    ),
    ProductType.TESOURO_PREFIXADO: ProductRule(
        allowed_issuer_kinds=frozenset({IssuerKind.TREASURY}),
        fgc_covered=False,
        tax_treatment=TaxTreatment.IR_REGRESSIVE,
        allowed_coupons=frozenset({CouponFrequency.NONE, CouponFrequency.SEMI_ANNUAL}),
        display_name="Tesouro Prefixado",
    ),
    ProductType.TESOURO_IPCA: ProductRule(
        allowed_issuer_kinds=frozenset({IssuerKind.TREASURY}),
        fgc_covered=False,
        tax_treatment=TaxTreatment.IR_REGRESSIVE,
        allowed_coupons=frozenset({CouponFrequency.NONE, CouponFrequency.SEMI_ANNUAL}),
        display_name="Tesouro IPCA+",
    ),
}


def rules_for(product: ProductType) -> ProductRule:
    """Look up the ProductRule for a given ProductType."""
    return PRODUCT_RULES[product]