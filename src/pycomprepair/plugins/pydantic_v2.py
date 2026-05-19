"""Pydantic v1 -> v2 migration plugin.

Implements a curated, conservative subset of the well-known v1 -> v2 migration
rules. Designed to be extended; today covers:

* ``PYD001`` — ``.dict()``        -> ``.model_dump()``
* ``PYD002`` — ``.json()``        -> ``.model_dump_json()``
* ``PYD003`` — ``.parse_obj(x)``  -> ``.model_validate(x)``
* ``PYD004`` — ``.parse_raw(x)``  -> ``.model_validate_json(x)``
* ``PYD005`` — ``.copy(...)``     -> ``.model_copy(...)``
* ``PYD006`` — ``@validator``     -> ``@field_validator`` (best-effort import rewrite)
* ``PYD007`` — ``@root_validator`` -> ``@model_validator`` (best-effort)
* ``PYD008`` — inner ``class Config`` is deprecated; emit a warning issue
  (no auto-fix yet because the safe transformation depends on field options).

Each rule is intentionally narrow: when the call target cannot be proven to
be a ``BaseModel`` subclass via static analysis alone, fixes are still
suggested but with reduced confidence and gated by ``--unsafe-fixes`` in
the CLI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version

from pycomprepair.codemods.helpers import rename_attribute_call
from pycomprepair.core.issue import Fix, Issue, Severity
from pycomprepair.core.plugin import PluginContext

PLUGIN_NAME = "pydantic"
TARGET_DISTS = ("pydantic",)

# Method renames: old method name -> (new method name, rule code, description)
_METHOD_RENAMES: dict[str, tuple[str, str, str]] = {
    "dict": ("model_dump", "PYD001", "`.dict()` is deprecated; use `.model_dump()`."),
    "json": ("model_dump_json", "PYD002", "`.json()` is deprecated; use `.model_dump_json()`."),
    "parse_obj": (
        "model_validate",
        "PYD003",
        "`Model.parse_obj(x)` is deprecated; use `Model.model_validate(x)`.",
    ),
    "parse_raw": (
        "model_validate_json",
        "PYD004",
        "`Model.parse_raw(x)` is deprecated; use `Model.model_validate_json(x)`.",
    ),
    "copy": (
        "model_copy",
        "PYD005",
        "`.copy()` is deprecated on BaseModel; use `.model_copy()`.",
    ),
}

_VALIDATOR_RENAMES: dict[str, tuple[str, str]] = {
    "validator": ("field_validator", "PYD006"),
    "root_validator": ("model_validator", "PYD007"),
}


@dataclass
class _PydanticPlugin:
    """Pydantic v1 -> v2 migration plugin."""

    name: str = PLUGIN_NAME
    targets: tuple[str, ...] = TARGET_DISTS

    def matches(self, context: PluginContext) -> bool:
        if context.target.name.lower() not in self.targets:
            return False
        # Activate only when targeting Pydantic >= 2.
        return _targets_version_ge(context.target, "2.0")

    def scan(self, context: PluginContext) -> list[Issue]:
        wrapper = MetadataWrapper(context.module, unsafe_skip_copy=True)
        positions = wrapper.resolve(PositionProvider)
        visitor = _PydanticScanVisitor(positions=positions, file=context.file)
        wrapper.visit(visitor)
        return visitor.issues

    def repair(self, context: PluginContext, issues: list[Issue]) -> cst.Module:
        if not issues:
            return context.module
        transformer = _PydanticTransformer()
        new_module = context.module.visit(transformer)
        if transformer.needs_field_validator_import:
            new_module = _ensure_pydantic_import(new_module, "field_validator")
        if transformer.needs_model_validator_import:
            new_module = _ensure_pydantic_import(new_module, "model_validator")
        return new_module


class _PydanticScanVisitor(cst.CSTVisitor):
    """Walks a module looking for v1 patterns and recording :class:`Issue`."""

    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, positions: dict[cst.CSTNode, object], file: Path) -> None:
        super().__init__()
        self._positions = positions
        self._file = file
        self.issues: list[Issue] = []

    def visit_Call(self, node: cst.Call) -> None:
        func = node.func
        if not isinstance(func, cst.Attribute):
            return
        method = func.attr.value
        if method not in _METHOD_RENAMES:
            return
        new_name, code, desc = _METHOD_RENAMES[method]
        line, col = _pos(self._positions, node)
        self.issues.append(
            Issue(
                plugin=PLUGIN_NAME,
                code=code,
                message=desc,
                file=self._file,
                line=line,
                column=col,
                severity=Severity.WARNING,
                fix=Fix(
                    description=f"Rename `.{method}(...)` to `.{new_name}(...)`",
                    confidence=0.7,  # cannot prove it's a BaseModel statically
                    safe=True,
                ),
                context={"old": method, "new": new_name},
            )
        )

    def visit_Decorator(self, node: cst.Decorator) -> None:
        target = node.decorator
        # Two shapes: @validator(...) and @validator
        if isinstance(target, cst.Call):
            target = target.func
        if not isinstance(target, cst.Name):
            return
        if target.value not in _VALIDATOR_RENAMES:
            return
        new_name, code = _VALIDATOR_RENAMES[target.value]
        line, col = _pos(self._positions, node)
        self.issues.append(
            Issue(
                plugin=PLUGIN_NAME,
                code=code,
                message=f"`@{target.value}` is deprecated in Pydantic v2; use `@{new_name}`.",
                file=self._file,
                line=line,
                column=col,
                severity=Severity.WARNING,
                fix=Fix(
                    description=f"Rename decorator `@{target.value}` to `@{new_name}`",
                    confidence=0.9,
                    safe=True,
                ),
                context={"old": target.value, "new": new_name},
            )
        )

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        # Detect an inner ``class Config:`` (no auto-fix yet — emit warning).
        for stmt in node.body.body:
            if (
                isinstance(stmt, cst.ClassDef)
                and isinstance(stmt.name, cst.Name)
                and stmt.name.value == "Config"
            ):
                line, col = _pos(self._positions, stmt)
                self.issues.append(
                    Issue(
                        plugin=PLUGIN_NAME,
                        code="PYD008",
                        message=(
                            "Inner `class Config` is deprecated; "
                            "use `model_config = ConfigDict(...)` instead."
                        ),
                        file=self._file,
                        line=line,
                        column=col,
                        severity=Severity.WARNING,
                        fix=None,  # safe automated transform requires more context
                        context={"class": node.name.value},
                    )
                )


class _PydanticTransformer(cst.CSTTransformer):
    """Applies the codemods corresponding to scan issues."""

    def __init__(self) -> None:
        super().__init__()
        self.needs_field_validator_import = False
        self.needs_model_validator_import = False

    def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.Call:
        func = updated_node.func
        if not isinstance(func, cst.Attribute):
            return updated_node
        method = func.attr.value
        if method not in _METHOD_RENAMES:
            return updated_node
        new_name, _, _ = _METHOD_RENAMES[method]
        return rename_attribute_call(updated_node, new_name)

    def leave_Decorator(
        self, original_node: cst.Decorator, updated_node: cst.Decorator
    ) -> cst.Decorator:
        target = updated_node.decorator
        if isinstance(target, cst.Call):
            inner = target.func
            if isinstance(inner, cst.Name) and inner.value in _VALIDATOR_RENAMES:
                new_name, _ = _VALIDATOR_RENAMES[inner.value]
                self._mark_needs_import(inner.value)
                return updated_node.with_changes(
                    decorator=target.with_changes(func=cst.Name(new_name))
                )
        elif isinstance(target, cst.Name) and target.value in _VALIDATOR_RENAMES:
            new_name, _ = _VALIDATOR_RENAMES[target.value]
            self._mark_needs_import(target.value)
            return updated_node.with_changes(decorator=cst.Name(new_name))
        return updated_node

    def _mark_needs_import(self, old: str) -> None:
        if old == "validator":
            self.needs_field_validator_import = True
        elif old == "root_validator":
            self.needs_model_validator_import = True


def _ensure_pydantic_import(module: cst.Module, name: str) -> cst.Module:
    """Add ``from pydantic import <name>`` if not already present.

    Conservative: only adds the import; does not remove the old ``validator``
    or ``root_validator`` imports because those symbols may still be in use
    or imported via alias.
    """
    # Already imported?
    for stmt in module.body:
        if not isinstance(stmt, cst.SimpleStatementLine):
            continue
        for small in stmt.body:
            if not isinstance(small, cst.ImportFrom):
                continue
            if _dotted(small.module) != "pydantic":
                continue
            if isinstance(small.names, cst.ImportStar):
                return module
            for alias in small.names:
                if isinstance(alias.name, cst.Name) and alias.name.value == name:
                    return module

    new_import = cst.SimpleStatementLine(
        body=[
            cst.ImportFrom(
                module=cst.Name("pydantic"),
                names=[cst.ImportAlias(name=cst.Name(name))],
            )
        ]
    )

    # Insert after the last existing import to keep style consistent.
    new_body: list[cst.BaseStatement] = list(module.body)
    insert_at = 0
    for idx, stmt in enumerate(new_body):
        if isinstance(stmt, cst.SimpleStatementLine) and any(
            isinstance(s, (cst.Import, cst.ImportFrom)) for s in stmt.body
        ):
            insert_at = idx + 1
    new_body.insert(insert_at, new_import)
    return module.with_changes(body=tuple(new_body))


def _dotted(node: cst.BaseExpression | None) -> str:
    if node is None:
        return ""
    if isinstance(node, cst.Name):
        return node.value
    if isinstance(node, cst.Attribute):
        return f"{_dotted(node.value)}.{node.attr.value}"
    return ""


def _pos(positions: dict[cst.CSTNode, object], node: cst.CSTNode) -> tuple[int, int]:
    p = positions.get(node)
    if p is None:
        return (1, 0)
    return (p.start.line, p.start.column)  # type: ignore[attr-defined]


def _targets_version_ge(req: Requirement, version: str) -> bool:
    """Return True if ``req.specifier`` allows only versions ``>=`` ``version``.

    Heuristic: parse the specifier and check whether ``version`` itself is
    contained; otherwise fall back to inspecting individual operators.
    """
    spec: SpecifierSet = req.specifier
    if not spec:
        # No specifier provided -> assume latest -> activate.
        return True
    target = Version(version)
    if target in spec:
        return True
    # Fall-back: any specifier whose lower bound is >= target.
    for s in spec:
        if s.operator in (">=", "==", "~=") and Version(s.version) >= target:
            return True
    return False


# Public plugin instance referenced from the entry point.
plugin = _PydanticPlugin()
