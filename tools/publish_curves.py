"""Admin script: parse ANBIMA ETTJ CSV + B3 BDI_00 PDF → publish curves/latest.json.

Usage:
    python tools/publish_curves.py \\
        --anbima /path/to/ETTJ.csv \\
        --b3 /path/to/BDI_00_20260515.pdf \\
        --data-repo /path/to/justfixed-data \\
        [--as-of 2026-05-15] \\
        [--push]

Requires the [tools] extra:
    pip install -e ".[tools]"
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import fitz

from justfixed.engine.calendar import business_days_between, next_business_day
from justfixed.engine.curve import CurveVertex

# Public alias so tests can import it directly
Vertex = CurveVertex

_B3_MONTH_CODES: dict[str, int] = {
    "F": 1, "G": 2, "H": 3, "J": 4, "K": 5, "M": 6,
    "N": 7, "Q": 8, "U": 9, "V": 10, "X": 11, "Z": 12,
}

_RATE_MIN = Decimal("0")
_RATE_MAX = Decimal("0.30")

# Matches a DI1 settlement row in BDI_00 pdfplumber text:
# "DI1J27 BRBMEFD1I7C2 FINANCIAL <remaining fields>"
_DI1_ROW_RE = re.compile(
    r"^(DI1[A-Z]\d{2})\s+\S+\s+FINANCIAL\s+(.+)$",
    re.MULTILINE,
)

# Groups words from page.get_text("words") into visual table rows by y-coordinate proximity
_ROW_Y_TOLERANCE = 3.0
# Page-skip guard: matches an exact DI1 contract token; avoids noise like NCDI11
_DI1_CONTRACT_RE = re.compile(r"^DI1[A-Z]\d{2}$")


def contract_to_maturity(code: str) -> date:
    """DI1J27 → first business day of April 2027 per ANBIMA calendar."""
    letter = code[3]
    year = 2000 + int(code[4:6])
    month = _B3_MONTH_CODES[letter]
    return next_business_day(date(year, month, 1))


def _br_to_decimal(s: str) -> Decimal:
    """Convert Brazilian number format to Decimal: '14,3720' → Decimal('14.3720')."""
    return Decimal(s.replace(".", "").replace(",", "."))


def _check_rate(rate: Decimal, label: str) -> None:
    if not (_RATE_MIN < rate < _RATE_MAX):
        sys.exit(
            f"Rate out of valid range (0, 0.30): {rate} [{label}]. "
            "Check input files or --as-of date."
        )


def parse_anbima(csv_path: Path, as_of: date) -> tuple[list[Vertex], list[Vertex]]:
    """Parse ANBIMA ETTJ CSV → (pre_vertices, ipca_real_vertices).

    Rates in the CSV are in % p.a. (e.g. 14.56 means 14.56% = 0.1456 as a
    decimal fraction). Vertices are sorted ascending; monotonicity is validated.
    """
    text = csv_path.read_text(encoding="latin-1")
    lines = text.splitlines()

    # Locate the header row that names the ETTJ columns
    header_idx: int | None = None
    for i, line in enumerate(lines):
        if "ETTJ IPCA" in line and "ETTJ PREF" in line:
            header_idx = i
            break
    if header_idx is None:
        sys.exit(
            f"ANBIMA CSV: could not find 'ETTJ IPCA'/'ETTJ PREF' header in {csv_path}"
        )

    headers = [h.strip() for h in lines[header_idx].split(";")]
    try:
        idx_bdays = headers.index("Vertices")
        idx_ipca = next(i for i, h in enumerate(headers) if "ETTJ IPCA" in h)
        idx_pre = next(i for i, h in enumerate(headers) if "ETTJ PREF" in h)
    except (ValueError, StopIteration) as exc:
        sys.exit(f"ANBIMA CSV: unexpected header format: {exc}")

    pre_vertices: list[Vertex] = []
    ipca_vertices: list[Vertex] = []

    for line in lines[header_idx + 1:]:
        stripped = line.strip()
        if not stripped:
            break  # blank line ends the ETTJ section
        parts = [p.strip() for p in stripped.split(";")]
        if len(parts) <= max(idx_bdays, idx_ipca, idx_pre):
            continue
        try:
            bdays = int(parts[idx_bdays])
            pre_pct = _br_to_decimal(parts[idx_pre])
            ipca_pct = _br_to_decimal(parts[idx_ipca])
        except (ValueError, IndexError):
            continue

        pre_rate = pre_pct / Decimal("100")
        ipca_rate = ipca_pct / Decimal("100")

        _check_rate(pre_rate, f"ANBIMA PRE vertex {bdays}bd")
        _check_rate(ipca_rate, f"ANBIMA IPCA real vertex {bdays}bd")

        pre_vertices.append(Vertex(business_days=bdays, rate=pre_rate))
        ipca_vertices.append(Vertex(business_days=bdays, rate=ipca_rate))

    for label, verts in (("PRE", pre_vertices), ("IPCA real", ipca_vertices)):
        for i in range(len(verts) - 1):
            if verts[i].business_days >= verts[i + 1].business_days:
                sys.exit(
                    f"ANBIMA {label}: vertices not monotonically increasing at index {i}"
                )

    if not pre_vertices:
        print(f"Warning: no PRE vertices parsed from {csv_path}", file=sys.stderr)
    if not ipca_vertices:
        print(f"Warning: no IPCA real vertices parsed from {csv_path}", file=sys.stderr)

    return pre_vertices, ipca_vertices


def _di1_vertices_from_text(text: str, as_of: date) -> list[Vertex]:
    """Extract DI1 settlement vertices from one page of BDI_00 pdfplumber text.

    The settlement rate is at token index 7 after FINANCIAL in each row:
      DI1J27 <isin> FINANCIAL <open> <lo> <hi> <avg> <close> <var>
                               [0]   [1]  [2]  [3]   [4]    [5]
              <prev_pu> <settlement_rate> <settle_pu> ...
              [6]       [7 — this one]   [8]
    For no-trade contracts, tokens [0]-[5] are '-'; [7] is still the rate.
    """
    vertices: list[Vertex] = []
    for m in _DI1_ROW_RE.finditer(text):
        code = m.group(1)
        tokens = m.group(2).split()
        if len(tokens) < 8:
            continue
        rate_str = tokens[7]
        if rate_str == "-":
            continue
        try:
            rate_pct = _br_to_decimal(rate_str)
        except Exception:
            continue

        rate = rate_pct / Decimal("100")
        _check_rate(rate, f"B3 DI1 contract {code}")

        try:
            maturity = contract_to_maturity(code)
        except (KeyError, ValueError):
            print(f"  Warning: cannot parse maturity for {code!r}", file=sys.stderr)
            continue

        bdays = business_days_between(as_of, maturity)
        if bdays <= 0:
            continue  # already expired or same day

        vertices.append(Vertex(business_days=bdays, rate=rate))

    return vertices


def parse_b3(pdf_path: Path, as_of: date) -> list[Vertex]:
    """Parse B3 BDI_00 PDF → CDI forward curve vertices (sorted, deduplicated).

    Scans all pages for DI1 settlement rows. Aborts if none are found or any
    settlement rate is outside the valid range.
    """
    all_vertices: list[Vertex] = []

    print(f"Opening {pdf_path} ...", flush=True)
    doc = fitz.open(str(pdf_path))
    print(f"  {doc.page_count} pages — scanning for DI1 rows ...", flush=True)
    for i in range(doc.page_count):
        words = doc[i].get_text("words")
        if not any(_DI1_CONTRACT_RE.match(wt[4]) for wt in words):
            continue
        rows: dict[float, list] = {}
        for wt in words:
            y1 = wt[3]
            key = next((k for k in rows if abs(k - y1) <= _ROW_Y_TOLERANCE), y1)
            rows.setdefault(key, []).append(wt)
        lines = []
        for key in sorted(rows):
            sorted_row = sorted(rows[key], key=lambda t: t[0])
            lines.append(" ".join(t[4] for t in sorted_row))
        text = "\n".join(lines)
        all_vertices.extend(_di1_vertices_from_text(text, as_of))

    if not all_vertices:
        sys.exit("B3 PDF: no DI1 settlement rows found. Check PDF file and --as-of date.")

    # Sort by business_days; keep first occurrence when two contracts map to
    # the same number of business days (shouldn't happen normally)
    seen: set[int] = set()
    unique: list[Vertex] = []
    for v in sorted(all_vertices, key=lambda x: x.business_days):
        if v.business_days not in seen:
            seen.add(v.business_days)
            unique.append(v)

    return unique


def build_unified_json(
    as_of: date,
    cdi: list[Vertex],
    pre: list[Vertex],
    ipca_real: list[Vertex],
) -> dict:
    """Build the curves/latest.json payload."""

    def _verts(verts: list[Vertex]) -> list[dict]:
        return [
            {"business_days": v.business_days, "rate": round(float(v.rate), 8)}
            for v in verts
        ]

    return {
        "as_of": as_of.isoformat(),
        "schema_version": 1,
        "cdi": {"anchor": as_of.isoformat(), "vertices": _verts(cdi)},
        "pre": {"anchor": as_of.isoformat(), "vertices": _verts(pre)},
        "ipca_real": {"anchor": as_of.isoformat(), "vertices": _verts(ipca_real)},
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Publish curves/latest.json from ANBIMA ETTJ CSV + B3 BDI_00 PDF."
    )
    parser.add_argument("--anbima", required=True, metavar="PATH",
                        help="Path to local ANBIMA ETTJ CSV file")
    parser.add_argument("--b3", required=True, metavar="PATH",
                        help="Path to local B3 BDI_00 PDF file")
    parser.add_argument("--data-repo", required=True, metavar="PATH",
                        help="Path to local clone of justfixed-data repo")
    parser.add_argument("--as-of", metavar="YYYY-MM-DD",
                        help="Anchor date (default: today)")
    parser.add_argument("--push", action="store_true",
                        help="git push after committing")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    anbima_path = Path(args.anbima)
    b3_path = Path(args.b3)
    data_repo_path = Path(args.data_repo)

    for p, label in (
        (anbima_path, "--anbima"),
        (b3_path, "--b3"),
        (data_repo_path, "--data-repo"),
    ):
        if not p.exists():
            sys.exit(f"{label}: path not found: {p}")

    print(f"Publishing curves for {as_of.isoformat()}", flush=True)

    print(f"\nParsing ANBIMA CSV: {anbima_path}", flush=True)
    pre_vertices, ipca_vertices = parse_anbima(anbima_path, as_of)
    print(f"  PRE: {len(pre_vertices)} vertices")
    print(f"  IPCA real: {len(ipca_vertices)} vertices")

    print(f"\nParsing B3 PDF: {b3_path}", flush=True)
    cdi_vertices = parse_b3(b3_path, as_of)
    print(f"  CDI: {len(cdi_vertices)} vertices")

    payload = build_unified_json(as_of, cdi_vertices, pre_vertices, ipca_vertices)

    out_path = data_repo_path / "curves" / "latest.json"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {out_path}")

    subprocess.run(["git", "add", "curves/latest.json"], cwd=data_repo_path, check=True)

    try:
        subprocess.run(
            ["git", "commit", "-m", f"Curves for {as_of.isoformat()}"],
            cwd=data_repo_path,
            check=True,
        )
        print("Committed.")
    except subprocess.CalledProcessError:
        print("Warning: git commit failed (nothing to commit?)", file=sys.stderr)

    if args.push:
        subprocess.run(["git", "push"], cwd=data_repo_path, check=True)
        print("Pushed.")


if __name__ == "__main__":
    main()
