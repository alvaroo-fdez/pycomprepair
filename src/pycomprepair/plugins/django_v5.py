"""Django 4.x -> 5.x migration plugin.

Implements a conservative subset of the 5.0 release notes focused on
removals and deprecations that are mechanical to detect:

* ``DJA001`` — ``django.utils.timezone.utc`` was removed in 5.0; use
  ``datetime.timezone.utc`` instead. Detection only (the safe rewrite
  depends on what is already imported in the file).
* ``DJA002`` — ``django.utils.encoding.smart_text`` / ``force_text`` have
  been removed in favour of ``smart_str`` / ``force_str``. Rewrites both
  the ``from ... import`` aliases and the bare-name call sites.
* ``DJA003`` — ``django.utils.translation.ugettext*`` removed in favour of
  ``gettext*``. Same shape as DJA002 (import + call-site rewrite).
* ``DJA004`` — ``Meta.index_together`` is deprecated; prefer ``indexes``
  with ``models.Index(fields=...)``. Detection only — merging existing
  ``indexes`` while preserving order is not a safe automatic transform.
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

PLUGIN_NAME = "django"
TARGET_DISTS = ("django",)

# DJA002 / DJA003 — name renames. ``module`` is the canonical import path
# the symbol lives in (used to filter false positives in unrelated files).
_NAME_RENAMES: dict[str, tuple[str, str, str, str]] = {
    # old_name -> (new_name, code, module, description)
    "smart_text": (
        "smart_str",
        "DJA002",
        "django.utils.encoding",
        "`django.utils.encoding.smart_text` was removed; use `smart_str`.",
    ),
    "force_text": (
        "force_str",
        "DJA002",
        "django.utils.encoding",
        "`django.utils.encoding.force_text` was removed; use `force_str`.",
    ),
    "ugettext": (
        "gettext",
        "DJA003",
        "django.utils.translation",
        "`django.utils.translation.ugettext` was removed; use `gettext`.",
    ),
    "ugettext_lazy": (
        "gettext_lazy",
        "DJA003",
        "django.utils.translation",
        "`django.utils.translation.ugettext_lazy` was removed; use `gettext_lazy`.",
    ),
    "ugettext_noop": (
        "gettext_noop",
        "DJA003",
        "django.utils.translation",
        "`django.utils.translation.ugettext_noop` was removed; use `gettext_noop`.",
    ),
}


@dataclass
class _DjangoPlugin:
    name: str = PLUGIN_NAME
    targets: tuple[str, ...] = TARGET_DISTS

    def matches(self, context: PluginContext) -> bool:
        if context.target.name.lower() not in self.targets:
            return False
        return _targets_version_ge(context.target, "5.0")

    def scan(self, context: PluginContext) -> list[Issue]:
        wrapper = MetadataWrapper(context.module, unsafe_skip_copy=True)
        positions = wrapper.resolve(PositionProvider)
        visitor = _DjangoScanVisitor(positions=positions, file=context.file)
        wrapper.visit(visitor)
        return visitor.issues

    def repair(self, context: PluginContext, issues: list[Issue]) -> cst.Module:
        if not issues:
            return context.module
        renamed_locally = {
            i.context["old"]: i.context["new"]
            for i in issues
            if i.code in {"DJA002", "DJA003"} and "old" in i.context
        }
        if not renamed_locally:
            return context.module
        return context.module.visit(_DjangoRenameTransformer(renamed_locally))


# ---------------------------------------------------------------------------
# Scan visitor
# ---------------------------------------------------------------------------


class _DjangoScanVisitor(cst.CSTVisitor):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, positions: dict[cst.CSTNode, object], file: Path) -> None:
        super().__init__()
        self._positions = positions
        self._file = file
        # Names that were imported from the affected django module in this
        # file. Only these are eligible for the DJA002/DJA003 rename, so
        # an unrelated local ``smart_text`` function is left alone.
        self._eligible_names: set[str] = set()
        self.issues: list[Issue] = []

    # DJA001 / DJA002 / DJA003 — track imports first so the call-site
    # visitor can decide whether to flag a bare name.
    def visit_ImportFrom(self, node: cst.ImportFrom) -> None:
        if node.module is None or isinstance(node.names, cst.ImportStar):
            return
        module = _dotted(node.module)

        # DJA001 — ``from django.utils.timezone import utc``.
        if module == "django.utils.timezone":
            for alias in node.names:
                if isinstance(alias.name, cst.Name) and alias.name.value == "utc":
                    line, col = _pos(self._positions, node)
                    self.issues.append(
                        Issue(
                            plugin=PLUGIN_NAME,
                            code="DJA001",
                            message=(
                                "`django.utils.timezone.utc` was removed in Django 5.0; "
                                "use `datetime.timezone.utc` instead."
                            ),
                            file=self._file,
                            line=line,
                            column=col,
                            severity=Severity.ERROR,
                            fix=Fix(
                                description="Replace with `datetime.timezone.utc`",
                                confidence=0.6,
                                safe=False,
                            ),
                            context={},
                        )
                    )
                    break

        # DJA002 / DJA003 — names that were renamed.
        for alias in node.names:
            if not isinstance(alias.name, cst.Name):
                continue
            name = alias.name.value
            spec = _NAME_RENAMES.get(name)
            if spec is None or spec[2] != module:
                continue
            new_name, code, _, desc = spec
            self._eligible_names.add(name)
            line, col = _pos(self._positions, node)
            self.issues.append(
                Issue(
                    plugin=PLUGIN_NAME,
                    code=code,
                    message=desc,
                    file=self._file,
                    line=line,
                    column=col,
                    severity=Severity.ERROR,
                    fix=Fix(
                        description=f"Rename `{name}` to `{new_name}`",
                        confidence=1.0,
                        safe=True,
                    ),
                    context={"old": name, "new": new_name},
                )
            )

    # DJA001 — also catch the fully-qualified ``django.utils.timezone.utc``.
    def visit_Attribute(self, node: cst.Attribute) -> None:
        if _dotted(node) == "django.utils.timezone.utc":
            line, col = _pos(self._positions, node)
            self.issues.append(
                Issue(
                    plugin=PLUGIN_NAME,
                    code="DJA001",
                    message=(
                        "`django.utils.timezone.utc` was removed in Django 5.0; "
                        "use `datetime.timezone.utc` instead."
                    ),
                    file=self._file,
                    line=line,
                    column=col,
                    severity=Severity.ERROR,
                    fix=Fix(
                        description="Replace with `datetime.timezone.utc`",
                        confidence=0.6,
                        safe=False,
                    ),
                    context={},
                )
            )

    # DJA004 — ``class Meta: index_together = (...)`` inside a model body.
    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        if node.name.value != "Meta":
            return
        for stmt in node.body.body:
            if not isinstance(stmt, cst.SimpleStatementLine):
                continue
            for small in stmt.body:
                if not isinstance(small, cst.Assign):
                    continue
                for tgt in small.targets:
                    if isinstance(tgt.target, cst.Name) and tgt.target.value == "index_together":
                        line, col = _pos(self._positions, small)
                        self.issues.append(
                            Issue(
                                plugin=PLUGIN_NAME,
                                code="DJA004",
                                message=(
                                    "`Meta.index_together` is deprecated; use `indexes` "
                                    "with `models.Index(fields=...)` (Django 5.1 removes it)."
                                ),
                                file=self._file,
                                line=line,
                                column=col,
                                severity=Severity.WARNING,
                                fix=Fix(
                                    description="Migrate to `indexes = [models.Index(fields=[...])]`",
                                    confidence=0.4,
                                    safe=False,
                                ),
                                context={},
                            )
                        )


# ---------------------------------------------------------------------------
# Codemod transformer (DJA002 + DJA003)
# ---------------------------------------------------------------------------


class _DjangoRenameTransformer(cst.CSTTransformer):
    """Rewrite both ``from ... import OLD`` aliases and bare-name uses."""

    def __init__(self, renames: dict[str, str]) -> None:
        super().__init__()
        self._renames = renames

    def leave_ImportAlias(
        self, original_node: cst.ImportAlias, updated_node: cst.ImportAlias
    ) -> cst.ImportAlias:
        if not isinstance(updated_node.name, cst.Name):
            return updated_node
        new = self._renames.get(updated_node.name.value)
        if new is None:
            return updated_node
        return updated_node.with_changes(name=cst.Name(new))

    def leave_Name(self, original_node: cst.Name, updated_node: cst.Name) -> cst.BaseExpression:
        new = self._renames.get(updated_node.value)
        if new is None:
            return updated_node
        return cst.Name(new)

    def leave_Attribute(
        self, original_node: cst.Attribute, updated_node: cst.Attribute
    ) -> cst.BaseExpression:
        # ``leave_Name`` rewrites every Name node, including the ``attr`` of
        # an Attribute (e.g. ``obj.smart_text``). For attribute access we
        # cannot tell statically whether the receiver is Django, so restore
        # the original attribute name and let DJA0xx flag it separately if
        # the receiver was actually ``django.utils.encoding``.
        if original_node.attr.value != updated_node.attr.value:
            return updated_node.with_changes(attr=original_node.attr)
        return updated_node


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dotted(node: cst.BaseExpression) -> str:
    if isinstance(node, cst.Name):
        return node.value
    if isinstance(node, cst.Attribute):
        left = _dotted(node.value)
        return f"{left}.{node.attr.value}"
    return ""


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
    for s in spec:
        if s.operator in (">=", "==", "~=") and Version(s.version) >= target:
            return True
    return False


plugin = _DjangoPlugin()
