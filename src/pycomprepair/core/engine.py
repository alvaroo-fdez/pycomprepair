"""High-level scan and repair engine.

This module orchestrates the pipeline:

1. Resolve target files (single file, directory, glob).
2. Parse each file once with :mod:`libcst`.
3. Dispatch the parsed module to plugins matching the target requirement.
4. Aggregate issues and, in repair mode, sequentially apply each plugin's
   transformation, re-parsing only when necessary.

The engine is intentionally synchronous and CPU-bound; parallelism can be
added later via :mod:`concurrent.futures` without changing the public API.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

import libcst as cst
from packaging.requirements import Requirement

from pycomprepair.core.issue import Issue, is_actionable
from pycomprepair.core.plugin import PluginContext, PluginRegistry, get_registry


@dataclass
class RepairResult:
    """Result of a repair operation on a single file."""

    file: Path
    original_source: str
    new_source: str
    issues: list[Issue]

    @property
    def changed(self) -> bool:
        return self.original_source != self.new_source


def _iter_python_files(path: Path) -> Iterator[Path]:
    """Yield Python files under ``path`` (file or directory)."""
    if path.is_file():
        if path.suffix == ".py":
            yield path
        return
    for child in sorted(path.rglob("*.py")):
        # Skip common virtualenv and build directories.
        parts = set(child.parts)
        if parts & {".venv", "venv", "env", ".env", "build", "dist", "__pycache__", ".tox"}:
            continue
        yield child


def _parse(source: str) -> cst.Module | None:
    """Parse ``source`` returning ``None`` on syntax errors."""
    try:
        return cst.parse_module(source)
    except cst.ParserSyntaxError:
        return None


def scan_path(
    path: str | Path,
    target: str | Requirement,
    *,
    registry: PluginRegistry | None = None,
    options: dict[str, str] | None = None,
    ignore_codes: frozenset[str] | set[str] | None = None,
) -> list[Issue]:
    """Scan ``path`` and return all detected :class:`Issue` objects.

    Parameters
    ----------
    path:
        File or directory to scan. Directories are traversed recursively,
        skipping common virtualenv/build folders.
    target:
        Target requirement (e.g. ``"pydantic>=2.0,<3.0"``) used to decide
        which plugins are activated.
    registry:
        Plugin registry. Defaults to the global one.
    options:
        Free-form options forwarded to plugins.
    ignore_codes:
        Optional set of rule codes (``"PYD001"``, ``"SQL002"``, ...) to drop
        from the result. Typically populated from the project's
        ``pycomprepair.toml``.
    """
    req = _coerce_requirement(target)
    reg = registry or get_registry()
    opts = options or {}
    ignored = frozenset(ignore_codes or ())
    issues: list[Issue] = []

    for file in _iter_python_files(Path(path)):
        source = file.read_text(encoding="utf-8")
        module = _parse(source)
        if module is None:
            continue
        ctx = PluginContext(
            target=req, file=file, source=source, module=module, options=opts
        )
        for plugin in reg.for_context(ctx):
            issues.extend(i for i in plugin.scan(ctx) if i.code not in ignored)

    return issues


def repair_path(
    path: str | Path,
    target: str | Requirement,
    *,
    dry_run: bool = True,
    registry: PluginRegistry | None = None,
    options: dict[str, str] | None = None,
    min_confidence: float = 0.0,
    unsafe_fixes: bool = False,
    ignore_codes: frozenset[str] | set[str] | None = None,
) -> list[RepairResult]:
    """Scan and (optionally) apply codemods.

    When ``dry_run`` is true, source files are not written; the returned
    :class:`RepairResult` objects still expose the proposed new source so
    callers can render diffs.

    The ``min_confidence`` and ``unsafe_fixes`` gates control which issues
    are passed to each plugin's :meth:`Plugin.repair`. Issues that do not
    pass the gate still appear in :attr:`RepairResult.issues` so the report
    remains complete; they are simply not auto-fixed. ``ignore_codes`` drops
    the listed rules entirely (they are neither reported nor applied).
    """
    req = _coerce_requirement(target)
    reg = registry or get_registry()
    opts = options or {}
    ignored = frozenset(ignore_codes or ())
    results: list[RepairResult] = []

    for file in _iter_python_files(Path(path)):
        original = file.read_text(encoding="utf-8")
        module = _parse(original)
        if module is None:
            continue

        current_source = original
        current_module = module
        all_issues: list[Issue] = []

        for plugin in reg.for_context(
            PluginContext(
                target=req, file=file, source=current_source, module=current_module, options=opts
            )
        ):
            ctx = PluginContext(
                target=req,
                file=file,
                source=current_source,
                module=current_module,
                options=opts,
            )
            issues = [i for i in plugin.scan(ctx) if i.code not in ignored]
            all_issues.extend(issues)
            if not issues:
                continue
            # Gate: only the actionable subset is passed to the plugin so it
            # never auto-applies a fix the user explicitly excluded.
            actionable = [
                i
                for i in issues
                if is_actionable(
                    i, min_confidence=min_confidence, unsafe_fixes=unsafe_fixes
                )
            ]
            if not actionable:
                continue
            transformed = plugin.repair(ctx, actionable)
            if transformed is not current_module:
                current_module = transformed
                current_source = transformed.code

        result = RepairResult(
            file=file,
            original_source=original,
            new_source=current_source,
            issues=all_issues,
        )
        results.append(result)

        if not dry_run and result.changed:
            file.write_text(current_source, encoding="utf-8")

    return results


def _coerce_requirement(target: str | Requirement) -> Requirement:
    return target if isinstance(target, Requirement) else Requirement(target)


def aggregate_issues(results: Iterable[RepairResult]) -> list[Issue]:
    """Flatten the ``issues`` of each :class:`RepairResult`."""
    out: list[Issue] = []
    for r in results:
        out.extend(r.issues)
    return out
