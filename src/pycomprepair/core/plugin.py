"""Plugin protocol and registry.

A plugin targets a specific library/ecosystem (e.g. Pydantic) and provides:

* :meth:`Plugin.matches`: returns ``True`` for a given :class:`PluginContext`
  (typically by checking the requested target spec).
* :meth:`Plugin.scan`: emits :class:`Issue` objects for a parsed module.
* :meth:`Plugin.repair`: returns a transformed CST for a module, applying
  the codemods bound to the issues.

Plugins are discovered via the ``pycomprepair.plugins`` entry point group,
plus a built-in registry seeded by the package itself for easy testing.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from typing import Protocol, runtime_checkable

import libcst as cst
from packaging.requirements import Requirement

from pycomprepair.core.issue import Issue

ENTRY_POINT_GROUP = "pycomprepair.plugins"


@dataclass(frozen=True)
class PluginContext:
    """Context passed to plugins on every scan/repair invocation."""

    target: Requirement
    """Target requirement specifier, e.g. ``Requirement('pydantic>=2.0,<3.0')``."""

    file: Path
    """Path to the source file being analyzed."""

    source: str
    """Full source text. Plugins should prefer the parsed CST over re-parsing."""

    module: cst.Module
    """Parsed CST for the source file."""

    options: dict[str, str] = field(default_factory=dict)
    """Free-form plugin-specific options coming from configuration."""


@runtime_checkable
class Plugin(Protocol):
    """Protocol every plugin must implement."""

    name: str
    """Unique short identifier (e.g. ``pydantic``, ``fastapi``)."""

    targets: tuple[str, ...]
    """Distribution names this plugin handles (e.g. ``('pydantic',)``)."""

    def matches(self, context: PluginContext) -> bool:
        """Return ``True`` when this plugin should run for ``context``."""
        ...

    def scan(self, context: PluginContext) -> list[Issue]:
        """Return the list of incompatibilities detected in ``context``."""
        ...

    def repair(self, context: PluginContext, issues: list[Issue]) -> cst.Module:
        """Return a transformed module applying fixes for the given issues.

        Plugins must return ``context.module`` unchanged if no fix applies.
        """
        ...


class PluginRegistry:
    """In-memory registry of plugins.

    Plugins can be registered explicitly (useful for tests) or loaded from
    entry points via :meth:`load_entry_points`.
    """

    def __init__(self) -> None:
        self._plugins: dict[str, Plugin] = {}

    def register(self, plugin: Plugin) -> None:
        """Register a plugin, overwriting any previous one with the same name."""
        if not isinstance(plugin, Plugin):  # pragma: no cover - defensive
            raise TypeError(f"Object {plugin!r} does not implement the Plugin protocol")
        self._plugins[plugin.name] = plugin

    def unregister(self, name: str) -> None:
        self._plugins.pop(name, None)

    def all(self) -> list[Plugin]:
        return list(self._plugins.values())

    def get(self, name: str) -> Plugin | None:
        return self._plugins.get(name)

    def for_context(self, context: PluginContext) -> list[Plugin]:
        """Return plugins whose :meth:`Plugin.matches` returns ``True``."""
        return [p for p in self._plugins.values() if p.matches(context)]

    def load_entry_points(self) -> None:
        """Discover and register plugins exposed via ``pycomprepair.plugins``."""
        eps = _iter_entry_points(ENTRY_POINT_GROUP)
        for ep in eps:
            try:
                obj = ep.load()
            except Exception as exc:  # pragma: no cover - third-party failure
                print(
                    f"[pycomprepair] warning: failed to load plugin {ep.name!r}: {exc}",
                    file=sys.stderr,
                )
                continue
            plugin = obj() if callable(obj) and not isinstance(obj, Plugin) else obj
            if isinstance(plugin, Plugin):
                self.register(plugin)


def _iter_entry_points(group: str) -> list[metadata.EntryPoint]:
    """Compatibility shim for ``importlib.metadata.entry_points``."""
    try:
        eps = metadata.entry_points(group=group)
    except TypeError:  # pragma: no cover - very old Python
        eps = metadata.entry_points().get(group, [])  # type: ignore[attr-defined]
    return list(eps)


_REGISTRY: PluginRegistry | None = None


def get_registry() -> PluginRegistry:
    """Return the lazily-initialized global plugin registry."""
    global _REGISTRY
    if _REGISTRY is None:
        registry = PluginRegistry()
        registry.load_entry_points()
        _REGISTRY = registry
    return _REGISTRY


def reset_registry() -> None:
    """Reset the global registry. Intended for tests."""
    global _REGISTRY
    _REGISTRY = None
