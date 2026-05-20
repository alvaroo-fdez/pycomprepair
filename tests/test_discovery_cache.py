"""Tests for the on-disk griffe cache."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pycomprepair.discovery import APIIndex
from pycomprepair.discovery import cache as cache_mod


@pytest.fixture(autouse=True)
def _redirect_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PYCOMPREPAIR_CACHE_DIR", str(tmp_path / "ccache"))
    return tmp_path / "ccache"


def _idx() -> APIIndex:
    return APIIndex(
        package="acme",
        symbols=frozenset({"acme", "acme.foo", "acme.bar"}),
        kinds={"acme": "module", "acme.foo": "function", "acme.bar": "class"},
    )


def test_round_trip_write_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cache_mod, "installed_version", lambda pkg: "1.2.3")
    idx = _idx()
    path = cache_mod.write_cached(idx)
    assert path is not None
    assert path.is_file()

    loaded = cache_mod.read_cached("acme")
    assert loaded is not None
    assert loaded.package == "acme"
    assert loaded.symbols == idx.symbols
    assert loaded.kinds == idx.kinds


def test_read_cached_returns_none_for_unknown_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cache_mod, "installed_version", lambda pkg: None)
    assert cache_mod.read_cached("acme") is None


def test_version_mismatch_invalidates_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cache_mod, "installed_version", lambda pkg: "1.0.0")
    cache_mod.write_cached(_idx())
    # Bump the installed version: the old snapshot must no longer match.
    monkeypatch.setattr(cache_mod, "installed_version", lambda pkg: "2.0.0")
    assert cache_mod.read_cached("acme") is None


def test_corrupted_cache_file_returns_none(
    monkeypatch: pytest.MonkeyPatch, _redirect_cache: Path
) -> None:
    monkeypatch.setattr(cache_mod, "installed_version", lambda pkg: "1.0.0")
    _redirect_cache.mkdir(parents=True, exist_ok=True)
    (cache_mod.cache_path("acme", "1.0.0")).write_text("not json", encoding="utf-8")
    assert cache_mod.read_cached("acme") is None


def test_schema_version_mismatch_returns_none(
    monkeypatch: pytest.MonkeyPatch, _redirect_cache: Path
) -> None:
    monkeypatch.setattr(cache_mod, "installed_version", lambda pkg: "1.0.0")
    _redirect_cache.mkdir(parents=True, exist_ok=True)
    cache_mod.cache_path("acme", "1.0.0").write_text(
        json.dumps(
            {
                "schema": 999,
                "package": "acme",
                "version": "1.0.0",
                "symbols": [],
                "kinds": {},
            }
        ),
        encoding="utf-8",
    )
    assert cache_mod.read_cached("acme") is None


def test_load_api_uses_cache_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """load_api must consult the disk cache before invoking griffe."""
    from pycomprepair.discovery import api_index

    monkeypatch.setattr(cache_mod, "installed_version", lambda pkg: "9.9.9")
    cache_mod.write_cached(_idx())
    # Force load_api to bypass its lru_cache.
    api_index.load_api.cache_clear()

    # If griffe were invoked, it would fail because ``acme`` doesn't exist.
    idx = api_index.load_api("acme")
    assert idx.symbols == _idx().symbols
    assert idx.kinds == _idx().kinds


def test_clear_cache_removes_files(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cache_mod, "installed_version", lambda pkg: "1.0.0")
    cache_mod.write_cached(_idx())
    removed = cache_mod.clear_cache()
    assert removed >= 1
    assert cache_mod.read_cached("acme") is None
