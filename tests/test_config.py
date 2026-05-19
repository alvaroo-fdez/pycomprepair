"""Tests for project-level configuration discovery and merging."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pycomprepair.cli import app
from pycomprepair.config import Config, load_config
from pycomprepair.core.engine import scan_path
from pycomprepair.core.plugin import PluginRegistry, get_registry
from pycomprepair.plugins.django_v5 import plugin as django_plugin
from pycomprepair.plugins.fastapi_migration import plugin as fastapi_plugin
from pycomprepair.plugins.pydantic_v2 import plugin as pydantic_plugin
from pycomprepair.plugins.sqlalchemy_v2 import plugin as sqlalchemy_plugin


def _bootstrap_registry() -> None:
    reg = get_registry()
    reg.register(pydantic_plugin)
    reg.register(fastapi_plugin)
    reg.register(sqlalchemy_plugin)
    reg.register(django_plugin)


def _write(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content), encoding="utf-8")


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def test_returns_empty_config_when_no_file_present(tmp_path: Path) -> None:
    cfg = load_config(tmp_path)
    assert cfg == Config.empty()


def test_loads_standalone_pycomprepair_toml(tmp_path: Path) -> None:
    _write(
        tmp_path / "pycomprepair.toml",
        """
        target = "pydantic>=2.0,<3.0"
        min_confidence = 0.8
        unsafe_fixes = true
        ignore = ["PYD001", "DJA004"]
        """,
    )
    cfg = load_config(tmp_path)
    assert cfg.target == "pydantic>=2.0,<3.0"
    assert cfg.min_confidence == 0.8
    assert cfg.unsafe_fixes is True
    assert cfg.ignore == frozenset({"PYD001", "DJA004"})
    assert cfg.source == (tmp_path / "pycomprepair.toml").resolve()


def test_loads_pyproject_table(tmp_path: Path) -> None:
    _write(
        tmp_path / "pyproject.toml",
        """
        [tool.pycomprepair]
        target = "sqlalchemy>=2.0"
        ignore = ["SQL005"]
        """,
    )
    cfg = load_config(tmp_path)
    assert cfg.target == "sqlalchemy>=2.0"
    assert cfg.ignore == frozenset({"SQL005"})


def test_pycomprepair_toml_wins_over_pyproject(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", "[tool.pycomprepair]\ntarget = \"a\"\n")
    _write(tmp_path / "pycomprepair.toml", 'target = "b"\n')
    cfg = load_config(tmp_path)
    assert cfg.target == "b"


def test_discovery_walks_up_to_ancestors(tmp_path: Path) -> None:
    nested = tmp_path / "src" / "pkg"
    nested.mkdir(parents=True)
    _write(tmp_path / "pycomprepair.toml", 'target = "django>=5.0"\n')
    cfg = load_config(nested)
    assert cfg.target == "django>=5.0"


def test_pyproject_without_table_is_ignored(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", "[project]\nname = \"x\"\n")
    cfg = load_config(tmp_path)
    assert cfg == Config.empty()


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_invalid_min_confidence_raises(tmp_path: Path) -> None:
    _write(tmp_path / "pycomprepair.toml", "min_confidence = 1.5\n")
    with pytest.raises(ValueError, match="min_confidence"):
        load_config(tmp_path)


def test_invalid_ignore_raises(tmp_path: Path) -> None:
    _write(tmp_path / "pycomprepair.toml", "ignore = [1, 2]\n")
    with pytest.raises(ValueError, match="ignore"):
        load_config(tmp_path)


# ---------------------------------------------------------------------------
# Engine — ignore_codes
# ---------------------------------------------------------------------------


def test_ignore_codes_drops_matching_issues(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    (tmp_path / "m.py").write_text(
        "a = obj.dict()\nb = obj.json()\n", encoding="utf-8"
    )
    full = scan_path(tmp_path, "pydantic>=2.0", registry=registry)
    assert {i.code for i in full} == {"PYD001", "PYD002"}

    filtered = scan_path(
        tmp_path,
        "pydantic>=2.0",
        registry=registry,
        ignore_codes={"PYD001"},
    )
    assert {i.code for i in filtered} == {"PYD002"}


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


def test_cli_falls_back_to_target_in_config(tmp_path: Path) -> None:
    _bootstrap_registry()
    _write(tmp_path / "pycomprepair.toml", 'target = "pydantic>=2.0"\n')
    (tmp_path / "m.py").write_text("x = obj.dict()\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app, ["scan", str(tmp_path)])
    # Found the target from config and produced PYD001 -> exit 1.
    assert result.exit_code == 1, result.stdout
    assert "PYD001" in result.stdout


def test_cli_errors_when_no_target_available(tmp_path: Path) -> None:
    _bootstrap_registry()
    (tmp_path / "m.py").write_text("x = 1\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app, ["scan", str(tmp_path)])
    assert result.exit_code == 2
    assert "Missing --target" in result.stdout or "Missing --target" in result.stderr


def test_cli_cli_flag_overrides_config_target(tmp_path: Path) -> None:
    _bootstrap_registry()
    # Config points at django but the user requests pydantic on the CLI.
    _write(tmp_path / "pycomprepair.toml", 'target = "django>=5.0"\n')
    (tmp_path / "m.py").write_text("x = obj.dict()\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app, ["scan", str(tmp_path), "--target", "pydantic>=2.0"])
    assert result.exit_code == 1
    assert "PYD001" in result.stdout


def test_cli_respects_ignore_from_config(tmp_path: Path) -> None:
    _bootstrap_registry()
    _write(
        tmp_path / "pycomprepair.toml",
        """
        target = "pydantic>=2.0"
        ignore = ["PYD001"]
        """,
    )
    (tmp_path / "m.py").write_text("x = obj.dict()\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app, ["scan", str(tmp_path)])
    # PYD001 was the only issue; ignore drops it -> exit 0, no incompatibilities.
    assert result.exit_code == 0
    assert "PYD001" not in result.stdout
