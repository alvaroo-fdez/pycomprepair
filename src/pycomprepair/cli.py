"""``pycomprepair`` command-line interface (Typer-based)."""

from __future__ import annotations

import difflib
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from pycomprepair.config import Config, load_config
from pycomprepair.core.engine import RepairResult, repair_path, scan_path
from pycomprepair.core.issue import Issue, Severity, is_actionable
from pycomprepair.report.markdown import render_issues_markdown, render_repair_markdown

app = typer.Typer(
    name="pycomprepair",
    help="Semantic upgrade assistant and compatibility codemods for Python dependencies.",
    no_args_is_help=True,
    add_completion=False,
)

def _make_console(stderr: bool = False) -> Console:
    """Construct a Rich console.

    When stdout is not a TTY (CI logs, piping, ``CliRunner`` in tests), Rich
    defaults to a narrow width and truncates table columns. We force a
    generous width in that case so issue codes and messages remain readable.
    """
    if sys.stdout.isatty():
        return Console(stderr=stderr)
    return Console(stderr=stderr, width=120, force_terminal=False, soft_wrap=False)


console = _make_console()
err_console = _make_console(stderr=True)


@app.command()
def scan(
    path: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=True,
            readable=True,
            resolve_path=True,
            help="File or directory to scan.",
        ),
    ],
    target: Annotated[
        str | None,
        typer.Option(
            "--target",
            "-t",
            help="Target requirement (e.g. 'pydantic>=2.0,<3.0'). "
            "Falls back to `target` in pycomprepair.toml when omitted.",
        ),
    ] = None,
) -> None:
    """Detect incompatibilities without modifying any files."""
    cfg = load_config(path)
    target = _resolve_target(target, cfg)
    issues = scan_path(path, target, ignore_codes=cfg.ignore)
    _print_issue_table(issues)
    if issues:
        raise typer.Exit(code=1)


@app.command()
def repair(
    path: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=True,
            readable=True,
            resolve_path=True,
        ),
    ],
    target: Annotated[
        str | None, typer.Option("--target", "-t", help="Target requirement.")
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run/--write",
            help="Print proposed diffs without modifying files (default: dry-run).",
        ),
    ] = True,
    show_diff: Annotated[
        bool,
        typer.Option("--diff/--no-diff", help="Print a unified diff for each changed file."),
    ] = True,
    min_confidence: Annotated[
        float | None,
        typer.Option(
            "--min-confidence",
            help=(
                "Only apply fixes whose confidence is >= this value (0.0-1.0). "
                "Issues below the threshold are still reported. Falls back to "
                "the project config when omitted."
            ),
            min=0.0,
            max=1.0,
        ),
    ] = None,
    unsafe_fixes: Annotated[
        bool | None,
        typer.Option(
            "--unsafe-fixes/--safe-fixes-only",
            help="Also apply fixes marked as unsafe (e.g. ambiguous receivers). "
            "Falls back to the project config when omitted.",
        ),
    ] = None,
) -> None:
    """Apply codemods (dry-run by default; pass ``--write`` to persist)."""
    cfg = load_config(path)
    target = _resolve_target(target, cfg)
    effective_min_confidence = (
        cfg.min_confidence if min_confidence is None else min_confidence
    )
    effective_unsafe_fixes = (
        cfg.unsafe_fixes if unsafe_fixes is None else unsafe_fixes
    )

    results = repair_path(
        path,
        target,
        dry_run=dry_run,
        min_confidence=effective_min_confidence,
        unsafe_fixes=effective_unsafe_fixes,
        ignore_codes=cfg.ignore,
    )
    changed = [r for r in results if r.changed]

    all_issues = [i for r in results for i in r.issues]
    _print_issue_table(all_issues)

    if show_diff and changed:
        for r in changed:
            _print_diff(r)

    actionable = sum(
        1
        for i in all_issues
        if is_actionable(
            i,
            min_confidence=effective_min_confidence,
            unsafe_fixes=effective_unsafe_fixes,
        )
    )
    mode = "dry-run" if dry_run else "applied"
    console.print(
        f"[bold]{mode}[/bold]: "
        f"{len(changed)} file(s) would change, "
        f"{len(all_issues)} issue(s) detected, "
        f"{actionable} actionable under current gates "
        f"(min-confidence={effective_min_confidence}, unsafe-fixes={effective_unsafe_fixes})."
    )
    if changed and dry_run:
        raise typer.Exit(code=1)


