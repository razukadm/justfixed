"""HTTP fetcher for live yield curve data (B9a Phase 2 + Phase 5a).

Fetches curves/latest.json from the justfixed-data GitHub repository,
caches to ~/.justfixed/curve_cache.json, and returns a FetchResult.

On network failure the on-disk cache is used. If both fail, returns
source="unavailable" with all curves None. The caller passes result.curve
to project(cdi_curve=...) — the engine handles None and empty-vertices
Curves identically (falls back to assumed_cdi).

parse_curve_payload() is a public convenience for the B30 "load from file"
handler: given a full curves/latest.json payload dict, it returns the CDI
Curve (or None).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from justfixed.engine.curve import Curve, CurveVertex

_log = logging.getLogger(__name__)

CURVES_URL = (
    "https://raw.githubusercontent.com/razukadm/justfixed-data/main/curves/latest.json"
)
SEED_URL = (
    "https://raw.githubusercontent.com/razukadm/justfixed-data/main/seed/issuers.json"
)
_DEFAULT_CACHE_PATH = Path.home() / ".justfixed" / "curve_cache.json"
_DEFAULT_SEED_CACHE_PATH = Path.home() / ".justfixed" / "seed_cache.json"
_TIMEOUT = 5  # seconds


@dataclass(frozen=True)
class FetchResult:
    """Result of a fetch_curves() call.

    curve:       Parsed CDI Curve, or None when vertices are empty or parse fails.
                 Pass directly to project(cdi_curve=...).
    source:      "live" | "cached" | "unavailable"
    pre:         Parsed PRE curve, or None.
    ipca_real:   Parsed IPCA-real curve, or None.
    source_time: When the fetch completed (None when source="unavailable").
    """

    curve: Curve | None
    source: str
    pre: Curve | None = None
    ipca_real: Curve | None = None
    source_time: datetime | None = None


def fetch_curves(
    *,
    url: str = CURVES_URL,
    cache_path: Path = _DEFAULT_CACHE_PATH,
) -> FetchResult:
    """Fetch yield curve data and return all three parsed curves.

    Tries the live URL first; on any failure falls back to the on-disk
    cache. Returns FetchResult(curve=None, source="unavailable") if both
    the network and cache are unavailable.
    """
    raw: dict | None = None
    source: str

    try:
        raw = _fetch_json(url)
        _write_cache(raw, cache_path)
        source = "live"
    except Exception:
        _log.debug("Live fetch failed; falling back to cache", exc_info=True)
        raw = _read_cache(cache_path)
        source = "cached" if raw is not None else "unavailable"

    if raw is None:
        return FetchResult(curve=None, source="unavailable")

    return FetchResult(
        curve=_parse_cdi_curve(raw),
        source=source,
        pre=_parse_pre_curve(raw),
        ipca_real=_parse_ipca_real_curve(raw),
        source_time=datetime.now(),
    )


def fetch_seed_data(
    *,
    url: str = SEED_URL,
    cache_path: Path = _DEFAULT_SEED_CACHE_PATH,
) -> dict | None:
    """Fetch issuer seed data and return the raw JSON dict.

    Tries the live URL first; on failure falls back to the on-disk cache.
    Returns None if both the network and cache are unavailable.
    """
    try:
        raw = _fetch_json(url)
        _write_cache(raw, cache_path)
        return raw
    except Exception:
        _log.debug("Seed fetch failed; falling back to cache", exc_info=True)
        return _read_cache(cache_path)


def parse_curve_payload(data: dict) -> Curve | None:
    """Parse the CDI curve from a curves/latest.json payload dict.

    Public entry point for the B30 'load from file' handler. Returns None
    if the CDI section is absent, the anchor is missing, vertices are empty,
    or any value is malformed.
    """
    return _parse_cdi_curve(data)


def _fetch_json(url: str) -> dict:
    req = Request(url, headers={"User-Agent": "justfixed/1.0"})
    with urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _write_cache(data: dict, cache_path: Path) -> None:
    cache_path.parent.mkdir(exist_ok=True)
    cache_path.write_text(json.dumps(data), encoding="utf-8")


def _read_cache(cache_path: Path) -> dict | None:
    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_section_curve(data: dict, key: str) -> Curve | None:
    """Parse a named section (cdi/pre/ipca_real) from the JSON payload."""
    try:
        section = data.get(key, {})
        anchor_str = section.get("anchor")
        vertices_raw = section.get("vertices", [])
        if not anchor_str or not vertices_raw:
            return None
        anchor = date.fromisoformat(anchor_str)
        vertices = tuple(
            CurveVertex(
                business_days=int(v["business_days"]),
                rate=Decimal(str(v["rate"])),
            )
            for v in vertices_raw
        )
        return Curve(anchor=anchor, vertices=vertices)
    except Exception:
        _log.debug("%s curve parse failed", key, exc_info=True)
        return None


def _parse_cdi_curve(data: dict) -> Curve | None:
    return _parse_section_curve(data, "cdi")


def _parse_pre_curve(data: dict) -> Curve | None:
    return _parse_section_curve(data, "pre")


def _parse_ipca_real_curve(data: dict) -> Curve | None:
    return _parse_section_curve(data, "ipca_real")
