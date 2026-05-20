"""Rewrite ``DSC002`` hits in place using :data:`KNOWN_FIXES`.

This module is the engine behind ``pycomprepair discover --fix``. It walks
the same import bindings as :mod:`pycomprepair.discovery.attr_check`, but
instead of emitting :class:`Issue` objects it produces a transformed
:class:`libcst.Module` where every attribute chain that matches a
:data:`KNOWN_FIXES` entry has been substituted.

Two replacement modes are supported (see
:mod:`pycomprepair.discovery.known_fixes`):

* :data:`RENAME_ATTR` rewrites only the leaf attribute, preserving the
  user's import alias (``np.NaN`` -> ``np.nan``).
* :data:`REPLACE_EXPRESSION` substitutes the whole dotted chain with a
  parsed expression (``np.float`` -> ``float``). Cross-package rewrites
  carry ``safe=False`` so they only run when the caller opts in.

The rewriter is intentionally conservative: any name shadowed in the
file (assignments, function params, ``for`` targets, ``with as ...``,
class/function definitions) is left alone, mirroring the detection pass.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import libcst as cst

from pycomprepair.discovery.attr_check import _BindingCollector
from pycomprepair.discovery.known_fixes import (
    KNOWN_FIXES,
    RENAME_ATTR,
    REPLACE_EXPRESSION,
    KnownFix,
)


@dataclass(frozen=True)
class FixResult:
    """Outcome of rewriting a single file."""

    file: Path
    original_source: str
    new_source: str
    applied: int

    @property
    def changed(self) -> bool:
        return self.original_source != self.new_source


def rewrite_source(
    source: str,
    *,
    allow_unsafe: bool = False,
) -> tuple[str, int]:
    """Return ``(new_source, applied_count)`` for the given Python source.

    The function is pure: no filesystem access, no logging. Syntax errors
    yield ``(source, 0)`` so callers can handle them uniformly.

    ``allow_unsafe`` mirrors ``repair --unsafe-fixes``: cross-package
    rewrites (``safe=False``) only execute when the caller opts in.
    """
    try:
        module = cst.parse_module(source)
    except cst.ParserSyntaxError:
        return source, 0

    collector = _BindingCollector()
    module.visit(collector)
    if not collector.imports:
        return source, 0

    transformer = _DSC002Transformer(
        imports=collector.imports,
        shadowed=collector.shadowed,
        allow_unsafe=allow_unsafe,
    )
    rewritten = module.visit(transformer)
    return rewritten.code, transformer.applied


def rewrite_file(file: Path, *, allow_unsafe: bool = False) -> FixResult:
    """Read ``file``, rewrite, and return a :class:`FixResult`.

    Writing back to disk is the caller's responsibility -- this keeps the
    function dry-run friendly.
    """
    source = file.read_text(encoding="utf-8")
    new_source, applied = rewrite_source(source, allow_unsafe=allow_unsafe)
    return FixResult(
        file=file,
        original_source=source,
        new_source=new_source,
        applied=applied,
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


class _DSC002Transformer(cst.CSTTransformer):
    """Rewrite outermost :class:`libcst.Attribute` chains matching KNOWN_FIXES.

    ``leave_Attribute`` is called bottom-up, so inner Attributes are visited
    first. Each visit attempts to match the *full* dotted chain rooted at
    the receiving Attribute. Inner chains that do not match (e.g.
    ``django.utils`` while the user wrote ``django.utils.timezone.utc``)
    return unchanged, and the outermost Attribute is eventually matched.
    """

    def __init__(
        self,
        imports: dict[str, str],
        shadowed: set[str],
        allow_unsafe: bool,
    ) -> None:
        super().__init__()
        self._imports = imports
        self._shadowed = shadowed
        self._allow_unsafe = allow_unsafe
        self.applied = 0

    def leave_Attribute(
        self, original_node: cst.Attribute, updated_node: cst.Attribute
    ) -> cst.BaseExpression:
        # Reconstruct the dotted chain from ``original_node`` so we can
        # match against KNOWN_FIXES (which is keyed by the user-facing
        # qualified path, not the libcst object identity).
        chain: list[str] = []
        current: cst.BaseExpression = original_node
        while isinstance(current, cst.Attribute):
            chain.append(current.attr.value)
            current = current.value
        if not isinstance(current, cst.Name):
            return updated_node

        base_name = current.value
        if base_name in self._shadowed:
            return updated_node
        qualified_base = self._imports.get(base_name)
        if qualified_base is None:
            return updated_node

        chain.reverse()
        full_path = ".".join([qualified_base, *chain])
        known: KnownFix | None = KNOWN_FIXES.get(full_path)
        if known is None:
            return updated_node
        if not known.safe and not self._allow_unsafe:
            return updated_node

        if known.mode == RENAME_ATTR:
            self.applied += 1
            return updated_node.with_changes(attr=cst.Name(known.value))

        if known.mode == REPLACE_EXPRESSION:
            try:
                replacement = cst.parse_expression(known.value)
            except cst.ParserSyntaxError:
                return updated_node
            self.applied += 1
            return replacement

        return updated_node
