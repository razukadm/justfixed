"""Tests for the FGC back-solve engine (engine/back_solve.py).

Eight test cases (A–H) covering the full contract:

  A — no existing holdings: only maturity date is binding
  B — binding at an interior date: existing holding matures mid-window
  C — pre-window holding excluded: matured before mock starts → filtered
  D — Treasury holding excluded: non-FGC issuer → filtered
  E — different-issuer holding excluded: name mismatch → filtered
  F — over-cap at start: existing_total >= cap → max_principal = 0
  G — rate-type guards: non-Prefixed rates raise NotImplementedError
  H — rounding: ROUND_DOWN, not ROUND_HALF_UP

Financial expected values are computed inline using exact Decimal arithmetic
and the same formula as the implementation. No floats; no approximation.
"""

from __future__ import annotations

import pytest
from datetime import date
from decimal import Decimal, ROUND_DOWN

from justfixed.domain.investment import Investment
from justfixed.domain.issuer import Issuer, IssuerKind
from justfixed.domain.money import Money
from justfixed.domain.product import ProductType
from justfixed.domain.rates import (
    PostFixedCDI,
    PostFixedCDIPlusSpread,
    PostFixedIPCA,
    Prefixed,
)
from justfixed.engine.back_solve import (
    BackSolveResult,
    FGC_CAP,
    max_principal_under_fgc,
)
from justfixed.engine.calendar import business_days_between

# ── Shared constants ──────────────────────────────────────────────────────────

ASSUMED_CDI  = Decimal("0.1065")
ASSUMED_IPCA = Decimal("0.0480")

_ONE  = Decimal("1")
_252  = Decimal("252")
_CENT = Decimal("0.01")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _bank(name: str) -> Issuer:
    return Issuer.create(name, name, IssuerKind.COMMERCIAL_BANK)


def _cdb(
    issuer: Issuer,
    principal: str,
    purchase: date,
    maturity: date,
    rate_pct: str = "10",
) -> Investment:
    return Investment.create(
        product=ProductType.CDB,
        issuer=issuer,
        principal=Money.from_reais(principal),
        rate=Prefixed.from_percent(rate_pct),
        purchase_date=purchase,
        maturity_date=maturity,
    )


def _growth(r: Decimal, purchase: date, as_of: date) -> Decimal:
    """(1 + r)^(bdays / 252) — same formula as back_solve uses."""
    bdays = business_days_between(purchase, as_of)
    return (_ONE + r) ** (Decimal(bdays) / _252)


# ── Test A: No existing holdings ──────────────────────────────────────────────

def test_a_empty_holdings() -> None:
    """Only the maturity date binds when there are no existing holdings.

    Sample dates: [T0, T1].
    At T0: existing=0, growth=1,          bound = 250000
    At T1: existing=0, growth=growth_T1,  bound = 250000 / growth_T1
    Since growth_T1 > 1, maturity is binding.
    max_principal = ROUND_DOWN(250000 / growth_T1)
    """
    issuer_name = "Banco Alpha"
    rate = Prefixed.from_percent("10")
    T0 = date(2024, 1, 2)
    T1 = date(2025, 1, 2)

    g = _growth(rate.annual_rate, T0, T1)
    expected_max = (Decimal("250000.00") / g).quantize(_CENT, rounding=ROUND_DOWN)

    result = max_principal_under_fgc(
        issuer_name=issuer_name,
        product=ProductType.CDB,
        rate=rate,
        purchase_date=T0,
        maturity_date=T1,
        existing_holdings=[],
        assumed_cdi=ASSUMED_CDI,
        assumed_ipca=ASSUMED_IPCA,
    )

    assert result.max_principal == expected_max
    assert result.peak_date == T1
    assert result.effective_rate_aa == rate.annual_rate


# ── Test B: Binding at an interior date ───────────────────────────────────────

