"""Tests for the maturity calendar export (exports/calendar.py).

All 8 tests are specified in docs/CALENDAR_EXPORT_DESIGN.md. The file is
written before exports/calendar.py exists; all tests fail with ImportError
until the export module is implemented.

Financial expected values:
- Test 7: net_at_maturity computed 2026-05-08 via scratch_compute_test7.py
  using the live projection engine. Display strings hardcoded; math documented
  in the test comment.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import icalendar

from justfixed.domain.investment import Investment
from justfixed.domain.issuer import Issuer, IssuerKind
from justfixed.domain.money import Money
from justfixed.domain.product import ProductType
from justfixed.domain.rates import Prefixed
from justfixed.exports.calendar import export_maturity_calendar

# ── Shared constants ──────────────────────────────────────────────────────────

ASSUMED_CDI = Decimal("0.12")
PURCHASE = date(2025, 1, 2)
AS_OF = date(2026, 1, 1)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _bank(name: str) -> Issuer:
    return Issuer.create(name, f"{name} S.A.", IssuerKind.COMMERCIAL_BANK)


def _cdb(
    issuer: Issuer,
    principal: str,
    maturity: date,
    purchase: date = PURCHASE,
    custodian: str | None = None,
) -> Investment:
    return Investment.create(
        product=ProductType.CDB,
        issuer=issuer,
        principal=Money.from_reais(principal),
        rate=Prefixed.from_percent("12"),
        purchase_date=purchase,
        maturity_date=maturity,
        custodian=custodian,
    )


def _parse(output: bytes) -> icalendar.Calendar:
    return icalendar.Calendar.from_ical(output)


def _events(cal: icalendar.Calendar) -> list:
    return [c for c in cal.walk() if c.name == "VEVENT"]


# ── Group A: Empty and trivial ────────────────────────────────────────────────

def test_empty_portfolio_emits_empty_calendar() -> None:
    output = export_maturity_calendar([], as_of=AS_OF, assumed_cdi=ASSUMED_CDI)
    assert _events(_parse(output)) == []


def test_single_investment_emits_single_event() -> None:
    inv = _cdb(_bank("Banco Inter"), "50000", date(2027, 6, 1))
    output = export_maturity_calendar([inv], as_of=AS_OF, assumed_cdi=ASSUMED_CDI)
    events = _events(_parse(output))
    assert len(events) == 1
    uid = str(events[0]["UID"])
    assert uid == f"justfixed-{inv.id}-maturity@justfixed"


# ── Group B: Event content ────────────────────────────────────────────────────

def test_event_summary_includes_issuer_and_payout() -> None:
    bank = _bank("Banco Inter")
    inv = _cdb(bank, "50000", date(2027, 6, 1))
    output = export_maturity_calendar([inv], as_of=AS_OF, assumed_cdi=ASSUMED_CDI)
    summary = str(_events(_parse(output))[0]["SUMMARY"])
    assert "Banco Inter" in summary
    assert "R$" in summary


def test_event_description_includes_custodian_when_present() -> None:
    inv = _cdb(_bank("Banco Inter"), "50000", date(2027, 6, 1), custodian="XP")
    output = export_maturity_calendar([inv], as_of=AS_OF, assumed_cdi=ASSUMED_CDI)
    desc = str(_events(_parse(output))[0]["DESCRIPTION"])
    assert "Custodiante: XP" in desc
    assert "XP" not in str(_events(_parse(output))[0]["SUMMARY"])


def test_event_description_omits_custodian_when_none() -> None:
    inv = _cdb(_bank("Banco Inter"), "50000", date(2027, 6, 1), custodian=None)
    output = export_maturity_calendar([inv], as_of=AS_OF, assumed_cdi=ASSUMED_CDI)
    desc = str(_events(_parse(output))[0]["DESCRIPTION"])
    assert "Custodiante" not in desc


def test_event_date_is_maturity_date() -> None:
    inv = _cdb(_bank("Banco Inter"), "50000", date(2027, 11, 15))
    output = export_maturity_calendar([inv], as_of=AS_OF, assumed_cdi=ASSUMED_CDI)
    event = _events(_parse(output))[0]
    dtstart = event["DTSTART"].dt
    assert dtstart == date(2027, 11, 15)
    assert type(dtstart) is date


# ── Group C: Stability and filtering ─────────────────────────────────────────

def test_event_uid_is_stable_across_exports() -> None:
    inv = _cdb(_bank("Banco Inter"), "50000", date(2027, 6, 1))
    output_a = export_maturity_calendar([inv], as_of=AS_OF, assumed_cdi=ASSUMED_CDI)
    output_b = export_maturity_calendar([inv], as_of=AS_OF, assumed_cdi=ASSUMED_CDI)
    uids_a = {str(e["UID"]) for e in _events(_parse(output_a))}
    uids_b = {str(e["UID"]) for e in _events(_parse(output_b))}
    assert uids_a == uids_b


def test_past_maturities_are_filtered_out() -> None:
    inv = _cdb(_bank("Banco Inter"), "50000", date(2024, 1, 1), purchase=date(2023, 1, 2))
    output = export_maturity_calendar([inv], as_of=date(2026, 1, 1), assumed_cdi=ASSUMED_CDI)
    assert _events(_parse(output)) == []


def test_maturity_on_as_of_date_is_included() -> None:
    # Boundary case from the design spec: a maturity == as_of is
    # in the future enough to put on the calendar.
    target_date = date(2026, 1, 1)
    inv = _cdb(_bank("Banco Inter"), "50000", target_date)
    output = export_maturity_calendar(
        [inv], as_of=target_date, assumed_cdi=ASSUMED_CDI
    )
    assert len(_events(_parse(output))) == 1


# ── Group D: Tax handling and validity ───────────────────────────────────────

def test_treasury_investment_uses_net_after_tax() -> None:
    # Computed 2026-05-08 via scratch_compute_test7.py using project() directly.
    #
    #   product             : TESOURO_PREFIXADO
    #   principal           : R$ 10.000,00
    #   rate                : 10% a.a. prefixed
    #   purchase_date       : 2025-01-02
    #   as_of               : 2025-01-02  (= purchase_date → no accrual yet)
    #   maturity_date       : 2026-01-02  (Du = 252 bd → factor = 1.10 exactly)
    #
    #   gross_at_maturity   : R$ 11.000,00  (10000 × 1.10)
    #   holding_calendar_days: 365          (IR bracket: 361–720 → 17.5%)
    #   IR                  : 1000 × 17.5% = R$ 175,00
    #   net_at_maturity     : R$ 10.825,00  ← must appear in SUMMARY
    NET_DISPLAY = "R$ 10.825,00"

    inv = Investment.create(
        product=ProductType.TESOURO_PREFIXADO,
        issuer=Issuer.treasury(),
        principal=Money.from_reais("10000"),
        rate=Prefixed.from_percent("10"),
        purchase_date=date(2025, 1, 2),
        maturity_date=date(2026, 1, 2),
    )
    output = export_maturity_calendar(
        [inv], as_of=date(2025, 1, 2), assumed_cdi=ASSUMED_CDI
    )
    summary = str(_events(_parse(output))[0]["SUMMARY"])
    assert NET_DISPLAY in summary


def test_ics_output_is_valid_format() -> None:
    invs = [
        _cdb(_bank("Banco A"), "50000",  date(2027, 6, 1)),
        _cdb(_bank("Banco B"), "80000",  date(2027, 9, 1)),
        _cdb(_bank("Banco C"), "120000", date(2028, 3, 1)),
    ]
    output = export_maturity_calendar(invs, as_of=AS_OF, assumed_cdi=ASSUMED_CDI)
    # Raises if output is not parseable iCalendar.
    icalendar.Calendar.from_ical(output)
