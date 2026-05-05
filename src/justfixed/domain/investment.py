"""Investment entity: one purchase of one fixed-income security.

Investments are entities (identity by UUID). All construction-time
validation is done in __post_init__; an Investment instance that exists
has already passed all invariants — making illegal states unrepresentable.

Validation rules enforced:
  1. principal must be positive
  2. maturity_date must be strictly after purchase_date
  3. issuer.kind must match the product's required_issuer_kind
  4. coupon_frequency must be in the product's allowed_coupons
  5. (maturity - purchase) >= product's minimum_term_days
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Self

from justfixed.domain.issuer import Issuer
from justfixed.domain.money import Money
from justfixed.domain.product import (
    CouponFrequency,
    ProductType,
    rules_for,
)
from justfixed.domain.rates import Rate


@dataclass(slots=True)
class Investment:
    """A single purchase of a fixed-income security.

    Construct via `Investment.create(...)` for new investments;
    pass an explicit `id` only when reconstructing from persistence.
    """

    product: ProductType
    issuer: Issuer
    principal: Money
    rate: Rate
    purchase_date: date
    maturity_date: date
    coupon_frequency: CouponFrequency = CouponFrequency.NONE
    description: str = ""
    id: uuid.UUID = field(default_factory=uuid.uuid4)

    def __post_init__(self) -> None:
        # 1. principal must be positive
        if self.principal <= Money.zero(self.principal.currency):
            raise ValueError(
                f"principal must be positive; got {self.principal.to_display()}"
            )

        # 2. maturity strictly after purchase
        if self.maturity_date <= self.purchase_date:
            raise ValueError(
                f"maturity_date ({self.maturity_date}) must be after "
                f"purchase_date ({self.purchase_date})"
            )

        # Lookup product rules for the remaining checks.
        rule = rules_for(self.product)

        # 3. issuer kind must match product
        if self.issuer.kind != rule.required_issuer_kind:
            raise ValueError(
                f"{rule.display_name} requires issuer kind "
                f"{rule.required_issuer_kind.value}; got {self.issuer.kind.value}"
            )

        # 4. coupon frequency must be allowed for this product
        if self.coupon_frequency not in rule.allowed_coupons:
            allowed_names = sorted(c.value for c in rule.allowed_coupons)
            raise ValueError(
                f"{rule.display_name} does not allow coupon frequency "
                f"{self.coupon_frequency.value}; allowed: {allowed_names}"
            )

        # 5. minimum term (e.g. LCD ≥ 12 months)
        if rule.minimum_term_days > 0:
            term_days = (self.maturity_date - self.purchase_date).days
            if term_days < rule.minimum_term_days:
                raise ValueError(
                    f"{rule.display_name} requires a minimum term of "
                    f"{rule.minimum_term_days} days; got {term_days}."
                )

        # Normalize description.
        self.description = self.description.strip()

    @classmethod
    def create(
        cls,
        product: ProductType,
        issuer: Issuer,
        principal: Money,
        rate: Rate,
        purchase_date: date,
        maturity_date: date,
        coupon_frequency: CouponFrequency = CouponFrequency.NONE,
        description: str = "",
    ) -> Self:
        """Create a new Investment with an auto-generated UUID."""
        return cls(
            product=product,
            issuer=issuer,
            principal=principal,
            rate=rate,
            purchase_date=purchase_date,
            maturity_date=maturity_date,
            coupon_frequency=coupon_frequency,
            description=description,
        )

    @property
    def term_days(self) -> int:
        """Total days between purchase and maturity (calendar days)."""
        return (self.maturity_date - self.purchase_date).days

    @property
    def is_bullet(self) -> bool:
        """True if no coupons are paid before maturity."""
        return self.coupon_frequency == CouponFrequency.NONE

    @property
    def is_fgc_covered(self) -> bool:
        """True if this investment is covered by FGC.

        Both the product type AND the issuer must be FGC-eligible.
        """
        return rules_for(self.product).fgc_covered and self.issuer.is_fgc_covered

    # Identity-based equality (entity).
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Investment):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)