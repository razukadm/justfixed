# FGC Concentration Engine — Design Spec

This document specifies the FGC concentration check feature implemented in
`src/justfixed/engine/fgc.py`, and describes its as-built behavior. The test
suite in `tests/engine/test_fgc.py` is the executable form of this spec.

## What it does

Given a portfolio of `Investment` objects, computes the user's exposure to
the FGC (Fundo Garantidor de Créditos) per-conglomerate limit of R$ 250,000.
Returns a structured report showing, for each conglomerate the user has
FGC-covered exposure to, both **current** exposure (today) and **peak**
exposure (worst-case future).

This is a calculation, not a policy enforcer. It does not block actions —
it informs the user about exposure they may want to manage.

## Scope

In scope for Phase 1:
- Per-conglomerate exposure (R$ 250,000 cap)
- Three status tiers: under / approaching / over
- Both current and peak exposure, with separate status flags
- `[unverified]` conglomerate flagging (per-conglomerate, not portfolio-wide)
- Per-investment exposure data inside each conglomerate (for the future
  timeline UI to consume without engine changes)

Out of scope (deferred to future versions):
- R$ 1,000,000 / 4-year aggregate cap. The R$ 1M cap depends on actual
  past FGC payouts, not current holdings, so it doesn't activate for a
  user with no prior claims.
