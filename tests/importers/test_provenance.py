"""Direct unit tests for _provenance.custodian_for_source (B42)."""
from __future__ import annotations

from justfixed.domain.investment import InvestmentSource
from justfixed.importers._provenance import custodian_for_source


class TestCustodianForSource:
    def test_xp_import_returns_xp(self) -> None:
        assert custodian_for_source(InvestmentSource.XP_IMPORT) == "XP"

    def test_btg_import_returns_btg_pactual(self) -> None:
        assert custodian_for_source(InvestmentSource.BTG_IMPORT) == "BTG Pactual"

    def test_bb_import_returns_banco_do_brasil(self) -> None:
        assert custodian_for_source(InvestmentSource.BB_IMPORT) == "Banco do Brasil"

    def test_manual_returns_none(self) -> None:
        assert custodian_for_source(InvestmentSource.MANUAL) is None