def test_b_binding_at_interior_date() -> None:
    """An existing holding that matures mid-window creates the tightest bound
    at its maturity date, not at the mock's start or end.

    Mock:     T0 ──────────────────────────── T2   (10% a.a.)
    Existing: T0 ──────────── T1                   (10% a.a., R$200,000)

    At T0: existing=200,000, growth=1,   bound = (250k-200k)/1     = 50,000
    At T1: existing=200k*g1, growth=g1,  bound = 250k/g1 - 200k   ≈ 38,000
    At T2: existing=0,        growth=g2,  bound = 250k/g2          ≈ 227,272

    T1 is the binding date (≈38k < 50k < 227k).
    max_principal = ROUND_DOWN(250k/g1 - 200k)
    """
    issuer_name = "Banco Beta"
    rate = Prefixed.from_percent("10")
    T0 = date(2024, 1, 2)
    T1 = date(2024, 7, 1)   # existing holding matures here
    T2 = date(2025, 1, 2)

    bank = _bank(issuer_name)
    existing = _cdb(bank, "200000", T0, T1)

    r = rate.annual_rate
    g1 = _growth(r, T0, T1)
    expected_max = (Decimal("250000.00") / g1 - Decimal("200000.00")).quantize(
        _CENT, rounding=ROUND_DOWN
    )

    result = max_principal_under_fgc(
        issuer_name=issuer_name,
        product=ProductType.CDB,
        rate=rate,
        purchase_date=T0,
        maturity_date=T2,
        existing_holdings=[existing],
        assumed_cdi=ASSUMED_CDI,
        assumed_ipca=ASSUMED_IPCA,
    )

    assert result.max_principal == expected_max
    assert result.peak_date == T1


# ── Test C: Pre-window holding excluded ───────────────────────────────────────

def test_c_pre_window_holding_excluded() -> None:
    """A holding that matured before the mock's purchase_date does not overlap
    the mock's window and is filtered out.  Result equals the empty-holdings case.
    """
    issuer_name = "Banco Gamma"
    rate = Prefixed.from_percent("10")
    T0 = date(2024, 6, 3)   # mock starts here
    T1 = date(2025, 6, 2)   # mock ends here

    bank = _bank(issuer_name)
    # This holding matured before T0 — zero overlap.
    pre_window = _cdb(bank, "200000", date(2023, 1, 2), date(2024, 1, 2))

    r = rate.annual_rate
    g = _growth(r, T0, T1)
    expected_max = (Decimal("250000.00") / g).quantize(_CENT, rounding=ROUND_DOWN)

    result = max_principal_under_fgc(
        issuer_name=issuer_name,
        product=ProductType.CDB,
        rate=rate,
        purchase_date=T0,
        maturity_date=T1,
        existing_holdings=[pre_window],
        assumed_cdi=ASSUMED_CDI,
        assumed_ipca=ASSUMED_IPCA,
    )

    assert result.max_principal == expected_max
    assert result.peak_date == T1


# ── Test D: Treasury holding excluded ─────────────────────────────────────────

def test_d_treasury_excluded() -> None:
    """A Treasury (Tesouro Nacional) holding with the same name as the mock
    issuer is excluded because issuer.kind == TREASURY.

    In practice a Treasury issuer won't share a name with a bank, but the
    filter is on kind — not name — so this test makes the exclusion explicit.
    """
    issuer_name = "Banco Delta"
    rate = Prefixed.from_percent("10")
    T0 = date(2024, 1, 2)
    T1 = date(2025, 1, 2)

    treasury_issuer = Issuer.create(
        issuer_name, issuer_name, IssuerKind.TREASURY
    )
    treasury_holding = Investment.create(
        product=ProductType.TESOURO_PREFIXADO,
        issuer=treasury_issuer,
        principal=Money.from_reais("200000"),
        rate=Prefixed.from_percent("10"),
        purchase_date=T0,
        maturity_date=T1,
    )

    r = rate.annual_rate
    g = _growth(r, T0, T1)
    expected_max = (Decimal("250000.00") / g).quantize(_CENT, rounding=ROUND_DOWN)

    result = max_principal_under_fgc(
        issuer_name=issuer_name,
        product=ProductType.CDB,
        rate=rate,
        purchase_date=T0,
        maturity_date=T1,
        existing_holdings=[treasury_holding],
        assumed_cdi=ASSUMED_CDI,
        assumed_ipca=ASSUMED_IPCA,
    )

    assert result.max_principal == expected_max


# ── Test E: Different-issuer holding excluded ─────────────────────────────────