@app.command()
def report(
    path: Annotated[
        Path,
        typer.Argument(exists=True, file_okay=True, dir_okay=True, readable=True, resolve_path=True),
    ],
    target: Annotated[str | None, typer.Option("--target", "-t")] = None,
    fmt: Annotated[
        str,
        typer.Option(
            "--format",
            "-f",
            help="Output format. One of: markdown.",
        ),
    ] = "markdown",
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write report to file instead of stdout."),
    ] = None,
    include_diff: Annotated[
        bool,
        typer.Option("--with-diff/--no-diff", help="Include proposed diffs (slower)."),
    ] = False,
) -> None:
    """Render a report for CI artifacts or PR comments."""
    if fmt != "markdown":
        err_console.print(f"[red]Unsupported format:[/red] {fmt}")
        raise typer.Exit(code=2)

    cfg = load_config(path)
    target = _resolve_target(target, cfg)

    if include_diff:
        results: list[RepairResult] = repair_path(
            path, target, dry_run=True, ignore_codes=cfg.ignore
        )
        text = render_repair_markdown(results)
    else:
        issues = scan_path(path, target, ignore_codes=cfg.ignore)
        text = render_issues_markdown(issues)

    if output is None:
        console.print(text, markup=False)
    else:
        output.write_text(text, encoding="utf-8")
        console.print(f"Wrote report to [bold]{output}[/bold]")


@app.command()
def version() -> None:
    """Print the installed PyCompatRepair version."""
    from pycomprepair import __version__

    console.print(__version__)


def _print_issue_table(issues: list[Issue]) -> None:
    """Print issues using the layout that best fits the current terminal.

    For wide terminals (>=120 columns) we use a Rich :class:`Table`; for
    narrower ones we fall back to a compact, per-issue list so messages and
    fixes are not fragmented vertically by Rich's auto column shrinking.
    """
    if not issues:
        console.print("[green]No incompatibilities detected.[/green]")
        return

    width = console.size.width
    sorted_issues = sorted(issues, key=lambda i: (str(i.file), i.line, i.column))

    if width >= 140:
        _print_issue_table_wide(sorted_issues)
    else:
        _print_issue_list_compact(sorted_issues)


def _print_issue_table_wide(issues: list[Issue]) -> None:
    table = Table(title=f"PyCompatRepair — {len(issues)} issue(s)", show_lines=False)
    table.add_column("Location", style="cyan", no_wrap=True)
    table.add_column("Code", style="magenta", no_wrap=True)
    table.add_column("Severity", no_wrap=True)
    table.add_column("Message", overflow="fold", ratio=2)
    table.add_column("Fix", overflow="fold", ratio=1)
    for issue in issues:
        table.add_row(
            issue.location,
            issue.code,
            _severity_style(issue.severity),
            issue.message,
            issue.fix.description if issue.fix else "[dim](manual)[/dim]",
        )
    console.print(table)


def _print_issue_list_compact(issues: list[Issue]) -> None:
    """Render issues as a compact, line-oriented list.

    Used on narrow terminals where a Rich :class:`Table` would shrink each
    column into a thin vertical strip. The layout is one block per issue::

        warning  PYD001  path/to/file.py:20:10
            `.dict()` is deprecated; use `.model_dump()`.
            fix: Rename `.dict(...)` to `.model_dump(...)`
    """
    console.print(f"[bold]PyCompatRepair — {len(issues)} issue(s)[/bold]")
    for issue in issues:
        console.print(
            f"{_severity_style(issue.severity)}  "
            f"[magenta]{issue.code}[/magenta]  "
            f"[cyan]{issue.location}[/cyan]"
        )
        console.print(f"    {issue.message}")
        fix_text = issue.fix.description if issue.fix else "[dim](manual)[/dim]"
        console.print(f"    [dim]fix:[/dim] {fix_text}")


def _severity_style(sev: Severity) -> str:
    return {
        Severity.INFO: "[blue]info[/blue]",
        Severity.WARNING: "[yellow]warning[/yellow]",
        Severity.ERROR: "[red]error[/red]",
    }[sev]


def _resolve_target(target: str | None, cfg: Config) -> str:
    """Return the requirement string, falling back to the project config.

    Exits the CLI with a clear message when neither source provides one.
    """
    if target is not None:
        return target
    if cfg.target is not None:
        return cfg.target
    err_console.print(
        "[red]Missing --target.[/red] Pass --target on the command line or set "
        "`target` in `pycomprepair.toml` / `[tool.pycomprepair]` in `pyproject.toml`."
    )
    raise typer.Exit(code=2)


def _print_diff(result: RepairResult) -> None:
    diff = difflib.unified_diff(
        result.original_source.splitlines(keepends=True),
        result.new_source.splitlines(keepends=True),
        fromfile=f"a/{result.file}",
        tofile=f"b/{result.file}",
    )
    console.print(f"\n[bold]{result.file}[/bold]")
    sys.stdout.writelines(diff)


def main() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
