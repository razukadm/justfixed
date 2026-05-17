"""Tests for the conglomerate report engine (engine/conglomerate_report.py).

Financial cross-checks:
- Tests 1–6: as_of == purchase_date so current_value == principal (no accrual).
  Structural invariants (sequential drawdown, sort order, NOT_FGC) are verified
  without hardcoded decimal values.
- Test 7 (duality proof): principal = 90,000, Prefixed 20%, purchase 2025-01-02,
  maturities 2027-01-04 and 2027-01-11 (both >720 calendar days → 15% IR).
  At 20% annual, each gross_at_maturity ≈ 129k–130k (> R$ 125k).
  IR at 15% on ≈ R$ 39k gain ≈ R$ 5.9k → each net ≈ R$ 123k–124k (< R$ 125k).
  Sum gross > R$ 250k (OVER); sum net < R$ 250k (would be UNDER).
  The FGC badge reads peak_balance (gross), not projected_balance (net) — that
  is what test 7 proves.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from justfixed.domain.investment import Investment
from justfixed.domain.issuer import Issuer, IssuerKind
from justfixed.domain.money import Money
from justfixed.domain.product import ProductType
from justfixed.domain.rates import Prefixed
from justfixed.engine.conglomerate_report import (
    ConglomerateStatus,
    build_conglomerate_report,
)
from justfixed.engine.fgc import FGC_PER_CONGLOMERATE_LIMIT
from justfixed.engine.projection import project

# ── Shared constants ──────────────────────────────────────────────────────────

ASSUMED_CDI = Decimal("0.12")
PURCHASE = date(2025, 1, 2)


# ── Helpers ───────────────────────────────────────────────────────────────────

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


def _tesouro(principal: str, maturity: date) -> Investment:
    return Investment.create(
        product=ProductType.TESOURO_PREFIXADO,
        issuer=Issuer.treasury(),
        principal=Money.from_reais(principal),
        rate=Prefixed.from_percent("12"),
        purchase_date=PURCHASE,
        maturity_date=maturity,
    )


# ── Test 1: Empty input ───────────────────────────────────────────────────────

def test_empty_input_returns_empty_report() -> None:
    report = build_conglomerate_report([], as_of=PURCHASE, assumed_cdi=ASSUMED_CDI)
    assert report.sections == []
    assert report.as_of == PURCHASE


# ── Test 2: Single non-Tesouro investment ────────────────────────────────────

def test_single_investment_single_section_single_row() -> None:
    bank = _bank("Banco Alpha", "Banco Alpha S.A.")
    inv = _cdb(bank, "50000", date(2026, 1, 2))

    report = build_conglomerate_report([inv], as_of=PURCHASE, assumed_cdi=ASSUMED_CDI)

    assert len(report.sections) == 1
    assert report.as_of == PURCHASE

    section = report.sections[0]
    assert section.conglomerate_name == "Banco Alpha S.A."
    assert section.investment_count == 1
    assert section.next_maturity == date(2026, 1, 2)
    assert len(section.rows) == 1

    row = section.rows[0]
    assert row.maturity_date == date(2026, 1, 2)
    assert row.issuer_name == "Banco Alpha"
    assert row.product == ProductType.CDB
    assert row.principal == Money.from_reais("50000")

    # as_of == purchase_date → current_value == principal (no accrual yet)
    assert row.current_value == Money.from_reais("50000")

    # Only one row: projected_balance == projected_value (no later rows).
    assert row.projected_balance == row.projected_value

    # Cross-check projected_value and peak_balance against project() directly.
    res = project(inv, as_of=PURCHASE, assumed_cdi=ASSUMED_CDI)
    assert row.projected_value == res.net_at_maturity
    assert row.peak_balance == res.gross_at_maturity

    # Section aggregates.
    assert section.total_projected_value == row.projected_value
    assert section.total_peak_value == row.peak_balance

    # R$50k gross is well under R$200k → UNDER for both row and section.
    assert row.fgc_status == ConglomerateStatus.UNDER
    assert section.summary_fgc_status == ConglomerateStatus.UNDER


# ── Test 3: Multiple investments, one conglomerate ───────────────────────────

def test_multiple_investments_sequential_drawdown() -> None:
    # Three CDBs, same conglomerate, different maturities. Verifies the
    # sequential-drawdown invariants without hardcoded decimal values.
    bank = _bank("Banco Beta", "Banco Beta S.A.")
    inv_a = _cdb(bank, "30000", date(2026, 1, 2))   # earliest
    inv_b = _cdb(bank, "30000", date(2026, 7, 1))   # middle
    inv_c = _cdb(bank, "30000", date(2027, 1, 2))   # latest

    report = build_conglomerate_report(
        [inv_a, inv_b, inv_c], as_of=PURCHASE, assumed_cdi=ASSUMED_CDI
    )

    assert len(report.sections) == 1
    section = report.sections[0]
    assert section.investment_count == 3
    assert len(section.rows) == 3

    rows = section.rows
    # Rows sorted by maturity ascending.
    assert rows[0].maturity_date == date(2026, 1, 2)
    assert rows[1].maturity_date == date(2026, 7, 1)
    assert rows[2].maturity_date == date(2027, 1, 2)

    # next_maturity is earliest.
    assert section.next_maturity == date(2026, 1, 2)

    # Sequential drawdown: each row's projected_balance decreases toward maturity.
    assert rows[0].projected_balance > rows[1].projected_balance > rows[2].projected_balance

    # Row 0: projected_balance is the sum of all — equals section total.
    assert rows[0].projected_balance == section.total_projected_value

    # Row 2 (last): projected_balance equals only its own projected_value.
    assert rows[2].projected_balance == rows[2].projected_value

    # Same invariants hold for peak_balance (gross sequential drawdown).
    assert rows[0].peak_balance > rows[1].peak_balance > rows[2].peak_balance
    assert rows[0].peak_balance == section.total_peak_value

    # Row 2's peak_balance cross-checked directly against project().
    res_c = project(inv_c, as_of=PURCHASE, assumed_cdi=ASSUMED_CDI)
    assert rows[2].peak_balance == res_c.gross_at_maturity

    # Total principal.
    assert section.total_principal == Money.from_reais("90000")

    # as_of == purchase_date → current_value == principal per row.
    assert rows[0].current_value == Money.from_reais("30000")


# ── Test 4: Multiple conglomerates, alphabetical sort ────────────────────────

def test_sections_sorted_alphabetically() -> None:
    invs = [
        _cdb(_bank("Banco Zebra", "Zebra S.A."),   "50000", date(2026, 1, 2)),
        _cdb(_bank("Banco Apple", "Apple S.A."),    "50000", date(2026, 1, 2)),
        _cdb(_bank("Banco Mango", "Mango S.A."),    "50000", date(2026, 1, 2)),
    ]
    report = build_conglomerate_report(invs, as_of=PURCHASE, assumed_cdi=ASSUMED_CDI)

    assert len(report.sections) == 3
    names = [s.conglomerate_name for s in report.sections]
    assert names == ["Apple S.A.", "Mango S.A.", "Zebra S.A."]


# ── Test 5: Single Tesouro investment → NOT_FGC ───────────────────────────────

def test_tesouro_section_is_not_fgc() -> None:
    inv = _tesouro("500000", date(2027, 1, 2))

    report = build_conglomerate_report([inv], as_of=PURCHASE, assumed_cdi=ASSUMED_CDI)

    assert len(report.sections) == 1
    section = report.sections[0]
    assert section.conglomerate_name == "Tesouro Nacional"
    assert section.summary_fgc_status == ConglomerateStatus.NOT_FGC

    assert len(section.rows) == 1
    row = section.rows[0]
    assert row.fgc_status == ConglomerateStatus.NOT_FGC

    # Balances are still computed (sequential drawdown runs).
    res = project(inv, as_of=PURCHASE, assumed_cdi=ASSUMED_CDI)
    assert row.projected_value == res.net_at_maturity
    assert row.peak_balance == res.gross_at_maturity
    assert row.projected_balance == row.projected_value  # only row


# ── Test 6: Mixed report (Tesouro + bank) ────────────────────────────────────

def test_mixed_report_tesouro_and_bank() -> None:
    bank = _bank("Banco Gamma", "Gamma S.A.")
    invs = [
        _cdb(bank, "80000", date(2026, 7, 1)),
        _tesouro("200000", date(2027, 1, 2)),
    ]
    report = build_conglomerate_report(invs, as_of=PURCHASE, assumed_cdi=ASSUMED_CDI)

    assert len(report.sections) == 2

    names = [s.conglomerate_name for s in report.sections]
    assert "Gamma S.A." in names
    assert "Tesouro Nacional" in names
    # Alphabetical: "Gamma S.A." < "Tesouro Nacional".
    assert names == ["Gamma S.A.", "Tesouro Nacional"]

    tesouro_section = next(s for s in report.sections if s.conglomerate_name == "Tesouro Nacional")
    bank_section = next(s for s in report.sections if s.conglomerate_name == "Gamma S.A.")

    assert tesouro_section.summary_fgc_status == ConglomerateStatus.NOT_FGC
    assert all(r.fgc_status == ConglomerateStatus.NOT_FGC for r in tesouro_section.rows)

    # Bank section evaluates FGC normally. R$80k gross < R$200k → UNDER.
    assert bank_section.summary_fgc_status == ConglomerateStatus.UNDER
    assert bank_section.rows[0].fgc_status == ConglomerateStatus.UNDER


# ── Test 7: Gross-vs-net duality proof ───────────────────────────────────────

def test_fgc_badge_uses_gross_peak_not_net_projected_balance() -> None:
    # Two CDB investments, one conglomerate.
    # principal = 90,000, Prefixed 20%, >720 calendar days → 15% IR bracket.
    # At 20% annual for ~500 business days:
    #   gross ≈ 90,000 × 1.44 ≈ 129k–130k  (each > R$ 125k)
    #   IR ≈ 15% × ~R$ 39k ≈ R$ 5.9k
    #   net ≈ 123k–124k  (each < R$ 125k)
    # Sum gross > R$ 250k → OVER if badge reads gross.
    # Sum net < R$ 250k → UNDER if badge read net (the wrong behavior).
    bank = _bank("Banco Duality", "Duality S.A.")
    inv_a = Investment.create(
        product=ProductType.CDB,
        issuer=bank,
        principal=Money.from_reais("90000"),
        rate=Prefixed.from_percent("20"),
        purchase_date=PURCHASE,
        maturity_date=date(2027, 1, 4),   # 732 calendar days > 720 → 15% IR
    )
    inv_b = Investment.create(
        product=ProductType.CDB,
        issuer=bank,
        principal=Money.from_reais("90000"),
        rate=Prefixed.from_percent("20"),
        purchase_date=PURCHASE,
        maturity_date=date(2027, 1, 11),  # 739 calendar days > 720 → 15% IR
    )

    as_of = PURCHASE
    res_a = project(inv_a, as_of=as_of, assumed_cdi=ASSUMED_CDI)
    res_b = project(inv_b, as_of=as_of, assumed_cdi=ASSUMED_CDI)

    # Precondition: confirm the gross/net split this test relies on.
    assert res_a.gross_at_maturity.amount > Decimal("125000"), (
        "inv_a gross_at_maturity must exceed R$125k; adjust parameters if this fails"
    )
    assert res_a.net_at_maturity.amount < Decimal("125000"), (
        "inv_a net_at_maturity must be below R$125k; adjust parameters if this fails"
    )
    assert res_b.gross_at_maturity.amount > Decimal("125000"), (
        "inv_b gross_at_maturity must exceed R$125k; adjust parameters if this fails"
    )
    assert res_b.net_at_maturity.amount < Decimal("125000"), (
        "inv_b net_at_maturity must be below R$125k; adjust parameters if this fails"
    )
    sum_gross = res_a.gross_at_maturity + res_b.gross_at_maturity
    sum_net   = res_a.net_at_maturity   + res_b.net_at_maturity
    assert sum_gross > FGC_PER_CONGLOMERATE_LIMIT, "sum gross must exceed R$250k"
    assert sum_net   < FGC_PER_CONGLOMERATE_LIMIT, "sum net must be below R$250k"

    report = build_conglomerate_report(
        [inv_a, inv_b], as_of=as_of, assumed_cdi=ASSUMED_CDI
    )

    [section] = report.sections
    assert len(section.rows) == 2
    row_a, row_b = section.rows  # sorted maturity ascending: inv_a (Jan 4) first

    # Row A (maturity Jan 4, earlier): cumulative sum of both investments.
    assert row_a.maturity_date == date(2027, 1, 4)
    assert row_a.projected_balance < FGC_PER_CONGLOMERATE_LIMIT   # net sum < 250k
    assert row_a.peak_balance > FGC_PER_CONGLOMERATE_LIMIT         # gross sum > 250k
    # The badge evaluates peak_balance (gross), not projected_balance (net).
    # If it used net, it would say UNDER. It says OVER — that's the proof.
    assert row_a.fgc_status == ConglomerateStatus.OVER

    # Row B (maturity Jan 11, later): only itself in its own drawdown.
    assert row_b.maturity_date == date(2027, 1, 11)
    assert row_b.peak_balance.amount < Decimal("250000")
    assert row_b.fgc_status == ConglomerateStatus.UNDER

    # Section summary also uses peak (gross): OVER.
    assert section.summary_fgc_status == ConglomerateStatus.OVER
