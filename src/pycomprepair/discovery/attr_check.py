"""Detect attribute accesses that target symbols missing from the installed API.

While :mod:`pycomprepair.discovery.import_check` (``DSC001``) only validates
``from pkg import X`` statements, real upgrade pain usually comes from call
sites that use a name *after* it was imported::

    import numpy as np

    arr.astype(np.float)            # DSC002: numpy.float was removed in 2.0
    df.append(other)                # not flagged here (df is local)
    django.utils.timezone.utc       # DSC002: removed in Django 5.0

This module performs a lightweight two-pass analysis:

1. **Bindings pass.** Module-level ``import`` statements are recorded as
   ``{local_name: qualified_path}``. Names that are *also* reassigned, used
   as function parameters or rebound inside ``for``/``with`` are marked as
   shadowed so we don't risk false positives.
2. **Attribute pass.** Every outermost :class:`libcst.Attribute` whose
   leftmost identifier resolves to a tracked import is rebuilt as a dotted
   path and validated against the appropriate :class:`APIIndex`. Walking
   stops as soon as the chain reaches a non-container symbol (functions,
   plain attributes) because runtime resolution makes anything beyond that
   point unreasoned-about.

The analysis is intentionally *conservative*: when in doubt we skip,
preferring zero false positives over exhaustive coverage. This keeps the
``DSC002`` signal trustworthy in CI gates.
"""

from __future__ import annotations

from pathlib import Path

import libcst as cst
from libcst.metadata import CodeRange, MetadataWrapper, PositionProvider

from pycomprepair.core.issue import Fix, Issue, Severity
from pycomprepair.discovery.api_index import APIIndex
from pycomprepair.discovery.known_fixes import KNOWN_FIXES
from pycomprepair.discovery.suggest import suggest_replacements

DSC002 = "DSC002"
"""Attribute access targets a symbol that no longer exists in the installed package."""


def _dotted_path(node: cst.Attribute | cst.Name) -> str:
    """Render a ``module.sub.sub`` CST node as a dotted string."""
    parts: list[str] = []
    current: cst.BaseExpression = node
    while isinstance(current, cst.Attribute):
        parts.append(current.attr.value)
        current = current.value
    if isinstance(current, cst.Name):
        parts.append(current.value)
    return ".".join(reversed(parts))


class _BindingCollector(cst.CSTVisitor):
    """First pass: collect top-level imports and shadowed names."""

    def __init__(self) -> None:
        super().__init__()
        # local-name -> fully qualified dotted path (a module or a symbol).
        self.imports: dict[str, str] = {}
        # Names that are rebound somewhere in the module (params, assigns,
        # for-targets, ``as`` clauses, class/function names). Such names are
        # excluded from the attribute pass to avoid false positives.
        self.shadowed: set[str] = set()

    # ----- imports -----

    def visit_ImportFrom(self, node: cst.ImportFrom) -> None:
        if node.relative or node.module is None:
            return
        module = _dotted_path(node.module)
        if isinstance(node.names, cst.ImportStar):
            return
        for alias in node.names:
            if not isinstance(alias.name, cst.Name):
                continue
            symbol = alias.name.value
            local = (
                alias.asname.name.value
                if alias.asname is not None and isinstance(alias.asname.name, cst.Name)
                else symbol
            )
            self.imports[local] = f"{module}.{symbol}"

    def visit_Import(self, node: cst.Import) -> None:
        for alias in node.names:
            name_node = alias.name
            if not isinstance(name_node, (cst.Attribute, cst.Name)):
                continue
            full = _dotted_path(name_node)
            if alias.asname is not None and isinstance(alias.asname.name, cst.Name):
                # ``import numpy.random as nr`` binds ``nr`` to numpy.random.
                self.imports[alias.asname.name.value] = full
            else:
                # ``import numpy.random`` binds the top-level name ``numpy``
                # to the root package (``numpy.random`` is reachable via
                # attribute access on that name).
                root_local = full.partition(".")[0]
                self.imports.setdefault(root_local, root_local)

    # ----- bindings that should mask an import -----

    def visit_Assign(self, node: cst.Assign) -> None:
        for target in node.targets:
            self._record_target(target.target)

    def visit_AugAssign(self, node: cst.AugAssign) -> None:
        self._record_target(node.target)

    def visit_AnnAssign(self, node: cst.AnnAssign) -> None:
        self._record_target(node.target)

    def visit_For(self, node: cst.For) -> None:
        self._record_target(node.target)

    def visit_With(self, node: cst.With) -> None:
        for item in node.items:
            if item.asname is not None:
                self._record_target(item.asname.name)

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
        self.shadowed.add(node.name.value)
        params = node.params
        for group in (
            params.params,
            params.kwonly_params,
            params.posonly_params,
        ):
            for param in group:
                self.shadowed.add(param.name.value)
        if params.star_arg is not None and isinstance(params.star_arg, cst.Param):
            self.shadowed.add(params.star_arg.name.value)
        if params.star_kwarg is not None:
            self.shadowed.add(params.star_kwarg.name.value)

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        self.shadowed.add(node.name.value)

    def _record_target(self, target: cst.BaseExpression) -> None:
        if isinstance(target, cst.Name):
            self.shadowed.add(target.value)
        elif isinstance(target, (cst.Tuple, cst.List)):
            for element in target.elements:
                if isinstance(element, cst.Element):
                    self._record_target(element.value)


