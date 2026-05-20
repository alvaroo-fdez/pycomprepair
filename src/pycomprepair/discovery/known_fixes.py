"""Registry of well-known DSC002 replacements shared with ``discover --fix``.

Each entry maps a fully-qualified dotted path (``numpy.float``,
``django.utils.timezone.utc``, ...) to a :class:`KnownFix` describing how
to rewrite *uses* of that symbol. The registry is consumed by:

* :mod:`pycomprepair.discovery.attr_check` to enrich ``DSC002`` issues with
  a :class:`pycomprepair.core.issue.Fix` payload so they surface in the
  issue table next to other actionable issues.
* :mod:`pycomprepair.discovery.fix` (driven by ``pycomprepair discover --fix``)
  to apply the replacement in place using libcst.

The registry is intentionally a plain ``dict`` so plugins or downstream
projects can extend it at import time. Use :func:`register` for clarity.
"""

from __future__ import annotations

from dataclasses import dataclass

# Replacement modes.
RENAME_ATTR = "rename_attr"
"""Rewrite only the leaf attribute, preserving the user's alias.

Use this when the replacement lives in the same package as the original
(``np.NaN`` -> ``np.nan``). The user's ``np`` alias is kept intact, so the
rewrite never breaks an unrelated import.
"""

REPLACE_EXPRESSION = "replace_expression"
"""Substitute the whole dotted chain with a new expression.

Use this when the replacement is a different identifier or lives in a
different package (``np.float`` -> ``float``,
``django.utils.timezone.utc`` -> ``datetime.timezone.utc``). Cross-package
rewrites are marked ``safe=False`` because they may require adding an
``import`` the file does not have yet.
"""


@dataclass(frozen=True)
class KnownFix:
    """How to rewrite a removed/renamed dotted symbol."""

    mode: str
    """Either :data:`RENAME_ATTR` or :data:`REPLACE_EXPRESSION`."""

    value: str
    """Identifier (for ``RENAME_ATTR``) or expression (for ``REPLACE_EXPRESSION``)."""

    description: str
    """Short human-readable summary surfaced as :attr:`Fix.description`."""

    safe: bool = True
    """Whether the rewrite can be applied without manual review.

    Cross-package replacements default to ``False`` because the caller may
    need to add a new ``import`` that we deliberately do not synthesize.
    """

    confidence: float = 1.0
    """Confidence score in ``[0.0, 1.0]`` — propagated to :attr:`Fix.confidence`."""


