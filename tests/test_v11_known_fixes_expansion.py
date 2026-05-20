"""Tests for the v1.1.0 KNOWN_FIXES expansion.

Covers the additional same-module renames (NumPy 2.0 function/scalar
aliases, Django 4.0/5.0 encoding/translation renames and SQLAlchemy 2.0
ORM renames) wired into :mod:`pycomprepair.discovery.known_fixes`.

All new entries use :data:`RENAME_ATTR` mode, so they must be applied by
default (``safe=True``) and preserve the user's alias.
"""

from __future__ import annotations

import pytest

from pycomprepair.discovery import KNOWN_FIXES, rewrite_source
from pycomprepair.discovery.known_fixes import RENAME_ATTR


@pytest.mark.parametrize(
    ("source_attr", "expected_attr"),
    [
        ("in1d", "isin"),
        ("trapz", "trapezoid"),
        ("row_stack", "vstack"),
        ("string_", "bytes_"),
        ("unicode_", "str_"),
        ("float_", "float64"),
        ("complex_", "complex128"),
        ("longfloat", "longdouble"),
        ("singlecomplex", "complex64"),
        ("cfloat", "complex128"),
        ("clongfloat", "clongdouble"),
    ],
)
def test_numpy_v11_renames_round_trip(source_attr: str, expected_attr: str) -> None:
    """Each new numpy entry rewrites under the user's alias and is safe."""
    qualified = f"numpy.{source_attr}"
    known = KNOWN_FIXES[qualified]
    assert known.mode == RENAME_ATTR
    assert known.safe is True
    assert known.value == expected_attr

    src = f"import numpy as np\nx = np.{source_attr}\n"
    out, applied = rewrite_source(src)
    assert applied == 1
    assert f"np.{expected_attr}" in out
    assert f"np.{source_attr}" not in out


def test_numpy_v11_renames_preserve_custom_alias() -> None:
    src = "import numpy as nump\nx = nump.in1d(a, b)\n"
    out, applied = rewrite_source(src)
    assert applied == 1
    assert "nump.isin(a, b)" in out
    assert "in1d" not in out


@pytest.mark.parametrize(
    ("module", "source_name", "expected_name"),
    [
        ("django.utils.encoding", "smart_text", "smart_str"),
        ("django.utils.encoding", "force_text", "force_str"),
        ("django.utils.translation", "ugettext", "gettext"),
        ("django.utils.translation", "ugettext_lazy", "gettext_lazy"),
        ("django.utils.translation", "ugettext_noop", "gettext_noop"),
        ("django.utils.translation", "ungettext", "ngettext"),
        ("django.utils.translation", "ungettext_lazy", "ngettext_lazy"),
    ],
)
def test_django_v11_renames_via_full_chain(
    module: str, source_name: str, expected_name: str
) -> None:
    """``import django`` + full dotted access rewrites the leaf only."""
    qualified = f"{module}.{source_name}"
    known = KNOWN_FIXES[qualified]
    assert known.mode == RENAME_ATTR
    assert known.safe is True
    assert known.value == expected_name

    src = f"import django\nx = django.{module.split('.', 1)[1]}.{source_name}\n"
    out, applied = rewrite_source(src)
    assert applied == 1
    assert f".{expected_name}\n" in out
    assert source_name not in out


@pytest.mark.parametrize(
    ("source_name", "expected_name"),
    [
        ("relation", "relationship"),
        ("eagerload", "joinedload"),
    ],
)
def test_sqlalchemy_v11_orm_renames(source_name: str, expected_name: str) -> None:
    qualified = f"sqlalchemy.orm.{source_name}"
    known = KNOWN_FIXES[qualified]
    assert known.mode == RENAME_ATTR
    assert known.safe is True
    assert known.value == expected_name

    src = f"import sqlalchemy\nrel = sqlalchemy.orm.{source_name}('User')\n"
    out, applied = rewrite_source(src)
    assert applied == 1
    assert f"sqlalchemy.orm.{expected_name}('User')" in out
    # The old leaf must not survive — anchor on the dotted call form so we
    # don't trip on substring overlap (``relation`` ⊂ ``relationship``).
    assert f"orm.{source_name}(" not in out


def test_no_v11_entry_marked_unsafe_by_mistake() -> None:
    """Every new RENAME_ATTR entry added in v1.1.0 must remain ``safe=True``."""
    new_entries = {
        "numpy.in1d",
        "numpy.trapz",
        "numpy.row_stack",
        "numpy.string_",
        "numpy.unicode_",
        "numpy.float_",
        "numpy.complex_",
        "numpy.longfloat",
        "numpy.singlecomplex",
        "numpy.cfloat",
        "numpy.clongfloat",
        "django.utils.encoding.smart_text",
        "django.utils.encoding.force_text",
        "django.utils.translation.ugettext",
        "django.utils.translation.ugettext_lazy",
        "django.utils.translation.ugettext_noop",
        "django.utils.translation.ungettext",
        "django.utils.translation.ungettext_lazy",
        "sqlalchemy.orm.relation",
        "sqlalchemy.orm.eagerload",
    }
    for qualified in new_entries:
        fix = KNOWN_FIXES[qualified]
        assert fix.safe is True, f"{qualified} should be a safe rename"
        assert fix.mode == RENAME_ATTR, f"{qualified} should use RENAME_ATTR"
        assert fix.confidence == 1.0, f"{qualified} should be max confidence"
