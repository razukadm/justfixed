# JustFixed — Calculation Methodology

**Status:** Control document. This is the asserted methodology for every number JustFixed
computes and displays. It is written from, and governed by, the engine source; where the two
ever disagree, the code is authoritative and this document is the bug.

**Reflects:** the engine as built at the Audit Slice 1 commit (calculation trace + single-
source-of-truth accrual/projection). Modules governed: `engine/accrual.py`, `engine/projection.py`,
`engine/cashflow.py`, `engine/tax.py`, `engine/curve.py`, `engine/calendar.py`,
`engine/fetcher.py`, `engine/trace.py`, `domain/money.py`, `domain/rates.py`, `domain/product.py`.

**Purpose (audit finding F-03):** give a third party the asserted control against which the
machine-generated calculation trace (`engine/trace.py`, `project_traced()`) can be checked.
Section 10 maps every trace field to the section that governs it.

**Scope and non-scope.** This document covers projection of a single fixed-income instrument:
current value, the cash-flow schedule, gross and net at maturity, and the tax calculation. It
does NOT cover portfolio aggregation, FGC concentration, importers, or the UI. Known
limitations and disclosures are consolidated in Section 9.

---

## 1. Numeric model and rounding

All monetary arithmetic uses Python `Decimal`. Floats are forbidden at construction
(`Money`, `Rate`, and curve parsing all reject `float`). Three rounding rules apply, and only
these three:

| # | Quantity | Rule |
|---|----------|------|
| R1 | Compound factor `(1 + i)^(Du/252)` | Computed at the default `Decimal` context — **28 significant digits**, `ROUND_HALF_EVEN`. Not quantized; carried full-precision. |
| R2 | Every `Money` amount | Quantized to **8 decimal places**, `ROUND_HALF_EVEN`, on every construction and every arithmetic operation. |
| R3 | Displayed `Money` (UI/export only) | Quantized to **2 decimal places**, `ROUND_HALF_EVEN`, at format time. Does not affect stored or computed values. |

R1 is the raw `factor` recorded on each `AccrualStep`. R2 governs `opening_balance`,
`closing_balance`, every flow amount, gross, tax, and net. R3 is presentation only.

**Reproduction tolerance.** Reproducing any computed number from the trace under R1+R2 is
**exact** (zero tolerance): verify `factor` per R1, then `closing_balance = quantize8(opening_balance × factor)`
per R2. Tolerance language is reserved exclusively for comparison against *external* oracles
(Tesouro Direto official prices, an ANBIMA worked example), where the counterparty's rounding
conventions differ from ours.

---

## 2. Business-day convention

Brazilian fixed-income interest accrues over business days (*dias úteis*), not calendar days.

- **Denominator:** 252. This is a market *convention*, not the empirical count of business
  days in a year. All rates in this system are quoted on the 252 basis.
- **Holiday calendar:** the **ANBIMA** calendar, loaded via the `bizdays` library
  (`Calendar.load("ANBIMA")`). This is the standard Brazilian financial-market holiday set;
  it coincides with the calendar B3 publishes. The trace records this convention as the string
  `"252 bd/yr; B3/ANBIMA holidays"`.
- **Interval semantics:** business-day counts use a **half-open interval `[start, end)`** —
  start inclusive, end exclusive — and return 0 when `end <= start`. This is the correct
  accrual semantic ("days from purchase up to but not including the end date").

`Du` (the business-day count in an accrual step) is always `business_days_between(from_date, to_date)`
under these rules.

---

## 3. Rate types and the effective annual rate

An instrument carries exactly one rate, one of four kinds. Each resolves to a single
**effective annual rate `i`** (a decimal fraction), after which accrual is identical across
kinds (Section 5). Rate parameters are stored as fractions/multipliers, not percentages.

| Rate kind | Stored parameter | Combination rule | Effective annual rate `i` |
|-----------|------------------|------------------|---------------------------|
| `Prefixed` | `annual_rate` (e.g. 0.12) | — (fixed) | `i = annual_rate` |
| `PostFixedCDI` | `cdi_percentage` as a **multiplier** (e.g. 1.10 for "110% do CDI") | **Multiplicative** | `i = cdi_percentage × CDI` |
| `PostFixedCDIPlusSpread` | `spread` (e.g. 0.0205 for "CDI + 2,05%") | **Fisher** | `i = (1 + CDI)(1 + spread) − 1` |
| `PostFixedIPCA` | `spread` (e.g. 0.055 for "IPCA + 5,5%") | **Fisher** | `i = (1 + IPCA)(1 + spread) − 1` |

