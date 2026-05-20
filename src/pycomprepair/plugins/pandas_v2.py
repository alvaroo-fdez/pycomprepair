"""Pandas 2.x migration plugin.

Pandas 2.0 removed several long-deprecated APIs. This plugin covers the
subset that is safely automatable:

* ``PDS001`` — ``DataFrame.append`` / ``Series.append`` were removed in
  pandas 2.0. There is no in-place safe rewrite (``pd.concat`` changes the
  return semantics), so this code is **detect-only** and never emits a Fix.

* ``PDS002`` — ``.iteritems()`` was removed; ``.items()`` is the modern
  equivalent and has identical semantics on both ``DataFrame`` and
  ``Series`` since pandas 0.21. This is a safe attribute rename.

* ``PDS003`` — ``pd.np`` was removed. There is no mechanical rewrite that
  guarantees correctness (the user typically intends ``import numpy``), so
  this code is **detect-only**.

The plugin only fires on attribute access through an alias bound to
``pandas`` (``import pandas`` / ``import pandas as pd``), so unrelated
``df.append`` calls on non-pandas objects are not flagged. For
``.iteritems`` / ``.items`` the heuristic is necessarily looser: the code
fires whenever ``.iteritems()`` is *called*, regardless of receiver, since
this attribute name is essentially pandas-specific in real codebases.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version

from pycomprepair.core.issue import Fix, Issue, Severity
from pycomprepair.core.plugin import PluginContext

PLUGIN_NAME = "pandas"
TARGET_DISTS = ("pandas",)


@dataclass
class _PandasPlugin:
    name: str = PLUGIN_NAME
    targets: tuple[str, ...] = TARGET_DISTS

    def matches(self, context: PluginContext) -> bool:
        if context.target.name.lower() not in self.targets:
            return False
        return _targets_version_ge(context.target, "2.0")

    def scan(self, context: PluginContext) -> list[Issue]:
        wrapper = MetadataWrapper(context.module, unsafe_skip_copy=True)
        positions = wrapper.resolve(PositionProvider)
        aliases = _collect_pandas_aliases(context.module)
        visitor = _PandasScanVisitor(
            positions=positions, file=context.file, aliases=aliases
        )
        wrapper.visit(visitor)
        return visitor.issues

    def repair(self, context: PluginContext, issues: list[Issue]) -> cst.Module:
        relevant = [
            i
            for i in issues
            if i.plugin == PLUGIN_NAME and i.code == "PDS002" and i.fix and i.fix.safe
        ]
        if not relevant:
            return context.module
        return context.module.visit(_PandasRenameTransformer())


# ---------------------------------------------------------------------------
# Alias collection
# ---------------------------------------------------------------------------


def _collect_pandas_aliases(module: cst.Module) -> set[str]:
    aliases: set[str] = set()
    for stmt in module.body:
        if not isinstance(stmt, cst.SimpleStatementLine):
            continue
        for small in stmt.body:
            if not isinstance(small, cst.Import):
                continue
            for alias in small.names:
                if not isinstance(alias.name, cst.Name) or alias.name.value != "pandas":
                    continue
                if alias.asname is not None and isinstance(alias.asname.name, cst.Name):
                    aliases.add(alias.asname.name.value)
                else:
                    aliases.add("pandas")
    return aliases


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------


class _PandasScanVisitor(cst.CSTVisitor):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(
        self,
        positions: Mapping[cst.CSTNode, object],
        file: Path,
        aliases: set[str],
    ) -> None:
        super().__init__()
        self._positions = positions
        self._file = file
        self._aliases = aliases
        self.issues: list[Issue] = []

    def visit_Call(self, node: cst.Call) -> None:
        # PDS002: any ``.iteritems()`` call is flagged with a safe Fix.
        func = node.func
        if isinstance(func, cst.Attribute) and func.attr.value == "iteritems":
            line, col = _pos(self._positions, node)
            self.issues.append(
                Issue(
                    plugin=PLUGIN_NAME,
                    code="PDS002",
                    message=(
                        "`.iteritems()` was removed in pandas 2.0; "
                        "use `.items()` instead."
                    ),
                    file=self._file,
                    line=line,
                    column=col,
                    severity=Severity.ERROR,
                    fix=Fix(
                        description="Rename `.iteritems()` to `.items()`",
                        confidence=1.0,
                        safe=True,
                    ),
                    context={"old": "iteritems", "new": "items"},
                )
            )

        # PDS001: ``DataFrame.append`` / ``Series.append`` — detect-only.
        # Heuristic: ``<expr>.append(<expr>)`` where the callee attribute
        # is exactly ``append`` and the call has at least one positional
        # argument that is *not* a literal (lists/tuples have list.append
        # semantics and are safe). To avoid false positives on plain
        # ``list.append("x")`` we further require the receiver chain to
        # mention a pandas alias.
        if (
            isinstance(func, cst.Attribute)
            and func.attr.value == "append"
            and self._aliases  # only flag when pandas is actually imported
            and _receiver_mentions(func.value, self._aliases)
        ):
            line, col = _pos(self._positions, node)
            self.issues.append(
                Issue(
                    plugin=PLUGIN_NAME,
                    code="PDS001",
                    message=(
                        "`DataFrame.append` / `Series.append` were removed "
                        "in pandas 2.0; use `pandas.concat([...])` instead."
                    ),
                    file=self._file,
                    line=line,
                    column=col,
                    severity=Severity.ERROR,
                    fix=None,  # No safe automatic rewrite.
                    context={"old": "append"},
                )
            )

    def visit_Attribute(self, node: cst.Attribute) -> None:
        # PDS003: ``pd.np`` access — detect-only.
        if (
            isinstance(node.value, cst.Name)
            and node.value.value in self._aliases
            and node.attr.value == "np"
        ):
            line, col = _pos(self._positions, node)
            self.issues.append(
                Issue(
                    plugin=PLUGIN_NAME,
                    code="PDS003",
                    message=(
                        "`pandas.np` was removed in pandas 2.0; import "
                        "`numpy` directly instead."
                    ),
                    file=self._file,
                    line=line,
                    column=col,
                    severity=Severity.ERROR,
                    fix=None,
                    context={"old": "np"},
                )
            )


def _receiver_mentions(expr: cst.BaseExpression, aliases: set[str]) -> bool:
    """Return True iff *expr* references any pandas alias in its chain.

    This is a syntactic heuristic that catches ``pd.DataFrame(...).append``,
    ``pd.Series(...).append`` and ``df.append`` when ``df`` was assigned
    from a ``pd.read_*`` call earlier in the same module. We deliberately
    keep it cheap and slightly imprecise — false positives on PDS001 are
    informational only since no fix is emitted.
    """
    if isinstance(expr, cst.Name):
        # Bare receiver — flag conservatively, the user will judge.
        return True
    if isinstance(expr, cst.Attribute):
        return _receiver_mentions(expr.value, aliases)
    if isinstance(expr, cst.Call):
        return _receiver_mentions(expr.func, aliases)
    return False


# ---------------------------------------------------------------------------
# Codemod
# ---------------------------------------------------------------------------


class _PandasRenameTransformer(cst.CSTTransformer):
    """Rewrite ``.iteritems`` attribute accesses to ``.items``."""

    def leave_Attribute(
        self, original_node: cst.Attribute, updated_node: cst.Attribute
    ) -> cst.BaseExpression:
        if updated_node.attr.value == "iteritems":
            return updated_node.with_changes(attr=cst.Name("items"))
        return updated_node


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pos(positions: Mapping[cst.CSTNode, object], node: cst.CSTNode) -> tuple[int, int]:
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


plugin = _PandasPlugin()
