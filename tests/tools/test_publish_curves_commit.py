"""Tests for the --commit path in tools/publish_curves.py.

Proves that git add stages ONLY curves/latest.json — NOT the retained raw inputs
(*.csv / BDI*.pdf) that the data repo's .gitignore intentionally excludes.

Uses a real git repo in tmp_path so that subprocess git calls execute against
real git, catching the CalledProcessError that the pre-fix code raised when
trying to `git add` a .gitignore-excluded file.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# tools/ is not on the installed package path; add it for direct import
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tools"))

from publish_curves import main  # noqa: E402

from tests.tools.test_publish_curves import (  # noqa: E402
    _ANBIMA_CSV,
    _AS_OF_REAL_BDI,
    _make_mock_pdf,
)
from tests.tools.fixtures.bdi_di1_page_words import PAGE_951_DI1_WORDS  # noqa: E402

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None,
    reason="git not available",
)


def _git(*args, cwd):
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def test_commit_stages_only_latest_json_when_raw_is_gitignored(tmp_path: Path) -> None:
    """--commit must succeed even when .gitignore excludes the raw input files.

    Before the fix, git add included anbima_retained and b3_retained; git raised
    a CalledProcessError because those paths matched the repo's .gitignore.
    After the fix, only curves/latest.json is staged, so add/commit succeed.
    """
    data_repo = tmp_path / "data_repo"
    data_repo.mkdir()

    # Initialise a real git repo with a .gitignore that excludes raw input types
    _git("init", cwd=data_repo)
    _git("config", "user.email", "t@e.st", cwd=data_repo)
    _git("config", "user.name", "Test", cwd=data_repo)
    (data_repo / ".gitignore").write_text("*.csv\nBDI*.pdf\n", encoding="utf-8")
    _git("add", ".gitignore", cwd=data_repo)
    _git("commit", "-m", "init", cwd=data_repo)

    # Raw input files live outside data_repo (they are NOT in the repo at all)
    csv = tmp_path / "CurvaZero_.csv"
    csv.write_text(_ANBIMA_CSV, encoding="latin-1")
    pdf = tmp_path / "BDI_00.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    # Run publish with --commit; before the fix this raised CalledProcessError
    with patch("publish_curves.fitz.open", _make_mock_pdf([PAGE_951_DI1_WORDS])):
        main([
            "--anbima", str(csv),
            "--b3", str(pdf),
            "--data-repo", str(data_repo),
            "--as-of", _AS_OF_REAL_BDI.isoformat(),
            "--commit",
        ])

    # The commit must have landed and must track ONLY curves/latest.json
    tracked = _git("ls-files", cwd=data_repo).stdout.splitlines()
    assert "curves/latest.json" in tracked
    assert not any(t.startswith("raw/") for t in tracked), (
        f"raw/ files must not be committed; found: {[t for t in tracked if t.startswith('raw/')]}"
    )

    # Raw input files must still exist on disk (retained), just untracked
    as_of = _AS_OF_REAL_BDI.isoformat()
    assert (data_repo / "raw" / as_of / csv.name).exists(), "ANBIMA CSV must be retained to disk"
    assert (data_repo / "raw" / as_of / pdf.name).exists(), "B3 PDF must be retained to disk"
