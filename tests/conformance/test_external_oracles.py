"""External-oracle conformance evidence for audit finding F-04.

Sources:
- Tesouro Nacional, "Metodologia de Calculo dos Titulos Publicos Federais"
  (LTN pricing: PU = 1000 / (1 + taxa)^(du/252), truncated at 6dp)
- ANBIMA, "Metodologias ANBIMA de Precificacao"
  (NTN-B Cotacao: Cotacao = 100 / (1 + real)^(du/252), truncated at 4dp)

Three conformance layers verified here:
1. Kernel — (1+i)^(du/252) reproduces the published price to the issuer's
   published truncation (exact).
2. Calendar — business_days_between(settlement, maturity) equals the stated du
   (exact integer).
3. End-to-end — buying at the published price and projecting to maturity
   reconstructs the face value within R$0.01.

Documented divergence boundaries:
- Full NTN-B PU (= VNA x Cotacao/100) is out of scope: the VNA is R$1000
  updated by realized IPCA since the 2000 base date; the engine uses a market
  breakeven inflation curve instead (F-05/F-08).
- CDI CDB: no public price oracle exists; kernel + documented rule only (V3).
- Curve interpolation (F-10): ANBIMA uses exponential interpolation; the engine
  uses linear-on-rates with flat extrapolation (disclosed in METHODOLOGY.md).
"""

from datetime import date
from decimal import Decimal, ROUND_DOWN

from justfixed.domain.investment import Investment
from justfixed.domain.issuer import Issuer, IssuerKind
from justfixed.domain.money import Money
from justfixed.domain.product import CouponFrequency, ProductType
from justfixed.domain.rates import PostFixedCDI, PostFixedIPCA, Prefixed
from justfixed.engine.accrual import accrue
from justfixed.engine.calendar import business_days_between
from justfixed.engine.projection import project_traced


def _trunc(x: Decimal, places: int) -> Decimal:
    return x.quantize(Decimal(1).scaleb(-places), rounding=ROUND_DOWN)


FACE_TOLERANCE = Decimal("0.01")


class TestTesouroLTNConformance:
    """V1 — Tesouro Prefixado (LTN) against the official Tesouro Nacional methodology.

    Published inputs: taxa = 14.3600% a.a.; settlement 2008-05-21;
    maturity 2010-07-01; du = 532; PU = 753.315323 (truncated at 6dp).
    """

    def test_calendar_matches_official_du(self):
        assert business_days_between(date(2008, 5, 21), date(2010, 7, 1)) == 532

    def test_engine_factor_reproduces_official_pu(self):
        inv = Investment.create(
            product=ProductType.TESOURO_PREFIXADO,
            issuer=Issuer.treasury(),
            principal=Money.from_reais("753.315323"),
            rate=Prefixed.from_percent("14.36"),
            purchase_date=date(2008, 5, 21),
            maturity_date=date(2010, 7, 1),
        )
        trace = project_traced(inv, as_of=date(2010, 7, 1))
        engine_factor = trace.cash_flows[0].accrual[0].factor
        assert _trunc(Decimal("1000") / engine_factor, 6) == Decimal("753.315323")

    def test_forward_reconstruction_to_face_via_accrue(self):
        g = accrue(Money.from_reais("753.315323"), Prefixed.from_percent("14.36"), 532)
        assert abs(g.amount - Decimal("1000")) < FACE_TOLERANCE

    def test_end_to_end_gross_at_maturity(self):
        inv = Investment.create(
            product=ProductType.TESOURO_PREFIXADO,
            issuer=Issuer.treasury(),
            principal=Money.from_reais("753.315323"),
            rate=Prefixed.from_percent("14.36"),
            purchase_date=date(2008, 5, 21),
            maturity_date=date(2010, 7, 1),
        )
        trace = project_traced(inv, as_of=date(2010, 7, 1))
        assert abs(trace.gross_at_maturity.amount - Decimal("1000")) < FACE_TOLERANCE


