from __future__ import annotations

import textwrap
from pathlib import Path

from pycomprepair.core.engine import repair_path, scan_path
from pycomprepair.core.plugin import PluginRegistry


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


def test_detects_dict_method(tmp_path: Path, registry: PluginRegistry) -> None:
    _write(tmp_path, "m.py", "x = user.dict()\n")
    issues = scan_path(tmp_path, "pydantic>=2.0", registry=registry)
    assert [i.code for i in issues] == ["PYD001"]


def test_detects_all_method_renames(tmp_path: Path, registry: PluginRegistry) -> None:
    _write(
        tmp_path,
        "m.py",
        """
        a = user.dict()
        b = user.json()
        c = User.parse_obj(d)
        e = User.parse_raw(f)
        g = user.copy()
        """,
    )
    issues = scan_path(tmp_path, "pydantic>=2.0", registry=registry)
    codes = sorted(i.code for i in issues)
    assert codes == ["PYD001", "PYD002", "PYD003", "PYD004", "PYD005"]


def test_repairs_dict_to_model_dump(tmp_path: Path, registry: PluginRegistry) -> None:
    _write(tmp_path, "m.py", "x = user.dict()\n")
    results = repair_path(tmp_path, "pydantic>=2.0", dry_run=True, registry=registry)
    assert results[0].new_source == "x = user.model_dump()\n"


def test_repairs_method_chain_preserves_args(tmp_path: Path, registry: PluginRegistry) -> None:
    _write(tmp_path, "m.py", "x = User.parse_obj({'a': 1, 'b': 2})\n")
    results = repair_path(tmp_path, "pydantic>=2.0", dry_run=True, registry=registry)
    assert "User.model_validate({'a': 1, 'b': 2})" in results[0].new_source


def test_detects_validator_decorator(tmp_path: Path, registry: PluginRegistry) -> None:
    _write(
        tmp_path,
        "m.py",
        """
        from pydantic import BaseModel, validator

        class M(BaseModel):
            x: int

            @validator("x")
            def check(cls, v):
                return v
        """,
    )
    issues = scan_path(tmp_path, "pydantic>=2.0", registry=registry)
    assert any(i.code == "PYD006" for i in issues)


def test_repairs_validator_decorator_adds_import(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    _write(
        tmp_path,
        "m.py",
        """
        from pydantic import BaseModel, validator

        class M(BaseModel):
            x: int

            @validator("x")
            def check(cls, v):
                return v
        """,
    )
    results = repair_path(tmp_path, "pydantic>=2.0", dry_run=True, registry=registry)
    new = results[0].new_source
    assert "@field_validator(\"x\")" in new
    assert "from pydantic import field_validator" in new


def test_detects_inner_config_class(tmp_path: Path, registry: PluginRegistry) -> None:
    _write(
        tmp_path,
        "m.py",
        """
        class Settings:
            class Config:
                env_prefix = "APP_"
        """,
    )
    issues = scan_path(tmp_path, "pydantic>=2.0", registry=registry)
    assert any(i.code == "PYD008" for i in issues)


def test_issue_has_line_and_column(tmp_path: Path, registry: PluginRegistry) -> None:
    _write(
        tmp_path,
        "m.py",
        """
        # comment
        x = obj.dict()
        """,
    )
    issues = scan_path(tmp_path, "pydantic>=2.0", registry=registry)
    assert len(issues) == 1
    # Line 3 in the textwrap.dedent'd content (blank, comment, x = ...).
    assert issues[0].line == 3
