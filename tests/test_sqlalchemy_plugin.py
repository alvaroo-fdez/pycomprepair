"""Tests for the SQLAlchemy 1.4 -> 2.0 migration plugin."""

from __future__ import annotations

import textwrap
from pathlib import Path

from pycomprepair.core.engine import repair_path, scan_path
from pycomprepair.core.plugin import PluginRegistry


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# matches() / target gating
# ---------------------------------------------------------------------------


def test_plugin_skips_when_target_is_below_2_0(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    _write(
        tmp_path,
        "m.py",
        """
        from sqlalchemy.ext.declarative import declarative_base
        Base = declarative_base()
        """,
    )
    # Targeting 1.4 — nothing from this plugin should fire.
    issues = scan_path(tmp_path, "sqlalchemy<2.0", registry=registry)
    assert [i for i in issues if i.plugin == "sqlalchemy"] == []


# ---------------------------------------------------------------------------
# SQL001 — declarative_base import path
# ---------------------------------------------------------------------------


def test_detects_legacy_declarative_base_import(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    _write(
        tmp_path,
        "m.py",
        "from sqlalchemy.ext.declarative import declarative_base\n",
    )
    issues = scan_path(tmp_path, "sqlalchemy>=2.0", registry=registry)
    sql001 = [i for i in issues if i.code == "SQL001"]
    assert len(sql001) == 1
    assert sql001[0].context["only_target"] == "true"


def test_repairs_legacy_declarative_base_import(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    _write(
        tmp_path,
        "m.py",
        "from sqlalchemy.ext.declarative import declarative_base\n",
    )
    results = repair_path(tmp_path, "sqlalchemy>=2.0", dry_run=True, registry=registry)
    assert results[0].new_source == "from sqlalchemy.orm import declarative_base\n"


def test_does_not_rewrite_mixed_import(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    # When other names share the line we keep the warning but skip the
    # automatic rewrite, since ``DeclarativeMeta`` lives elsewhere.
    src = "from sqlalchemy.ext.declarative import declarative_base, DeclarativeMeta\n"
    _write(tmp_path, "m.py", src)
    results = repair_path(tmp_path, "sqlalchemy>=2.0", dry_run=True, registry=registry)
    assert results[0].new_source == src
    codes = [i.code for i in results[0].issues]
    assert "SQL001" in codes
    sql001 = next(i for i in results[0].issues if i.code == "SQL001")
    assert sql001.context["only_target"] == "false"
    assert sql001.fix is not None and sql001.fix.safe is False


# ---------------------------------------------------------------------------
# SQL002 — session.query(Model).get(pk)
# ---------------------------------------------------------------------------


def test_detects_query_get(tmp_path: Path, registry: PluginRegistry) -> None:
    _write(tmp_path, "m.py", "user = session.query(User).get(1)\n")
    issues = scan_path(tmp_path, "sqlalchemy>=2.0", registry=registry)
    assert [i.code for i in issues if i.code == "SQL002"] == ["SQL002"]


def test_repairs_query_get(tmp_path: Path, registry: PluginRegistry) -> None:
    _write(tmp_path, "m.py", "user = session.query(User).get(1)\n")
    results = repair_path(tmp_path, "sqlalchemy>=2.0", dry_run=True, registry=registry)
    assert results[0].new_source == "user = session.get(User, 1)\n"


def test_repairs_query_get_keeps_complex_receiver(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    _write(tmp_path, "m.py", "user = db.session.query(User).get(pk)\n")
    results = repair_path(tmp_path, "sqlalchemy>=2.0", dry_run=True, registry=registry)
    assert results[0].new_source == "user = db.session.get(User, pk)\n"


def test_does_not_touch_flask_sqlalchemy_query_attribute(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    # ``Model.query`` (attribute, not a call) is the Flask-SQLAlchemy idiom;
    # rewriting it would be wrong, so we leave it alone and emit nothing.
    src = "user = User.query.get(1)\n"
    _write(tmp_path, "m.py", src)
    results = repair_path(tmp_path, "sqlalchemy>=2.0", dry_run=True, registry=registry)
    assert results[0].new_source == src
    assert [i for i in results[0].issues if i.code == "SQL002"] == []


def test_does_not_rewrite_query_with_multiple_models(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    # ``session.query(A, B).get(1)`` is ambiguous; skip the codemod.
    src = "row = session.query(A, B).get(1)\n"
    _write(tmp_path, "m.py", src)
    results = repair_path(tmp_path, "sqlalchemy>=2.0", dry_run=True, registry=registry)
    assert results[0].new_source == src


# ---------------------------------------------------------------------------
# SQL003 — declarative_base() call
# ---------------------------------------------------------------------------


def test_detects_declarative_base_call(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    _write(
        tmp_path,
        "m.py",
        """
        from sqlalchemy.orm import declarative_base
        Base = declarative_base()
        """,
    )
    issues = scan_path(tmp_path, "sqlalchemy>=2.0", registry=registry)
    assert any(i.code == "SQL003" for i in issues)
    sql003 = next(i for i in issues if i.code == "SQL003")
    assert sql003.fix is not None and sql003.fix.safe is False


# ---------------------------------------------------------------------------
# SQL005 — Query.update / Query.delete
# ---------------------------------------------------------------------------


def test_detects_query_update(tmp_path: Path, registry: PluginRegistry) -> None:
    _write(
        tmp_path,
        "m.py",
        "n = session.query(User).update({'active': False})\n",
    )
    issues = scan_path(tmp_path, "sqlalchemy>=2.0", registry=registry)
    sql005 = [i for i in issues if i.code == "SQL005"]
    assert len(sql005) == 1
    assert sql005[0].context["method"] == "update"
    assert sql005[0].fix is None  # info only


def test_detects_query_delete(tmp_path: Path, registry: PluginRegistry) -> None:
    _write(tmp_path, "m.py", "session.query(User).delete()\n")
    issues = scan_path(tmp_path, "sqlalchemy>=2.0", registry=registry)
    assert any(i.code == "SQL005" for i in issues)


def test_session_delete_does_not_fire_sql005(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    # ``session.delete(obj)`` is the Session API and stays valid in 2.0.
    _write(tmp_path, "m.py", "session.delete(obj)\n")
    issues = scan_path(tmp_path, "sqlalchemy>=2.0", registry=registry)
    assert [i for i in issues if i.code == "SQL005"] == []
