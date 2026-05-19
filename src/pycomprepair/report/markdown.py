"""Markdown report renderer for CI artifacts and PR comments."""

from __future__ import annotations

import difflib
from collections.abc import Iterable

from pycomprepair.core.engine import RepairResult
from pycomprepair.core.issue import Issue


def render_issues_markdown(issues: Iterable[Issue]) -> str:
    """Render a list of issues as a Markdown table grouped by file."""
    issues = list(issues)
    if not issues:
        return "# PyCompatRepair\n\nNo incompatibilities detected. ✅\n"

    by_file: dict[str, list[Issue]] = {}
    for issue in issues:
        by_file.setdefault(str(issue.file), []).append(issue)

    lines: list[str] = ["# PyCompatRepair report", ""]
    lines.append(f"Detected **{len(issues)}** incompatibilities across "
                 f"**{len(by_file)}** files.")
    lines.append("")
    for file, file_issues in sorted(by_file.items()):
        lines.append(f"## `{file}`")
        lines.append("")
        lines.append("| Line | Code | Severity | Message | Fix |")
        lines.append("| ---: | :--- | :------- | :------ | :-- |")
        for issue in sorted(file_issues, key=lambda i: (i.line, i.column)):
            fix = issue.fix.description if issue.fix else "_(manual)_"
            lines.append(
                f"| {issue.line} | `{issue.code}` | {issue.severity.value} "
                f"| {_escape_pipes(issue.message)} | {_escape_pipes(fix)} |"
            )
        lines.append("")
    return "\n".join(lines)


def render_repair_markdown(results: Iterable[RepairResult]) -> str:
    """Render a Markdown summary with diffs for changed files."""
    results = list(results)
    issues = [i for r in results for i in r.issues]
    parts: list[str] = [render_issues_markdown(issues)]

    changed = [r for r in results if r.changed]
    if changed:
        parts.append("## Proposed changes")
        parts.append("")
        for r in changed:
            diff = "".join(
                difflib.unified_diff(
                    r.original_source.splitlines(keepends=True),
                    r.new_source.splitlines(keepends=True),
                    fromfile=f"a/{r.file}",
                    tofile=f"b/{r.file}",
                )
            )
            parts.append(f"### `{r.file}`")
            parts.append("")
            parts.append("```diff")
            parts.append(diff.rstrip("\n"))
            parts.append("```")
            parts.append("")
    return "\n".join(parts)


def _escape_pipes(text: str) -> str:
    return text.replace("|", "\\|")
