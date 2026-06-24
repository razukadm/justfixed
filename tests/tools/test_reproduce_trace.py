"""Tests for tools/reproduce_trace.py (Audit-readiness Slice 2, finding F-11).

Nine test groups matching the acceptance spec:
  1. build_rate -- four rate kinds
  2. build_issuer + build_investment -- domain builders
  3. load_curves -- with and without curve data
  4. Serializer types -- no floats, ISO dates, 8dp Money, enum .value, null
  5. Determinism -- byte-identical to_json across two calls
  6. Envelope structure -- schema, methodology, inputs echo, sha256, as_of
  7. FIDELITY -- CLI numbers match project_traced directly for all four cases
  8. Text worksheet -- key strings present
  9. main() routing + errors
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tools"))

from reproduce_trace import (  # noqa: E402
    build_envelope,
    build_investment,
    build_issuer,
    build_rate,
    load_curves,
    main,
    parse_decimal_opt,
    to_json,
    trace_to_dict,
    trace_to_text,
)

from justfixed.domain.issuer import IssuerKind  # noqa: E402
from justfixed.domain.product import CouponFrequency, ProductType  # noqa: E402
from justfixed.domain.rates import (  # noqa: E402
    PostFixedCDI,
    PostFixedCDIPlusSpread,
    PostFixedIPCA,
    Prefixed,
)
from justfixed.engine.breakeven import breakeven_inflation_curve  # noqa: E402
from justfixed.engine.fetcher import (  # noqa: E402
    _parse_ipca_real_curve,
    _parse_pre_curve,
)
from justfixed.engine.projection import project_traced  # noqa: E402


# =============================================================================
# Shared spec/curve helpers
# =============================================================================

_BANK_ISSUER = {
    "name": "Banco Teste",
    "conglomerate": "Banco Teste S.A.",
    "kind": "commercial_bank",
}

_CURVE_DATA = {
    "as_of": "2024-01-15",
    "schema_version": 1,
    "cdi": {
        "anchor": "2024-01-15",
        "vertices": [
            {"business_days": 126, "rate": 0.119},
            {"business_days": 252, "rate": 0.12},
            {"business_days": 504, "rate": 0.125},
            {"business_days": 756, "rate": 0.13},
        ],
    },
    "pre": {
        "anchor": "2024-01-15",
        "vertices": [
            {"business_days": 126, "rate": 0.139},
            {"business_days": 252, "rate": 0.14},
            {"business_days": 504, "rate": 0.143},
            {"business_days": 756, "rate": 0.145},
        ],
    },
    "ipca_real": {
        "anchor": "2024-01-15",
        "vertices": [
            {"business_days": 126, "rate": 0.059},
            {"business_days": 252, "rate": 0.06},
            {"business_days": 504, "rate": 0.062},
            {"business_days": 756, "rate": 0.065},
        ],
    },
}

_SPEC_A = {
    "investment": {
        "product": "cdb",
        "issuer": _BANK_ISSUER,
        "principal": "10000",
        "rate": {"kind": "prefixed", "annual_percent": "12"},
        "purchase_date": "2024-01-15",
        "maturity_date": "2025-01-15",
    },
    "as_of": "2024-07-15",
}

_SPEC_B = {
    "investment": {
        "product": "cdb",
        "issuer": _BANK_ISSUER,
        "principal": "10000",
        "rate": {"kind": "post_fixed_cdi", "cdi_percent": "110"},
        "purchase_date": "2024-01-15",
        "maturity_date": "2026-01-15",
    },
    "as_of": "2024-07-15",
}

_SPEC_C = {
    "investment": {
        "product": "cdb",
        "issuer": _BANK_ISSUER,
        "principal": "10000",
        "rate": {"kind": "post_fixed_ipca", "spread_percent": "5.5"},
        "purchase_date": "2024-01-15",
        "maturity_date": "2027-01-15",
    },
    "as_of": "2024-07-15",
}

_SPEC_D = {
    "investment": {
        "product": "cdb",
        "issuer": _BANK_ISSUER,
        "principal": "10000",
        "rate": {"kind": "prefixed", "annual_percent": "12"},
        "purchase_date": "2024-01-15",
        "maturity_date": "2026-01-15",
        "coupon_frequency": "semi_annual",
    },
    "as_of": "2024-07-15",
}


def _has_float(obj) -> bool:
    if isinstance(obj, float):
        return True
    if isinstance(obj, dict):
        return any(_has_float(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_float(v) for v in obj)
    return False


# =============================================================================
# 1. build_rate -- four rate kinds
# =============================================================================


def test_build_rate_prefixed():
    r = build_rate({"kind": "prefixed", "annual_percent": "12"})
    assert isinstance(r, Prefixed)
    assert r.annual_rate == Decimal("0.12")


def test_build_rate_post_fixed_cdi():
    r = build_rate({"kind": "post_fixed_cdi", "cdi_percent": "110"})
    assert isinstance(r, PostFixedCDI)
    assert r.cdi_percentage == Decimal("1.10")


def test_build_rate_post_fixed_cdi_plus_spread():
    r = build_rate({"kind": "post_fixed_cdi_plus_spread", "spread_percent": "2.05"})
    assert isinstance(r, PostFixedCDIPlusSpread)
    assert r.spread == Decimal("0.0205")


def test_build_rate_post_fixed_ipca():
    r = build_rate({"kind": "post_fixed_ipca", "spread_percent": "5.5"})
    assert isinstance(r, PostFixedIPCA)
    assert r.spread == Decimal("0.055")


def test_build_rate_unknown_raises():
    with pytest.raises(ValueError, match="unknown rate kind"):
        build_rate({"kind": "mystery_rate"})


# =============================================================================
# 2. build_issuer + build_investment
# =============================================================================


def test_build_issuer_treasury():
    spec = {"kind": "treasury"}
    issuer = build_issuer(spec)
    assert issuer.kind == IssuerKind.TREASURY
    assert issuer.name == "Tesouro Nacional"


def test_build_issuer_commercial_bank():
    spec = {
        "name": "Banco Foobar",
        "conglomerate": "Foobar Holding",
        "kind": "commercial_bank",
        "tax_id": "",
    }
    issuer = build_issuer(spec)
    assert issuer.kind == IssuerKind.COMMERCIAL_BANK
    assert issuer.name == "Banco Foobar"
    assert issuer.conglomerate == "Foobar Holding"


def test_build_investment_full_spec():
    inv = build_investment(_SPEC_A["investment"])
    assert inv.product == ProductType.CDB
    assert inv.principal.amount == Decimal("10000.00000000")
    assert isinstance(inv.rate, Prefixed)
    assert inv.rate.annual_rate == Decimal("0.12")
    assert inv.purchase_date == date(2024, 1, 15)
    assert inv.maturity_date == date(2025, 1, 15)
    assert inv.coupon_frequency == CouponFrequency.NONE


def test_build_investment_semi_annual():
    inv = build_investment(_SPEC_D["investment"])
    assert inv.coupon_frequency == CouponFrequency.SEMI_ANNUAL


# =============================================================================
# 3. load_curves
# =============================================================================


def test_load_curves_none_input():
    cdi, ipca = load_curves(None)
    assert cdi is None
    assert ipca is None


def test_load_curves_with_data():
    cdi, ipca = load_curves(_CURVE_DATA)
    # CDI curve parsed directly
    assert cdi is not None
    assert cdi.anchor == date(2024, 1, 15)
    # IPCA curve derived via breakeven (same anchor as pre/ipca_real share)
    expected_ipca = breakeven_inflation_curve(
        _parse_pre_curve(_CURVE_DATA),
        _parse_ipca_real_curve(_CURVE_DATA),
    )
    assert ipca is not None
    assert expected_ipca is not None
    assert ipca.anchor == expected_ipca.anchor
    assert len(ipca.vertices) == len(expected_ipca.vertices)
    for got, exp in zip(ipca.vertices, expected_ipca.vertices):
        assert got.business_days == exp.business_days
        assert got.rate == exp.rate


# =============================================================================
# 4. Serializer types -- no floats, ISO dates, 8dp Money, .value enums, nulls
# =============================================================================


def test_serializer_no_floats_and_type_correctness():
    inv = build_investment(_SPEC_A["investment"])
    trace = project_traced(inv, as_of=date(2024, 7, 15))
    envelope = build_envelope(
        _SPEC_A, trace, curve_path=None, curve_data=None, curve_bytes=None
    )
    parsed = json.loads(to_json(envelope))

    # No Python float anywhere in the structure
    assert not _has_float(parsed), "float value found in serialized JSON"

    t = parsed["trace"]

    # Dates are ISO strings
    assert t["as_of"] == "2024-07-15"
    assert t["investment"]["purchase_date"] == "2024-01-15"
    assert t["investment"]["maturity_date"] == "2025-01-15"

    # Money amounts serialized as 8-decimal strings
    cv = t["current_value"]
    assert "." in cv
    assert len(cv.split(".")[1]) == 8

    # Enum fields are lowercase .value strings
    assert t["investment"]["product"] == "cdb"
    assert t["investment"]["coupon_frequency"] == "none"
    assert t["tax"]["treatment"] == "ir_regressive"
    assert t["cash_flows"][0]["kind"] in ("coupon", "principal", "coupon_and_principal")

    # Absent optional assumptions serialized as null
    assert t["assumptions"]["assumed_cdi"] is None
    assert t["assumptions"]["assumed_ipca"] is None

    # iof_modeled is a JSON bool, not a string
    assert isinstance(t["tax"]["iof_modeled"], bool)
    assert t["tax"]["iof_modeled"] is False


# =============================================================================
# 5. Determinism -- byte-identical across two calls
# =============================================================================


def test_to_json_deterministic():
    inv = build_investment(_SPEC_A["investment"])
    trace = project_traced(inv, as_of=date(2024, 7, 15))
    envelope = build_envelope(
        _SPEC_A, trace, curve_path=None, curve_data=None, curve_bytes=None
    )
    first = to_json(envelope)
    second = to_json(envelope)
    assert first == second

    # Also check that re-building the envelope from the same inputs produces
    # the same JSON (no timestamp or random data embedded)
    inv2 = build_investment(_SPEC_A["investment"])
    trace2 = project_traced(inv2, as_of=date(2024, 7, 15))
    envelope2 = build_envelope(
        _SPEC_A, trace2, curve_path=None, curve_data=None, curve_bytes=None
    )
    # trace_to_dict fields must match (UUIDs differ but they're not serialized)
    assert json.loads(to_json(envelope))["trace"] == json.loads(to_json(envelope2))["trace"]


# =============================================================================
# 6. Envelope structure
# =============================================================================


def test_envelope_schema_and_methodology():
    inv = build_investment(_SPEC_A["investment"])
    trace = project_traced(inv, as_of=date(2024, 7, 15))
    envelope = build_envelope(
        _SPEC_A, trace, curve_path=None, curve_data=None, curve_bytes=None
    )
    assert envelope["trace_schema"] == 1
    assert envelope["methodology"] == "docs/METHODOLOGY.md"


def test_envelope_inputs_echo():
    inv = build_investment(_SPEC_A["investment"])
    trace = project_traced(inv, as_of=date(2024, 7, 15))
    envelope = build_envelope(
        _SPEC_A, trace, curve_path=None, curve_data=None, curve_bytes=None
    )
    assert envelope["inputs"] is _SPEC_A


def test_envelope_no_curve_file_is_none():
    inv = build_investment(_SPEC_A["investment"])
    trace = project_traced(inv, as_of=date(2024, 7, 15))
    envelope = build_envelope(
        _SPEC_A, trace, curve_path=None, curve_data=None, curve_bytes=None
    )
    assert envelope["curve_file"] is None


def test_envelope_curve_file_sha256_and_as_of(tmp_path):
    curve_bytes = json.dumps(_CURVE_DATA).encode("utf-8")
    curve_path = tmp_path / "latest.json"
    curve_path.write_bytes(curve_bytes)

    cdi_curve, ipca_curve = load_curves(_CURVE_DATA)
    inv = build_investment(_SPEC_B["investment"])
    trace = project_traced(inv, as_of=date(2024, 7, 15), cdi_curve=cdi_curve)
    envelope = build_envelope(
        _SPEC_B,
        trace,
        curve_path=str(curve_path),
        curve_data=_CURVE_DATA,
        curve_bytes=curve_bytes,
    )
    cf = envelope["curve_file"]
    assert cf is not None
    assert cf["sha256"] == hashlib.sha256(curve_bytes).hexdigest()
    assert cf["as_of"] == _CURVE_DATA["as_of"]
    assert cf["path"] == str(curve_path)


# =============================================================================
# 7. FIDELITY -- CLI numbers match project_traced directly
# =============================================================================


def _assert_fidelity(loaded_trace: dict, truth) -> None:
    """Assert every numeric in the loaded JSON trace equals str() of the truth."""
    assert loaded_trace["current_value"] == str(truth.current_value.amount)
    assert loaded_trace["gross_at_maturity"] == str(truth.gross_at_maturity.amount)
    assert loaded_trace["net_at_maturity"] == str(truth.net_at_maturity.amount)

    for step_d, step_t in zip(
        loaded_trace["current_value_accrual"], truth.current_value_accrual
    ):
        assert step_d["factor"] == str(step_t.factor)
        assert step_d["closing_balance"] == str(step_t.closing_balance.amount)

    for flow_d, flow_t in zip(loaded_trace["cash_flows"], truth.cash_flows):
        assert flow_d["amount"] == str(flow_t.amount.amount)
        assert flow_d["interest_component"] == str(flow_t.interest_component.amount)
        assert flow_d["principal_component"] == str(flow_t.principal_component.amount)
        for step_d, step_t in zip(flow_d["accrual"], flow_t.accrual):
            assert step_d["factor"] == str(step_t.factor)
            assert step_d["closing_balance"] == str(step_t.closing_balance.amount)

    assert loaded_trace["tax"]["bracket_rate"] == str(truth.tax.bracket_rate)
    assert loaded_trace["tax"]["taxable_gain"] == str(truth.tax.taxable_gain.amount)
    assert loaded_trace["tax"]["tax_amount"] == str(truth.tax.tax_amount.amount)


def test_fidelity_prefixed_cdb_bullet(tmp_path):
    spec_path = tmp_path / "spec_a.json"
    spec_path.write_text(json.dumps(_SPEC_A), encoding="utf-8")
    out_path = tmp_path / "out_a.json"

    main([str(spec_path), "--json-out", str(out_path)])

    loaded = json.loads(out_path.read_text(encoding="utf-8"))
    truth = project_traced(
        build_investment(_SPEC_A["investment"]),
        as_of=date.fromisoformat(_SPEC_A["as_of"]),
    )
    _assert_fidelity(loaded["trace"], truth)


def test_fidelity_cdi_cdb_bullet_with_curve(tmp_path):
    curve_bytes = json.dumps(_CURVE_DATA).encode("utf-8")
    curve_path = tmp_path / "curve.json"
    curve_path.write_bytes(curve_bytes)
    spec_path = tmp_path / "spec_b.json"
    spec_path.write_text(json.dumps(_SPEC_B), encoding="utf-8")
    out_path = tmp_path / "out_b.json"

    main([str(spec_path), "--curve", str(curve_path), "--json-out", str(out_path)])

    loaded = json.loads(out_path.read_text(encoding="utf-8"))
    cdi_curve, ipca_curve = load_curves(_CURVE_DATA)
    truth = project_traced(
        build_investment(_SPEC_B["investment"]),
        as_of=date.fromisoformat(_SPEC_B["as_of"]),
        cdi_curve=cdi_curve,
        ipca_curve=ipca_curve,
    )
    _assert_fidelity(loaded["trace"], truth)


def test_fidelity_ipca_cdb_bullet_with_curve(tmp_path):
    curve_bytes = json.dumps(_CURVE_DATA).encode("utf-8")
    curve_path = tmp_path / "curve.json"
    curve_path.write_bytes(curve_bytes)
    spec_path = tmp_path / "spec_c.json"
    spec_path.write_text(json.dumps(_SPEC_C), encoding="utf-8")
    out_path = tmp_path / "out_c.json"

    main([str(spec_path), "--curve", str(curve_path), "--json-out", str(out_path)])

    loaded = json.loads(out_path.read_text(encoding="utf-8"))
    cdi_curve, ipca_curve = load_curves(_CURVE_DATA)
    truth = project_traced(
        build_investment(_SPEC_C["investment"]),
        as_of=date.fromisoformat(_SPEC_C["as_of"]),
        cdi_curve=cdi_curve,
        ipca_curve=ipca_curve,
    )
    _assert_fidelity(loaded["trace"], truth)


def test_fidelity_semi_annual_coupon(tmp_path):
    spec_path = tmp_path / "spec_d.json"
    spec_path.write_text(json.dumps(_SPEC_D), encoding="utf-8")
    out_path = tmp_path / "out_d.json"

    main([str(spec_path), "--json-out", str(out_path)])

    loaded = json.loads(out_path.read_text(encoding="utf-8"))
    truth = project_traced(
        build_investment(_SPEC_D["investment"]),
        as_of=date.fromisoformat(_SPEC_D["as_of"]),
    )
    _assert_fidelity(loaded["trace"], truth)
    # Semiannual: multiple cash flows present
    assert len(loaded["trace"]["cash_flows"]) > 1


def test_per_flow_tax_in_coupon_json(tmp_path):
    # Coupon instrument: per_flow list has one entry per cash flow; aggregate keys intact.
    spec_path = tmp_path / "spec_d.json"
    spec_path.write_text(json.dumps(_SPEC_D), encoding="utf-8")
    out_path = tmp_path / "out_d.json"

    main([str(spec_path), "--json-out", str(out_path)])

    loaded = json.loads(out_path.read_text(encoding="utf-8"))
    tax = loaded["trace"]["tax"]
    n_flows = len(loaded["trace"]["cash_flows"])

    # per_flow list is present and has one entry per flow
    assert "per_flow" in tax
    assert len(tax["per_flow"]) == n_flows

    # Each entry has all required keys and no floats
    for pf in tax["per_flow"]:
        assert "pay_date" in pf
        assert "holding_days" in pf
        assert "bracket_rate" in pf
        assert "taxable_interest" in pf
        assert "tax_amount" in pf
        assert isinstance(pf["holding_days"], int)
        assert not isinstance(pf["bracket_rate"], float)

    # Aggregate keys still present and unchanged in structure
    assert "bracket_rate" in tax
    assert "taxable_gain" in tax
    assert "tax_amount" in tax
    assert "holding_calendar_days" in tax


def test_per_flow_tax_bullet_still_present_length_one(tmp_path):
    # Bullet instrument: per_flow has exactly one entry (but text worksheet omits it).
    spec_path = tmp_path / "spec_a.json"
    spec_path.write_text(json.dumps(_SPEC_A), encoding="utf-8")
    out_path = tmp_path / "out_a.json"

    main([str(spec_path), "--json-out", str(out_path)])

    loaded = json.loads(out_path.read_text(encoding="utf-8"))
    tax = loaded["trace"]["tax"]
    assert len(tax["per_flow"]) == 1


def test_per_flow_text_section_present_for_coupon(tmp_path):
    # Text worksheet includes per-flow breakdown only for coupon instruments.
    spec_path = tmp_path / "spec_d.json"
    spec_path.write_text(json.dumps(_SPEC_D), encoding="utf-8")
    out_path = tmp_path / "out_d.txt"

    main([str(spec_path), "--text-out", str(out_path)])

    text = out_path.read_text(encoding="utf-8")
    assert "Per-flow IR withholding" in text


def test_per_flow_text_section_absent_for_bullet(tmp_path):
    # Text worksheet omits per-flow breakdown for bullet instruments.
    spec_path = tmp_path / "spec_a.json"
    spec_path.write_text(json.dumps(_SPEC_A), encoding="utf-8")
    out_path = tmp_path / "out_a.txt"

    main([str(spec_path), "--text-out", str(out_path)])

    text = out_path.read_text(encoding="utf-8")
    assert "Per-flow IR withholding" not in text


# =============================================================================
# 8. Text worksheet -- key strings present (light assertions)
# =============================================================================


def test_text_worksheet_contains_key_strings():
    inv = build_investment(_SPEC_A["investment"])
    trace = project_traced(inv, as_of=date(2024, 7, 15))
    text = trace_to_text(trace, curve_file=None)

    # Convention string from ProjectionTrace
    assert trace.convention in text

    # Tax section mentions IR
    assert "IR" in text

    # Bracket rate appears as a string
    from reproduce_trace import dec  # noqa: F401
    assert dec(trace.tax.bracket_rate) in text

    # IOF disclosure
    assert "IOF" in text

    # Gross at maturity in Money.to_display() form
    assert trace.gross_at_maturity.to_display() in text

    # Methodology pointer
    assert "docs/METHODOLOGY.md" in text


# =============================================================================
# 9. main() routing + errors
# =============================================================================


def test_main_default_routing_prints_text_and_json(tmp_path, capsys):
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(_SPEC_A), encoding="utf-8")

    result = main([str(spec_path)])
    assert result == 0

    captured = capsys.readouterr()
    assert "JustFixed" in captured.out
    assert "===== TRACE JSON =====" in captured.out
    # JSON section should contain trace_schema key
    assert '"trace_schema"' in captured.out


def test_main_json_out_to_file(tmp_path):
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(_SPEC_A), encoding="utf-8")
    out_path = tmp_path / "out.json"

    result = main([str(spec_path), "--json-out", str(out_path)])
    assert result == 0
    assert out_path.exists()
    loaded = json.loads(out_path.read_text(encoding="utf-8"))
    assert loaded["trace_schema"] == 1


def test_main_text_out_to_file(tmp_path):
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(_SPEC_A), encoding="utf-8")
    out_path = tmp_path / "out.txt"

    result = main([str(spec_path), "--text-out", str(out_path)])
    assert result == 0
    assert out_path.exists()
    content = out_path.read_text(encoding="utf-8")
    assert "JustFixed" in content


def test_main_post_fixed_cdi_no_curve_no_assumed_exits(tmp_path):
    spec_no_cdi = {
        "investment": {
            "product": "cdb",
            "issuer": _BANK_ISSUER,
            "principal": "10000",
            "rate": {"kind": "post_fixed_cdi", "cdi_percent": "110"},
            "purchase_date": "2024-01-15",
            "maturity_date": "2025-01-15",
        },
        "as_of": "2024-07-15",
    }
    spec_path = tmp_path / "spec_no_cdi.json"
    spec_path.write_text(json.dumps(spec_no_cdi), encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        main([str(spec_path)])
    assert exc_info.value.code  # nonzero / non-empty string


def test_main_missing_spec_exits():
    with pytest.raises(SystemExit) as exc_info:
        main(["nonexistent_spec_that_does_not_exist_abc123.json"])
    assert exc_info.value.code  # truthy message
