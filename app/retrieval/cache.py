"""File-based cache of raw CT.gov pages, supporting live/replay/force_refresh.

Layout: ``<cache_dir>/studies/<params_hash>/<data_timestamp>.json``.

The data timestamp lives in the *filename*, not in the directory hash. That is
deliberate: the params hash is computable with no network, so ``replay`` can
locate the cached entry without ever calling ``/version`` to learn the live
timestamp. A new CT.gov data release simply writes a new sibling file, so live
mode picks up fresh data automatically while old captures stay reproducible.

Raw API pages are cached (not parsed records), so re-running with a fixed parser
picks up the fix without re-fetching.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_STUDIES_SUBDIR = "studies"
_VOLATILE_PARAMS = frozenset({"pageToken", "pageSize", "countTotal"})


@dataclass
class CacheEnvelope:
    """The on-disk cache entry: raw pages plus the metadata needed to replay."""

    data_timestamp: str
    params_hash: str
    truncated: bool
    pages: list[dict[str, Any]]


def cache_key_params(server_params: dict[str, str], max_studies: int) -> str:
    """Return a stable hash of the normalized server-side query + page budget.

    Volatile paging params are dropped; keys are sorted so ordering never affects
    the hash. ``max_studies`` is included so a 50-study capture and a 2000-study
    capture of the same query do not collide.
    """
    norm = {k: v for k, v in server_params.items() if k not in _VOLATILE_PARAMS}
    norm["_budget"] = str(max_studies)
    blob = json.dumps(norm, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _key_dir(cache_dir: str, key: str) -> Path:
    return Path(cache_dir) / _STUDIES_SUBDIR / key


def _safe_filename(data_timestamp: str) -> str:
    # ``:`` is illegal in filenames on some platforms; the raw timestamp with
    # colons is kept inside the envelope.
    return data_timestamp.replace(":", "-") + ".json"


def _load(path: Path) -> CacheEnvelope:
    data = json.loads(path.read_text(encoding="utf-8"))
    return CacheEnvelope(
        data_timestamp=str(data.get("data_timestamp", "")),
        params_hash=str(data.get("params_hash", "")),
        truncated=bool(data.get("truncated", False)),
        pages=list(data.get("pages", [])),
    )


def read_exact(cache_dir: str, key: str, data_timestamp: str) -> CacheEnvelope | None:
    """Live read-through: return the entry for this exact data timestamp, if any."""
    path = _key_dir(cache_dir, key) / _safe_filename(data_timestamp)
    if not path.is_file():
        return None
    return _load(path)


def read_latest(cache_dir: str, key: str) -> CacheEnvelope | None:
    """Replay read: return the most recent cached entry for ``key`` (no network)."""
    directory = _key_dir(cache_dir, key)
    if not directory.is_dir():
        return None
    files = sorted(directory.glob("*.json"))
    if not files:
        return None
    return _load(files[-1])


def write(
    cache_dir: str,
    key: str,
    data_timestamp: str,
    pages: list[dict[str, Any]],
    truncated: bool,
) -> None:
    """Write-through: persist raw pages under ``<key>/<data_timestamp>.json``."""
    directory = _key_dir(cache_dir, key)
    directory.mkdir(parents=True, exist_ok=True)
    envelope = {
        "data_timestamp": data_timestamp,
        "params_hash": key,
        "truncated": truncated,
        "pages": pages,
    }
    target = directory / _safe_filename(data_timestamp)
    target.write_text(json.dumps(envelope), encoding="utf-8")
