"""On-disk cache for griffe-derived :class:`APIIndex` snapshots.

Loading a package's full public API via griffe is slow (seconds per
package on first invocation). This cache stores the resolved symbol set
keyed by ``(package, version)`` so that subsequent invocations on the
same machine reuse the snapshot. The cache is invalidated automatically
whenever the installed package version changes.

Layout
------

``~/.cache/pycomprepair/<package>-<version>.json``

Each file is a JSON document::

    {
      "package": "numpy",
      "version": "2.0.1",
      "schema": 1,
      "symbols": ["numpy", "numpy.array", ...],
      "kinds":   {"numpy": "module", "numpy.array": "function", ...}
    }

The cache is best-effort: any I/O or schema error is swallowed and the
caller falls back to the live griffe load. The directory is created on
first write.
"""

from __future__ import annotations

import json
import os
from importlib import metadata
from pathlib import Path
from typing import Any

from pycomprepair.discovery.api_index import APIIndex

_SCHEMA_VERSION = 1


def cache_dir() -> Path:
    """Return the on-disk cache directory, honouring ``XDG_CACHE_HOME``."""
    env = os.environ.get("PYCOMPREPAIR_CACHE_DIR")
    if env:
        return Path(env)
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg) / "pycomprepair"
    return Path.home() / ".cache" / "pycomprepair"


def _safe_segment(value: str) -> str:
    """Sanitise a ``package`` or ``version`` for use in a filename."""
    return "".join(ch if ch.isalnum() or ch in ".-_" else "_" for ch in value)


def cache_path(package: str, version: str) -> Path:
    return cache_dir() / f"{_safe_segment(package)}-{_safe_segment(version)}.json"


def installed_version(package: str) -> str | None:
    """Best-effort lookup of an installed distribution version."""
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return None
    except Exception:
        return None


def read_cached(package: str, version: str | None = None) -> APIIndex | None:
    """Return a cached :class:`APIIndex` if one exists for the version.

    When ``version`` is ``None`` we look it up from ``importlib.metadata``;
    if the package isn't installed (or we can't read the cache file) we
    return ``None`` so the caller falls back to a live griffe load.
    """
    ver = version or installed_version(package)
    if ver is None:
        return None
    path = cache_path(package, ver)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("schema") != _SCHEMA_VERSION:
        return None
    if data.get("package") != package or data.get("version") != ver:
        return None
    symbols = data.get("symbols")
    kinds = data.get("kinds")
    if not isinstance(symbols, list) or not isinstance(kinds, dict):
        return None
    try:
        return APIIndex(
            package=package,
            symbols=frozenset(str(s) for s in symbols),
            kinds={str(k): str(v) for k, v in kinds.items()},
        )
    except Exception:
        return None


def write_cached(index: APIIndex, version: str | None = None) -> Path | None:
    """Persist *index* to disk. Returns the written path, or ``None`` on
    failure (cache writes are best-effort).
    """
    ver = version or installed_version(index.package)
    if ver is None:
        return None
    try:
        directory = cache_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = cache_path(index.package, ver)
        payload: dict[str, Any] = {
            "schema": _SCHEMA_VERSION,
            "package": index.package,
            "version": ver,
            "symbols": sorted(index.symbols),
            "kinds": dict(index.kinds),
        }
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        tmp.replace(path)
        return path
    except OSError:
        return None


def clear_cache() -> int:
    """Remove every cached snapshot. Returns the number of files deleted."""
    directory = cache_dir()
    if not directory.is_dir():
        return 0
    removed = 0
    for entry in directory.glob("*.json"):
        try:
            entry.unlink()
            removed += 1
        except OSError:
            pass
    return removed
