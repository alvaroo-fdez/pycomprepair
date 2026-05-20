"""FastAPI migration plugin (modern lifespan + small deprecations).

Covers a curated, conservative subset of the FastAPI deprecation guide:

* ``FAS001`` — ``@app.on_event("startup")`` / ``"shutdown"`` are deprecated;
  recommend migrating to the ``lifespan`` context manager. We emit a
  warning issue (no automatic codemod yet because the safe transformation
  depends on the user's existing application structure).

The plugin is built so that future rules (e.g. ``Depends(..., use_cache=False)``
re-arrangement, ``status_code`` imports, ``BackgroundTasks`` migration) can be
added next to ``_RULES`` without touching the engine.
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

PLUGIN_NAME = "fastapi"
TARGET_DISTS = ("fastapi",)


@dataclass
class _FastAPIPlugin:
    name: str = PLUGIN_NAME
    targets: tuple[str, ...] = TARGET_DISTS

    def matches(self, context: PluginContext) -> bool:
        if context.target.name.lower() not in self.targets:
            return False
        return _targets_version_ge(context.target, "0.100")

    def scan(self, context: PluginContext) -> list[Issue]:
        wrapper = MetadataWrapper(context.module, unsafe_skip_copy=True)
        positions = wrapper.resolve(PositionProvider)
        visitor = _FastAPIScanVisitor(positions=positions, file=context.file)
        wrapper.visit(visitor)
        return visitor.issues

    def repair(self, context: PluginContext, issues: list[Issue]) -> cst.Module:
        # No safe automatic codemod yet for the rules emitted by this plugin.
        return context.module


class _FastAPIScanVisitor(cst.CSTVisitor):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, positions: dict[cst.CSTNode, object], file: Path) -> None:
        super().__init__()
        self._positions = positions
        self._file = file
        self.issues: list[Issue] = []

    def visit_Decorator(self, node: cst.Decorator) -> None:
        target = node.decorator
        if not isinstance(target, cst.Call):
            return
        func = target.func
        if not isinstance(func, cst.Attribute) or func.attr.value != "on_event":
            return
        # Extract the first positional argument if it's a string.
        event_name: str | None = None
        for arg in target.args:
            if arg.keyword is None:
                if isinstance(arg.value, cst.SimpleString):
                    event_name = arg.value.evaluated_value
                break
        if event_name not in {"startup", "shutdown"}:
            return
        line, col = _pos(self._positions, node)
        self.issues.append(
            Issue(
                plugin=PLUGIN_NAME,
                code="FAS001",
                message=(
                    f"`@app.on_event({event_name!r})` is deprecated; "
                    "migrate to the `lifespan` context manager."
                ),
                file=self._file,
                line=line,
                column=col,
                severity=Severity.WARNING,
                fix=Fix(
                    description="Migrate to FastAPI `lifespan` context manager",
                    confidence=0.5,
                    safe=False,
                ),
                context={"event": event_name},
            )
        )


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


plugin = _FastAPIPlugin()
