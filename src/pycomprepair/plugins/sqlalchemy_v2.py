"""SQLAlchemy 1.4 -> 2.0 migration plugin.

Implements a conservative subset of the 2.0 migration guide focused on
patterns that show up in virtually every codebase using the ORM:

* ``SQL001`` — ``from sqlalchemy.ext.declarative import declarative_base``
  is moved to ``sqlalchemy.orm`` in 2.0. Rewritten automatically when the
  import statement contains exactly that single name.
* ``SQL002`` — ``session.query(Model).get(pk)`` -> ``session.get(Model, pk)``.
  Applied only when both ``query`` and ``get`` receive a single positional
  argument (the common case).
* ``SQL003`` — call to ``declarative_base()`` is detected and reported as a
  warning so users migrate to the new ``DeclarativeBase`` class style. No
  automatic codemod because the safe rewrite depends on mixins, metaclass
  kwargs and naming conventions that the plugin cannot infer statically.
* ``SQL005`` — ``<x>.query(Model).update(...)`` / ``.delete()`` — informational
  note: the default for ``synchronize_session`` changed in 2.0 (from
  ``"evaluate"`` to ``"auto"``). No codemod, just visibility.

Designed to be extended next to ``_RULES``: more rules (``engine.execute``
with raw strings, legacy ``Session.execute(query_obj)``, etc.) can be added
without changing the engine.
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

PLUGIN_NAME = "sqlalchemy"
TARGET_DISTS = ("sqlalchemy", "sqlalchemy[asyncio]")

# The legacy module path that re-exports ``declarative_base``. In 2.0 it
# still works but emits a deprecation warning; the canonical location is
# ``sqlalchemy.orm``.
_LEGACY_DECLARATIVE_MODULE = "sqlalchemy.ext.declarative"
_NEW_DECLARATIVE_MODULE = "sqlalchemy.orm"


@dataclass
class _SQLAlchemyPlugin:
    name: str = PLUGIN_NAME
    targets: tuple[str, ...] = TARGET_DISTS

    def matches(self, context: PluginContext) -> bool:
        if context.target.name.lower() not in self.targets:
            return False
        return _targets_version_ge(context.target, "2.0")

    def scan(self, context: PluginContext) -> list[Issue]:
        wrapper = MetadataWrapper(context.module, unsafe_skip_copy=True)
        positions = wrapper.resolve(PositionProvider)
        visitor = _SQLAlchemyScanVisitor(positions=positions, file=context.file)
        wrapper.visit(visitor)
        return visitor.issues

    def repair(self, context: PluginContext, issues: list[Issue]) -> cst.Module:
        if not issues:
            return context.module
        # Only SQL001 and SQL002 have a codemod; if the scan emitted neither,
        # there is nothing to rewrite.
        actionable = {i.code for i in issues} & {"SQL001", "SQL002"}
        if not actionable:
            return context.module
        return context.module.visit(_SQLAlchemyTransformer())


# ---------------------------------------------------------------------------
# Scan visitor
# ---------------------------------------------------------------------------


class _SQLAlchemyScanVisitor(cst.CSTVisitor):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, positions: Mapping[cst.CSTNode, object], file: Path) -> None:
        super().__init__()
        self._positions = positions
        self._file = file
        self.issues: list[Issue] = []

    # SQL001 — legacy declarative_base import path.
    def visit_ImportFrom(self, node: cst.ImportFrom) -> None:
        if node.module is None:
            return
        module = _dotted(node.module)
        if module != _LEGACY_DECLARATIVE_MODULE:
            return
        if isinstance(node.names, cst.ImportStar):
            return
        names = [a.name.value for a in node.names if isinstance(a.name, cst.Name)]
        if "declarative_base" not in names:
            return
        line, col = _pos(self._positions, node)
        # Only auto-fix the simple case ``from X import declarative_base``;
        # mixed imports keep the warning but lose the codemod.
        only_target = names == ["declarative_base"]
        self.issues.append(
            Issue(
                plugin=PLUGIN_NAME,
                code="SQL001",
                message=(
                    "`sqlalchemy.ext.declarative.declarative_base` is deprecated; "
                    "import it from `sqlalchemy.orm` instead."
                ),
                file=self._file,
                line=line,
                column=col,
                severity=Severity.WARNING,
                fix=Fix(
                    description="Rewrite import to `from sqlalchemy.orm import declarative_base`",
                    confidence=1.0 if only_target else 0.5,
                    safe=only_target,
                ),
                context={"only_target": "true" if only_target else "false"},
            )
        )

    def visit_Call(self, node: cst.Call) -> None:
        func = node.func

        # SQL003 — declarative_base() call.
        if isinstance(func, cst.Name) and func.value == "declarative_base":
            line, col = _pos(self._positions, node)
            self.issues.append(
                Issue(
                    plugin=PLUGIN_NAME,
                    code="SQL003",
                    message=(
                        "`declarative_base()` is legacy in SQLAlchemy 2.0; "
                        "prefer subclassing `DeclarativeBase` directly."
                    ),
                    file=self._file,
                    line=line,
                    column=col,
                    severity=Severity.WARNING,
                    fix=Fix(
                        description="Migrate to `class Base(DeclarativeBase): pass`",
                        confidence=0.4,
                        safe=False,
                    ),
                    context={},
                )
            )
            return

        # SQL002 / SQL005 — chains starting with ``<x>.query(M).<method>(...)``.
        if not isinstance(func, cst.Attribute):
            return
        method = func.attr.value
        inner = func.value
        if not isinstance(inner, cst.Call):
            return
        inner_func = inner.func
        if not isinstance(inner_func, cst.Attribute) or inner_func.attr.value != "query":
            return
        # The query() call must have exactly one positional argument (the model).
        if len(inner.args) != 1 or inner.args[0].keyword is not None:
            return

        if method == "get" and _has_single_positional(node):
            line, col = _pos(self._positions, node)
            self.issues.append(
                Issue(
                    plugin=PLUGIN_NAME,
                    code="SQL002",
                    message=(
                        "`session.query(Model).get(pk)` is legacy; "
                        "use `session.get(Model, pk)` in SQLAlchemy 2.0."
                    ),
                    file=self._file,
                    line=line,
                    column=col,
                    severity=Severity.WARNING,
                    fix=Fix(
                        description="Rewrite to `session.get(Model, pk)`",
                        confidence=0.9,
                        safe=True,
                    ),
                    context={},
                )
            )
            return

        if method in {"update", "delete"}:
            line, col = _pos(self._positions, node)
            self.issues.append(
                Issue(
                    plugin=PLUGIN_NAME,
                    code="SQL005",
                    message=(
                        f"`Query.{method}(...)` default for `synchronize_session` "
                        "changed in SQLAlchemy 2.0 (now `'auto'`). Review the call "
                        "and pass an explicit value if your code relies on the old "
                        "`'evaluate'` behavior."
                    ),
                    file=self._file,
                    line=line,
                    column=col,
                    severity=Severity.INFO,
                    fix=None,
                    context={"method": method},
                )
            )


# ---------------------------------------------------------------------------
# Codemod transformer (SQL001 + SQL002)
# ---------------------------------------------------------------------------


class _SQLAlchemyTransformer(cst.CSTTransformer):
    def leave_ImportFrom(
        self, original_node: cst.ImportFrom, updated_node: cst.ImportFrom
    ) -> cst.BaseSmallStatement:
        if updated_node.module is None:
            return updated_node
        if _dotted(updated_node.module) != _LEGACY_DECLARATIVE_MODULE:
            return updated_node
        if isinstance(updated_node.names, cst.ImportStar):
            return updated_node
        names = [a.name.value for a in updated_node.names if isinstance(a.name, cst.Name)]
        if names != ["declarative_base"]:
            # Mixed import — leave it alone, the scan issue is informational.
            return updated_node
        return updated_node.with_changes(
            module=cst.Attribute(
                value=cst.Name("sqlalchemy"), attr=cst.Name("orm")
            )
        )

    def leave_Call(
        self, original_node: cst.Call, updated_node: cst.Call
    ) -> cst.BaseExpression:
        func = updated_node.func
        if not isinstance(func, cst.Attribute) or func.attr.value != "get":
            return updated_node
        if not _has_single_positional(updated_node):
            return updated_node
        inner = func.value
        if not isinstance(inner, cst.Call):
            return updated_node
        inner_func = inner.func
        if (
            not isinstance(inner_func, cst.Attribute)
            or inner_func.attr.value != "query"
        ):
            return updated_node
        if len(inner.args) != 1 or inner.args[0].keyword is not None:
            return updated_node

        receiver = inner_func.value  # e.g. ``session``
        model_arg = inner.args[0]
        pk_arg = updated_node.args[0]

        # Rebuild ``<receiver>.get(<model>, <pk>)`` keeping the original
        # whitespace/comments of the outer call as much as possible.
        return updated_node.with_changes(
            func=cst.Attribute(value=receiver, attr=cst.Name("get")),
            args=[
                model_arg.with_changes(
                    comma=cst.Comma(
                        whitespace_after=cst.SimpleWhitespace(" "),
                    ),
                ),
                pk_arg.with_changes(comma=cst.MaybeSentinel.DEFAULT),
            ],
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _has_single_positional(call: cst.Call) -> bool:
    return len(call.args) == 1 and call.args[0].keyword is None


def _dotted(node: cst.BaseExpression) -> str:
    if isinstance(node, cst.Name):
        return node.value
    if isinstance(node, cst.Attribute):
        left = _dotted(node.value)
        return f"{left}.{node.attr.value}"
    return ""


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


plugin = _SQLAlchemyPlugin()
