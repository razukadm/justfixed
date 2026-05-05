"""Tests for the Issuer entity."""

import uuid

import pytest

from justfixed.domain.issuer import Issuer, IssuerKind


# ---------- IssuerKind ----------
class TestIssuerKind:
    def test_commercial_bank_is_fgc_covered(self) -> None:
        assert IssuerKind.COMMERCIAL_BANK.is_fgc_covered is True

    def test_development_bank_is_fgc_covered(self) -> None:
        assert IssuerKind.DEVELOPMENT_BANK.is_fgc_covered is True

    def test_treasury_is_not_fgc_covered(self) -> None:
        assert IssuerKind.TREASURY.is_fgc_covered is False


# ---------- Construction ----------
class TestConstruction:
    def test_create_assigns_uuid(self) -> None:
        i = Issuer.create("Banco Inter", "Banco Inter S.A.", IssuerKind.COMMERCIAL_BANK)
        assert isinstance(i.id, uuid.UUID)

    def test_create_two_yields_distinct_ids(self) -> None:
        a = Issuer.create("Banco Inter", "Banco Inter S.A.", IssuerKind.COMMERCIAL_BANK)
        b = Issuer.create("Banco Inter", "Banco Inter S.A.", IssuerKind.COMMERCIAL_BANK)
        assert a.id != b.id

    def test_strips_whitespace(self) -> None:
        i = Issuer.create("  Banco Inter  ", "  Banco Inter S.A.  ", IssuerKind.COMMERCIAL_BANK)
        assert i.name == "Banco Inter"
        assert i.conglomerate == "Banco Inter S.A."

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValueError, match="name cannot be empty"):
            Issuer.create("", "Some Conglomerate", IssuerKind.COMMERCIAL_BANK)

    def test_empty_conglomerate_rejected(self) -> None:
        with pytest.raises(ValueError, match="conglomerate cannot be empty"):
            Issuer.create("Some Bank", "", IssuerKind.COMMERCIAL_BANK)

    def test_whitespace_only_name_rejected(self) -> None:
        with pytest.raises(ValueError, match="name cannot be empty"):
            Issuer.create("   ", "Some Conglomerate", IssuerKind.COMMERCIAL_BANK)


# ---------- CNPJ handling ----------
class TestCNPJ:
    def test_formatted_cnpj_normalized(self) -> None:
        i = Issuer.create(
            "Banco Inter",
            "Banco Inter S.A.",
            IssuerKind.COMMERCIAL_BANK,
            tax_id="00.416.968/0001-01",
        )
        assert i.tax_id == "00416968000101"

    def test_unformatted_cnpj_kept(self) -> None:
        i = Issuer.create(
            "Banco Inter",
            "Banco Inter S.A.",
            IssuerKind.COMMERCIAL_BANK,
            tax_id="00416968000101",
        )
        assert i.tax_id == "00416968000101"

    def test_cnpj_with_extra_chars_normalized(self) -> None:
        # Common copy-paste mistakes: leading/trailing spaces, slashes, dots.
        i = Issuer.create(
            "Banco Inter",
            "Banco Inter S.A.",
            IssuerKind.COMMERCIAL_BANK,
            tax_id=" 00.416.968 / 0001-01 ",
        )
        assert i.tax_id == "00416968000101"

    def test_invalid_length_cnpj_rejected(self) -> None:
        with pytest.raises(ValueError, match="14 digits"):
            Issuer.create(
                "Banco Inter",
                "Banco Inter S.A.",
                IssuerKind.COMMERCIAL_BANK,
                tax_id="123",
            )

    def test_empty_cnpj_allowed(self) -> None:
        # CNPJ may legitimately be unknown for a hand-entered issuer.
        i = Issuer.create("Some Bank", "Some Conglomerate", IssuerKind.COMMERCIAL_BANK)
        assert i.tax_id == ""

    def test_cnpj_display_format(self) -> None:
        i = Issuer.create(
            "Banco Inter",
            "Banco Inter S.A.",
            IssuerKind.COMMERCIAL_BANK,
            tax_id="00416968000101",
        )
        assert i.tax_id_display == "00.416.968/0001-01"

    def test_empty_cnpj_display_is_empty(self) -> None:
        i = Issuer.create("Some Bank", "Some Conglomerate", IssuerKind.COMMERCIAL_BANK)
        assert i.tax_id_display == ""


