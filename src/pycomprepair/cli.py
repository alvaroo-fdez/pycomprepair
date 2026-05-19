"""``pycomprepair`` command-line interface (Typer-based)."""

from __future__ import annotations

import difflib
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from pycomprepair.core.engine import RepairResult, repair_path, scan_path
from pycomprepair.core.issue import Issue, Severity
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
    return Console(stderr=stderr, width=200, force_terminal=False, soft_wrap=False)


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
        str,
        typer.Option(
            "--target",
            "-t",
            help="Target requirement (e.g. 'pydantic>=2.0,<3.0').",
        ),
    ],
) -> None:
    """Detect incompatibilities without modifying any files."""
    issues = scan_path(path, target)
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
        str, typer.Option("--target", "-t", help="Target requirement.")
    ],
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
) -> None:
    """Apply codemods (dry-run by default; pass ``--write`` to persist)."""
    results = repair_path(path, target, dry_run=dry_run)
    changed = [r for r in results if r.changed]

    _print_issue_table([i for r in results for i in r.issues])

    if show_diff and changed:
        for r in changed:
            _print_diff(r)

    mode = "dry-run" if dry_run else "applied"
    console.print(
        f"[bold]{mode}[/bold]: "
        f"{len(changed)} file(s) would change, "
        f"{sum(len(r.issues) for r in results)} issue(s) detected."
    )
    if changed and dry_run:
        raise typer.Exit(code=1)


@app.command()
def report(
    path: Annotated[
        Path,
        typer.Argument(exists=True, file_okay=True, dir_okay=True, readable=True, resolve_path=True),
    ],
    target: Annotated[str, typer.Option("--target", "-t")],
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

    if include_diff:
        results: list[RepairResult] = repair_path(path, target, dry_run=True)
        text = render_repair_markdown(results)
    else:
        issues = scan_path(path, target)
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
    if not issues:
        console.print("[green]No incompatibilities detected.[/green]")
        return
    table = Table(title=f"PyCompatRepair — {len(issues)} issue(s)", show_lines=False)
    table.add_column("Location", style="cyan", no_wrap=True)
    table.add_column("Code", style="magenta")
    table.add_column("Severity")
    table.add_column("Message", overflow="fold")
    table.add_column("Fix", overflow="fold")
    for issue in sorted(issues, key=lambda i: (str(i.file), i.line, i.column)):
        table.add_row(
            issue.location,
            issue.code,
            _severity_style(issue.severity),
            issue.message,
            issue.fix.description if issue.fix else "[dim](manual)[/dim]",
        )
    console.print(table)


def _severity_style(sev: Severity) -> str:
    return {
        Severity.INFO: "[blue]info[/blue]",
        Severity.WARNING: "[yellow]warning[/yellow]",
        Severity.ERROR: "[red]error[/red]",
    }[sev]


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