KNOWN_FIXES: dict[str, KnownFix] = {
    # ------------------------------------------------------------------
    # NumPy 2.0 removals (mirror the numpy_v2 plugin).
    # ------------------------------------------------------------------
    # Scalar aliases: rewrite to the Python builtin (different identifier,
    # so we use REPLACE_EXPRESSION; semantics are identical, safe=True).
    "numpy.float": KnownFix(REPLACE_EXPRESSION, "float", "Use Python builtin `float`."),
    "numpy.int": KnownFix(REPLACE_EXPRESSION, "int", "Use Python builtin `int`."),
    "numpy.bool": KnownFix(REPLACE_EXPRESSION, "bool", "Use Python builtin `bool`."),
    "numpy.complex": KnownFix(
        REPLACE_EXPRESSION, "complex", "Use Python builtin `complex`."
    ),
    "numpy.object": KnownFix(
        REPLACE_EXPRESSION, "object", "Use Python builtin `object`."
    ),
    "numpy.long": KnownFix(REPLACE_EXPRESSION, "int", "Use Python builtin `int`."),
    "numpy.unicode": KnownFix(REPLACE_EXPRESSION, "str", "Use Python builtin `str`."),
    # Constant aliases: same package, just the leaf changes -> RENAME_ATTR.
    "numpy.NaN": KnownFix(RENAME_ATTR, "nan", "Use lowercase `nan`."),
    "numpy.NAN": KnownFix(RENAME_ATTR, "nan", "Use lowercase `nan`."),
    "numpy.Inf": KnownFix(RENAME_ATTR, "inf", "Use lowercase `inf`."),
    "numpy.PINF": KnownFix(RENAME_ATTR, "inf", "Use lowercase `inf`."),
    "numpy.Infinity": KnownFix(RENAME_ATTR, "inf", "Use lowercase `inf`."),
    "numpy.infty": KnownFix(RENAME_ATTR, "inf", "Use lowercase `inf`."),
    # Function renames: same package -> RENAME_ATTR.
    "numpy.product": KnownFix(RENAME_ATTR, "prod", "Renamed to `prod` in 2.0."),
    "numpy.cumproduct": KnownFix(RENAME_ATTR, "cumprod", "Renamed to `cumprod` in 2.0."),
    "numpy.alltrue": KnownFix(RENAME_ATTR, "all", "Renamed to `all` in 2.0."),
    "numpy.sometrue": KnownFix(RENAME_ATTR, "any", "Renamed to `any` in 2.0."),
    "numpy.round_": KnownFix(RENAME_ATTR, "round", "Renamed to `round` in 2.0."),
    # Function renames added in v1.1.0 (still same package, safe).
    "numpy.in1d": KnownFix(RENAME_ATTR, "isin", "Renamed to `isin` in 2.0."),
    "numpy.trapz": KnownFix(RENAME_ATTR, "trapezoid", "Renamed to `trapezoid` in 2.0."),
    "numpy.row_stack": KnownFix(RENAME_ATTR, "vstack", "Renamed to `vstack` in 2.0."),
    # Scalar type aliases removed in 2.0 with same-package replacements.
    "numpy.string_": KnownFix(RENAME_ATTR, "bytes_", "Renamed to `bytes_` in 2.0."),
    "numpy.unicode_": KnownFix(RENAME_ATTR, "str_", "Renamed to `str_` in 2.0."),
    "numpy.float_": KnownFix(RENAME_ATTR, "float64", "Use `float64` (alias removed in 2.0)."),
    "numpy.complex_": KnownFix(
        RENAME_ATTR, "complex128", "Use `complex128` (alias removed in 2.0)."
    ),
    "numpy.longfloat": KnownFix(
        RENAME_ATTR, "longdouble", "Renamed to `longdouble` in 2.0."
    ),
    "numpy.singlecomplex": KnownFix(
        RENAME_ATTR, "complex64", "Renamed to `complex64` in 2.0."
    ),
    "numpy.cfloat": KnownFix(
        RENAME_ATTR, "complex128", "Renamed to `complex128` in 2.0."
    ),
    "numpy.clongfloat": KnownFix(
        RENAME_ATTR, "clongdouble", "Renamed to `clongdouble` in 2.0."
    ),
    # ------------------------------------------------------------------
    # Django 5.0 removals.
    # ------------------------------------------------------------------
    # Cross-package rewrite, so safe=False: the user may need to add a
    # ``import datetime`` we deliberately do not synthesize.
    "django.utils.timezone.utc": KnownFix(
        REPLACE_EXPRESSION,
        "datetime.timezone.utc",
        "Use `datetime.timezone.utc` (may require `import datetime`).",
        safe=False,
        confidence=0.7,
    ),
    # Same-module renames removed in Django 4.0 / 5.0 (safe rewrites).
    "django.utils.encoding.smart_text": KnownFix(
        RENAME_ATTR, "smart_str", "Renamed to `smart_str` (removed in Django 4.0)."
    ),
    "django.utils.encoding.force_text": KnownFix(
        RENAME_ATTR, "force_str", "Renamed to `force_str` (removed in Django 4.0)."
    ),
    "django.utils.translation.ugettext": KnownFix(
        RENAME_ATTR, "gettext", "Renamed to `gettext` (removed in Django 4.0)."
    ),
    "django.utils.translation.ugettext_lazy": KnownFix(
        RENAME_ATTR, "gettext_lazy", "Renamed to `gettext_lazy` (removed in Django 4.0)."
    ),
    "django.utils.translation.ugettext_noop": KnownFix(
        RENAME_ATTR, "gettext_noop", "Renamed to `gettext_noop` (removed in Django 4.0)."
    ),
    "django.utils.translation.ungettext": KnownFix(
        RENAME_ATTR, "ngettext", "Renamed to `ngettext` (removed in Django 4.0)."
    ),
    "django.utils.translation.ungettext_lazy": KnownFix(
        RENAME_ATTR, "ngettext_lazy", "Renamed to `ngettext_lazy` (removed in Django 4.0)."
    ),
    # ------------------------------------------------------------------
    # SQLAlchemy 2.0 removals (same-module renames, safe).
    # ------------------------------------------------------------------
    "sqlalchemy.orm.relation": KnownFix(
        RENAME_ATTR, "relationship", "Renamed to `relationship` in SQLAlchemy 2.0."
    ),
    "sqlalchemy.orm.eagerload": KnownFix(
        RENAME_ATTR, "joinedload", "Renamed to `joinedload` in SQLAlchemy 2.0."
    ),
}


def register(qualified: str, fix: KnownFix) -> None:
    """Register a new replacement at import time.

    Plugins can call this in their module body to teach ``discover --fix``
    about additional removals without forking the core table.
    """
    KNOWN_FIXES[qualified] = fix
