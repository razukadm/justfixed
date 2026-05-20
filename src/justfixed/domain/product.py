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

    def to_display(self) -> str:
        return {
            CouponFrequency.NONE:        "Nenhum",
            CouponFrequency.MONTHLY:     "Mensal",
            CouponFrequency.SEMI_ANNUAL: "Semestral",
        }[self]


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
        allowed_issuer_kinds=frozenset({
            # Knowingly-possible CDB issuers: deposit-taking institutions that
            # issue CDBs. Commercial, multiple, investment, and development banks
            # all take deposits and issue CDBs; Caixa Econômica issues CDBs;
            # credit cooperatives issue CDBs (confirmed — CDB is among the
            # cooperative deposit products covered by FGCoop).
            # CREDIT_FINANCE_INVESTMENT_COMPANY, REAL_ESTATE_CREDIT_COMPANY,
            # MORTGAGE_COMPANY, and SAVINGS_LOAN_ASSOCIATION are excluded as
            # unconfirmed — if a real CDB from one appears and crashes the
            # loader, that crash is the signal to verify and add it.
            IssuerKind.COMMERCIAL_BANK,
            IssuerKind.MULTIPLE_BANK,
            IssuerKind.INVESTMENT_BANK,
            IssuerKind.DEVELOPMENT_BANK,
            IssuerKind.CAIXA_ECONOMICA,
            IssuerKind.COOP,
        }),
        fgc_covered=True,
        tax_treatment=TaxTreatment.IR_REGRESSIVE,
        allowed_coupons=frozenset(CouponFrequency),  # any
        display_name="CDB",
    ),
    ProductType.LCI: ProductRule(
        allowed_issuer_kinds=frozenset({
            # Knowingly-possible LCI issuers (Banco Central authorizations,
            # corroborated from public sources). DEVELOPMENT_BANK and
            # INVESTMENT_BANK are excluded as unconfirmed — if a real LCI
            # from either appears, the crash is the signal to verify and add it.
            IssuerKind.COMMERCIAL_BANK,
            IssuerKind.MULTIPLE_BANK,
            IssuerKind.CAIXA_ECONOMICA,
            IssuerKind.CREDIT_FINANCE_INVESTMENT_COMPANY,
            IssuerKind.REAL_ESTATE_CREDIT_COMPANY,
            IssuerKind.MORTGAGE_COMPANY,
            IssuerKind.SAVINGS_LOAN_ASSOCIATION,
            IssuerKind.COOP,
        }),
        fgc_covered=True,
        tax_treatment=TaxTreatment.IR_EXEMPT,
        # LCI is NONE-only until a real coupon-paying LCI appears in broker
        # data and crashes the loader — same audit-when-it-crashes discipline.
        allowed_coupons=frozenset({CouponFrequency.NONE}),
        display_name="LCI",
    ),
    ProductType.LCA: ProductRule(
        allowed_issuer_kinds=frozenset({
            # Knowingly-possible LCA issuers (Banco Central authorizations,
            # corroborated from public sources). DEVELOPMENT_BANK is a confirmed
            # LCA issuer — development banks operate in agribusiness credit.
            # INVESTMENT_BANK is excluded as unconfirmed — if a real LCA from one
            # appears, the crash is the signal to verify and add it.
            IssuerKind.COMMERCIAL_BANK,
            IssuerKind.MULTIPLE_BANK,
            IssuerKind.DEVELOPMENT_BANK,
            IssuerKind.CAIXA_ECONOMICA,
            IssuerKind.CREDIT_FINANCE_INVESTMENT_COMPANY,
            IssuerKind.REAL_ESTATE_CREDIT_COMPANY,
            IssuerKind.MORTGAGE_COMPANY,
            IssuerKind.SAVINGS_LOAN_ASSOCIATION,
            IssuerKind.COOP,
        }),
        fgc_covered=True,
        tax_treatment=TaxTreatment.IR_EXEMPT,
        # LCAs are commonly issued with monthly coupons in the Brazilian
        # market (juros mensais), and semi-annual variants exist too.
        # Allow any frequency; we trust the broker's reported value.
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