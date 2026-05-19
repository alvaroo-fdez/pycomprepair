"""Common libcst utilities shared by multiple plugins."""

from __future__ import annotations

from collections.abc import Iterable

import libcst as cst


def position_of(module: cst.Module, node: cst.CSTNode) -> tuple[int, int]:
    """Return the ``(line, column)`` of ``node`` within ``module``.

    Uses libcst's metadata wrapper. Returns ``(1, 0)`` when the node is not
    found (typically because the caller did not use a metadata wrapper).
    """
    from libcst.metadata import MetadataWrapper, PositionProvider

    wrapper = MetadataWrapper(module, unsafe_skip_copy=True)
    positions = wrapper.resolve(PositionProvider)
    pos = positions.get(node)
    if pos is None:
        return (1, 0)
    return (pos.start.line, pos.start.column)


def is_name(node: cst.BaseExpression, name: str) -> bool:
    """Return ``True`` if ``node`` is exactly ``Name(name)``."""
    return isinstance(node, cst.Name) and node.value == name


def attribute_chain(node: cst.BaseExpression) -> list[str] | None:
    """Return the dotted-name chain of an attribute expression.

    For ``a.b.c`` returns ``["a", "b", "c"]``; returns ``None`` if the
    expression is not a plain attribute chain.
    """
    parts: list[str] = []
    current: cst.BaseExpression = node
    while isinstance(current, cst.Attribute):
        parts.append(current.attr.value)
        current = current.value
    if not isinstance(current, cst.Name):
        return None
    parts.append(current.value)
    parts.reverse()
    return parts


def has_import_from(module: cst.Module, module_name: str, names: Iterable[str]) -> bool:
    """Return ``True`` if ``module`` contains ``from <module_name> import <name>``
    for any of ``names``.
    """
    wanted = set(names)
    for stmt in module.body:
        if not isinstance(stmt, cst.SimpleStatementLine):
            continue
        for small in stmt.body:
            if not isinstance(small, cst.ImportFrom) or small.module is None:
                continue
            mod = _dotted(small.module)
            if mod != module_name:
                continue
            if isinstance(small.names, cst.ImportStar):
                return True
            for alias in small.names:
                if isinstance(alias.name, cst.Name) and alias.name.value in wanted:
                    return True
    return False


def _dotted(node: cst.BaseExpression) -> str:
    """Render a ``Name``/``Attribute`` chain as a dotted string."""
    if isinstance(node, cst.Name):
        return node.value
    if isinstance(node, cst.Attribute):
        left = _dotted(node.value)
        return f"{left}.{node.attr.value}"
    return ""


def rename_attribute_call(
    call: cst.Call, new_attr: str
) -> cst.Call:
    """Rewrite ``obj.<old>(...)`` to ``obj.<new>(...)`` preserving arguments."""
    func = call.func
    if not isinstance(func, cst.Attribute):
        return call
    return call.with_changes(func=func.with_changes(attr=cst.Name(new_attr)))
