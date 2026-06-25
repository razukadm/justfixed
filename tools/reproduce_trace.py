"""Headless trace-reproduce CLI for audit finding F-11.

Given an instrument-spec JSON and an optional published curve file, runs
project_traced() and emits the ProjectionTrace as deterministic JSON and
as a readable audit worksheet.

Usage:
    python tools/reproduce_trace.py spec.json [--curve curves/latest.json]
        [--json-out trace.json] [--text-out trace.txt]

Omit --json-out and --text-out to receive both formats on stdout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from justfixed.domain.investment import Investment
from justfixed.domain.issuer import Issuer, IssuerKind
from justfixed.domain.money import Money
from justfixed.domain.product import CouponFrequency, ProductType
from justfixed.domain.rates import (
    PostFixedCDI,
    PostFixedCDIPlusSpread,
    PostFixedIPCA,
    Prefixed,
    Rate,
)
from justfixed.engine.breakeven import breakeven_inflation_curve
from justfixed.engine.curve import Curve
from justfixed.engine.fetcher import (
    _parse_ipca_real_curve,
    _parse_pre_curve,
    parse_curve_payload,
)
from justfixed.engine.projection import project_traced
from justfixed.engine.trace import (
    AccrualStep,
    FlowTrace,
    ProjectionTrace,
    RateResolution,
    TaxTrace,
)


# =============================================================================
# Step A -- Domain builders
# =============================================================================


def build_rate(rate_spec: dict) -> Rate:
    kind = rate_spec["kind"]
    if kind == "prefixed":
        return Prefixed.from_percent(rate_spec["annual_percent"])
    if kind == "post_fixed_cdi":
        return PostFixedCDI.from_percent(rate_spec["cdi_percent"])
    if kind == "post_fixed_cdi_plus_spread":
        return PostFixedCDIPlusSpread.from_percent(rate_spec["spread_percent"])
    if kind == "post_fixed_ipca":
        return PostFixedIPCA.from_percent(rate_spec["spread_percent"])
    raise ValueError(f"unknown rate kind: {rate_spec['kind']!r}")


def build_issuer(issuer_spec: dict) -> Issuer:
    if issuer_spec["kind"] == "treasury":
        return Issuer.treasury()
    return Issuer.create(
        issuer_spec["name"],
        issuer_spec["conglomerate"],
        IssuerKind(issuer_spec["kind"]),
        issuer_spec.get("tax_id", ""),
    )


def build_investment(inv_spec: dict) -> Investment:
    return Investment.create(
        product=ProductType(inv_spec["product"]),
        issuer=build_issuer(inv_spec["issuer"]),
        principal=Money.from_reais(inv_spec["principal"]),
        rate=build_rate(inv_spec["rate"]),
        purchase_date=date.fromisoformat(inv_spec["purchase_date"]),
        maturity_date=date.fromisoformat(inv_spec["maturity_date"]),
        coupon_frequency=CouponFrequency(inv_spec.get("coupon_frequency", "none")),
    )


def parse_decimal_opt(spec: dict, key: str) -> Decimal | None:
    if key in spec and spec[key] is not None:
        return Decimal(str(spec[key]))
    return None


# =============================================================================
# Step B -- Curve loading
# =============================================================================


def load_curves(curve_data: dict | None) -> tuple[Curve | None, Curve | None]:
    if curve_data is None:
        return None, None
    cdi_curve = parse_curve_payload(curve_data)
    ipca_curve = breakeven_inflation_curve(
        _parse_pre_curve(curve_data),
        _parse_ipca_real_curve(curve_data),
    )
    return cdi_curve, ipca_curve


# =============================================================================
# Step C -- Serialization (deterministic, Decimal-as-string, no floats)
# =============================================================================


def dec(x: Decimal) -> str:
    return str(x)


def amt(m: Money) -> str:
    return str(m.amount)


def iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def rate_echo(rate: Rate) -> dict:
    match rate:
        case Prefixed():
            return {"kind": "Prefixed", "annual_rate": dec(rate.annual_rate)}
        case PostFixedCDI():
            return {"kind": "PostFixedCDI", "cdi_percentage": dec(rate.cdi_percentage)}
        case PostFixedCDIPlusSpread():
            return {"kind": "PostFixedCDIPlusSpread", "spread": dec(rate.spread)}
        case PostFixedIPCA():
            return {"kind": "PostFixedIPCA", "spread": dec(rate.spread)}
        case _:
            raise ValueError(f"unknown rate type: {type(rate).__name__!r}")


def rr_to_dict(rr: RateResolution) -> dict:
    return {
        "rate_kind": rr.rate_kind,
        "effective_annual_rate": dec(rr.effective_annual_rate),
        "source": rr.source,
        "resolved_index_rate": (
            dec(rr.resolved_index_rate)
            if rr.resolved_index_rate is not None
            else None
        ),
        "index_multiplier_or_spread": (
            dec(rr.index_multiplier_or_spread)
            if rr.index_multiplier_or_spread is not None
            else None
        ),
        "curve_anchor": iso(rr.curve_anchor),
        "curve_tenor_date": iso(rr.curve_tenor_date),
        "curve_ref": rr.curve_ref,
    }


def step_to_dict(s: AccrualStep) -> dict:
    return {
        "from_date": iso(s.from_date),
        "to_date": iso(s.to_date),
        "business_days": s.business_days,
        "rate": rr_to_dict(s.rate),
        "factor": dec(s.factor),
        "opening_balance": amt(s.opening_balance),
        "closing_balance": amt(s.closing_balance),
    }


def flow_to_dict(f: FlowTrace) -> dict:
    return {
        "pay_date": iso(f.pay_date),
        "kind": f.kind.value,
        "amount": amt(f.amount),
        "interest_component": amt(f.interest_component),
        "principal_component": amt(f.principal_component),
        "accrual": [step_to_dict(s) for s in f.accrual],
    }


def tax_to_dict(t: TaxTrace) -> dict:
    return {
        "treatment": t.treatment.value,
        "holding_calendar_days": t.holding_calendar_days,
        "bracket_rate": dec(t.bracket_rate),
        "taxable_gain": amt(t.taxable_gain),
        "tax_amount": amt(t.tax_amount),
        "iof_modeled": t.iof_modeled,
        "per_flow": [
            {
                "pay_date": iso(f.pay_date),
                "holding_days": f.holding_days,
                "bracket_rate": dec(f.bracket_rate),
                "taxable_interest": amt(f.taxable_interest),
                "tax_amount": amt(f.tax_amount),
            }
            for f in t.per_flow
        ],
    }


def trace_to_dict(trace: ProjectionTrace) -> dict:
    inv = trace.investment
    return {
        "investment": {
            "product": inv.product.value,
            "issuer": {
                "name": inv.issuer.name,
                "conglomerate": inv.issuer.conglomerate,
                "kind": inv.issuer.kind.value,
                "tax_id": inv.issuer.tax_id,
            },
            "principal": amt(inv.principal),
            "rate": rate_echo(inv.rate),
            "purchase_date": iso(inv.purchase_date),
            "maturity_date": iso(inv.maturity_date),
            "coupon_frequency": inv.coupon_frequency.value,
        },
        "as_of": iso(trace.as_of),
        "currency": trace.investment.principal.currency,
        "convention": trace.convention,
        "current_value": amt(trace.current_value),
        "current_value_accrual": [step_to_dict(s) for s in trace.current_value_accrual],
        "cash_flows": [flow_to_dict(f) for f in trace.cash_flows],
        "gross_at_maturity": amt(trace.gross_at_maturity),
        "tax": tax_to_dict(trace.tax),
        "net_at_maturity": amt(trace.net_at_maturity),
        "assumptions": {
            "assumed_cdi": (
                dec(trace.assumptions.assumed_cdi)
                if trace.assumptions.assumed_cdi is not None
                else None
            ),
            "assumed_ipca": (
                dec(trace.assumptions.assumed_ipca)
                if trace.assumptions.assumed_ipca is not None
                else None
            ),
        },
        "curve_provenance": {
            "source": trace.curve_provenance.source,
            "anchor": iso(trace.curve_provenance.anchor),
            "curve_ref": trace.curve_provenance.curve_ref,
        },
    }


def build_envelope(
    spec: dict,
    trace: ProjectionTrace,
    *,
    curve_path: str | None,
    curve_data: dict | None,
    curve_bytes: bytes | None,
) -> dict:
    if curve_path is None:
        curve_file = None
    else:
        curve_file = {
            "path": curve_path,
            "as_of": curve_data.get("as_of") if curve_data else None,
            "sha256": sha256_hex(curve_bytes),
        }
    return {
        "trace_schema": 1,
        "methodology": "docs/METHODOLOGY.md",
        "inputs": spec,
        "curve_file": curve_file,
        "trace": trace_to_dict(trace),
    }


def to_json(envelope: dict) -> str:
    return json.dumps(envelope, indent=2, ensure_ascii=False) + "\n"


def trace_to_text(trace: ProjectionTrace, *, curve_file: dict | None) -> str:
    inv = trace.investment
    lines: list[str] = []

    # 1. Header
    lines.append("JustFixed -- Calculation Trace")
    lines.append(f"Product:        {inv.product.value}")
    lines.append(f"Issuer:         {inv.issuer.name}")
    lines.append(f"Principal:      {inv.principal.to_display()}")
    lines.append(f"Rate:           {inv.rate.to_display()}")
    lines.append(
        f"Purchase:       {iso(inv.purchase_date)}  ->  Maturity: {iso(inv.maturity_date)}"
    )
    lines.append(f"As of:          {iso(trace.as_of)}")
    lines.append(f"Convention:     {trace.convention}")
    lines.append("")

    # 2. Rate / current value
    lines.append("=== Current Value ===")
    if not trace.current_value_accrual:
        lines.append(
            f"Current value: {inv.principal.to_display()} (no accrual -- as_of <= purchase)"
        )
    else:
        s = trace.current_value_accrual[0]
        rr = s.rate
        lines.append(f"Source:               {rr.source}")
        lines.append(
            f"Resolved index rate:  "
            + (dec(rr.resolved_index_rate) if rr.resolved_index_rate is not None else "--")
        )
        lines.append(f"Effective annual:     {dec(rr.effective_annual_rate)}")
        lines.append(f"Du (business days):   {s.business_days}")
        lines.append(f"Factor:               {dec(s.factor)}")
        lines.append(f"Opening balance:      {s.opening_balance.to_display()}")
        lines.append(f"Closing balance:      {s.closing_balance.to_display()}")
        lines.append(f"Current value:        {trace.current_value.to_display()}")
    lines.append("")

    # 3. Cash flows
    lines.append("=== Cash Flows ===")
    for i, f in enumerate(trace.cash_flows, 1):
        lines.append(
            f"Flow {i}: {iso(f.pay_date)}  kind={f.kind.value}"
            f"  amount={f.amount.to_display()}"
        )
        lines.append(f"  Interest component:   {f.interest_component.to_display()}")
        lines.append(f"  Principal component:  {f.principal_component.to_display()}")
        for s in f.accrual:
            lines.append(f"  Accrual:  Du={s.business_days}  factor={dec(s.factor)}")
    lines.append("")

    # 4. Gross at maturity
    lines.append("=== Gross at Maturity ===")
    lines.append(f"Gross at maturity: {trace.gross_at_maturity.to_display()}")
    lines.append("")

    # 5. Tax
    t = trace.tax
    lines.append("=== Tax (IR) ===")
    lines.append(f"Treatment:             {t.treatment.value}")
    lines.append(f"Holding calendar days: {t.holding_calendar_days}")
    lines.append(f"Bracket rate:          {dec(t.bracket_rate)}")
    lines.append(f"Taxable gain:          {t.taxable_gain.to_display()}")
    lines.append(f"Tax amount (IR):       {t.tax_amount.to_display()}")
    lines.append(f"Net at maturity:       {trace.net_at_maturity.to_display()}")
    if len(t.per_flow) > 1:
        lines.append("  Per-flow IR withholding:")
        for pf in t.per_flow:
            lines.append(
                f"    {iso(pf.pay_date)}  hd={pf.holding_days}"
                f"  rate={dec(pf.bracket_rate)}"
                f"  interest={pf.taxable_interest.to_display()}"
                f"  tax={pf.tax_amount.to_display()}"
            )
    lines.append("")

    # 6. Assumptions
    lines.append("=== Assumptions ===")
    cdi_str = dec(trace.assumptions.assumed_cdi) if trace.assumptions.assumed_cdi is not None else "--"
    ipca_str = dec(trace.assumptions.assumed_ipca) if trace.assumptions.assumed_ipca is not None else "--"
    lines.append(f"assumed_cdi:   {cdi_str}")
    lines.append(f"assumed_ipca:  {ipca_str}")
    lines.append("")

    # 7. Curve provenance
    cp = trace.curve_provenance
    lines.append("=== Curve Provenance ===")
    source_str = (
        cp.source
        if cp.source is not None
        else "not stamped (no curve_source supplied)"
    )
    ref_str = cp.curve_ref if cp.curve_ref is not None else "(no curve)"
    lines.append(f"Source:    {source_str}")
    lines.append(f"Anchor:    {iso(cp.anchor) if cp.anchor is not None else '--'}")
    lines.append(f"curve_ref: {ref_str}")
    if curve_file is not None:
        lines.append(f"File path: {curve_file['path']}")
        lines.append(f"File as_of: {curve_file.get('as_of', '--')}")
        lines.append(f"SHA-256:   {curve_file['sha256']}")
    lines.append("")

    # 8. Disclosures
    lines.append("=== Disclosures ===")
    lines.append(
        "IOF not modeled (iof_modeled=false): redemptions before 30 days may incur"
    )
    lines.append(
        "  additional IOF taxes not reflected in this trace."
    )
    lines.append("Current value is accrual-only, not mark-to-market.")
    lines.append(
        "Post-fixed rates use a single-point flat curve assumption unless a published"
    )
    lines.append("  curve file is provided.")
    lines.append("Methodology: docs/METHODOLOGY.md")

    return "\n".join(lines) + "\n"


# =============================================================================
# Step D -- CLI
# =============================================================================


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce a JustFixed calculation trace from an instrument-spec JSON."
    )
    parser.add_argument("spec", help="Path to the instrument-spec JSON file")
    parser.add_argument(
        "--curve",
        metavar="PATH",
        help="Path to a curves/latest.json-format file",
    )
    parser.add_argument(
        "--curve-source",
        metavar="TEXT",
        help="Label stamped into CurveProvenance.source (e.g. the curve file path or origin tag)",
    )
    parser.add_argument(
        "--json-out",
        metavar="PATH",
        help="Write trace JSON to this path ('-' for stdout)",
    )
    parser.add_argument(
        "--text-out",
        metavar="PATH",
        help="Write text worksheet to this path ('-' for stdout)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = _parse_args(argv)

    spec_path = Path(args.spec)
    if not spec_path.exists():
        sys.exit(f"spec not found: {args.spec}")
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"invalid spec: {e}")

    curve_data: dict | None = None
    curve_bytes: bytes | None = None
    if args.curve:
        curve_path_obj = Path(args.curve)
        if not curve_path_obj.exists():
            sys.exit(f"curve not found: {args.curve}")
        curve_bytes = curve_path_obj.read_bytes()
        curve_data = json.loads(curve_bytes.decode("utf-8"))

    try:
        investment = build_investment(spec["investment"])
        as_of = date.fromisoformat(spec["as_of"])
        assumed_cdi = parse_decimal_opt(spec, "assumed_cdi")
        assumed_ipca = parse_decimal_opt(spec, "assumed_ipca")
    except (KeyError, ValueError) as e:
        sys.exit(f"invalid spec: {e}")

    cdi_curve, ipca_curve = load_curves(curve_data)

    try:
        trace = project_traced(
            investment,
            as_of=as_of,
            assumed_cdi=assumed_cdi,
            assumed_ipca=assumed_ipca,
            cdi_curve=cdi_curve,
            ipca_curve=ipca_curve,
            curve_source=args.curve_source,
        )
    except ValueError as e:
        sys.exit(str(e))

    envelope = build_envelope(
        spec,
        trace,
        curve_path=args.curve,
        curve_data=curve_data,
        curve_bytes=curve_bytes,
    )
    json_text = to_json(envelope)
    text = trace_to_text(trace, curve_file=envelope["curve_file"])

    if args.json_out is None and args.text_out is None:
        print(text, end="")
        print("\n===== TRACE JSON =====\n")
        print(json_text, end="")
    else:
        if args.text_out is not None:
            if args.text_out == "-":
                print(text, end="")
            else:
                Path(args.text_out).write_text(text, encoding="utf-8")
        if args.json_out is not None:
            if args.json_out == "-":
                print(json_text, end="")
            else:
                Path(args.json_out).write_text(json_text, encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
