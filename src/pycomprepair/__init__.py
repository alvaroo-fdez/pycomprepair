"""PyCompatRepair: semantic upgrade assistant and compatibility codemods.

Public API:
    - :class:`Issue`, :class:`Severity`: data model for detected incompatibilities.
    - :class:`Plugin`: base class for ecosystem-specific plugins.
    - :func:`scan_path`, :func:`repair_path`: high-level entry points.
"""

from __future__ import annotations

from pycomprepair.core.engine import repair_path, scan_path
from pycomprepair.core.issue import Fix, Issue, Severity
from pycomprepair.core.plugin import Plugin, PluginContext, get_registry

__all__ = [
    "Fix",
    "Issue",
    "Plugin",
    "PluginContext",
    "Severity",
    "get_registry",
    "repair_path",
    "scan_path",
]

__version__ = "0.1.0"
