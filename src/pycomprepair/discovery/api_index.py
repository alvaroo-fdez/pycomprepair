"""Build a flat index of public symbols for an installed Python package.

This module wraps :mod:`griffe` so the rest of PyCompatRepair can ask simple
questions like *"does ``django.utils.encoding.smart_text`` exist in the
installed Django?"* without dealing with griffe's object model directly.

The index is intentionally a frozen set of fully-qualified dotted names. That
representation is cheap to share between plugins, easy to serialise for
debugging, and matches exactly what user code writes in ``from X import Y``.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any


class PackageNotInstalledError(RuntimeError):
    """Raised when griffe cannot locate the requested package on ``sys.path``."""


@dataclass(frozen=True)
class APIIndex:
    """Immutable view of a package's public API.

    ``symbols`` contains every public dotted path reachable from the package
    root, including classes, functions, attributes *and* re-exports
    (griffe aliases). Private members (names starting with a single
    underscore) are skipped; dunder members are kept because they form part
    of the documented protocol surface.
    """

    package: str
    symbols: frozenset[str]

    def has(self, qualified: str) -> bool:
        """Return ``True`` when ``qualified`` is a known public path."""
        return qualified in self.symbols

    def has_module_attr(self, module: str, attr: str) -> bool:
        """Return ``True`` when ``module.attr`` is a known public path."""
        return f"{module}.{attr}" in self.symbols

    def belongs_to(self, module: str) -> bool:
        """Return ``True`` when ``module`` is (or lives inside) this package."""
        return module == self.package or module.startswith(self.package + ".")


def _is_private(name: str) -> bool:
    """Treat ``_foo`` as private but keep ``__init__`` / ``__all__``."""
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def _collect_symbols(root: Any) -> frozenset[str]:
    """Walk a griffe ``Module`` and collect every public dotted path."""
    symbols: set[str] = set()
    visited: set[int] = set()

    def walk(obj: Any) -> None:
        if id(obj) in visited:
            return
        visited.add(id(obj))

        members = getattr(obj, "members", None)
        if not members:
            return

        for child in members.values():
            name = getattr(child, "name", "")
            if _is_private(name):
                continue
            path = getattr(child, "path", None)
            if path:
                symbols.add(path)
            # Aliases re-export an external object; do not recurse into them
            # to keep the walk bounded and avoid infinite loops on circular
            # re-exports.
            if getattr(child, "is_alias", False):
                continue
            walk(child)

    walk(root)
    return frozenset(symbols)


@lru_cache(maxsize=32)
def load_api(package: str) -> APIIndex:
    """Load ``package`` via griffe and return an :class:`APIIndex`.

    The result is memoised per process so repeated CLI invocations (and
    test runs) only pay the parsing cost once. ``allow_inspection=True``
    lets griffe fall back to runtime introspection for C extensions and
    other modules it cannot parse statically.
    """
    try:
        import griffe
    except ImportError as exc:  # pragma: no cover - griffe is a hard dep
        raise PackageNotInstalledError(
            "griffe is required for API discovery but is not installed"
        ) from exc

    try:
        module = griffe.load(package, allow_inspection=True)
    except Exception as exc:
        raise PackageNotInstalledError(
            f"Could not load package {package!r} via griffe: {exc}"
        ) from exc

    return APIIndex(package=package, symbols=_collect_symbols(module))
