"""Focused tests for the ``class Config`` -> ``ConfigDict`` codemod (PYD008)."""

from __future__ import annotations

import textwrap
from pathlib import Path

from pycomprepair.core.engine import repair_path, scan_path
from pycomprepair.core.plugin import PluginRegistry


def _write(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "m.py"
    p.write_text(textwrap.dedent(content).lstrip("\n"), encoding="utf-8")
    return p


def test_renames_anystr_strip_whitespace(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    _write(
        tmp_path,
        """
        class M:
            class Config:
                anystr_strip_whitespace = True
        """,
    )
    results = repair_path(tmp_path, "pydantic>=2.0", dry_run=True, registry=registry)
    new = results[0].new_source
    assert "model_config = ConfigDict(str_strip_whitespace=True)" in new
    assert "class Config" not in new


def test_renames_orm_mode_and_populate_by_name(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    _write(
        tmp_path,
        """
        class M:
            class Config:
                orm_mode = True
                allow_population_by_field_name = True
        """,
    )
    results = repair_path(tmp_path, "pydantic>=2.0", dry_run=True, registry=registry)
    new = results[0].new_source
    assert "from_attributes=True" in new
    assert "populate_by_name=True" in new
    assert "orm_mode" not in new
    assert "allow_population_by_field_name" not in new


def test_negates_allow_mutation_to_frozen(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    _write(
        tmp_path,
        """
        class M:
            class Config:
                allow_mutation = False
        """,
    )
    results = repair_path(tmp_path, "pydantic>=2.0", dry_run=True, registry=registry)
    new = results[0].new_source
    assert "frozen=True" in new


def test_keeps_warning_when_unknown_key(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    """Unknown keys must abort the auto-fix and leave the warning intact."""
    _write(
        tmp_path,
        """
        class M:
            class Config:
                anystr_strip_whitespace = True
                some_unknown_option = "value"
        """,
    )
    issues = scan_path(tmp_path, "pydantic>=2.0", registry=registry)
    pyd008 = [i for i in issues if i.code == "PYD008"]
    assert len(pyd008) == 1
    assert pyd008[0].fix is None  # not safely convertible

    results = repair_path(tmp_path, "pydantic>=2.0", dry_run=True, registry=registry)
    assert "class Config" in results[0].new_source


def test_keeps_warning_when_removed_in_v2(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    """Keys removed entirely in v2 (e.g. ``fields``) must not be migrated."""
    _write(
        tmp_path,
        """
        class M:
            class Config:
                fields = {"name": "alias"}
        """,
    )
    results = repair_path(tmp_path, "pydantic>=2.0", dry_run=True, registry=registry)
    assert "class Config" in results[0].new_source
    assert "ConfigDict" not in results[0].new_source


def test_pyd008_fix_is_emitted_when_convertible(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    _write(
        tmp_path,
        """
        class M:
            class Config:
                anystr_strip_whitespace = True
        """,
    )
    issues = scan_path(tmp_path, "pydantic>=2.0", registry=registry)
    pyd008 = next(i for i in issues if i.code == "PYD008")
    assert pyd008.fix is not None
    assert "ConfigDict" in pyd008.fix.description


def test_pass_in_config_body_is_tolerated(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    _write(
        tmp_path,
        """
        class M:
            class Config:
                orm_mode = True
                pass
        """,
    )
    results = repair_path(tmp_path, "pydantic>=2.0", dry_run=True, registry=registry)
    assert "from_attributes=True" in results[0].new_source


def test_docstring_in_config_body_is_tolerated(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    _write(
        tmp_path,
        '''
        class M:
            class Config:
                """Inline docs."""
                orm_mode = True
        ''',
    )
    results = repair_path(tmp_path, "pydantic>=2.0", dry_run=True, registry=registry)
    assert "from_attributes=True" in results[0].new_source


def test_method_in_config_body_aborts(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    """A method/function inside ``class Config`` makes migration unsafe."""
    _write(
        tmp_path,
        """
        class M:
            class Config:
                orm_mode = True

                @classmethod
                def alias_generator(cls, field):
                    return field
        """,
    )
    results = repair_path(tmp_path, "pydantic>=2.0", dry_run=True, registry=registry)
    assert "class Config" in results[0].new_source
    assert "ConfigDict" not in results[0].new_source