def test_e_different_issuer_excluded() -> None:
    """A holding with a different issuer name is not counted toward the cap."""
    rate = Prefixed.from_percent("10")
    T0 = date(2024, 1, 2)
    T1 = date(2025, 1, 2)

    other_bank = _bank("Banco Outro")
    other_holding = _cdb(other_bank, "200000", T0, T1)

    r = rate.annual_rate
    g = _growth(r, T0, T1)
    expected_max = (Decimal("250000.00") / g).quantize(_CENT, rounding=ROUND_DOWN)

    result = max_principal_under_fgc(
        issuer_name="Banco Epsilon",
        product=ProductType.CDB,
        rate=rate,
        purchase_date=T0,
        maturity_date=T1,
        existing_holdings=[other_holding],
        assumed_cdi=ASSUMED_CDI,
        assumed_ipca=ASSUMED_IPCA,
    )

    assert result.max_principal == expected_max


# ── Test F: Over-cap at start ─────────────────────────────────────────────────

def test_f_over_cap_at_start() -> None:
    """When existing holdings already reach or exceed the cap at purchase_date,
    max_principal is 0.

    At T0: existing=250,000, growth=1,   bound = (250k-250k)/1         = 0
    At T1: existing=250k*g1, growth=g1,  bound = (250k-250k*g1)/g1 < 0
    Binding date is T1 (more negative); max_principal = ROUND_DOWN(0) = 0.
    """
    issuer_name = "Banco Zeta"
    rate = Prefixed.from_percent("10")
    T0 = date(2024, 1, 2)
    T1 = date(2025, 1, 2)

    bank = _bank(issuer_name)
    # existing principal == cap; value at T0 == principal (no accrual yet)
    at_cap = _cdb(bank, "250000", T0, T1)

    result = max_principal_under_fgc(
        issuer_name=issuer_name,
        product=ProductType.CDB,
        rate=rate,
        purchase_date=T0,
        maturity_date=T1,
        existing_holdings=[at_cap],
        assumed_cdi=ASSUMED_CDI,
        assumed_ipca=ASSUMED_IPCA,
    )

    assert result.max_principal == Decimal("0.00")
    assert result.projected_at_maturity == Decimal("0.00")


# ── Test G: Rate-type guards ──────────────────────────────────────────────────

@pytest.mark.parametrize("bad_rate", [
    PostFixedCDI.from_percent("110"),
    PostFixedIPCA.from_percent("5"),
    PostFixedCDIPlusSpread.from_percent("2"),
])
def test_g_non_prefixed_raises(bad_rate) -> None:
    """All non-Prefixed rate types raise NotImplementedError (Phase 1.5 work)."""
    with pytest.raises(NotImplementedError):
        max_principal_under_fgc(
            issuer_name="Banco Any",
            product=ProductType.CDB,
            rate=bad_rate,
            purchase_date=date(2024, 1, 2),
            maturity_date=date(2025, 1, 2),
            existing_holdings=[],
            assumed_cdi=ASSUMED_CDI,
            assumed_ipca=ASSUMED_IPCA,
        )


# ── Test H: ROUND_DOWN, not ROUND_HALF_UP ────────────────────────────────────

def test_h_rounding_direction() -> None:
    """max_principal is rounded DOWN so the cap is never violated.

    Verifies two invariants for the empty-holdings case:
      1.  max_principal * growth_at_maturity  <= cap         (cap never breached)
      2. (max_principal + 0.01) * growth_at_maturity > cap   (no cent left on the table)

    Condition 2 only holds when the unrounded bound is not exactly a cent
    boundary.  It will fail (incorrectly report a test failure) if growth
    happens to divide 250,000 exactly — astronomically unlikely for a real
    ANBIMA business-day count but noted for completeness.
    """
    rate = Prefixed.from_percent("10")
    T0 = date(2024, 1, 2)
    T1 = date(2025, 1, 2)

    result = max_principal_under_fgc(
        issuer_name="Banco Eta",
        product=ProductType.CDB,
        rate=rate,
        purchase_date=T0,
        maturity_date=T1,
        existing_holdings=[],
        assumed_cdi=ASSUMED_CDI,
        assumed_ipca=ASSUMED_IPCA,
    )

    g = _growth(rate.annual_rate, T0, T1)
    cap = Decimal("250000.00")

    # Invariant 1: cap is never breached.
    assert result.max_principal * g <= cap

    # Invariant 2: could not round up even one cent without breaching.
    one_cent_more = result.max_principal + Decimal("0.01")
    assert one_cent_more * g > cap
