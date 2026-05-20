"""Tests for the optional LSP server.

These tests exercise the pure helpers and the graceful pygls-missing
guard. The actual ``build_server()`` path is only exercised when pygls
is installed; otherwise the test is skipped (pygls is an optional
extra).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from pycomprepair.core.issue import Issue, Severity
from pycomprepair.lsp import _issue_to_diagnostic, _uri_to_path


def test_uri_to_path_round_trips_posix() -> None:
    if sys.platform.startswith("win"):
        pytest.skip("posix-only path shape")
    assert _uri_to_path("file:///tmp/x.py") == Path("/tmp/x.py")


def test_uri_to_path_handles_windows_drive_letter() -> None:
    if not sys.platform.startswith("win"):
        pytest.skip("windows-only path shape")
    result = _uri_to_path("file:///C:/repo/m.py")
    assert result is not None
    assert result.drive.lower() == "c:"
    assert "repo" in result.parts


def test_uri_to_path_rejects_non_file_scheme() -> None:
    assert _uri_to_path("http://example.com/x.py") is None


def test_pygls_missing_raises_helpful_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When pygls isn't importable, ``build_server`` must fail loudly."""
    import builtins

    real_import = builtins.__import__

    def _blocked(name: str, *args, **kwargs):
        if name.startswith("pygls") or name == "lsprotocol":
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked)

    from pycomprepair import lsp

    with pytest.raises(SystemExit):
        lsp.build_server()


def test_issue_to_diagnostic_when_pygls_installed() -> None:
    """If pygls is installed, conversion produces a valid Diagnostic."""
    pytest.importorskip("pygls")
    from lsprotocol import types

    issue = Issue(
        plugin="test",
        code="TST001",
        message="hello",
        file=Path("m.py"),
        line=3,
        column=4,
        severity=Severity.WARNING,
    )
    diag = _issue_to_diagnostic(issue, types)
    assert diag.message == "hello"
    assert diag.code == "TST001"
    assert diag.range.start.line == 2  # 0-based
    assert diag.range.start.character == 4
    assert diag.severity == types.DiagnosticSeverity.Warning


def test_build_server_when_pygls_installed() -> None:
    """If pygls is installed, the server should instantiate cleanly."""
    pytest.importorskip("pygls")
    from pycomprepair.lsp import build_server

    server = build_server()
    assert server is not None
