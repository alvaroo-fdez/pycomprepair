"""Build a flat index of public symbols for an installed Python package.

This module wraps :mod:`griffe` so the rest of PyCompatRepair can ask simple
questions like *"does ``django.utils.encoding.smart_text`` exist in the
installed Django?"* without dealing with griffe's object model directly.

The index is intentionally a frozen set of fully-qualified dotted names. That
representation is cheap to share between plugins, easy to serialise for
debugging, and matches exactly what user code writes in ``from X import Y``.
In addition to the set of paths, the index keeps a ``kinds`` mapping that
records whether each symbol is a module, class, function, attribute or alias.
The attribute-access check (``DSC002``) uses that to decide whether it can
keep walking a dotted chain: only modules and classes have a known public
surface; functions can return anything at runtime.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

# Symbol kinds we know how to introspect further. Anything outside this set
# (functions, attributes, unknown) is treated as opaque: ``foo.bar`` where
# ``foo`` is a function is left alone because its result type is unknown.
CONTAINER_KINDS: frozenset[str] = frozenset({"module", "class"})


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
    kinds: dict[str, str] = field(default_factory=dict)

    def has(self, qualified: str) -> bool:
        """Return ``True`` when ``qualified`` is a known public path."""
        return qualified in self.symbols

    def has_module_attr(self, module: str, attr: str) -> bool:
        """Return ``True`` when ``module.attr`` is a known public path."""
        return f"{module}.{attr}" in self.symbols

    def belongs_to(self, module: str) -> bool:
        """Return ``True`` when ``module`` is (or lives inside) this package."""
        return module == self.package or module.startswith(self.package + ".")

    def kind_of(self, qualified: str) -> str | None:
        """Return the kind of ``qualified`` or ``None`` when unknown."""
        return self.kinds.get(qualified)

    def is_container(self, qualified: str) -> bool:
        """Return ``True`` when ``qualified`` exposes a knowable public surface.

        Modules and classes are containers because griffe enumerates their
        members; functions and attributes can return arbitrary objects at
        runtime so we cannot reason about their dotted children.
        """
        return self.kinds.get(qualified) in CONTAINER_KINDS


def _is_private(name: str) -> bool:
    """Treat ``_foo`` as private but keep ``__init__`` / ``__all__``."""
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def _kind_of(obj: Any) -> str:
    """Return the lowercase griffe kind of ``obj`` (``"module"``, ``"class"``...)."""
    k = getattr(obj, "kind", None)
    if k is None:
        return "unknown"
    v = getattr(k, "value", None)
    if v is None:
        return str(k).lower()
    return str(v).lower()


def _resolved_kind(obj: Any) -> str:
    """Like :func:`_kind_of`, but follow griffe aliases one hop to their target.

    Re-exports (``from .sub import X``) are recorded by griffe as ``Alias``
    nodes. For attribute-chain analysis we care about the *target* kind: a
    re-exported module should still be walkable. Failing to resolve is
    cheap and falls back to ``"alias"``.
    """
    kind = _kind_of(obj)
    if kind != "alias":
        return kind
    try:
        target = obj.final_target
    except Exception:
        return kind
    target_kind = _kind_of(target)
    return target_kind if target_kind != "unknown" else kind


def _collect(root: Any) -> tuple[frozenset[str], dict[str, str]]:
    """Walk a griffe ``Module`` and collect public paths plus their kinds."""
    symbols: set[str] = set()
    kinds: dict[str, str] = {}
    visited: set[int] = set()

    def record(obj: Any) -> None:
        path = getattr(obj, "path", None)
        if not path or path in symbols:
            return
        symbols.add(path)
        kinds[path] = _resolved_kind(obj)

    def walk(obj: Any) -> None:
        if id(obj) in visited:
            return
        visited.add(id(obj))
        record(obj)

        members = getattr(obj, "members", None)
        if not members:
            return

        for child in members.values():
            name = getattr(child, "name", "")
            if _is_private(name):
                continue
            record(child)
            # Aliases re-export an external object; do not recurse into them
            # to keep the walk bounded and avoid infinite loops on circular
            # re-exports.
            if getattr(child, "is_alias", False):
                continue
            walk(child)

    walk(root)
    # The root module itself is registered as a container so the attribute
    # check can walk into it even when griffe did not surface a ``path``
    # entry for the root object during ``record``.
    root_path = getattr(root, "path", None)
    if root_path:
        symbols.add(root_path)
        kinds.setdefault(root_path, "module")
    return frozenset(symbols), kinds


def _collect_symbols(root: Any) -> frozenset[str]:
    """Backwards-compatible wrapper kept for older callers and tests."""
    symbols, _ = _collect(root)
    return symbols


@lru_cache(maxsize=32)
def load_api(package: str) -> APIIndex:
    """Load ``package`` via griffe and return an :class:`APIIndex`.

    The result is memoised per process so repeated CLI invocations (and
    test runs) only pay the parsing cost once. ``allow_inspection=True``
    lets griffe fall back to runtime introspection for C extensions and
    other modules it cannot parse statically.

    A disk cache (see :mod:`pycomprepair.discovery.cache`) is consulted
    before delegating to griffe. The cache key is ``(package, installed
    version)``, so an upgrade automatically invalidates the snapshot. Set
    ``PYCOMPREPAIR_DISABLE_CACHE=1`` in the environment to bypass it.
    """
    # Late import to avoid a circular dependency on package load.
    from pycomprepair.discovery import cache as _cache

    use_cache = os.environ.get("PYCOMPREPAIR_DISABLE_CACHE", "") not in {"1", "true", "yes"}

    if use_cache:
        cached = _cache.read_cached(package)
        if cached is not None:
            return cached

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

    symbols, kinds = _collect(module)
    index = APIIndex(package=package, symbols=symbols, kinds=kinds)

    if use_cache:
        _cache.write_cached(index)

    return index
