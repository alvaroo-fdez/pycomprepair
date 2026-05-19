from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from pycomprepair.cli import app
from pycomprepair.core.plugin import get_registry
from pycomprepair.plugins.fastapi_migration import plugin as fastapi_plugin
from pycomprepair.plugins.pydantic_v2 import plugin as pydantic_plugin


def _bootstrap_registry() -> None:
    """Register built-in plugins explicitly: entry points may not be wired
    when running the suite without an install step."""
    reg = get_registry()
    reg.register(pydantic_plugin)
    reg.register(fastapi_plugin)


def test_cli_version() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip()


def test_cli_scan_reports_issues_and_exits_non_zero(tmp_path: Path) -> None:
    _bootstrap_registry()
    file = tmp_path / "m.py"
    file.write_text("x = obj.dict()\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app, ["scan", str(tmp_path), "--target", "pydantic>=2.0"])
    assert result.exit_code == 1
    assert "PYD001" in result.stdout


def test_cli_scan_clean_codebase_exits_zero(tmp_path: Path) -> None:
    _bootstrap_registry()
    file = tmp_path / "m.py"
    file.write_text("x = 1 + 1\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app, ["scan", str(tmp_path), "--target", "pydantic>=2.0"])
    assert result.exit_code == 0
    assert "No incompatibilities" in result.stdout


def test_cli_repair_dry_run_does_not_write(tmp_path: Path) -> None:
    _bootstrap_registry()
    file = tmp_path / "m.py"
    file.write_text("x = obj.dict()\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        app, ["repair", str(tmp_path), "--target", "pydantic>=2.0", "--dry-run", "--no-diff"]
    )
    # Exit code 1 because changes would be made.
    assert result.exit_code == 1
    assert file.read_text(encoding="utf-8") == "x = obj.dict()\n"


def test_cli_repair_write_persists(tmp_path: Path) -> None:
    _bootstrap_registry()
    file = tmp_path / "m.py"
    file.write_text("x = obj.dict()\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        app, ["repair", str(tmp_path), "--target", "pydantic>=2.0", "--write", "--no-diff"]
    )
    assert result.exit_code == 0
    assert "model_dump" in file.read_text(encoding="utf-8")


def test_cli_report_markdown_to_file(tmp_path: Path) -> None:
    _bootstrap_registry()
    file = tmp_path / "m.py"
    file.write_text("x = obj.dict()\n", encoding="utf-8")
    out = tmp_path / "report.md"

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "report",
            str(tmp_path),
            "--target",
            "pydantic>=2.0",
            "--format",
            "markdown",
            "--output",
            str(out),
        ],
    )
    assert result.exit_code == 0
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "PYD001" in content
