"""Tests for the conglomerate report engine (engine/conglomerate_report.py).

Financial cross-checks: as_of == purchase_date so current_value == principal
(no accrual). Structural invariants (sequential drawdown, sort order, NOT_FGC)
are verified without hardcoded decimal values. All values are gross (Option B).
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

    # Cross-check projected_value against project() directly.
    res = project(inv, as_of=PURCHASE, assumed_cdi=ASSUMED_CDI)
    assert row.projected_value == res.gross_at_maturity

    # Section aggregates.
    assert section.total_projected_value == row.projected_value

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

    # Cross-check last row's projected_value directly against project().
    res_c = project(inv_c, as_of=PURCHASE, assumed_cdi=ASSUMED_CDI)
    assert rows[2].projected_value == res_c.gross_at_maturity

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
    assert row.projected_value == res.gross_at_maturity
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
