"""Tests for engine/fetcher.py — HTTP fetch, disk cache, and JSON parse."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import URLError

import pytest

from justfixed.engine.fetcher import fetch_curves


# ── Helpers ───────────────────────────────────────────────────────────────────

SAMPLE_PAYLOAD = {
    "cdi": {
        "anchor": "2026-05-15",
        "vertices": [
            {"business_days": 126, "rate": 0.144},
            {"business_days": 252, "rate": 0.143},
        ],
    }
}

EMPTY_VERTICES_PAYLOAD = {
    "cdi": {
        "anchor": "2026-05-15",
        "vertices": [],
    }
}


def _mock_urlopen(payload: dict):
    """Return a patched urlopen that serves payload as JSON."""
    body = json.dumps(payload).encode()
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return MagicMock(return_value=resp)


# ── Live fetch (network succeeds) ─────────────────────────────────────────────

class TestLiveFetch:
    def test_returns_curve_with_vertices(self, tmp_path: Path) -> None:
        cache = tmp_path / "curve_cache.json"
        with patch("justfixed.engine.fetcher.urlopen", _mock_urlopen(SAMPLE_PAYLOAD)):
            result = fetch_curves(cache_path=cache)
        assert result.curve is not None
        assert len(result.curve.vertices) == 2

    def test_source_is_live(self, tmp_path: Path) -> None:
        cache = tmp_path / "curve_cache.json"
        with patch("justfixed.engine.fetcher.urlopen", _mock_urlopen(SAMPLE_PAYLOAD)):
            result = fetch_curves(cache_path=cache)
        assert result.source == "live"

    def test_writes_cache_file(self, tmp_path: Path) -> None:
        cache = tmp_path / "curve_cache.json"
        with patch("justfixed.engine.fetcher.urlopen", _mock_urlopen(SAMPLE_PAYLOAD)):
            fetch_curves(cache_path=cache)
        assert cache.exists()
        cached = json.loads(cache.read_text())
        assert cached["cdi"]["anchor"] == "2026-05-15"

    def test_empty_vertices_curve_is_none(self, tmp_path: Path) -> None:
        cache = tmp_path / "curve_cache.json"
        with patch("justfixed.engine.fetcher.urlopen", _mock_urlopen(EMPTY_VERTICES_PAYLOAD)):
            result = fetch_curves(cache_path=cache)
        assert result.curve is None

    def test_empty_vertices_source_is_still_live(self, tmp_path: Path) -> None:
        cache = tmp_path / "curve_cache.json"
        with patch("justfixed.engine.fetcher.urlopen", _mock_urlopen(EMPTY_VERTICES_PAYLOAD)):
            result = fetch_curves(cache_path=cache)
        assert result.source == "live"


# ── Network failure — cache fallback ─────────────────────────────────────────

class TestCacheFallback:
    def test_falls_back_to_cache_on_network_error(self, tmp_path: Path) -> None:
        cache = tmp_path / "curve_cache.json"
        cache.write_text(json.dumps(SAMPLE_PAYLOAD), encoding="utf-8")
        with patch("justfixed.engine.fetcher.urlopen", side_effect=URLError("timeout")):
            result = fetch_curves(cache_path=cache)
        assert result.source == "cached"
        assert result.curve is not None

    def test_no_cache_returns_unavailable(self, tmp_path: Path) -> None:
        cache = tmp_path / "curve_cache.json"
        with patch("justfixed.engine.fetcher.urlopen", side_effect=URLError("timeout")):
            result = fetch_curves(cache_path=cache)
        assert result.source == "unavailable"
        assert result.curve is None


# ── Parse failures ────────────────────────────────────────────────────────────

class TestParsing:
    def test_malformed_anchor_curve_is_none(self, tmp_path: Path) -> None:
        bad = {"cdi": {"anchor": "not-a-date", "vertices": [{"business_days": 252, "rate": 0.14}]}}
        cache = tmp_path / "curve_cache.json"
        with patch("justfixed.engine.fetcher.urlopen", _mock_urlopen(bad)):
            result = fetch_curves(cache_path=cache)
        assert result.curve is None

    def test_missing_anchor_curve_is_none(self, tmp_path: Path) -> None:
        no_anchor = {"cdi": {"vertices": [{"business_days": 252, "rate": 0.14}]}}
        cache = tmp_path / "curve_cache.json"
        with patch("justfixed.engine.fetcher.urlopen", _mock_urlopen(no_anchor)):
            result = fetch_curves(cache_path=cache)
        assert result.curve is None
