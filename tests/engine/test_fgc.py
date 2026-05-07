"""Tests for the FGC concentration engine (engine/fgc.py).

All eleven tests are specified in docs/FGC_DESIGN.md. The file is written
before engine/fgc.py exists; all tests fail with ImportError until the
engine is implemented.

Financial expected values:
- Tests 1–8, 11: as_of == purchase_date, so current_value == principal exactly.
  No accrual math needed; principal is hardcoded as the expected exposure.
- Tests 9, 10: values computed 2026-05-07 via scratch_compute_test9.py using
  the live projection engine. Raw Decimal amounts (8 decimal places) are
  hardcoded; the math is documented in each test's comment.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from justfixed.domain.investment import Investment
from justfixed.domain.issuer import Issuer, IssuerKind, UNVERIFIED_CONGLOMERATE_PREFIX
from justfixed.domain.money import Money
from justfixed.domain.product import ProductType
from justfixed.domain.rates import Prefixed
from justfixed.engine.fgc import (
    ConglomerateExposure,
    ExposureStatus,
    FGCReport,
    InvestmentExposure,
    fgc_concentration_report,
)

# ── Shared constants ─────────────────────────────────────────────────────────

ASSUMED_CDI = Decimal("0.12")

# All tests that use as_of == purchase_date anchor to this date.
PURCHASE = date(2025, 1, 2)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _bank(name: str, conglomerate: str) -> Issuer:
    return Issuer.create(name, conglomerate, IssuerKind.COMMERCIAL_BANK)


def _cdb(
    issuer: Issuer,
    principal: str,
    maturity: date,
    purchase: date = PURCHASE,
) -> Investment:
    return Investment.create(
        product=ProductType.CDB,
        issuer=issuer,
        principal=Money.from_reais(principal),
        rate=Prefixed.from_percent("12"),
        purchase_date=purchase,
        maturity_date=maturity,
    )


# ── Group A: Empty and trivial cases ─────────────────────────────────────────

def test_empty_portfolio_returns_empty_report() -> None:
    report = fgc_concentration_report([], as_of=PURCHASE, assumed_cdi=ASSUMED_CDI)
    assert report.conglomerates == []
    assert report.total_current_exposure == Money.zero()
    assert report.total_peak_exposure == Money.zero()
    assert report.conglomerates_at_or_over_limit == []


def test_only_treasury_holdings_returns_empty_report() -> None:
    # Treasury is not FGC-covered; even large holdings produce no FGC exposure.
    inv = Investment.create(
        product=ProductType.TESOURO_PREFIXADO,
        issuer=Issuer.treasury(),
        principal=Money.from_reais("500000"),
        rate=Prefixed.from_percent("12"),
        purchase_date=PURCHASE,
        maturity_date=date(2027, 1, 2),
    )
    report = fgc_concentration_report([inv], as_of=PURCHASE, assumed_cdi=ASSUMED_CDI)
    assert report.conglomerates == []


def test_single_conglomerate_under_limit() -> None:
    # as_of == purchase_date → current_value == principal == R$ 50,000.
    bank = _bank("Banco Inter", "Banco Inter S.A.")
    inv = _cdb(bank, "50000", date(2026, 1, 2))
    report = fgc_concentration_report([inv], as_of=PURCHASE, assumed_cdi=ASSUMED_CDI)
    assert len(report.conglomerates) == 1
    c = next(c for c in report.conglomerates if c.conglomerate_name == "Banco Inter S.A.")
    assert c.current_status == ExposureStatus.UNDER
    assert c.current_exposure == Money.from_reais("50000")


# ── Group B: Status tier boundaries ──────────────────────────────────────────

def test_status_under_below_approaching_threshold() -> None:
    # R$ 199,000 < R$ 200,000 threshold → UNDER.  as_of == purchase_date.
    bank = _bank("Banco A", "Banco A S.A.")
    inv = _cdb(bank, "199000", date(2026, 1, 2))
    report = fgc_concentration_report([inv], as_of=PURCHASE, assumed_cdi=ASSUMED_CDI)
    c = next(c for c in report.conglomerates if c.conglomerate_name == "Banco A S.A.")
    assert c.current_status == ExposureStatus.UNDER
    assert c.current_exposure == Money.from_reais("199000")
    assert report.conglomerates_at_or_over_limit == []


def test_status_approaching_between_thresholds() -> None:
    # R$ 220,000 in [200k, 250k] → APPROACHING.  as_of == purchase_date.
    bank = _bank("Banco B", "Banco B S.A.")
    inv = _cdb(bank, "220000", date(2026, 1, 2))
    report = fgc_concentration_report([inv], as_of=PURCHASE, assumed_cdi=ASSUMED_CDI)
    c = next(c for c in report.conglomerates if c.conglomerate_name == "Banco B S.A.")
    assert c.current_status == ExposureStatus.APPROACHING
    assert c.current_exposure == Money.from_reais("220000")


def test_status_over_above_limit() -> None:
    # R$ 280,000 > R$ 250,000 limit → OVER.  as_of == purchase_date.
    bank = _bank("Banco C", "Banco C S.A.")
    inv = _cdb(bank, "280000", date(2026, 1, 2))
    report = fgc_concentration_report([inv], as_of=PURCHASE, assumed_cdi=ASSUMED_CDI)
    c = next(c for c in report.conglomerates if c.conglomerate_name == "Banco C S.A.")
    assert c.current_status == ExposureStatus.OVER
    assert c.current_exposure == Money.from_reais("280000")
    assert report.total_current_exposure == Money.from_reais("280000")
    assert len(report.conglomerates_at_or_over_limit) == 1
    assert report.conglomerates_at_or_over_limit[0].conglomerate_name == "Banco C S.A."


# ── Group C: Multi-investment aggregation ────────────────────────────────────

def test_multiple_investments_same_conglomerate_sum() -> None:
    # Three CDBs at R$ 100k each → sum R$ 300k → OVER.  as_of == purchase_date.
    bank = _bank("Banco Inter", "Banco Inter S.A.")
    invs = [_cdb(bank, "100000", date(2026, 1, 2)) for _ in range(3)]
    report = fgc_concentration_report(invs, as_of=PURCHASE, assumed_cdi=ASSUMED_CDI)
    assert len(report.conglomerates) == 1
    c = next(c for c in report.conglomerates if c.conglomerate_name == "Banco Inter S.A.")
    assert c.current_exposure == Money.from_reais("300000")
    assert c.current_status == ExposureStatus.OVER
    assert len(c.investments) == 3
    assert report.total_current_exposure == Money.from_reais("300000")
    assert len(report.conglomerates_at_or_over_limit) == 1


def test_multiple_conglomerates_separate_rows() -> None:
    # Three banks → three separate conglomerate rows, sorted by exposure desc.
    invs = [
        _cdb(_bank("Banco A", "Banco A S.A."), "50000",  date(2026, 1, 2)),
        _cdb(_bank("Banco B", "Banco B S.A."), "80000",  date(2026, 1, 2)),
        _cdb(_bank("Banco C", "Banco C S.A."), "120000", date(2026, 1, 2)),
    ]
    report = fgc_concentration_report(invs, as_of=PURCHASE, assumed_cdi=ASSUMED_CDI)
    assert len(report.conglomerates) == 3
    assert {c.conglomerate_name for c in report.conglomerates} == {
        "Banco A S.A.", "Banco B S.A.", "Banco C S.A."
    }
    # Primary sort: current_exposure descending.
    assert report.conglomerates[0].conglomerate_name == "Banco C S.A."
    assert report.conglomerates[1].conglomerate_name == "Banco B S.A."
    assert report.conglomerates[2].conglomerate_name == "Banco A S.A."


# ── Group D: Peak vs current divergence ──────────────────────────────────────

def test_peak_status_can_exceed_current_status() -> None:
    # Computed 2026-05-07 via scratch_compute_test9.py using project() directly.
    # project().current_value is gross (no tax deducted); gross_at_maturity is
    # pre-tax gross at maturity. Both used directly by the FGC engine.
    #
    #   principal      : R$ 210,000.00
    #   rate           : 12% a.a. prefixed
    #   purchase_date  : 2025-01-02
    #   as_of          : 2025-11-03
    #   maturity_date  : 2026-11-02
    #
    #   Du purchase → as_of    : 211 business days
    #   Du purchase → maturity : 459 business days
    #
    #   current_value.amount    : 230903.02537584  → APPROACHING [200k, 250k]
    #   gross_at_maturity.amount: 258146.59883741  → OVER (> 250k)
    bank = _bank("Banco Approaching", "Banco Approaching S.A.")
    inv = _cdb(bank, "210000", date(2026, 11, 2))
    report = fgc_concentration_report(
        [inv], as_of=date(2025, 11, 3), assumed_cdi=ASSUMED_CDI
    )
    # Lookup by issuer.conglomerate ("Banco Approaching S.A."), not issuer.name
    # ("Banco Approaching") — the engine groups by conglomerate, not brand name.
    c = next(c for c in report.conglomerates if c.conglomerate_name == "Banco Approaching S.A.")
    assert c.current_status == ExposureStatus.APPROACHING
    assert c.peak_status == ExposureStatus.OVER
    assert c.current_exposure == Money(amount=Decimal("230903.02537584"), currency="BRL")
    assert c.peak_exposure == Money(amount=Decimal("258146.59883741"), currency="BRL")


def test_peak_exposure_sum_of_per_investment_maturity_values() -> None:
    # Computed 2026-05-07 via scratch_compute_test9.py using project() directly.
    # as_of == purchase_date so current_value == principal exactly (no accrual).
    # Peak is gross_at_maturity at each investment's OWN maturity — a deliberate
    # conservative overestimate (simultaneous peaks are impossible in practice).
    # If both investments were projected to the later date (2027-01-02),
    # peak_exposure would be ~R$ 301k instead of ~R$ 285k — that would be wrong,
    # and this test catches that bug.
    #
    #   principal each : R$ 120,000.00   rate: 12% a.a. prefixed
    #   purchase_date  : 2025-01-02   as_of: 2025-01-02
    #   maturity_A     : 2026-01-02  (Du = 252 bd → factor = 1.12 exactly)
    #   maturity_B     : 2027-01-02  (Du = 500 bd)
    #
    #   inv_A gross_at_maturity.amount : 134400.00000000  (= 120000 × 1.12)
    #   inv_B gross_at_maturity.amount : 150257.46339735
    #   peak_sum.amount                : 284657.46339735
    bank = _bank("Banco Dual", "Banco Dual S.A.")
    inv_a = _cdb(bank, "120000", date(2026, 1, 2))
    inv_b = _cdb(bank, "120000", date(2027, 1, 2))
    report = fgc_concentration_report([inv_a, inv_b], as_of=PURCHASE, assumed_cdi=ASSUMED_CDI)
    c = next(c for c in report.conglomerates if c.conglomerate_name == "Banco Dual S.A.")

    assert c.current_exposure == Money.from_reais("240000")  # 120k + 120k exactly
    assert c.peak_exposure == Money(amount=Decimal("284657.46339735"), currency="BRL")

    # Pin the per-investment maturity contributions individually.
    exp_a = next(e for e in c.investments if e.maturity_date == date(2026, 1, 2))
    exp_b = next(e for e in c.investments if e.maturity_date == date(2027, 1, 2))
    assert exp_a.peak_value == Money(amount=Decimal("134400.00000000"), currency="BRL")
    assert exp_b.peak_value == Money(amount=Decimal("150257.46339735"), currency="BRL")


# ── Group E: Unverified conglomerate handling ─────────────────────────────────

def test_unverified_conglomerate_flagged() -> None:
    # Two unverified banks and one verified bank — pins both directions of the flag.
    invs = [
        _cdb(_bank("BMG",  f"{UNVERIFIED_CONGLOMERATE_PREFIX}BMG"),  "50000", date(2026, 1, 2)),
        _cdb(_bank("PINE", f"{UNVERIFIED_CONGLOMERATE_PREFIX}PINE"), "50000", date(2026, 1, 2)),
        _cdb(_bank("Banco XP", "Banco XP S.A."),                     "50000", date(2026, 1, 2)),
    ]
    report = fgc_concentration_report(invs, as_of=PURCHASE, assumed_cdi=ASSUMED_CDI)
    assert len(report.conglomerates) == 3
    unverified = [c for c in report.conglomerates if c.is_unverified]
    verified   = [c for c in report.conglomerates if not c.is_unverified]
    assert len(unverified) == 2
    assert len(verified) == 1
    assert verified[0].conglomerate_name == "Banco XP S.A."