Here `CDI` and `IPCA` are the **resolved index levels** (Section 4). `PostFixedCDI` and
`PostFixedCDIPlusSpread` are mathematically distinct and must not be conflated: the first
scales CDI multiplicatively; the second adds a spread with the Fisher cross-term.

**Worked checks** (resolved CDI = 0.12, resolved IPCA = 0.04):
- `Prefixed` 12%: `i = 0.12`.
- 110% do CDI: `i = 1.10 × 0.12 = 0.132`.
- CDI + 2,05%: `i = (1.12)(1.0205) − 1 = 0.142960`.
- IPCA + 5,5%: `i = (1.04)(1.055) − 1 = 0.0972`.

In the trace, `RateResolution` records `rate_kind`, the resulting `effective_annual_rate`,
the `resolved_index_rate` (the `CDI`/`IPCA` level used; `None` for `Prefixed`), and
`index_multiplier_or_spread` (the multiplier for `PostFixedCDI`, the spread for the two Fisher
kinds; `None` for `Prefixed`). An auditor recomputes `i` from those two components using the
rule selected by `rate_kind` and asserts equality.

---

## 4. Rate resolution and curve usage

For post-fixed kinds the index level is resolved from a yield curve when one is available, and
otherwise from a static assumed scalar. The resolution is recorded on `RateResolution.source`:

| `source` | Condition | Resolved level |
|----------|-----------|----------------|
| `"fixed"` | `Prefixed` | n/a — the rate is the instrument's own fixed rate |
| `"curve"` | a curve is supplied **and has vertices** | `curve.rate_at(lookup_date)` |
| `"assumed_fallback"` | no curve, or an empty curve | the assumed scalar (`assumed_cdi` / `assumed_ipca`) |

When `source == "curve"`, the trace also records `curve_anchor` (the curve's anchor date) and
`curve_tenor_date` (the `lookup_date` passed to `rate_at`). Both are `None` otherwise. If a
post-fixed instrument has neither a usable curve nor an assumed scalar, resolution raises
`ValueError`.

**Lookup-date rules (a deliberate CDI/IPCA divergence — do not harmonize):**

| Context | `PostFixedCDI` / `PostFixedCDIPlusSpread` | `PostFixedIPCA` |
|---------|-------------------------------------------|-----------------|
| Current value | `min(as_of, maturity_date)` | `maturity_date` |
| Coupon flow | that coupon's pay date | `maturity_date` |
| Bullet / final flow | `maturity_date` | `maturity_date` |

Rationale: the breakeven-inflation curve used for IPCA instruments expresses a **term
expectation for the whole instrument**, so every flow reads it at the maturity tenor; the CDI
curve is read at each flow's own date. A consequence: for a CDI coupon instrument the effective
rate `i` can differ between coupon periods (each period reads the curve at its own date), while
for an IPCA coupon instrument `i` is the same across all periods.

**Curve interpolation and extrapolation.** A curve is an anchor date plus vertices, each a
`(business_days_from_anchor, annualized_rate)` pair sorted ascending. `rate_at(target)`:

1. Converts `target` to `Du = business_days_between(anchor, target)`.
2. If `Du <= first vertex`, returns the first vertex's rate; if `Du >= last vertex`, returns the
   last vertex's rate (**flat extrapolation** beyond both ends; pre-anchor and at-anchor dates
   return the first vertex — the curve does not model historical rates).
3. Otherwise **linear interpolation on the rate** between the two bracketing vertices.

**Single-point-flat application.** The resolved level is **one** rate, read at **one**
`lookup_date`, and then applied **flat** across the entire accrual span via the constant
effective rate `i`. The engine does **not** integrate forward rates across the curve. See
disclosure F-08.

The assumptions actually used are echoed on `ProjectionTrace.assumptions`
(`assumed_cdi`, `assumed_ipca`). Curve **data provenance** (which published curve, fetched
live vs from cache) is a separate layer carried on `ProjectionTrace.curve_provenance`; see
Section 9, F-02/F-08, for its current state.

---

## 5. Accrual and current value

**Accrual.** Over a period of `Du` business days at effective annual rate `i`:

> `closing_balance = opening_balance × (1 + i)^(Du / 252)`

applied as a **single compound factor** for the whole period (not a day-by-day product). The
factor obeys R1; the balance obeys R2.

**Current value.** The value as of a valuation date `as_of` is the **principal compounded at
the instrument's effective rate from `purchase_date` to `min(as_of, maturity_date)`**:

- If `as_of <= purchase_date`, or the business-day count is 0: current value = principal, and
  `current_value_accrual` is the empty tuple `()` (nothing has accrued).
