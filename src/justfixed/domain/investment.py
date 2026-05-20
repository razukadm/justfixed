"""Investment entity: one purchase of one fixed-income security.

Investments are entities (identity by UUID). All construction-time
validation is done in __post_init__; an Investment instance that exists
has already passed all invariants — making illegal states unrepresentable.

A note on dates:
  - issue_date: when the SECURITY was first issued. Used for regulatory
    minimum-term checks (e.g. LCD ≥ 12 months).
  - purchase_date: when YOU bought it. May be later than issue_date if
    bought on the secondary market. Used for holding-period tax brackets.
  - maturity_date: when the security matures (same for everyone).

When buying a fresh issuance (the common case), issue_date == purchase_date,
so issue_date defaults to purchase_date when not specified.

Validation rules enforced:
  1. principal must be positive
  2. maturity_date must be strictly after both issue_date and purchase_date
  3. purchase_date must be on or after issue_date
  4. issuer.kind must be in the product's allowed_issuer_kinds
  5. coupon_frequency must be in the product's allowed_coupons
  6. (maturity_date - issue_date) >= product's minimum_term_days
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Self

from justfixed.domain.issuer import Issuer
from justfixed.domain.money import Money
from justfixed.domain.product import (
    CouponFrequency,
    ProductType,
    rules_for,
)
from justfixed.domain.rates import Rate


class InvestmentSource(str, Enum):
    XP_IMPORT = "xp_import"
    MANUAL = "manual"


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
    issue_date: date | None = None
    coupon_frequency: CouponFrequency = CouponFrequency.NONE
    description: str = ""
    source: InvestmentSource = InvestmentSource.XP_IMPORT
    id: uuid.UUID = field(default_factory=uuid.uuid4)

    def __post_init__(self) -> None:
        # Default issue_date to purchase_date for primary-market buys.
        if self.issue_date is None:
            self.issue_date = self.purchase_date

        # 1. principal must be positive
        if self.principal <= Money.zero(self.principal.currency):
            raise ValueError(
                f"principal must be positive; got {self.principal.to_display()}"
            )

        # 2. maturity strictly after issue (security has positive term)
        if self.maturity_date <= self.issue_date:
            raise ValueError(
                f"maturity_date ({self.maturity_date}) must be after "
                f"issue_date ({self.issue_date})"
            )

        # 2b. maturity strictly after purchase (cannot buy a matured security)
        if self.maturity_date <= self.purchase_date:
            raise ValueError(
                f"maturity_date ({self.maturity_date}) must be after "
                f"purchase_date ({self.purchase_date})"
            )

        # 3. purchase on or after issue (cannot buy before issued)
        if self.purchase_date < self.issue_date:
            raise ValueError(
                f"purchase_date ({self.purchase_date}) cannot be before "
                f"issue_date ({self.issue_date})"
            )

        # Lookup product rules for the remaining checks.
        rule = rules_for(self.product)

        # 4. issuer kind must be in the product's allowed set
        if self.issuer.kind not in rule.allowed_issuer_kinds:
            allowed_kinds = ", ".join(sorted(k.value for k in rule.allowed_issuer_kinds))
            raise ValueError(
                f"{rule.display_name} requires issuer kind one of: "
                f"{allowed_kinds}; got {self.issuer.kind.value}"
            )

        # 5. coupon frequency must be allowed for this product
        if self.coupon_frequency not in rule.allowed_coupons:
            allowed_names = sorted(c.value for c in rule.allowed_coupons)
            raise ValueError(
                f"{rule.display_name} does not allow coupon frequency "
                f"{self.coupon_frequency.value}; allowed: {allowed_names}"
            )

        # 6. minimum security term (issue to maturity, NOT purchase to maturity)
        if rule.minimum_term_days > 0:
            security_term_days = (self.maturity_date - self.issue_date).days
            if security_term_days < rule.minimum_term_days:
                raise ValueError(
                    f"{rule.display_name} requires a minimum security term of "
                    f"{rule.minimum_term_days} days from issue to maturity; "
                    f"got {security_term_days}."
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
        issue_date: date | None = None,
        coupon_frequency: CouponFrequency = CouponFrequency.NONE,
        description: str = "",
        source: InvestmentSource = InvestmentSource.XP_IMPORT,
    ) -> Self:
        """Create a new Investment with an auto-generated UUID.

        If issue_date is not provided, it defaults to purchase_date
        (the common case of buying a fresh issuance).
        """
        return cls(
            product=product,
            issuer=issuer,
            principal=principal,
            rate=rate,
            purchase_date=purchase_date,
            maturity_date=maturity_date,
            issue_date=issue_date,
            coupon_frequency=coupon_frequency,
            description=description,
            source=source,
        )

    @property
    def security_term_days(self) -> int:
        """Total days of the security's life (issue to maturity)."""
        # issue_date is guaranteed non-None after __post_init__.
        assert self.issue_date is not None
        return (self.maturity_date - self.issue_date).days

    @property
    def holding_term_days(self) -> int:
        """Total days from purchase to maturity (your holding period)."""
        return (self.maturity_date - self.purchase_date).days

    @property
    def term_days(self) -> int:
        """Alias for holding_term_days, preserved for backward compatibility."""
        return self.holding_term_days

    @property
    def is_secondary_market(self) -> bool:
        """True if this position was bought on the secondary market."""
        assert self.issue_date is not None
        return self.purchase_date > self.issue_date

    @property
    def is_bullet(self) -> bool:
        """True if no coupons are paid before maturity."""
        return self.coupon_frequency == CouponFrequency.NONE

    @property
    def is_deposit_guaranteed(self) -> bool:
        """True if this investment is covered by a deposit-guarantee fund."""
        return rules_for(self.product).fgc_covered and self.issuer.is_deposit_guaranteed

    # Identity-based equality (entity).
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Investment):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)