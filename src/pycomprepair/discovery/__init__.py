"""Dynamic API discovery layer.

The :mod:`pycomprepair.discovery` package introspects the *installed* version
of a third-party library through `griffe`_ and turns it into a flat index of
qualified symbol names. Plugins (and the ``discover`` CLI command) use that
index to validate hand-written rename tables and to flag user code that
imports symbols which simply no longer exist in the target version.

The whole layer is optional: if griffe cannot load a package (because it is
not installed or fails to parse) callers receive a clear exception and can
degrade gracefully to the hardcoded plugin knowledge.

.. _griffe: https://mkdocstrings.github.io/griffe/
"""

from __future__ import annotations

from pycomprepair.discovery.api_index import (
    APIIndex,
    PackageNotInstalledError,
    load_api,
)
from pycomprepair.discovery.attr_check import scan_missing_attributes
from pycomprepair.discovery.fix import FixResult, rewrite_file, rewrite_source
from pycomprepair.discovery.import_check import scan_missing_imports
from pycomprepair.discovery.known_fixes import KNOWN_FIXES, KnownFix

__all__ = [
    "KNOWN_FIXES",
    "APIIndex",
    "FixResult",
    "KnownFix",
    "PackageNotInstalledError",
    "load_api",
    "rewrite_file",
    "rewrite_source",
    "scan_missing_attributes",
    "scan_missing_imports",
]
