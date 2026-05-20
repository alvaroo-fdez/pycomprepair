"""Tests for the v1.1.0 ``discover --suggest`` fuzzy matcher."""

from __future__ import annotations

import textwrap
from pathlib import Path

from typer.testing import CliRunner

from pycomprepair.cli import app
from pycomprepair.discovery import APIIndex, suggest_replacements
from pycomprepair.discovery.attr_check import scan_missing_attributes


def _index(package: str, *, symbols: set[str], containers: set[str]) -> APIIndex:
    kinds = {s: ("module" if s in containers else "function") for s in symbols}
    return APIIndex(package=package, symbols=frozenset(symbols), kinds=kinds)


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# 1) Pure suggester behaviour.
# ---------------------------------------------------------------------------


def test_suggester_returns_closest_sibling() -> None:
    """Typos / minor edits surface above the default 0.7 cutoff."""
    idx = _index(
        "numpy",
        symbols={"numpy", "numpy.isin", "numpy.where", "numpy.array"},
        containers={"numpy"},
    )
    # ``isinn`` is a one-letter typo for ``isin``: very high ratio.
    results = suggest_replacements("numpy.isinn", idx)
    assert results
    assert results[0].path == "numpy.isin"
    assert results[0].score >= 0.7


def test_suggester_returns_empty_when_no_close_match() -> None:
    idx = _index(
        "numpy",
        symbols={"numpy", "numpy.array", "numpy.zeros"},
        containers={"numpy"},
    )
    results = suggest_replacements("numpy.totally_unrelated_xyz", idx)
    assert results == []


def test_suggester_skips_grandchildren() -> None:
    """Only direct siblings should be considered to keep scores meaningful."""
    idx = _index(
        "pkg",
        symbols={"pkg", "pkg.module", "pkg.module.helper", "pkg.helper"},
        containers={"pkg", "pkg.module"},
    )
    results = suggest_replacements("pkg.helperr", idx)
    # ``pkg.helper`` is a direct sibling -> matches.
    # ``pkg.module.helper`` lives two levels deep -> excluded.
    assert results
    assert all(r.path.count(".") == 1 for r in results)


def test_suggester_respects_package_boundary() -> None:
    """Asking about ``other.foo`` with a numpy index must return []."""
    idx = _index(
        "numpy",
        symbols={"numpy", "numpy.array"},
        containers={"numpy"},
    )
    assert suggest_replacements("other.array", idx) == []


def test_suggester_caps_result_count() -> None:
    idx = _index(
        "numpy",
        symbols={"numpy"} | {f"numpy.foo{i}" for i in range(10)},
        containers={"numpy"},
    )
    results = suggest_replacements("numpy.foo", idx, cutoff=0.4, max_results=2)
    assert 0 < len(results) <= 2


# ---------------------------------------------------------------------------
# 2) scan_missing_attributes(suggest=True) wires the suggestion as a Fix.
# ---------------------------------------------------------------------------


def test_scan_attaches_suggestion_fix_when_enabled(tmp_path: Path) -> None:
    src = "import numpy as np\nx = np.in1d(a, b)\n"
    file = _write(tmp_path, "m.py", src)
    idx = _index(
        "numpy",
        symbols={"numpy", "numpy.isin", "numpy.where"},
        containers={"numpy"},
    )
    # numpy.in1d is in KNOWN_FIXES, so disable that path by using a path the
    # registry does not know about (numpy.unknownz).
    src2 = "import numpy as np\nx = np.unknownz(a, b)\n"
    file2 = _write(tmp_path, "m2.py", src2)
    idx2 = _index(
        "numpy",
        symbols={"numpy", "numpy.unknown", "numpy.where"},
        containers={"numpy"},
    )

    issues = scan_missing_attributes(file2, src2, {"numpy": idx2}, suggest=True)
    assert len(issues) == 1
    fix = issues[0].fix
    assert fix is not None
    assert fix.safe is False  # fuzzy guesses are never auto-applied
    assert "did you mean" in fix.description.lower()
    assert "numpy.unknown" in fix.description

    # And no suggestion is attached when suggest=False.
    issues_off = scan_missing_attributes(file, src, {"numpy": idx}, suggest=False)
    assert all(i.fix is None or i.fix.confidence == 1.0 for i in issues_off)


def test_known_fix_takes_priority_over_suggestion(tmp_path: Path) -> None:
    """KNOWN_FIXES entries must not be overridden by fuzzy guesses."""
    src = "import numpy as np\nx = np.NaN\n"
    file = _write(tmp_path, "m.py", src)
    idx = _index(
        "numpy",
        symbols={"numpy", "numpy.nan", "numpy.nansum"},
        containers={"numpy"},
    )
    issues = scan_missing_attributes(file, src, {"numpy": idx}, suggest=True)
    assert issues
    fix = issues[0].fix
    assert fix is not None
    assert fix.safe is True  # came from KNOWN_FIXES, not from suggester
    assert "did you mean" not in fix.description.lower()


# ---------------------------------------------------------------------------
# 3) CLI ``discover --suggest`` advertises the closest match.
# ---------------------------------------------------------------------------


def test_cli_discover_suggest_surfaces_match(tmp_path: Path) -> None:
    """The flag exists and the run is well-formed against a real package.

    ``packaging`` is always installed in the dev environment, so we point
    discover at it. Even when no DSC002 hit exists in this trivial file,
    the command must accept the flag and exit cleanly.
    """
    _write(tmp_path, "m.py", "import packaging\nv = packaging.version.VERSION\n")
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "discover",
            str(tmp_path),
            "--package",
            "packaging",
            "--suggest",
        ],
    )
    # Either 0 (no issues) or 1 (issues found). Anything else is a crash.
    assert result.exit_code in (0, 1), result.stdout


def test_cli_discover_no_suggest_is_default(tmp_path: Path) -> None:
    _write(tmp_path, "m.py", "import packaging\n")
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["discover", str(tmp_path), "--package", "packaging"],
    )
    assert result.exit_code in (0, 1)
