"""Detect imports that point to symbols missing from the installed package.

This module powers the ``pycomprepair discover`` command. Given a parsed
Python file and one or more :class:`~pycomprepair.discovery.APIIndex`
instances, it walks every ``from X import Y`` / ``import X.Y`` statement and
emits a :class:`DSC001 <pycomprepair.core.issue.Issue>` issue whenever the
referenced symbol is not present in the indexed API.

The check is intentionally narrow: it only fires for imports whose root
package is one of the indexes the caller supplied, so unrelated dependencies
are never flagged.
"""

from __future__ import annotations

from pathlib import Path

import libcst as cst
from libcst.metadata import CodeRange, MetadataWrapper, PositionProvider

from pycomprepair.core.issue import Issue, Severity
from pycomprepair.discovery.api_index import APIIndex

DSC001 = "DSC001"
"""Imported symbol not present in the installed package."""


def _module_dotted_path(node: cst.Attribute | cst.Name) -> str:
    """Render a ``module.sub.sub`` CST node as a dotted string."""
    parts: list[str] = []
    current: cst.BaseExpression = node
    while isinstance(current, cst.Attribute):
        parts.append(current.attr.value)
        current = current.value
    if isinstance(current, cst.Name):
        parts.append(current.value)
    return ".".join(reversed(parts))


class _ImportVisitor(cst.CSTVisitor):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, indexes: dict[str, APIIndex], file: Path, source: str) -> None:
        super().__init__()
        self._indexes = indexes
        self._file = file
        self._source = source
        self.issues: list[Issue] = []

    def _root_package(self, dotted: str) -> str:
        return dotted.partition(".")[0]

    def _index_for(self, dotted: str) -> APIIndex | None:
        return self._indexes.get(self._root_package(dotted))

    def _pos(self, node: cst.CSTNode) -> tuple[int, int]:
        meta = self.get_metadata(PositionProvider, node)
        if isinstance(meta, CodeRange):
            return meta.start.line, meta.start.column
        return 1, 0

    def visit_ImportFrom(self, node: cst.ImportFrom) -> None:
        if node.module is None or node.relative:
            # ``from . import X`` is project-local; nothing to validate.
            return
        module = _module_dotted_path(node.module)
        index = self._index_for(module)
        if index is None or not index.belongs_to(module):
            return
        names = node.names
        if isinstance(names, cst.ImportStar):
            return
        for alias in names:
            symbol = alias.name.value if isinstance(alias.name, cst.Name) else None
            if symbol is None:
                continue
            qualified = f"{module}.{symbol}"
            if index.has(qualified):
                continue
            line, col = self._pos(alias)
            self.issues.append(
                Issue(
                    plugin="discover",
                    code=DSC001,
                    message=(
                        f"`{qualified}` is not present in the installed "
                        f"`{index.package}`. The symbol was likely removed "
                        "or renamed in this version."
                    ),
                    file=self._file,
                    line=line,
                    column=col,
                    severity=Severity.ERROR,
                    context={"package": index.package, "symbol": qualified},
                )
            )

    def visit_Import(self, node: cst.Import) -> None:
        for alias in node.names:
            name_node = alias.name
            if not isinstance(name_node, (cst.Attribute, cst.Name)):
                continue
            dotted = _module_dotted_path(name_node)
            index = self._index_for(dotted)
            if index is None or not index.belongs_to(dotted):
                continue
            # For ``import foo.bar`` we only check sub-modules; the root
            # package is always present if griffe loaded it.
            if dotted == index.package:
                continue
            if index.has(dotted):
                continue
            line, col = self._pos(alias)
            self.issues.append(
                Issue(
                    plugin="discover",
                    code=DSC001,
                    message=(
                        f"Module `{dotted}` is not present in the installed "
                        f"`{index.package}`."
                    ),
                    file=self._file,
                    line=line,
                    column=col,
                    severity=Severity.ERROR,
                    context={"package": index.package, "symbol": dotted},
                )
            )


def scan_missing_imports(
    file: Path,
    source: str,
    indexes: dict[str, APIIndex],
) -> list[Issue]:
    """Return :class:`Issue` objects for every removed/renamed import in ``source``.

    Parameters
    ----------
    file:
        Path used to populate :attr:`Issue.file` (no I/O is performed here).
    source:
        The raw Python source. Files with syntax errors silently yield an
        empty list — the caller is expected to surface parse failures via
        the regular scan pipeline.
    indexes:
        Mapping of *root package name* to its :class:`APIIndex`. Only
        imports whose root matches one of the keys are validated.
    """
    if not indexes:
        return []
    try:
        module = cst.parse_module(source)
    except cst.ParserSyntaxError:
        return []
    wrapper = MetadataWrapper(module)
    visitor = _ImportVisitor(indexes, file, source)
    wrapper.visit(visitor)
    return visitor.issues
