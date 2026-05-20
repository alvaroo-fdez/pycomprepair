"""Tests for the v0.5.0 ``init`` wizard and ``cache`` CLI commands."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from pycomprepair.cli import app


def test_init_writes_config_in_non_interactive_mode(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "init",
            str(tmp_path),
            "--non-interactive",
            "--target",
            "numpy>=2.0",
        ],
    )
    assert result.exit_code == 0, result.stdout
    cfg = (tmp_path / "pycomprepair.toml").read_text(encoding="utf-8")
    assert "numpy>=2.0" in cfg


def test_init_writes_list_form_for_multiple_targets(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "init",
            str(tmp_path),
            "--non-interactive",
            "--target",
            "numpy>=2.0",
            "--target",
            "pandas>=2.0",
        ],
    )
    assert result.exit_code == 0, result.stdout
    cfg = (tmp_path / "pycomprepair.toml").read_text(encoding="utf-8")
    assert "numpy>=2.0" in cfg
    assert "pandas>=2.0" in cfg
    assert "target = [" in cfg


def test_init_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    (tmp_path / "pycomprepair.toml").write_text('target = "old"\n', encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["init", str(tmp_path), "--non-interactive", "--target", "numpy>=2.0"],
    )
    assert result.exit_code != 0


def test_init_overwrites_with_force(tmp_path: Path) -> None:
    (tmp_path / "pycomprepair.toml").write_text('target = "old"\n', encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "init",
            str(tmp_path),
            "--non-interactive",
            "--force",
            "--target",
            "numpy>=2.0",
        ],
    )
    assert result.exit_code == 0
    assert (
        "numpy>=2.0"
        in (tmp_path / "pycomprepair.toml").read_text(encoding="utf-8")
    )


def test_cache_path_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYCOMPREPAIR_CACHE_DIR", str(tmp_path / "ccache"))
    runner = CliRunner()
    result = runner.invoke(app, ["cache", "path"])
    assert result.exit_code == 0
    assert "ccache" in result.stdout


def test_cache_clear_reports_removed_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYCOMPREPAIR_CACHE_DIR", str(tmp_path / "ccache"))
    (tmp_path / "ccache").mkdir()
    (tmp_path / "ccache" / "acme-1.0.0.json").write_text("{}", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(app, ["cache", "clear"])
    assert result.exit_code == 0
    assert "Removed 1" in result.stdout
