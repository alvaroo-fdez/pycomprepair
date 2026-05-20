"""NumPy 1.x -> 2.x migration plugin.

NumPy 2.0 removed a large number of long-deprecated aliases that had been
emitting ``DeprecationWarning`` for years. This plugin covers the subset of
those removals that are mechanical and safe to rewrite:

* ``NPY001`` — removed *scalar type aliases* (``np.float``, ``np.int``,
  ``np.bool``, ``np.complex``, ``np.object``, ``np.long``, ``np.unicode``).
  Each one is rewritten to the equivalent Python builtin. This is a strict
  rename: NumPy 1.20+ already documents these as exact aliases to the
  Python builtin types, so the rewrite is semantically identical.

* ``NPY002`` — removed *constant aliases* (``np.NaN``, ``np.NAN``,
  ``np.Inf``, ``np.PINF``, ``np.Infinity``, ``np.infty``). The lowercase
  ``np.nan`` / ``np.inf`` survived 2.0 and are the canonical spellings.

* ``NPY003`` — *function renames* removed in 2.0 (``np.product`` ->
  ``np.prod``, ``np.cumproduct`` -> ``np.cumprod``, ``np.alltrue`` ->
  ``np.all``, ``np.sometrue`` -> ``np.any``, ``np.round_`` -> ``np.round``).
  These pairs have identical signatures and semantics in 2.0.

All three codes only fire on attribute access through an alias that was
introduced by ``import numpy [as <alias>]``, so a hand-written local
``np.float`` (where ``np`` is something else) is left alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version

from pycomprepair.core.issue import Fix, Issue, Severity
from pycomprepair.core.plugin import PluginContext

PLUGIN_NAME = "numpy"
TARGET_DISTS = ("numpy",)


# Removed scalar aliases (NPY001). Map -> Python builtin replacement.
_SCALAR_ALIASES: dict[str, str] = {
    "float": "float",
    "int": "int",
    "bool": "bool",
    "complex": "complex",
    "object": "object",
    "long": "int",
    "unicode": "str",
}

# Removed constant aliases (NPY002). All rewrite to lowercase form.
_CONSTANT_ALIASES: dict[str, str] = {
    "NaN": "nan",
    "NAN": "nan",
    "Inf": "inf",
    "PINF": "inf",
    "Infinity": "inf",
    "infty": "inf",
}

# Removed function aliases (NPY003). Map -> replacement attribute name.
_FUNCTION_RENAMES: dict[str, str] = {
    "product": "prod",
    "cumproduct": "cumprod",
    "alltrue": "all",
    "sometrue": "any",
    "round_": "round",
}


@dataclass
class _NumPyPlugin:
    name: str = PLUGIN_NAME
    targets: tuple[str, ...] = TARGET_DISTS

    def matches(self, context: PluginContext) -> bool:
        if context.target.name.lower() not in self.targets:
            return False
        return _targets_version_ge(context.target, "2.0")

    def scan(self, context: PluginContext) -> list[Issue]:
        wrapper = MetadataWrapper(context.module, unsafe_skip_copy=True)
        positions = wrapper.resolve(PositionProvider)
        aliases = _collect_numpy_aliases(context.module)
        if not aliases:
            return []
        visitor = _NumPyScanVisitor(
            positions=positions, file=context.file, aliases=aliases
        )
        wrapper.visit(visitor)
        return visitor.issues

    def repair(self, context: PluginContext, issues: list[Issue]) -> cst.Module:
        relevant = [i for i in issues if i.plugin == PLUGIN_NAME and i.fix and i.fix.safe]
        if not relevant:
            return context.module
        aliases = _collect_numpy_aliases(context.module)
        if not aliases:
            return context.module
        return context.module.visit(_NumPyRenameTransformer(aliases=aliases))


# ---------------------------------------------------------------------------
# Alias collection
# ---------------------------------------------------------------------------


def _collect_numpy_aliases(module: cst.Module) -> set[str]:
    """Return the set of local names bound to ``numpy`` in this module.

    Handles ``import numpy``, ``import numpy as np`` and the corner case of
    multiple aliases (``import numpy as np, numpy as alt_np``). Names that
    are later reassigned at top level are still returned: the scan is
    intentionally over-eager but the rename only triggers on attribute
    access, so a top-level ``np = something_else`` would simply produce a
    benign rewrite at most.
    """
    aliases: set[str] = set()
    for stmt in module.body:
        if not isinstance(stmt, cst.SimpleStatementLine):
            continue
        for small in stmt.body:
            if not isinstance(small, cst.Import):
                continue
            for alias in small.names:
                if not isinstance(alias.name, cst.Name) or alias.name.value != "numpy":
                    continue
                if alias.asname is not None and isinstance(alias.asname.name, cst.Name):
                    aliases.add(alias.asname.name.value)
                else:
                    aliases.add("numpy")
    return aliases


# ---------------------------------------------------------------------------
# Scan visitor
# ---------------------------------------------------------------------------


class _NumPyScanVisitor(cst.CSTVisitor):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(
        self,
        positions: dict[cst.CSTNode, object],
        file: Path,
        aliases: set[str],
    ) -> None:
        super().__init__()
        self._positions = positions
        self._file = file
        self._aliases = aliases
        self.issues: list[Issue] = []

    def visit_Attribute(self, node: cst.Attribute) -> None:
        if not isinstance(node.value, cst.Name):
            return
        if node.value.value not in self._aliases:
            return
        attr = node.attr.value
        line, col = _pos(self._positions, node)

        if attr in _SCALAR_ALIASES:
            target = _SCALAR_ALIASES[attr]
            self.issues.append(
                Issue(
                    plugin=PLUGIN_NAME,
                    code="NPY001",
                    message=(
                        f"`numpy.{attr}` was removed in NumPy 2.0; "
                        f"use the Python builtin `{target}` instead."
                    ),
                    file=self._file,
                    line=line,
                    column=col,
                    severity=Severity.ERROR,
                    fix=Fix(
                        description=f"Replace `np.{attr}` with `{target}`",
                        confidence=1.0,
                        safe=True,
                    ),
                    context={"old": attr, "new": target, "kind": "scalar"},
                )
            )
            return

        if attr in _CONSTANT_ALIASES:
            target = _CONSTANT_ALIASES[attr]
            self.issues.append(
                Issue(
                    plugin=PLUGIN_NAME,
                    code="NPY002",
                    message=(
                        f"`numpy.{attr}` was removed in NumPy 2.0; "
                        f"use `numpy.{target}` instead."
                    ),
                    file=self._file,
                    line=line,
                    column=col,
                    severity=Severity.ERROR,
                    fix=Fix(
                        description=f"Rename `{attr}` to `{target}`",
                        confidence=1.0,
                        safe=True,
                    ),
                    context={"old": attr, "new": target, "kind": "constant"},
                )
            )
            return

        if attr in _FUNCTION_RENAMES:
            target = _FUNCTION_RENAMES[attr]
            self.issues.append(
                Issue(
                    plugin=PLUGIN_NAME,
                    code="NPY003",
                    message=(
                        f"`numpy.{attr}` was removed in NumPy 2.0; "
                        f"use `numpy.{target}` instead."
                    ),
                    file=self._file,
                    line=line,
                    column=col,
                    severity=Severity.ERROR,
                    fix=Fix(
                        description=f"Rename `{attr}` to `{target}`",
                        confidence=1.0,
                        safe=True,
                    ),
                    context={"old": attr, "new": target, "kind": "function"},
                )
            )


# ---------------------------------------------------------------------------
# Codemod transformer
# ---------------------------------------------------------------------------


class _NumPyRenameTransformer(cst.CSTTransformer):
    """Rewrite ``np.<old>`` attribute accesses.

    * Scalar aliases collapse to a bare ``Name`` (``np.float`` -> ``float``).
    * Constant + function renames keep the ``np.`` prefix and replace just
      the ``attr`` (``np.product`` -> ``np.prod``).
    """

    def __init__(self, aliases: set[str]) -> None:
        super().__init__()
        self._aliases = aliases

    def leave_Attribute(
        self, original_node: cst.Attribute, updated_node: cst.Attribute
    ) -> cst.BaseExpression:
        if not isinstance(updated_node.value, cst.Name):
            return updated_node
        if updated_node.value.value not in self._aliases:
            return updated_node
        attr = updated_node.attr.value

        if attr in _SCALAR_ALIASES:
            return cst.Name(_SCALAR_ALIASES[attr])
        if attr in _CONSTANT_ALIASES:
            return updated_node.with_changes(attr=cst.Name(_CONSTANT_ALIASES[attr]))
        if attr in _FUNCTION_RENAMES:
            return updated_node.with_changes(attr=cst.Name(_FUNCTION_RENAMES[attr]))
        return updated_node


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pos(positions: dict[cst.CSTNode, object], node: cst.CSTNode) -> tuple[int, int]:
    p = positions.get(node)
    if p is None:
        return (1, 0)
    return (p.start.line, p.start.column)  # type: ignore[attr-defined]


def _targets_version_ge(req: Requirement, version: str) -> bool:
    spec: SpecifierSet = req.specifier
    if not spec:
        return True
    target = Version(version)
    if target in spec:
        return True
    return any(
        s.operator in (">=", "==", "~=") and Version(s.version) >= target for s in spec
    )


plugin = _NumPyPlugin()