- Otherwise: one `AccrualStep` over `[purchase_date, min(as_of, maturity)]`; current value is
  that step's `closing_balance`. Accrual is capped at maturity (it does not accrue past it).

Current value is a **gross accrual of the full principal**. For a coupon-paying instrument it
does **not** deduct coupons already disbursed and does not reset to face at each coupon date;
it is therefore not a position value or a clean/dirty market price for coupon instruments.
Current value is **accrual-only** — there is no mark-to-market. See disclosure F-05.

---

## 6. Cash-flow schedule

**Bullet instruments** (`CouponFrequency.NONE`): a single flow at `maturity_date` of kind
`PRINCIPAL`, amount = principal accrued over `[purchase_date, maturity_date]`.

**Coupon instruments** (`MONTHLY` / `SEMI_ANNUAL`): coupon dates are generated by stepping
**backward** from maturity by the period and rolling any non-business day **forward** to the
next business day; the maturity date itself is the principal payment and is not a coupon date.
Then:

- Each **coupon** flow (kind `COUPON`) pays the interest accrued on the **face principal** over
  its own period `[period_start, coupon_date]`:
  `coupon = principal × ((1 + i)^(Du_period / 252) − 1)`, with `period_start` advancing to each
  coupon date. The principal is **not** compounded across coupons (each period accrues face).
- The **final** flow (kind `COUPON_AND_PRINCIPAL`) pays the last period's interest **plus** the
  principal: `final = principal × ((1 + i)^(Du_final / 252) − 1) + principal`.

`gross_at_maturity` is the **sum of all flow amounts**.

In the trace, each `FlowTrace` carries the schedule's `amount` **unchanged** (it is never
recomputed in the trace layer), its `kind`, an `interest_component` and a `principal_component`
(`principal_component` = principal for `PRINCIPAL` and `COUPON_AND_PRINCIPAL`, zero for
`COUPON`; the two components sum to `amount`), and exactly one `AccrualStep` mirroring the
single accrual the schedule performed for that flow.

---

## 7. Taxation (IR)

Tax is **Imposto de Renda (IR)** only, applied to the **gain** `gross − principal`. There is no
tax on a non-positive gain.

**Regressive regime (`IR_REGRESSIVE`).** The rate is selected by holding period in **calendar
days** (not business days — one of the few places Brazilian tax law uses calendar days), per
**Instrução Normativa RFB nº 1.585/2015**:

| Holding period (calendar days) | IR rate |
|--------------------------------|---------|
| 0 – 180 | 22.5% |
| 181 – 360 | 20.0% |
| 361 – 720 | 17.5% |
| 721 or more | 15.0% |

**Exempt regime (`IR_EXEMPT`).** Rate is 0% for individuals (PF).

**Holding period used.** `holding_calendar_days = (maturity_date − purchase_date).days`, i.e.
the full holding period to maturity.

**Coupon instruments — simplification.** IR is computed once, on the **summed** gross at the
**terminal** bracket implied by the full holding period — it is **not** withheld per coupon at
each coupon's own bracket. The per-coupon rule would apply higher (less favourable) brackets to
early coupons; the difference is modest for typical retail holdings. See disclosure F-07.

**IOF.** Not modelled. The trace's `TaxTrace.iof_modeled` is always `False`, self-disclosing
the omission. See disclosure F-06.

In the trace, `TaxTrace` records `treatment`, `holding_calendar_days`, `bracket_rate`,
`taxable_gain`, `tax_amount`, and `iof_modeled`. `net_at_maturity = gross_at_maturity − tax_amount`.

---

## 8. Product taxonomy

Each product type maps to a fixed tax treatment, FGC coverage flag, and allowed coupon
frequencies (single source of truth in `domain/product.py`):

| Product | Tax treatment | FGC-covered | Coupons allowed |
|---------|---------------|-------------|-----------------|
| CDB | Regressive | Yes | Any |
| LCI | Exempt | Yes | None (bullet) |
| LCA | Exempt | Yes | Any |
| LC (Letra de Câmbio) | Regressive | Yes | Any |
| LCD | Exempt | Yes | None (bullet); min. term 365 days |
| Tesouro Selic | Regressive | No (Treasury) | None (bullet) |
| Tesouro Prefixado | Regressive | No (Treasury) | None or semi-annual |
| Tesouro IPCA+ | Regressive | No (Treasury) | None or semi-annual |

---

## 9. Stated limitations and disclosures

These are deliberate, known properties of the current engine. Each states what the engine does,
why, its materiality, and where it is surfaced in the trace.