class _AttrVisitor(cst.CSTVisitor):
    """Second pass: validate attribute chains rooted in tracked imports."""

    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(
        self,
        indexes: dict[str, APIIndex],
        imports: dict[str, str],
        shadowed: set[str],
        file: Path,
        suggest: bool = False,
    ) -> None:
        super().__init__()
        self._indexes = indexes
        self._imports = imports
        self._shadowed = shadowed
        self._file = file
        self._suggest = suggest
        self._processed: set[int] = set()
        self.issues: list[Issue] = []

    def _pos(self, node: cst.CSTNode) -> tuple[int, int]:
        meta = self.get_metadata(PositionProvider, node)
        if isinstance(meta, CodeRange):
            return meta.start.line, meta.start.column
        return 1, 0

    def visit_Attribute(self, node: cst.Attribute) -> None:
        # An outer Attribute walks the whole chain in one go and marks every
        # nested Attribute so we never report the same chain twice.
        if id(node) in self._processed:
            return

        chain: list[str] = []
        current: cst.BaseExpression = node
        while isinstance(current, cst.Attribute):
            self._processed.add(id(current))
            chain.append(current.attr.value)
            current = current.value
        if not isinstance(current, cst.Name):
            return  # chain rooted on a call/subscript/etc.; we can't reason.

        base_name = current.value
        if base_name in self._shadowed:
            return
        qualified_base = self._imports.get(base_name)
        if qualified_base is None:
            return

        root = qualified_base.partition(".")[0]
        index = self._indexes.get(root)
        if index is None or not index.belongs_to(qualified_base):
            return

        # If the base itself is not in the index, the import is already
        # flagged by ``DSC001`` -- don't double-report.
        if qualified_base != index.package and not index.has(qualified_base):
            return
        # The chain is built leaves-first; reverse it to walk root -> leaf.
        chain.reverse()

        current_path = qualified_base
        for attr in chain:
            if not index.is_container(current_path):
                # We've reached an opaque object (function/attribute); we
                # cannot reason about further attribute accesses.
                return
            next_path = f"{current_path}.{attr}"
            if not index.has(next_path):
                line, col = self._pos(node)
                known = KNOWN_FIXES.get(next_path)
                fix: Fix | None
                if known is not None:
                    fix = Fix(
                        description=known.description,
                        confidence=known.confidence,
                        safe=known.safe,
                    )
                elif self._suggest:
                    matches = suggest_replacements(next_path, index)
                    if matches:
                        top = matches[0]
                        # Fuzzy guesses are never applied automatically: they
                        # exist to point the developer at the most likely new
                        # name. ``safe=False`` keeps ``discover --fix`` from
                        # ever rewriting them, while the confidence carries
                        # the underlying similarity ratio.
                        fix = Fix(
                            description=(
                                f"Did you mean `{top.path}`? "
                                f"(similarity {top.score:.2f})"
                            ),
                            confidence=top.score,
                            safe=False,
                        )
                    else:
                        fix = None
                else:
                    fix = None
                self.issues.append(
                    Issue(
                        plugin="discover",
                        code=DSC002,
                        message=(
                            f"`{next_path}` is not present in the installed "
                            f"`{index.package}`. The attribute was likely "
                            "removed or renamed in this version."
                        ),
                        file=self._file,
                        line=line,
                        column=col,
                        severity=Severity.ERROR,
                        fix=fix,
                        context={"package": index.package, "symbol": next_path},
                    )
                )
                return
            current_path = next_path


def scan_missing_attributes(
    file: Path,
    source: str,
    indexes: dict[str, APIIndex],
    *,
    suggest: bool = False,
) -> list[Issue]:
    """Return :class:`Issue` objects for attribute chains that target removed symbols.

    Parameters
    ----------
    file:
        Path used to populate :attr:`Issue.file`. No I/O is performed here.
    source:
        Raw Python source. Syntax errors yield an empty list -- they are
        surfaced by the regular scan pipeline.
    indexes:
        Mapping of *root package name* to its :class:`APIIndex`. Only
        attribute chains whose leftmost binding belongs to a listed package
        are validated.
    suggest:
        When ``True``, attach a fuzzy-match suggestion (``Did you mean ...``)
        to issues that are not covered by
        :data:`pycomprepair.discovery.known_fixes.KNOWN_FIXES`. Suggestions
        are always marked ``safe=False`` so ``discover --fix`` never auto-
        applies them.
    """
    if not indexes:
        return []
    try:
        module = cst.parse_module(source)
    except cst.ParserSyntaxError:
        return []

    collector = _BindingCollector()
    module.visit(collector)
    if not collector.imports:
        return []

    wrapper = MetadataWrapper(module)
    visitor = _AttrVisitor(
        indexes, collector.imports, collector.shadowed, file, suggest=suggest
    )
    wrapper.visit(visitor)
    return visitor.issues
