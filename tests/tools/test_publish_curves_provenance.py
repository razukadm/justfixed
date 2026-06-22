"""Tests for Track B provenance additions to tools/publish_curves.py (finding F-02).

Nine test groups:
  1. build_provenance basic structure and per-source fields
  2. Determinism + no-timestamp guarantee
  3. Tool resolvers return str|None (smoke)
  4. main() publish integration: provenance key, retained files, sha256, curve sections additive
  5. Additive guard: build_unified_json still returns only the five curve keys
  6. verify_publication match after a clean publish
  7. verify_publication detects sha256 tampering
  8. verify_publication rejects as_of mismatch
  9. CLI verify mode: SystemExit(0) when clean, truthy code when tampered

ZERO edits to tests/tools/test_publish_curves.py — reuse its helpers by import.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest

# tools/ is not on the installed package path; add it for direct import
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tools"))

from publish_curves import (  # noqa: E402
    build_provenance,
    build_unified_json,
    main,
    parse_anbima,
    parse_b3,
    resolve_git_commit,
    resolve_tool_version,
    verify_publication,
)

# Reuse helpers from the existing test module (import, never edit)
from tests.tools.test_publish_curves import (  # noqa: E402
    _ANBIMA_CSV,
    _AS_OF_REAL_BDI,
    _make_mock_pdf,
)
from tests.tools.fixtures.bdi_di1_page_words import PAGE_951_DI1_WORDS  # noqa: E402


# =============================================================================
# Shared setup helpers
# =============================================================================


def _write_inputs(tmp_path: Path) -> tuple[Path, Path]:
    """Write a fake PDF and the shared ANBIMA CSV to tmp_path. Return (csv, pdf)."""
    csv_path = tmp_path / "CurvaZero_.csv"
    csv_path.write_text(_ANBIMA_CSV, encoding="latin-1")
    pdf_path = tmp_path / "BDI_00.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    return csv_path, pdf_path


def _do_publish(data_repo: Path, csv_path: Path, pdf_path: Path) -> None:
    """Run main() in publish mode within a fitz mock context."""
    mock_open = _make_mock_pdf([PAGE_951_DI1_WORDS])
    with patch("publish_curves.fitz.open", mock_open):
        main([
            "--anbima", str(csv_path),
            "--b3", str(pdf_path),
            "--data-repo", str(data_repo),
            "--as-of", _AS_OF_REAL_BDI.isoformat(),
        ])


# =============================================================================
# 1. build_provenance basic structure and per-source fields
# =============================================================================


def test_build_provenance_manifest_version_and_tool(tmp_path):
    csv_bytes = b"Vertices;ETTJ IPCA;ETTJ PREF\n21;9.23;14.56\n"
    pdf_bytes = b"%PDF-1.4 test"
    csv_path = tmp_path / "CurvaZero_.csv"
    pdf_path = tmp_path / "BDI.pdf"
    csv_path.write_bytes(csv_bytes)
    pdf_path.write_bytes(pdf_bytes)

    prov = build_provenance(
        anbima_path=csv_path,
        b3_path=pdf_path,
        anbima_retained="raw/D/CurvaZero_.csv",
        b3_retained="raw/D/BDI.pdf",
        tool_version="v9",
        tool_git_commit="abc123",
    )

    assert prov["manifest_version"] == 1
    assert prov["tool"] == {
        "name": "justfixed.publish_curves",
        "version": "v9",
        "git_commit": "abc123",
    }


def test_build_provenance_sources_order_and_roles(tmp_path):
    csv_bytes = b"csv content"
    pdf_bytes = b"pdf content"
    csv_path = tmp_path / "CurvaZero_.csv"
    pdf_path = tmp_path / "BDI.pdf"
    csv_path.write_bytes(csv_bytes)
    pdf_path.write_bytes(pdf_bytes)

    prov = build_provenance(
        anbima_path=csv_path,
        b3_path=pdf_path,
        anbima_retained="raw/D/CurvaZero_.csv",
        b3_retained="raw/D/BDI.pdf",
        tool_version="v9",
        tool_git_commit="abc123",
    )

    # B3 is first, ANBIMA is second
    assert prov["sources"][0]["role"] == "b3_bdi_pdf"
    assert prov["sources"][0]["produces"] == ["cdi"]
    assert prov["sources"][1]["role"] == "anbima_ettj_csv"
    assert prov["sources"][1]["produces"] == ["pre", "ipca_real"]


def test_build_provenance_source_fields(tmp_path):
    csv_bytes = b"csv content here"
    pdf_bytes = b"pdf content here"
    csv_path = tmp_path / "CurvaZero_.csv"
    pdf_path = tmp_path / "BDI.pdf"
    csv_path.write_bytes(csv_bytes)
    pdf_path.write_bytes(pdf_bytes)

    prov = build_provenance(
        anbima_path=csv_path,
        b3_path=pdf_path,
        anbima_retained="raw/D/CurvaZero_.csv",
        b3_retained="raw/D/BDI.pdf",
        tool_version="v9",
        tool_git_commit="abc123",
    )

    b3_src = prov["sources"][0]
    anbima_src = prov["sources"][1]

    assert b3_src["sha256"] == hashlib.sha256(pdf_bytes).hexdigest()
    assert b3_src["size_bytes"] == len(pdf_bytes)
    assert b3_src["filename"] == "BDI.pdf"
    assert b3_src["retained"] == "raw/D/BDI.pdf"

    assert anbima_src["sha256"] == hashlib.sha256(csv_bytes).hexdigest()
    assert anbima_src["size_bytes"] == len(csv_bytes)
    assert anbima_src["filename"] == "CurvaZero_.csv"
    assert anbima_src["retained"] == "raw/D/CurvaZero_.csv"


def test_build_provenance_convention_and_notes(tmp_path):
    csv_path = tmp_path / "c.csv"
    pdf_path = tmp_path / "p.pdf"
    csv_path.write_bytes(b"a")
    pdf_path.write_bytes(b"b")

    prov = build_provenance(
        anbima_path=csv_path,
        b3_path=pdf_path,
        anbima_retained="raw/D/c.csv",
        b3_retained="raw/D/p.pdf",
    )

    assert prov["convention"] == "252 bd/yr; B3/ANBIMA holidays"
    assert "notes" in prov
    assert isinstance(prov["notes"], str)


# =============================================================================
# 2. Determinism + no-timestamp guarantee
# =============================================================================


def _has_key_recursive(obj, key: str) -> bool:
    if isinstance(obj, dict):
        if key in obj:
            return True
        return any(_has_key_recursive(v, key) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_key_recursive(item, key) for item in obj)
    return False


def test_build_provenance_deterministic(tmp_path):
    csv_path = tmp_path / "c.csv"
    pdf_path = tmp_path / "p.pdf"
    csv_path.write_bytes(b"csv data")
    pdf_path.write_bytes(b"pdf data")

    kwargs = dict(
        anbima_path=csv_path,
        b3_path=pdf_path,
        anbima_retained="raw/D/c.csv",
        b3_retained="raw/D/p.pdf",
        tool_version="v1",
        tool_git_commit="deadbeef",
    )
    prov1 = build_provenance(**kwargs)
    prov2 = build_provenance(**kwargs)

    assert prov1 == prov2
    assert json.dumps(prov1, indent=2, ensure_ascii=False) == json.dumps(prov2, indent=2, ensure_ascii=False)


def test_build_provenance_no_timestamp_key(tmp_path):
    csv_path = tmp_path / "c.csv"
    pdf_path = tmp_path / "p.pdf"
    csv_path.write_bytes(b"a")
    pdf_path.write_bytes(b"b")

    prov = build_provenance(
        anbima_path=csv_path,
        b3_path=pdf_path,
        anbima_retained="raw/D/c.csv",
        b3_retained="raw/D/p.pdf",
        tool_version="v1",
        tool_git_commit="abc",
    )

    for forbidden in ("generated_at", "timestamp"):
        assert not _has_key_recursive(prov, forbidden), (
            f"forbidden key '{forbidden}' found in provenance"
        )


# =============================================================================
# 3. Tool resolvers return str|None (smoke)
# =============================================================================


def test_resolve_tool_version_returns_str_or_none():
    result = resolve_tool_version()
    assert result is None or isinstance(result, str)


def test_resolve_git_commit_returns_str_or_none():
    result = resolve_git_commit()
    assert result is None or isinstance(result, str)


# =============================================================================
# 4. main() publish integration
# =============================================================================


def test_main_publish_creates_latest_json_with_provenance(tmp_path):
    data_repo = tmp_path / "data_repo"
    data_repo.mkdir()
    csv_path, pdf_path = _write_inputs(tmp_path)
    _do_publish(data_repo, csv_path, pdf_path)

    latest_path = data_repo / "curves" / "latest.json"
    assert latest_path.exists()
    payload = json.loads(latest_path.read_text(encoding="utf-8"))
    assert "provenance" in payload


def test_main_publish_retains_raw_inputs(tmp_path):
    data_repo = tmp_path / "data_repo"
    data_repo.mkdir()
    csv_path, pdf_path = _write_inputs(tmp_path)
    _do_publish(data_repo, csv_path, pdf_path)

    as_of_str = _AS_OF_REAL_BDI.isoformat()
    assert (data_repo / "raw" / as_of_str / csv_path.name).exists()
    assert (data_repo / "raw" / as_of_str / pdf_path.name).exists()


def test_main_publish_provenance_sha256_matches_original_inputs(tmp_path):
    data_repo = tmp_path / "data_repo"
    data_repo.mkdir()
    csv_path, pdf_path = _write_inputs(tmp_path)
    _do_publish(data_repo, csv_path, pdf_path)

    payload = json.loads((data_repo / "curves" / "latest.json").read_text(encoding="utf-8"))
    sources = payload["provenance"]["sources"]
    b3_src = next(s for s in sources if s["role"] == "b3_bdi_pdf")
    anbima_src = next(s for s in sources if s["role"] == "anbima_ettj_csv")

    assert b3_src["sha256"] == hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    assert anbima_src["sha256"] == hashlib.sha256(csv_path.read_bytes()).hexdigest()


def test_main_publish_curve_sections_unchanged(tmp_path):
    """Provenance is additive; cdi/pre/ipca_real sections must equal build_unified_json output."""
    data_repo = tmp_path / "data_repo"
    data_repo.mkdir()
    csv_path, pdf_path = _write_inputs(tmp_path)

    mock_open = _make_mock_pdf([PAGE_951_DI1_WORDS])
    with patch("publish_curves.fitz.open", mock_open):
        main([
            "--anbima", str(csv_path),
            "--b3", str(pdf_path),
            "--data-repo", str(data_repo),
            "--as-of", _AS_OF_REAL_BDI.isoformat(),
        ])
        # Compute ground truth within the same fitz mock context
        pre_v, ipca_v = parse_anbima(csv_path, _AS_OF_REAL_BDI)
        cdi_v = parse_b3(pdf_path, _AS_OF_REAL_BDI)
        expected = build_unified_json(_AS_OF_REAL_BDI, cdi_v, pre_v, ipca_v)

    payload = json.loads((data_repo / "curves" / "latest.json").read_text(encoding="utf-8"))
    for section in ("cdi", "pre", "ipca_real"):
        assert payload[section] == expected[section], f"section '{section}' was modified"


# =============================================================================
# 5. Additive guard: build_unified_json still returns only the five curve keys
# =============================================================================


def test_build_unified_json_still_has_only_five_keys():
    from publish_curves import Vertex
    v = [Vertex(business_days=21, rate=Decimal("0.1437"))]
    result = build_unified_json(_AS_OF_REAL_BDI, v, v, v)
    assert set(result.keys()) == {"as_of", "schema_version", "cdi", "pre", "ipca_real"}
    assert result["schema_version"] == 1
    assert "provenance" not in result


# =============================================================================
# 6. verify_publication returns [] after a clean publish
# =============================================================================


def test_verify_publication_clean(tmp_path):
    data_repo = tmp_path / "data_repo"
    data_repo.mkdir()
    csv_path, pdf_path = _write_inputs(tmp_path)

    mock_open = _make_mock_pdf([PAGE_951_DI1_WORDS])
    with patch("publish_curves.fitz.open", mock_open):
        main([
            "--anbima", str(csv_path),
            "--b3", str(pdf_path),
            "--data-repo", str(data_repo),
            "--as-of", _AS_OF_REAL_BDI.isoformat(),
        ])
        # Verify within the same fitz mock so re-parse works
        discrepancies = verify_publication(data_repo, _AS_OF_REAL_BDI)

    assert discrepancies == []


# =============================================================================
# 7. verify_publication detects sha256 tampering
# =============================================================================


def test_verify_publication_detects_tampering(tmp_path):
    data_repo = tmp_path / "data_repo"
    data_repo.mkdir()
    csv_path, pdf_path = _write_inputs(tmp_path)
    _do_publish(data_repo, csv_path, pdf_path)

    # Overwrite the retained PDF with garbage bytes
    retained_pdf = data_repo / "raw" / _AS_OF_REAL_BDI.isoformat() / pdf_path.name
    retained_pdf.write_bytes(b"tampered -- not a valid PDF")

    # Verify outside fitz mock: sha256 mismatch is detected before re-parse
    discrepancies = verify_publication(data_repo, _AS_OF_REAL_BDI)
    assert len(discrepancies) > 0


# =============================================================================
# 8. verify_publication rejects as_of mismatch
# =============================================================================


def test_verify_publication_as_of_mismatch(tmp_path):
    data_repo = tmp_path / "data_repo"
    data_repo.mkdir()
    csv_path, pdf_path = _write_inputs(tmp_path)
    _do_publish(data_repo, csv_path, pdf_path)

    discrepancies = verify_publication(data_repo, date(2030, 1, 1))
    assert len(discrepancies) > 0
    # The message must mention the as_of mismatch
    assert "does not match" in discrepancies[0]


# =============================================================================
# 9. CLI verify mode
# =============================================================================


def test_cli_verify_mode_clean_exits_zero(tmp_path):
    data_repo = tmp_path / "data_repo"
    data_repo.mkdir()
    csv_path, pdf_path = _write_inputs(tmp_path)

    mock_open = _make_mock_pdf([PAGE_951_DI1_WORDS])
    with patch("publish_curves.fitz.open", mock_open):
        # Publish
        main([
            "--anbima", str(csv_path),
            "--b3", str(pdf_path),
            "--data-repo", str(data_repo),
            "--as-of", _AS_OF_REAL_BDI.isoformat(),
        ])
        # Verify in the same fitz mock so the re-parse step works
        with pytest.raises(SystemExit) as exc_info:
            main([
                "--data-repo", str(data_repo),
                "--verify-as-of", _AS_OF_REAL_BDI.isoformat(),
            ])

    assert not exc_info.value.code  # 0 or None == verified


def test_cli_verify_mode_tampered_exits_truthy(tmp_path):
    data_repo = tmp_path / "data_repo"
    data_repo.mkdir()
    csv_path, pdf_path = _write_inputs(tmp_path)
    _do_publish(data_repo, csv_path, pdf_path)

    # Tamper with retained PDF after publish
    retained_pdf = data_repo / "raw" / _AS_OF_REAL_BDI.isoformat() / pdf_path.name
    retained_pdf.write_bytes(b"tampered garbage bytes")

    # Verify outside fitz mock: sha256 mismatch is detected before re-parse
    with pytest.raises(SystemExit) as exc_info:
        main([
            "--data-repo", str(data_repo),
            "--verify-as-of", _AS_OF_REAL_BDI.isoformat(),
        ])

    assert exc_info.value.code  # truthy string "verification failed"