**F-05 — Current value is accrual-only, not mark-to-market.** Current value compounds principal
at the instrument's effective rate (Section 5); it is not a marked price. **Materiality: high
for Tesouro Direto**, whose official daily price (PU) reflects secondary-market marking and can
diverge materially from accrual. For CDI-linked bank instruments held to maturity, accrual and a
marked value are close. Surfaced: `ProjectionTrace.current_value` is the accrual figure; there
is no MtM field.

**F-06 — IOF is not modelled.** The IOF levied on redemptions within the first 30 days is not
computed. **Materiality: low** (most holdings clear 30 days). Surfaced: `TaxTrace.iof_modeled = False`.

**F-07 — Coupon IR uses the terminal bracket on summed gain.** Per Section 7, coupon instruments
are not taxed with per-coupon withholding. **Materiality: medium for coupon instruments**, low
otherwise. Surfaced: the single `TaxTrace` with `holding_calendar_days` to maturity; `cash_flows`
shows the gross coupons it was applied to.

**F-08 — Single-point-flat curve use; assumed-scalar fallback; live/cached source not yet stamped
by the app.** The curve is read at one tenor and applied flat (Section 4); when no usable curve is
present the engine falls back to a static assumed scalar. **Materiality: medium.** The fallback,
previously silent, is now surfaced via `RateResolution.source == "assumed_fallback"`, and the
tenor via `curve_tenor_date`. **Provenance status:** `curve_provenance.curve_ref` is now populated
with a deterministic SHA-256 content-hash of the curve used (anchor + sorted vertices); it is
`None` only when no curve resolved the rate (pure-fixed or assumed-fallback). `curve_provenance.source`
is threaded via a `curve_source` parameter on `project_traced()`; it is stamped when a caller
supplies it. The running application does not yet emit traces (it calls `project()`, not
`project_traced()`), so the live-vs-cached source captured from a live fetch is still future work —
the plumbing exists, the app-level producer does not. `curve_provenance.anchor` is populated from
the curve when one is used.

**F-02 — Published curve provenance/chain of custody (resolved).** The published curve now carries
a Track B provenance manifest: per-source role, filename, sha256, size, retained-path, tool
name/version/git_commit, and convention. `curve_ref` in the trace is populated with a deterministic
SHA-256 content-hash of the curve used (see F-08 above).

**F-09 — Curve rates are serialized as floating point (advisory).** The published curve stores
rates as JSON floats; they are parsed back into `Decimal` on load. The serialization format is a
float; all *computation* is `Decimal`.

**F-10 — Interpolation is linear-on-rates with flat extrapolation (advisory).** Section 4
describes the method. It is a simplification and **may differ from the index provider's official
ETTJ interpolation methodology; it has not been reconciled against ANBIMA's published method.**

**F-11 — Headless reproduce-trace command (shipped).** `tools/reproduce_trace.py` takes an
instrument-spec JSON plus an optional curve file and emits the full calculation trace as JSON and
readable text; see `tools/` for usage.

---

## 10. Trace ↔ methodology cross-reference

For an auditor reading a `ProjectionTrace`, each field is governed by:

| Trace field | Governed by |
|-------------|-------------|
| `investment` (echoed principal, rate, dates, product, coupon_frequency) | §3, §8 |
| `as_of` | §5 |
| `convention` | §2 |
| `current_value`, `current_value_accrual` | §5 (R1/R2 for the step) |
| `cash_flows` (`FlowTrace`) | §6 |
| `FlowTrace.amount` / `interest_component` / `principal_component` | §6 |
| `FlowTrace.accrual` (`AccrualStep`) | §5 (`factor` R1, balances R2), §2 (`Du`) |
| `AccrualStep.rate` (`RateResolution`) | §3 (effective rate), §4 (source, curve lookup) |
| `gross_at_maturity` | §6 |
| `tax` (`TaxTrace`), `net_at_maturity` | §7 |
| `tax.iof_modeled` | §7, §9 F-06 |
| `assumptions` | §4 |
| `curve_provenance` | §4, §9 F-08/F-02 |

---

## 11. Authoritative sources

- **IR (regressive table, calendar-day basis):** Instrução Normativa RFB nº 1.585/2015.
- **252 business-day basis and holiday calendar:** ANBIMA market convention (holiday set loaded
  via the `bizdays` library's `ANBIMA` calendar).
- **Curve interpolation vs. official ETTJ:** not yet reconciled — see F-10.

---

*Maintenance:* this document is governed by the engine modules listed at the top. Any change to
accrual, rate resolution, curve usage, scheduling, or taxation must update the corresponding
section here in the same change. The machine-readable counterpart is `engine/trace.py`.
