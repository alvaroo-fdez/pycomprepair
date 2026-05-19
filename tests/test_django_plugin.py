"""Tests for the Django 4.x -> 5.x migration plugin."""

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


def test_plugin_skips_when_target_below_5_0(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    _write(
        tmp_path,
        "m.py",
        "from django.utils.encoding import smart_text\n",
    )
    issues = scan_path(tmp_path, "django<5.0", registry=registry)
    assert [i for i in issues if i.plugin == "django"] == []


# ---------------------------------------------------------------------------
# DJA001 — timezone.utc removal
# ---------------------------------------------------------------------------


def test_detects_timezone_utc_import(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    _write(tmp_path, "m.py", "from django.utils.timezone import utc\n")
    issues = scan_path(tmp_path, "django>=5.0", registry=registry)
    assert [i.code for i in issues if i.code == "DJA001"] == ["DJA001"]


def test_detects_timezone_utc_attribute_access(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    _write(
        tmp_path,
        "m.py",
        """
        import django.utils.timezone
        now_utc = django.utils.timezone.utc
        """,
    )
    issues = scan_path(tmp_path, "django>=5.0", registry=registry)
    assert any(i.code == "DJA001" for i in issues)


def test_dja001_is_not_auto_fixed(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    src = "from django.utils.timezone import utc\n"
    _write(tmp_path, "m.py", src)
    results = repair_path(tmp_path, "django>=5.0", dry_run=True, registry=registry)
    # safe=False, so default repair gate skips it.
    assert results[0].new_source == src


# ---------------------------------------------------------------------------
# DJA002 — smart_text / force_text
# ---------------------------------------------------------------------------


def test_detects_smart_text_import(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    _write(tmp_path, "m.py", "from django.utils.encoding import smart_text\n")
    issues = scan_path(tmp_path, "django>=5.0", registry=registry)
    sql_codes = [i.code for i in issues]
    assert sql_codes.count("DJA002") == 1


def test_repairs_smart_text_import_and_calls(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    _write(
        tmp_path,
        "m.py",
        """
        from django.utils.encoding import smart_text

        def fmt(v):
            return smart_text(v)
        """,
    )
    results = repair_path(tmp_path, "django>=5.0", dry_run=True, registry=registry)
    new = results[0].new_source
    assert "from django.utils.encoding import smart_str" in new
    assert "return smart_str(v)" in new
    assert "smart_text" not in new


def test_repairs_force_text_alongside_smart_text(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    _write(
        tmp_path,
        "m.py",
        """
        from django.utils.encoding import smart_text, force_text

        a = smart_text(x)
        b = force_text(y)
        """,
    )
    results = repair_path(tmp_path, "django>=5.0", dry_run=True, registry=registry)
    new = results[0].new_source
    assert "smart_str, force_str" in new
    assert "a = smart_str(x)" in new
    assert "b = force_str(y)" in new


def test_does_not_rename_unrelated_smart_text(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    # No import from django.utils.encoding — leave the local name alone.
    src = "def smart_text(v): return v\nx = smart_text(1)\n"
    _write(tmp_path, "m.py", src)
    results = repair_path(tmp_path, "django>=5.0", dry_run=True, registry=registry)
    assert results[0].new_source == src


def test_does_not_rename_obj_smart_text_attribute(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    # ``obj.smart_text`` is an attribute access; we cannot prove ``obj`` is
    # the django module, so leave it untouched even when we DO rewrite the
    # import in the same file.
    _write(
        tmp_path,
        "m.py",
        """
        from django.utils.encoding import smart_text

        a = smart_text(x)  # rewritten
        b = obj.smart_text  # left as-is
        """,
    )
    results = repair_path(tmp_path, "django>=5.0", dry_run=True, registry=registry)
    new = results[0].new_source
    assert "a = smart_str(x)" in new
    assert "b = obj.smart_text" in new


# ---------------------------------------------------------------------------
# DJA003 — ugettext family
# ---------------------------------------------------------------------------


def test_repairs_ugettext_lazy(tmp_path: Path, registry: PluginRegistry) -> None:
    _write(
        tmp_path,
        "m.py",
        """
        from django.utils.translation import ugettext_lazy

        label = ugettext_lazy("Hello")
        """,
    )
    results = repair_path(tmp_path, "django>=5.0", dry_run=True, registry=registry)
    new = results[0].new_source
    assert "from django.utils.translation import gettext_lazy" in new
    assert "gettext_lazy(\"Hello\")" in new


def test_preserves_aliased_import(tmp_path: Path, registry: PluginRegistry) -> None:
    # ``import ugettext_lazy as _`` is the canonical Django idiom; we rename
    # the imported symbol but the alias ``_`` (and all its call sites) must
    # stay intact.
    _write(
        tmp_path,
        "m.py",
        """
        from django.utils.translation import ugettext_lazy as _

        label = _("Hello")
        """,
    )
    results = repair_path(tmp_path, "django>=5.0", dry_run=True, registry=registry)
    new = results[0].new_source
    assert "from django.utils.translation import gettext_lazy as _" in new
    assert "label = _(\"Hello\")" in new


# ---------------------------------------------------------------------------
# DJA004 — index_together
# ---------------------------------------------------------------------------


def test_detects_index_together(tmp_path: Path, registry: PluginRegistry) -> None:
    _write(
        tmp_path,
        "models.py",
        """
        from django.db import models

        class Article(models.Model):
            class Meta:
                index_together = [["a", "b"]]
        """,
    )
    issues = scan_path(tmp_path, "django>=5.0", registry=registry)
    assert any(i.code == "DJA004" for i in issues)


def test_ignores_index_together_outside_meta(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    # A module-level ``index_together`` is not a Django model option.
    _write(tmp_path, "m.py", "index_together = [[1, 2]]\n")
    issues = scan_path(tmp_path, "django>=5.0", registry=registry)
    assert [i for i in issues if i.code == "DJA004"] == []
