"""Tests for verify_publication override params (--anbima/--b3 furnished-input path).

Covers the auditor scenario: raw inputs are gitignored in the public data repo,
but an auditor furnished with those files can still re-derive and verify.

Five scenarios per task spec:
  1. Override success — furnished files with matching sha256 → [] (verified)
  2. Override sha256 mismatch — furnished files have wrong bytes → discrepancy
  3. Raw not available / no override — retained files absent, no override → discrepancy
  4. No-override clean (regression) — retained files intact, no override → []
  5. CLI override — main() verify branch passes overrides; clean exits 0, tampered exits truthy
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tools"))

from publish_curves import main, verify_publication  # noqa: E402

# Reuse helpers from the existing test modules (import, never edit)
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
    """Write the fake ANBIMA CSV and a stub PDF to tmp_path. Return (csv, pdf)."""
    csv_path = tmp_path / "CurvaZero_.csv"
    csv_path.write_text(_ANBIMA_CSV, encoding="latin-1")
    pdf_path = tmp_path / "BDI_00.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    return csv_path, pdf_path


def _do_publish(data_repo: Path, csv_path: Path, pdf_path: Path) -> None:
    """Run main() in publish mode under the fitz mock."""
    mock_open = _make_mock_pdf([PAGE_951_DI1_WORDS])
    with patch("publish_curves.fitz.open", mock_open):
        main([
            "--anbima", str(csv_path),
            "--b3", str(pdf_path),
            "--data-repo", str(data_repo),
            "--as-of", _AS_OF_REAL_BDI.isoformat(),
        ])


def _delete_retained(data_repo: Path) -> None:
    """Remove all retained raw files for _AS_OF_REAL_BDI, simulating a fresh
    public clone where raw/ is gitignored and those files are absent."""
    raw_dir = data_repo / "raw" / _AS_OF_REAL_BDI.isoformat()
    for f in raw_dir.iterdir():
        f.unlink()


def _make_furnished(tmp_path: Path, csv_bytes: bytes, pdf_bytes: bytes) -> tuple[Path, Path]:
    """Create furnished copies of the input files in a separate directory."""
    furnished_dir = tmp_path / "furnished"
    furnished_dir.mkdir(exist_ok=True)
    furnished_csv = furnished_dir / "CurvaZero_.csv"
    furnished_pdf = furnished_dir / "BDI_00.pdf"
    furnished_csv.write_bytes(csv_bytes)
    furnished_pdf.write_bytes(pdf_bytes)
    return furnished_csv, furnished_pdf


# =============================================================================
# 1. Override success — furnished files with correct sha256 → []
# =============================================================================


def test_override_success(tmp_path):
    data_repo = tmp_path / "data_repo"
    data_repo.mkdir()
    csv_path, pdf_path = _write_inputs(tmp_path)

    # Record original bytes so furnished copies match exactly
    csv_bytes = csv_path.read_bytes()
    pdf_bytes = pdf_path.read_bytes()

    _do_publish(data_repo, csv_path, pdf_path)
    _delete_retained(data_repo)

    # Furnished copies carry the same bytes as the published inputs → sha256 matches
    furnished_csv, furnished_pdf = _make_furnished(tmp_path, csv_bytes, pdf_bytes)

    mock_open = _make_mock_pdf([PAGE_951_DI1_WORDS])
    with patch("publish_curves.fitz.open", mock_open):
        discrepancies = verify_publication(
            data_repo,
            _AS_OF_REAL_BDI,
            anbima_override=furnished_csv,
            b3_override=furnished_pdf,
        )

    assert discrepancies == []


# =============================================================================
# 2. Override sha256 mismatch — furnished files have different bytes → discrepancy
# =============================================================================


def test_override_sha256_mismatch(tmp_path):
    data_repo = tmp_path / "data_repo"
    data_repo.mkdir()
    csv_path, pdf_path = _write_inputs(tmp_path)
    _do_publish(data_repo, csv_path, pdf_path)
    _delete_retained(data_repo)

    # Furnished files have different bytes → sha256 will not match manifest
    furnished_csv, furnished_pdf = _make_furnished(
        tmp_path, b"not the original csv", b"not the original pdf"
    )

    discrepancies = verify_publication(
        data_repo,
        _AS_OF_REAL_BDI,
        anbima_override=furnished_csv,
        b3_override=furnished_pdf,
    )

    assert len(discrepancies) > 0
    joined = " ".join(discrepancies)
    assert "does not match the published manifest" in joined
    assert "this is not the file that was published" in joined


# =============================================================================
# 3. Raw not available / no override — retained files absent → clear message
# =============================================================================


def test_raw_not_available_no_override(tmp_path):
    data_repo = tmp_path / "data_repo"
    data_repo.mkdir()
    csv_path, pdf_path = _write_inputs(tmp_path)
    _do_publish(data_repo, csv_path, pdf_path)
    _delete_retained(data_repo)

    # No overrides; retained raw files are gone
    discrepancies = verify_publication(data_repo, _AS_OF_REAL_BDI)

    assert len(discrepancies) > 0
    joined = " ".join(discrepancies)
    assert "raw input not available" in joined
    assert "--anbima" in joined or "--b3" in joined


# =============================================================================
# 4. No-override clean (regression guard) — retained files intact → []
# =============================================================================


def test_no_override_clean_regression(tmp_path):
    data_repo = tmp_path / "data_repo"
    data_repo.mkdir()
    csv_path, pdf_path = _write_inputs(tmp_path)

    mock_open = _make_mock_pdf([PAGE_951_DI1_WORDS])
    with patch("publish_curves.fitz.open", mock_open):
        _do_publish(data_repo, csv_path, pdf_path)
        # Retained files intact, no overrides — must still verify clean
        discrepancies = verify_publication(data_repo, _AS_OF_REAL_BDI)

    assert discrepancies == []


# =============================================================================
# 5a. CLI override — furnished files correct → SystemExit(0)
# =============================================================================


def test_cli_override_clean_exits_zero(tmp_path):
    data_repo = tmp_path / "data_repo"
    data_repo.mkdir()
    csv_path, pdf_path = _write_inputs(tmp_path)

    csv_bytes = csv_path.read_bytes()
    pdf_bytes = pdf_path.read_bytes()

    _do_publish(data_repo, csv_path, pdf_path)
    _delete_retained(data_repo)

    furnished_csv, furnished_pdf = _make_furnished(tmp_path, csv_bytes, pdf_bytes)

    mock_open = _make_mock_pdf([PAGE_951_DI1_WORDS])
    with patch("publish_curves.fitz.open", mock_open):
        with pytest.raises(SystemExit) as exc_info:
            main([
                "--data-repo", str(data_repo),
                "--verify-as-of", _AS_OF_REAL_BDI.isoformat(),
                "--anbima", str(furnished_csv),
                "--b3", str(furnished_pdf),
            ])

    assert not exc_info.value.code  # 0 or None == verified


# =============================================================================
# 5b. CLI override — tampered furnished file → SystemExit truthy
# =============================================================================


def test_cli_override_tampered_exits_truthy(tmp_path):
    data_repo = tmp_path / "data_repo"
    data_repo.mkdir()
    csv_path, pdf_path = _write_inputs(tmp_path)
    _do_publish(data_repo, csv_path, pdf_path)
    _delete_retained(data_repo)

    # Tampered furnished files → sha256 mismatch → verification failed
    furnished_csv, furnished_pdf = _make_furnished(
        tmp_path, b"tampered csv content", b"tampered pdf content"
    )

    with pytest.raises(SystemExit) as exc_info:
        main([
            "--data-repo", str(data_repo),
            "--verify-as-of", _AS_OF_REAL_BDI.isoformat(),
            "--anbima", str(furnished_csv),
            "--b3", str(furnished_pdf),
        ])

    assert exc_info.value.code  # truthy string "verification failed"
