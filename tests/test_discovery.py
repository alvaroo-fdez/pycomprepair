"""Tests for the griffe-backed discovery layer."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from pycomprepair.cli import app
from pycomprepair.discovery import (
    APIIndex,
    PackageNotInstalledError,
    load_api,
    scan_missing_imports,
)


# ---------------------------------------------------------------------------
# load_api / APIIndex
# ---------------------------------------------------------------------------


def test_load_api_packaging_has_core_symbols() -> None:
    index = load_api("packaging")
    assert isinstance(index, APIIndex)
    assert index.package == "packaging"
    assert index.has("packaging.version.Version")
    assert index.has("packaging.requirements.Requirement")
    assert index.has("packaging.specifiers.SpecifierSet")


def test_api_index_helpers() -> None:
    index = load_api("packaging")
    assert index.has_module_attr("packaging.version", "Version")
    assert not index.has_module_attr("packaging.version", "DoesNotExist")
    assert index.belongs_to("packaging")
    assert index.belongs_to("packaging.version")
    assert not index.belongs_to("packaging_clone")


def test_api_index_rejects_missing_symbols() -> None:
    index = load_api("packaging")
    assert not index.has("packaging.version.NotARealClass")
    assert not index.has("packaging.totally.fake.path")


def test_load_api_caches_repeated_calls() -> None:
    first = load_api("packaging")
    second = load_api("packaging")
    assert first is second


def test_load_api_missing_package_raises() -> None:
    with pytest.raises(PackageNotInstalledError):
        load_api("pycomprepair_definitely_not_a_real_package_xyz")


# ---------------------------------------------------------------------------
# scan_missing_imports
# ---------------------------------------------------------------------------


def _index_with(package: str, *paths: str) -> APIIndex:
    return APIIndex(package=package, symbols=frozenset(paths))


def test_scan_flags_removed_import(tmp_path: Path) -> None:
    src = "from acme.utils import smart_text\n"
    index = _index_with("acme", "acme.utils.smart_str", "acme.utils")
    issues = scan_missing_imports(tmp_path / "f.py", src, {"acme": index})
    assert len(issues) == 1
    issue = issues[0]
    assert issue.code == "DSC001"
    assert issue.plugin == "discover"
    assert "acme.utils.smart_text" in issue.message
    assert issue.context["symbol"] == "acme.utils.smart_text"


def test_scan_accepts_existing_import(tmp_path: Path) -> None:
    src = "from acme.utils import smart_str\n"
    index = _index_with("acme", "acme.utils.smart_str")
    issues = scan_missing_imports(tmp_path / "f.py", src, {"acme": index})
    assert issues == []


def test_scan_ignores_unrelated_packages(tmp_path: Path) -> None:
    src = "from other_lib import whatever\n"
    index = _index_with("acme", "acme.utils.smart_str")
    issues = scan_missing_imports(tmp_path / "f.py", src, {"acme": index})
    assert issues == []


def test_scan_handles_multiple_symbols(tmp_path: Path) -> None:
    src = "from acme.utils import smart_str, smart_text, force_text\n"
    index = _index_with("acme", "acme.utils.smart_str")
    issues = scan_missing_imports(tmp_path / "f.py", src, {"acme": index})
    codes = sorted(i.context["symbol"] for i in issues)
    assert codes == ["acme.utils.force_text", "acme.utils.smart_text"]


def test_scan_handles_aliased_import(tmp_path: Path) -> None:
    src = "from acme.translation import ugettext as _\n"
    index = _index_with("acme", "acme.translation.gettext")
    issues = scan_missing_imports(tmp_path / "f.py", src, {"acme": index})
    assert len(issues) == 1
    assert issues[0].context["symbol"] == "acme.translation.ugettext"


def test_scan_skips_relative_imports(tmp_path: Path) -> None:
    src = "from . import something\nfrom .sub import other\n"
    index = _index_with("acme", "acme.utils.smart_str")
    issues = scan_missing_imports(tmp_path / "f.py", src, {"acme": index})
    assert issues == []


def test_scan_skips_star_imports(tmp_path: Path) -> None:
    src = "from acme.utils import *\n"
    index = _index_with("acme", "acme.utils.smart_str")
    issues = scan_missing_imports(tmp_path / "f.py", src, {"acme": index})
    assert issues == []


def test_scan_flags_missing_submodule(tmp_path: Path) -> None:
    src = "import acme.removed_module\n"
    index = _index_with("acme", "acme.utils")
    issues = scan_missing_imports(tmp_path / "f.py", src, {"acme": index})
    assert len(issues) == 1
    assert issues[0].context["symbol"] == "acme.removed_module"


def test_scan_ignores_root_import(tmp_path: Path) -> None:
    src = "import acme\n"
    index = _index_with("acme", "acme.utils")
    issues = scan_missing_imports(tmp_path / "f.py", src, {"acme": index})
    assert issues == []


def test_scan_returns_empty_on_syntax_error(tmp_path: Path) -> None:
    src = "from acme import (oops\n"
    index = _index_with("acme")
    issues = scan_missing_imports(tmp_path / "f.py", src, {"acme": index})
    assert issues == []


def test_scan_returns_empty_when_no_indexes(tmp_path: Path) -> None:
    src = "from anywhere import anything\n"
    assert scan_missing_imports(tmp_path / "f.py", src, {}) == []


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


def test_cli_discover_reports_missing_symbol(tmp_path: Path) -> None:
    file = tmp_path / "uses_packaging.py"
    file.write_text(
        "from packaging.version import Version, NoLongerExists\n",
        encoding="utf-8",
    )
    result = CliRunner().invoke(app, ["discover", str(file), "--package", "packaging"])
    assert result.exit_code == 1
    assert "DSC001" in result.stdout
    assert "NoLongerExists" in result.stdout


def test_cli_discover_clean_file_exits_zero(tmp_path: Path) -> None:
    file = tmp_path / "ok.py"
    file.write_text("from packaging.version import Version\n", encoding="utf-8")
    result = CliRunner().invoke(app, ["discover", str(file), "--package", "packaging"])
    assert result.exit_code == 0


def test_cli_discover_unknown_package_errors(tmp_path: Path) -> None:
    file = tmp_path / "x.py"
    file.write_text("x = 1\n", encoding="utf-8")
    result = CliRunner().invoke(
        app,
        [
            "discover",
            str(file),
            "--package",
            "pycomprepair_definitely_not_a_real_package_xyz",
        ],
    )
    assert result.exit_code == 2
