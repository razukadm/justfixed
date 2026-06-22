# JustFixed — External-Oracle Conformance Evidence

**Status:** Audit evidence for finding F-04. Demonstrates that the engine's calculations conform to
authoritative external methodologies (Tesouro Nacional, ANBIMA) within a stated tolerance, and
states precisely where the engine's methodology diverges (by design and disclosure) from official
pricing. The machine-checkable form of this document is `tests/conformance/test_external_oracles.py`.

**Companion artifacts:** `docs/METHODOLOGY.md` (asserted methodology), `engine/trace.py` /
`project_traced()` (calculation trace), and `tools/publish_curves.py --verify-as-of` (independent
re-derivation of the curve from archived raw inputs).

## Conformance layers

Each vector is checked at up to three layers:
1. **Kernel** — the engine's compound factor `(1 + i)^(du/252)` reproduces the published price to the
   issuer's published truncation (exact; the engine uses the same Decimal kernel).
2. **Calendar** — the engine's `business_days_between(settlement, maturity)` equals the issuer's stated
   `du` (exact integer match; this conforms the engine's ANBIMA holiday calendar to the issuer's).
3. **End-to-end** — buying at the published price and projecting to maturity reconstructs the face
   value within R$0.01 (the only residual is the published price's truncation times the factor).

## V1 — Tesouro Prefixado (LTN), official Tesouro Nacional methodology

- **Source:** Tesouro Nacional, "Metodologia de Calculo dos Titulos Publicos Federais."
- **Formula:** `PU = 1000 / (1 + taxa)^(du/252)`, PU truncated at the 6th decimal.
- **Inputs:** taxa = 14.3600% a.a.; settlement 2008-05-21; maturity 2010-07-01; du = 532.
- **Published PU:** 753.315323.
- **Engine result:** factor `(1.1436)^(532/252)` gives `1000 / factor = 753.315323` (6dp) — exact
  match; `business_days_between(2008-05-21, 2010-07-01) = 532` — exact; forward reconstruction
  `753.315323 x factor = 999.99999990` ≈ R$1000.00 (< R$0.01).
- **Tolerance:** PU exact to 6 decimals; du exact; face within R$0.01. **PASS.**
- This vector covers both the "prefixed CDB" and "Tesouro bond" samples (identical prefixed math).

## V2 — Tesouro IPCA+ (NTN-B) real-rate Cotação, ANBIMA / Tesouro methodology

- **Source:** ANBIMA, "Metodologias ANBIMA de Precificacao" (and the Tesouro NTN-B methodology).
- **Formula (Cotação):** `Cotacao = 100 / (1 + real)^(du/252)`, truncated at the 4th decimal.
- **Inputs:** real = IPCA + 2,19%; settlement 2019-10-25; maturity 2024-08-15; du = 1205.
- **Published Cotação:** 90.1594.
- **Engine result:** factor `(1.0219)^(1205/252)` gives `100 / factor = 90.1594` (4dp) — exact match;
  `business_days_between(2019-10-25, 2024-08-15) = 1205` — exact.
- **Tolerance:** Cotação exact to 4 decimals; du exact. **PASS (real-rate kernel).**
- **Divergence (out of scope, disclosed F-05/F-08):** the full NTN-B price is `PU = VNA x Cotacao/100`,
  where the VNA is R$1000 updated by *realized* IPCA since the 2000 base date. The engine does not
  model the VNA / realized-IPCA indexation; it Fisher-combines a *market breakeven* inflation curve
  with the real spread. Only the real-rate Cotação kernel is conformed here; full NTN-B PU
  conformance is not claimed.

## V3 — CDI-linked CDB

- **No public price oracle exists** for bank CDBs (they are not publicly priced like Treasury bonds).
- **Conformance:** the engine's `% CDI` rule is multiplicative — effective rate = multiplier x CDI
  (e.g. 110% of a 10% CDI = 11.0%) — and the accrual then uses the same `(1 + i)^(du/252)` kernel that
  V1 validates against the official Tesouro oracle. No external market-price match is asserted.

## Curve re-derivation (DoD)

The audit's definition of done requires the curve to be independently re-derivable from archived
source. `tools/publish_curves.py --verify-as-of <YYYY-MM-DD>` re-reads the retained raw inputs
(`raw/<as_of>/`), re-parses them, and confirms the published curve sections and source hashes match
(see `docs/METHODOLOGY.md` and the Track B provenance block).

## Known methodology divergences (consolidated)

- **NTN-B full PU:** engine uses a market breakeven curve, not realized-IPCA VNA (F-05/F-08).
- **CDB market price:** no public oracle; kernel + rule only (V3).
- **Curve interpolation (F-10):** ANBIMA uses exponential interpolation and forward-rate
  extrapolation; the engine uses linear-on-rates interpolation with flat extrapolation. This is not
  reconciled and is disclosed in `docs/METHODOLOGY.md`.

## Mark-to-market

Conformance here is against *carry/accrual to maturity* and the issuers' *curve/discount* formulas,
not against secondary-market marked prices. The engine's current value is accrual-only (F-05); it is
not a marked price and is not conformed against one.
