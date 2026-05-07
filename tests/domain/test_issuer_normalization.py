"""Tests for Issuer.normalize_name — the canonical form used for persistence lookup."""

from __future__ import annotations

from justfixed.domain.issuer import Issuer


class TestNormalizeName:
    def test_uppercases(self) -> None:
        assert Issuer.normalize_name("Banco BV") == "BANCO BV"

    def test_strips_outer_whitespace(self) -> None:
        assert Issuer.normalize_name("  Banco BV  ") == "BANCO BV"

    def test_collapses_internal_whitespace(self) -> None:
        assert Issuer.normalize_name("Banco   BV") == "BANCO BV"

    def test_collapses_tabs_and_mixed_whitespace(self) -> None:
        assert Issuer.normalize_name("Banco\tBV\n S/A") == "BANCO BV S/A"

    def test_preserves_punctuation(self) -> None:
        # Different punctuation variants stay distinct — we don't try
        # to be clever about S/A vs S.A. vs SA.
        assert Issuer.normalize_name("Banco BV S/A") == "BANCO BV S/A"
        assert Issuer.normalize_name("Banco BV S.A.") == "BANCO BV S.A."
        assert Issuer.normalize_name("Banco BV SA") == "BANCO BV SA"

    def test_preserves_accents(self) -> None:
        # Itaú and Itau are distinct names; we don't strip accents.
        assert Issuer.normalize_name("Banco Itaú") == "BANCO ITAÚ"

    def test_empty_string_normalizes_to_empty(self) -> None:
        # Edge case: this would never come from a real Issuer (post_init
        # rejects empty names) but the classmethod itself is stateless
        # and should handle it without crashing.
        assert Issuer.normalize_name("") == ""

    def test_treasury_canonical_name(self) -> None:
        # Sanity: the canonical Tesouro name normalizes to a stable string,
        # which is what the loader will match against.
        assert Issuer.normalize_name("Tesouro Nacional") == "TESOURO NACIONAL"