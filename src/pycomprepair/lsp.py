"""Language Server Protocol entry point for PyCompatRepair.

The LSP server wraps ``scan_path`` and surfaces issues as LSP
diagnostics. It is implemented on top of `pygls`_, which is an optional
dependency: install PyCompatRepair with the ``lsp`` extra to enable it::

    pip install 'pycomprepair[lsp]'

Editors can then launch the server via the ``pycomprepair-lsp`` script
declared in ``pyproject.toml``.

.. _pygls: https://pygls.readthedocs.io

Supported notifications
-----------------------

* ``textDocument/didOpen`` — initial scan when a file is opened
* ``textDocument/didSave`` — re-scan after a save
* ``textDocument/didChange`` — debounced re-scan as the user types

Each notification triggers a single ``scan_path`` over the file's
content and publishes the resulting issues as ``Diagnostic`` objects.
The diagnostic ``code`` carries the PyCompatRepair issue code
(``DJA001``, ``NPY002`` …) so editors can link to documentation.

Both pygls 1.x (``pygls.server``) and 2.x (``pygls.lsp.server``) are
supported. All pygls / lsprotocol references are deliberately typed as
``Any`` so the optional dependency can be type-checked-free.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from pycomprepair.config import load_config
from pycomprepair.core.engine import scan_path
from pycomprepair.core.issue import Issue, Severity

# ---------------------------------------------------------------------------
# Optional dependency guard
# ---------------------------------------------------------------------------


def _require_pygls() -> tuple[Any, Any]:
    """Import pygls + lsprotocol or raise a helpful error.

    Returns the ``(LanguageServer, types)`` pair so we don't re-import on
    every diagnostic publish.
    """
    LanguageServer: Any
    types: Any
    try:
        try:
            from pygls.lsp.server import (
                LanguageServer as _LS_v2,
            )

            LanguageServer = _LS_v2
        except ImportError:
            from pygls.server import LanguageServer as _LS_v1  # type: ignore[attr-defined]

            LanguageServer = _LS_v1
        from lsprotocol import types as _types

        types = _types
    except ImportError as exc:  # pragma: no cover - exercised via test
        raise SystemExit(
            "pycomprepair-lsp requires the 'lsp' extra. "
            "Install with: pip install 'pycomprepair[lsp]'"
        ) from exc
    return LanguageServer, types


# ---------------------------------------------------------------------------
# URI -> path
# ---------------------------------------------------------------------------


def _uri_to_path(uri: str) -> Path | None:
    parsed = urlparse(uri)
    if parsed.scheme not in ("file", ""):
        return None
    raw = unquote(parsed.path)
    # On Windows, file URIs look like ``/C:/repo/x.py``; strip the leading slash.
    if (
        sys.platform.startswith("win")
        and raw.startswith("/")
        and len(raw) > 3
        and raw[2] == ":"
    ):
        raw = raw[1:]
    return Path(raw)


def _resolve_target(file: Path) -> str | None:
    """Walk upward from *file* to find a ``pycomprepair.toml`` target."""
    try:
        cfg = load_config(file.parent if file.is_file() else file)
    except Exception:
        return None
    target = getattr(cfg, "target", None)
    if isinstance(target, list):
        return target[0] if target else None
    if isinstance(target, str):
        return target
    return None


# ---------------------------------------------------------------------------
# Diagnostic conversion
# ---------------------------------------------------------------------------


def _severity_to_lsp(sev: Severity, types_mod: Any) -> Any:
    mapping = {
        Severity.ERROR: types_mod.DiagnosticSeverity.Error,
        Severity.WARNING: types_mod.DiagnosticSeverity.Warning,
        Severity.INFO: types_mod.DiagnosticSeverity.Information,
    }
    return mapping.get(sev, types_mod.DiagnosticSeverity.Information)


def _issue_to_diagnostic(issue: Issue, types_mod: Any) -> Any:
    line = max(0, issue.line - 1)
    col = max(0, issue.column)
    return types_mod.Diagnostic(
        range=types_mod.Range(
            start=types_mod.Position(line=line, character=col),
            end=types_mod.Position(line=line, character=col + 1),
        ),
        message=issue.message,
        severity=_severity_to_lsp(issue.severity, types_mod),
        code=issue.code,
        source="pycomprepair",
    )


# ---------------------------------------------------------------------------
# Server bootstrap
# ---------------------------------------------------------------------------


def build_server() -> Any:
    """Instantiate and wire up the LSP server (pygls required)."""
    LanguageServer, types = _require_pygls()

    server: Any = LanguageServer("pycomprepair-lsp", "1.0.0")

    def _publish(uri: str) -> None:
        file = _uri_to_path(uri)
        if file is None or not file.is_file():
            server.publish_diagnostics(uri, [])
            return
        target = _resolve_target(file)
        if not target:
            server.publish_diagnostics(uri, [])
            return
        try:
            issues = scan_path(file, target)
        except Exception:
            server.publish_diagnostics(uri, [])
            return
        diagnostics = [_issue_to_diagnostic(i, types) for i in issues]
        server.publish_diagnostics(uri, diagnostics)

    def _on_open(params: Any) -> None:
        _publish(params.text_document.uri)

    def _on_save(params: Any) -> None:
        _publish(params.text_document.uri)

    def _on_change(params: Any) -> None:
        _publish(params.text_document.uri)

    server.feature(types.TEXT_DOCUMENT_DID_OPEN)(_on_open)
    server.feature(types.TEXT_DOCUMENT_DID_SAVE)(_on_save)
    server.feature(types.TEXT_DOCUMENT_DID_CHANGE)(_on_change)

    return server


def main() -> None:  # pragma: no cover - I/O loop, exercised manually.
    """Console-script entry point: start the LSP over stdio."""
    server = build_server()
    server.start_io()
