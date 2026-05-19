"""Tests for the Markdown reporter.

The strings asserted here are part of the *public contract* consumed by the
GitHub Action (``action.yml``). Renaming or rewording them must be done in
lockstep with the action, otherwise the parsed issue count will silently
fall back to zero on real runs.
"""

from __future__ import annotations

from pathlib import Path

from pycomprepair.core.engine import scan_path
from pycomprepair.core.plugin import PluginRegistry
from pycomprepair.report.markdown import render_issues_markdown


def test_no_issues_uses_canonical_phrase(tmp_path: Path, registry: PluginRegistry) -> None:
    (tmp_path / "ok.py").write_text("x = 1 + 1\n", encoding="utf-8")
    issues = scan_path(tmp_path, "pydantic>=2.0", registry=registry)
    md = render_issues_markdown(issues)
    assert "No incompatibilities detected" in md


def test_summary_line_contains_count(tmp_path: Path, registry: PluginRegistry) -> None:
    (tmp_path / "m.py").write_text("x = obj.dict()\n", encoding="utf-8")
    issues = scan_path(tmp_path, "pydantic>=2.0", registry=registry)
    md = render_issues_markdown(issues)
    # The action's regex looks for ``Detected **<N>**`` literally.
    assert f"Detected **{len(issues)}**" in md


def test_table_header_lists_expected_columns(tmp_path: Path, registry: PluginRegistry) -> None:
    (tmp_path / "m.py").write_text("x = obj.dict()\n", encoding="utf-8")
    issues = scan_path(tmp_path, "pydantic>=2.0", registry=registry)
    md = render_issues_markdown(issues)
    assert "| Line | Code | Severity | Message | Fix |" in md