class TestNTNBCotacaoConformance:
    """V2 — Tesouro IPCA+ (NTN-B) real-rate Cotação kernel only.

    Published inputs: real = IPCA + 2.19%; settlement 2019-10-25;
    maturity 2024-08-15; du = 1205; Cotacao = 90.1594 (truncated at 4dp).
    Formula: Cotacao = 100 / (1 + real)^(du/252).

    The full NTN-B PU (= VNA x Cotacao/100) is out of scope: the VNA
    is R$1000 updated by realized IPCA since the 2000 base date, which
    the engine does not model (F-05/F-08).
    """

    def test_calendar_matches_official_du(self):
        assert business_days_between(date(2019, 10, 25), date(2024, 8, 15)) == 1205

    def test_engine_real_rate_factor_reproduces_cotacao(self):
        # Isolate the real-rate discount kernel using a Prefixed(real) instrument.
        # This is exactly what the NTN-B Cotacao formula computes; the engine's
        # PostFixedIPCA additionally Fisher-combines a breakeven-IPCA term
        # (the disclosed divergence documented in test_ipca_methodology_divergence_is_real).
        inv = Investment.create(
            product=ProductType.TESOURO_PREFIXADO,
            issuer=Issuer.treasury(),
            principal=Money.from_reais("1000"),
            rate=Prefixed.from_percent("2.19"),
            purchase_date=date(2019, 10, 25),
            maturity_date=date(2024, 8, 15),
        )
        trace = project_traced(inv, as_of=date(2024, 8, 15))
        engine_factor = trace.cash_flows[0].accrual[0].factor
        assert _trunc(Decimal("100") / engine_factor, 4) == Decimal("90.1594")

    def test_ipca_methodology_divergence_is_real(self):
        # Document WHY full NTN-B PU is out of scope: PostFixedIPCA Fisher-combines
        # IPCA with the real spread, so its effective annual rate exceeds the bare
        # real spread of 2.19%. The engine cannot reproduce the bare Cotacao kernel
        # via PostFixedIPCA — that is the disclosed divergence (F-05/F-08).
        inv = Investment.create(
            product=ProductType.TESOURO_IPCA,
            issuer=Issuer.treasury(),
            principal=Money.from_reais("1000"),
            rate=PostFixedIPCA.from_percent("2.19"),
            purchase_date=date(2019, 10, 25),
            maturity_date=date(2024, 8, 15),
        )
        trace = project_traced(inv, as_of=date(2024, 8, 15), assumed_ipca=Decimal("0.04"))
        eff = trace.cash_flows[0].accrual[0].rate.effective_annual_rate
        assert eff > Decimal("0.0219")


class TestCDIKernelConformance:
    """V3 — CDI-linked CDB: no public price oracle exists.

    Conformance is the documented multiplicative % CDI rule plus the same
    (1+i)^(du/252) kernel validated against the Tesouro oracle in V1.
    """

    _bank_issuer = Issuer.create(
        "Banco X",
        "Banco X S.A.",
        IssuerKind.COMMERCIAL_BANK,
    )

    def _cdi_inv(self) -> Investment:
        return Investment.create(
            product=ProductType.CDB,
            issuer=self._bank_issuer,
            principal=Money.from_reais("10000"),
            rate=PostFixedCDI.from_percent("110"),
            purchase_date=date(2024, 1, 15),
            maturity_date=date(2026, 1, 15),
        )

    def test_cdi_multiplicative_rule(self):
        trace = project_traced(
            self._cdi_inv(), as_of=date(2026, 1, 15), assumed_cdi=Decimal("0.10")
        )
        eff = trace.cash_flows[0].accrual[0].rate.effective_annual_rate
        # 110% of 10% CDI = 1.10 x 0.10 = 0.11 (multiplicative rule)
        assert eff == Decimal("1.10") * Decimal("0.10")

    def test_cdi_uses_same_kernel_as_oracle_validated_prefixed(self):
        trace = project_traced(
            self._cdi_inv(), as_of=date(2026, 1, 15), assumed_cdi=Decimal("0.10")
        )
        step = trace.cash_flows[0].accrual[0]
        assert step.factor == (
            (Decimal("1") + step.rate.effective_annual_rate)
            ** (Decimal(step.business_days) / Decimal("252"))
        )