- Multiple CPFs / joint accounts. Phase 1 assumes one user owns all positions.
- Per-investment timeline view ("show me when each investment matures and
  what my running exposure looks like over time").
- Currency mixing. Phase 1 is BRL-only.
- Sector / non-FGC concentration metrics.

## Public API

Two public functions, both returning an `FGCReport`:

```python
def fgc_concentration_report(
    investments: list[Investment],
    as_of: date,
    assumed_cdi: Decimal,
    assumed_ipca: Decimal | None = None,
) -> FGCReport:
    """Compute FGC concentration exposure across the portfolio."""


def fgc_concentration_report_from_projections(
    projections: list[ProjectionResult],
) -> FGCReport:
    """Compute FGC concentration exposure from already-projected results."""
```

`fgc_concentration_report` parameters:
- `investments` — all of the user's investments. Treasury holdings are
  filtered out internally (FGC does not cover Tesouro).
- `as_of` — date for "current" calculations. Tests pass fixed dates; UI
  passes `date.today()`.
- `assumed_cdi` — annualized CDI rate (e.g., `Decimal("0.12")` for 12%).
  Required by the projection engine for post-fixed-rate investments.
  Unused for Prefixed and IPCA but still required for API consistency.
- `assumed_ipca` — annualized IPCA rate, optional; required only when the
  portfolio holds IPCA-linked investments. Propagated to `project()`.

It delegates to `engine/projection.py:project()` to compute each investment's
current and peak values, then aggregates by conglomerate.

`fgc_concentration_report_from_projections` takes a list of already-computed
`ProjectionResult`s instead of projecting internally — use it when projections
are already cached (e.g. on a conglomerate rename) to avoid re-projecting. It
derives `as_of` from the projections' shared `as_of` and raises `ValueError`
if they disagree. Both functions share the private
`_build_report_from_projections` helper, so they produce identical reports for
the same inputs.

## Data structures

All dataclasses are `frozen=True` (immutable value objects).

```python
class ExposureStatus(Enum):
    UNDER = "under"          # current value < R$ 200,000
    APPROACHING = "approaching"  # R$ 200,000 ≤ current value ≤ R$ 250,000
    OVER = "over"            # current value > R$ 250,000


@dataclass(frozen=True)
class InvestmentExposure:
    """Exposure data for one investment, for the future timeline view."""
    investment_id: uuid.UUID
    issuer_name: str
    product: ProductType
    purchase_date: date
    maturity_date: date
    principal: Money
    current_value: Money     # value at as_of date
    peak_value: Money        # value at this investment's own maturity


@dataclass(frozen=True)
class ConglomerateExposure:
    """FGC exposure for one conglomerate."""
    conglomerate_name: str
    investments: list[InvestmentExposure]   # constituent investments
    current_exposure: Money                  # sum of current_value across investments
    peak_exposure: Money                     # sum of peak_value across investments
    current_status: ExposureStatus           # threshold check on current_exposure
    peak_status: ExposureStatus              # threshold check on peak_exposure
    is_unverified: bool                      # True if conglomerate_name starts with [unverified]


@dataclass(frozen=True)
class FGCReport:
    """Top-level FGC concentration report."""
    conglomerates: list[ConglomerateExposure]   # sorted by current_exposure desc
    as_of: date

    @property
    def total_current_exposure(self) -> Money: ...

    @property
    def total_peak_exposure(self) -> Money: ...

    @property
    def conglomerates_at_or_over_limit(self) -> list[ConglomerateExposure]: ...

    @property
    def conglomerates_by_name(self) -> list[ConglomerateExposure]: ...
        # Same conglomerates, sorted alphabetically by name. For test
        # stability — production usage prefers `conglomerates` (by exposure).
```

## Module-level constants

```python
FGC_PER_CONGLOMERATE_LIMIT = Money.from_reais("250000")
FGC_APPROACHING_THRESHOLD = Money.from_reais("200000")
```

Both exported from `engine/fgc.py`. The approaching threshold is a tunable
buffer below the hard limit.

## Algorithm

1. **Filter to FGC-covered investments.** Skip any investment whose
   `issuer.kind == IssuerKind.TREASURY`. The issuer kind — not the product
   type — is the authoritative FGC-coverage signal. (Treasury is not
   FGC-covered: the user's Tesouro holdings are guaranteed by the federal
   government instead.)

2. **Group by conglomerate.** Each remaining investment's
   `issuer.conglomerate` is the grouping key. `[unverified] BMG` is its own
   group; `[unverified] PINE` is its own group; truly-grouped issuers
   share a key.

3. **Project each investment once.** Call
   `project(investment, as_of=as_of, assumed_cdi=assumed_cdi, assumed_ipca=assumed_ipca)`.
   A single call yields both numbers: `current_value` comes from
   `result.current_value` and `peak_value` (the per-investment peak) from
   `result.gross_at_maturity` — both live on the same `ProjectionResult`, so
   no second call with `as_of=maturity_date` is needed.

4. **Sum to produce conglomerate-level exposures.**
   - `current_exposure = sum(inv.current_value for inv in conglomerate)`
   - `peak_exposure = sum(inv.peak_value for inv in conglomerate)`

5. **Determine status for each.**
   - `< FGC_APPROACHING_THRESHOLD` → `UNDER`
   - `>= FGC_APPROACHING_THRESHOLD and <= FGC_PER_CONGLOMERATE_LIMIT` → `APPROACHING`
   - `> FGC_PER_CONGLOMERATE_LIMIT` → `OVER`

6. **Mark `is_unverified`** as `conglomerate_name.startswith(UNVERIFIED_CONGLOMERATE_PREFIX)`.

7. **Sort `conglomerates` by `current_exposure` descending.** Tied conglomerates
   resolve by alphabetical name as a stable secondary sort.

### Note on peak exposure being conservative

`peak_exposure` is computed as **sum of each investment's value at its own
maturity date**. This overstates the true peak because it assumes
simultaneous peaks, which can't actually happen — earlier-maturing
investments will have paid out before later ones reach their peak.

This is a deliberate conservative approximation. False positives (flagging a
conglomerate as peak-OVER when no instantaneous moment would have you over)
are safe; false negatives would mislead the user about future risk. The
engine docstring must document this clearly so future maintainers don't
"correct" it into a less-conservative number.

## Test plan

Sixteen tests, in `tests/engine/test_fgc.py`. The test list is the spec —
implementation that doesn't satisfy these tests is wrong, and implementation
satisfying these tests is correct.

### Group A — Empty and trivial cases

1. **`test_empty_portfolio_returns_empty_report`**
   Input: `investments=[]`. Expected: `FGCReport` with no conglomerates,
   `total_current_exposure == Money.from_reais("0")`,
   `total_peak_exposure == Money.from_reais("0")`,
   `conglomerates_at_or_over_limit == []`.

2. **`test_only_treasury_holdings_returns_empty_report`**
   Input: one or more `Investment` instances with TESOURO_IPCA / TESOURO_SELIC.
   Expected: empty `conglomerates` list. Treasury is FGC-excluded, so even if
   the user holds R$ 5M in Tesouro, the report shows zero exposure.

3. **`test_single_conglomerate_under_limit`**
   Input: one CDB at R$ 50,000, as_of == purchase_date so current_value ≈ principal.
   Expected: one conglomerate with `current_status == UNDER`,
   `current_exposure ≈ R$ 50,000`.

### Group B — Status tier boundaries (use β: as_of == purchase_date)

4. **`test_status_under_below_approaching_threshold`**
   Input: one investment with principal R$ 199,000, as_of == purchase_date.
   Expected: `current_status == UNDER`.

5. **`test_status_approaching_between_thresholds`**
   Input: one investment with principal R$ 220,000, as_of == purchase_date.
   Expected: `current_status == APPROACHING`.

6. **`test_status_over_above_limit`**
   Input: one investment with principal R$ 280,000, as_of == purchase_date.
   Expected: `current_status == OVER`.

### Group C — Multi-investment aggregation

7. **`test_multiple_investments_same_conglomerate_sum`**
   Input: three CDBs at the same bank (same conglomerate), each at
   R$ 100,000, as_of == purchase_date.
   Expected: one conglomerate, `current_exposure == R$ 300,000`,
   `current_status == OVER`, `len(investments) == 3`.

8. **`test_multiple_conglomerates_separate_rows`**
   Input: three CDBs at three different banks (three different conglomerates).
   Expected: three conglomerates in the report, each with its own status.

### Group D — Peak vs current divergence (use α: hand-compute)

9. **`test_peak_status_can_exceed_current_status`**
   Input: one CDB constructed so that `current_value` falls in the
   APPROACHING band (~R$ 230k today) but `peak_value` falls in the OVER
   band (~R$ 280k at maturity). Specific dates and rate must be
   hand-computed and documented in test comments.
   Expected: `current_status == APPROACHING`, `peak_status == OVER`.

10. **`test_peak_exposure_sum_of_per_investment_maturity_values`**
    Input: two CDBs in the same conglomerate with **different maturity dates**.
    Expected: `peak_exposure == inv1.peak_value + inv2.peak_value`, where
    each `peak_value` is the projected value at *that investment's own*
    maturity (not at the latest maturity). This test pins the conservative
    approximation described above.

### Group E — Unverified handling

11. **`test_unverified_conglomerate_flagged`**
    Input: two CDBs at two different unverified-conglomerate banks
    (e.g., `[unverified] BMG` and `[unverified] PINE`).
    Expected: two conglomerates in the report, both with
    `is_unverified == True`.

### Group F — `conglomerates_at_or_over_limit` and IPCA propagation

12. **`test_approaching_not_in_at_or_over_limit_list`**
    Input: one conglomerate whose `current_status == APPROACHING` (between the
    thresholds). Expected: it appears in `conglomerates` but **not** in
    `conglomerates_at_or_over_limit` — that property lists only OVER (and
    exactly-at-limit) conglomerates.

13. **`test_fgc_concentration_report_propagates_assumed_ipca`**
    Input: an IPCA-linked investment with a non-None `assumed_ipca`.
    Expected: the value reflects the supplied `assumed_ipca` — i.e. the rate
    is passed through to `project()` rather than dropped.

### Group G — `fgc_concentration_report_from_projections`

14. **`test_from_projections_empty`**
    Input: `projections=[]`. Expected: empty `FGCReport` (no conglomerates),
    `as_of` defaulting to `date.today()`.

15. **`test_from_projections_single_conglomerate_sums_exposure`**
    Input: already-computed `ProjectionResult`s for one conglomerate.
    Expected: the same aggregation as `fgc_concentration_report`, consuming
    `current_value` from each result without re-projecting.

16. **`test_from_projections_mismatched_as_of_raises`**
    Input: projections with two different `as_of` dates. Expected:
    `ValueError` — the variant requires a single shared valuation date.

### Test-style guidance

- **Tests look up conglomerates by name**, not by index. Use:
```python
  inter = next(c for c in report.conglomerates if c.conglomerate_name == "Banco Inter")
```
  Indexing is fragile because sort order depends on the test's exposure
  values — a small change can shift positions. Lookup by name is stable.

- **Use `report.conglomerates_by_name` when iterating in deterministic order**
  for assertions that don't depend on a specific name.

- **Hand-computed values get a code comment showing the math.** For test 9
  in particular, the comment should show: principal, rate, days from
  purchase to as_of, days from purchase to maturity, accrual factor,
  resulting current_value, resulting peak_value. The test must remain
  understandable without re-deriving the math from scratch.

## Prerequisite (done first)

`UNVERIFIED_CONGLOMERATE_PREFIX` was moved from
`src/justfixed/importers/xp_loader.py` to `src/justfixed/domain/issuer.py`
before this engine landed: the engine needs it to detect unverified
conglomerates, and importing it from the importers layer would have broken
the layer ordering (engine sits "below" importers in the dependency graph).
It now lives in `domain/issuer.py` as a module-level export, consumed by both
the loaders and this engine.

## How it was built

1. Moved `UNVERIFIED_CONGLOMERATE_PREFIX` to `domain/issuer.py`.
2. Wrote the test file `tests/engine/test_fgc.py` (TDD — the tests failed with
   `ImportError` until the engine existed).
3. Implemented `engine/fgc.py` until the tests turned green. The second entry
   point, `fgc_concentration_report_from_projections`, and its tests were added
   later when the UI needed cache-aware re-aggregation on a conglomerate rename.
4. Updated `docs/ARCHITECTURE.md` and `CLAUDE.md` to reflect FGC as built.