# ---------- Identity-based equality ----------
class TestIdentity:
    """Issuers are entities: equality is by id, not by attributes."""

    def test_same_attributes_different_ids_are_unequal(self) -> None:
        a = Issuer.create("Banco Inter", "Banco Inter S.A.", IssuerKind.COMMERCIAL_BANK)
        b = Issuer.create("Banco Inter", "Banco Inter S.A.", IssuerKind.COMMERCIAL_BANK)
        assert a != b

    def test_same_id_different_attributes_are_equal(self) -> None:
        # Edge case: same entity post-rename. The id is the truth.
        shared_id = uuid.uuid4()
        a = Issuer(
            name="Old Name",
            conglomerate="Old Conglomerate",
            kind=IssuerKind.COMMERCIAL_BANK,
            id=shared_id,
        )
        b = Issuer(
            name="New Name",
            conglomerate="New Conglomerate",
            kind=IssuerKind.COMMERCIAL_BANK,
            id=shared_id,
        )
        assert a == b

    def test_self_equality(self) -> None:
        a = Issuer.create("Banco Inter", "Banco Inter S.A.", IssuerKind.COMMERCIAL_BANK)
        assert a == a

    def test_compared_to_non_issuer(self) -> None:
        a = Issuer.create("Banco Inter", "Banco Inter S.A.", IssuerKind.COMMERCIAL_BANK)
        assert (a == "Banco Inter") is False
        assert (a == 42) is False

    def test_hashable(self) -> None:
        # We override __eq__, so __hash__ must also be defined.
        # This test ensures Issuers can be used in sets and as dict keys.
        a = Issuer.create("Banco Inter", "Banco Inter S.A.", IssuerKind.COMMERCIAL_BANK)
        b = Issuer.create("Banco BTG", "Banco BTG Pactual", IssuerKind.COMMERCIAL_BANK)
        s = {a, b, a}  # Adding a twice should not duplicate it.
        assert len(s) == 2

    def test_mutability(self) -> None:
        # Issuers are mutable (entities can change). Identity stays via id.
        a = Issuer.create("Banco Inter", "Banco Inter S.A.", IssuerKind.COMMERCIAL_BANK)
        original_id = a.id
        a.name = "Inter"
        assert a.name == "Inter"
        assert a.id == original_id


# ---------- FGC delegation ----------
class TestFGC:
    def test_commercial_bank_covered(self) -> None:
        i = Issuer.create("Banco Inter", "Banco Inter S.A.", IssuerKind.COMMERCIAL_BANK)
        assert i.is_fgc_covered is True

    def test_development_bank_covered(self) -> None:
        i = Issuer.create("BNDES", "BNDES", IssuerKind.DEVELOPMENT_BANK)
        assert i.is_fgc_covered is True

    def test_treasury_not_covered(self) -> None:
        i = Issuer.treasury()
        assert i.is_fgc_covered is False


# ---------- Treasury factory ----------
class TestTreasuryFactory:
    def test_treasury_basic_attributes(self) -> None:
        t = Issuer.treasury()
        assert t.name == "Tesouro Nacional"
        assert t.kind == IssuerKind.TREASURY
        assert t.is_fgc_covered is False

    def test_treasury_has_canonical_cnpj(self) -> None:
        t = Issuer.treasury()
        assert t.tax_id == "00394460000141"

    def test_treasury_factory_yields_fresh_uuids(self) -> None:
        # Each call produces a new instance; persistence will canonicalize.
        a = Issuer.treasury()
        b = Issuer.treasury()
        assert a.id != b.id