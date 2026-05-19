"""Tests for ``--min-confidence`` and ``--unsafe-fixes`` gates.

These cover both the engine-level filtering (``repair_path``) and the CLI
flags exposed by ``pycomprepair repair``.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from typer.testing import CliRunner

from pycomprepair.cli import app
from pycomprepair.core.engine import repair_path
from pycomprepair.core.issue import Fix, Issue, Severity, is_actionable
from pycomprepair.core.plugin import PluginRegistry, get_registry
from pycomprepair.plugins.fastapi_migration import plugin as fastapi_plugin
from pycomprepair.plugins.pydantic_v2 import plugin as pydantic_plugin
from pycomprepair.plugins.sqlalchemy_v2 import plugin as sqlalchemy_plugin


def _bootstrap_registry() -> None:
    reg = get_registry()
    reg.register(pydantic_plugin)
    reg.register(fastapi_plugin)
    reg.register(sqlalchemy_plugin)


def _make_issue(*, confidence: float = 1.0, safe: bool = True, with_fix: bool = True) -> Issue:
    return Issue(
        plugin="x",
        code="X001",
        message="m",
        file=Path("m.py"),
        line=1,
        fix=Fix(description="d", confidence=confidence, safe=safe) if with_fix else None,
        severity=Severity.WARNING,
    )


# ---------------------------------------------------------------------------
# is_actionable() unit tests
# ---------------------------------------------------------------------------


def test_detection_only_issue_is_never_actionable() -> None:
    issue = _make_issue(with_fix=False)
    assert not is_actionable(issue)
    assert not is_actionable(issue, unsafe_fixes=True)


def test_unsafe_fix_is_skipped_by_default() -> None:
    issue = _make_issue(safe=False, confidence=1.0)
    assert not is_actionable(issue)
    assert is_actionable(issue, unsafe_fixes=True)


def test_min_confidence_filters_low_confidence_fixes() -> None:
    issue = _make_issue(confidence=0.5)
    assert is_actionable(issue, min_confidence=0.5)
    assert not is_actionable(issue, min_confidence=0.6)


# ---------------------------------------------------------------------------
# Engine-level filtering
# ---------------------------------------------------------------------------


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


def test_high_min_confidence_blocks_pydantic_method_renames(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    # PYD001 carries confidence=0.7; raise the bar above that and the
    # codemod is suppressed even though the issue is still reported.
    _write(tmp_path, "m.py", "x = obj.dict()\n")
    results = repair_path(
        tmp_path,
        "pydantic>=2.0",
        dry_run=True,
        registry=registry,
        min_confidence=0.95,
    )
    assert results[0].new_source == "x = obj.dict()\n"  # unchanged
    assert any(i.code == "PYD001" for i in results[0].issues)  # still reported


def test_min_confidence_at_threshold_still_applies(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    _write(tmp_path, "m.py", "x = obj.dict()\n")
    results = repair_path(
        tmp_path,
        "pydantic>=2.0",
        dry_run=True,
        registry=registry,
        min_confidence=0.7,
    )
    assert results[0].new_source == "x = obj.model_dump()\n"


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


def test_cli_repair_respects_min_confidence(tmp_path: Path) -> None:
    _bootstrap_registry()
    file = tmp_path / "m.py"
    file.write_text("x = obj.dict()\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "repair",
            str(tmp_path),
            "--target",
            "pydantic>=2.0",
            "--dry-run",
            "--no-diff",
            "--min-confidence",
            "0.95",
        ],
    )
    # Nothing applied -> exit 0 (no changed files even in dry-run).
    assert result.exit_code == 0
    assert "0 actionable" in result.stdout
    assert file.read_text(encoding="utf-8") == "x = obj.dict()\n"


def test_cli_repair_summary_reports_actionable_count(tmp_path: Path) -> None:
    _bootstrap_registry()
    file = tmp_path / "m.py"
    file.write_text("x = obj.dict()\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "repair",
            str(tmp_path),
            "--target",
            "pydantic>=2.0",
            "--dry-run",
            "--no-diff",
        ],
    )
    assert "1 actionable" in result.stdout
    assert "min-confidence=0.0" in result.stdout
