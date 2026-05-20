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
from pycomprepair.report.sarif import render_issues_sarif

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
    safe_only: Annotated[
        bool,
        typer.Option(
            "--safe-only/--no-safe-only",
            help=(
                "Convenience alias for --safe-fixes-only. When passed, it "
                "forces safe-only behaviour even if the config opts into "
                "unsafe fixes."
            ),
        ),
    ] = False,
) -> None:
    """Apply codemods (dry-run by default; pass ``--write`` to persist).

    Safety defaults: only fixes flagged ``safe=True`` are applied. Pass
    ``--unsafe-fixes`` (or set ``unsafe_fixes = true`` in
    ``pycomprepair.toml``) to opt into cross-package or otherwise risky
    rewrites; ``--safe-only`` re-enables the conservative default even when
    the config opts in.
    """
    cfg = load_config(path)
    target = _resolve_target(target, cfg)
    effective_min_confidence = (
        cfg.min_confidence if min_confidence is None else min_confidence
    )
    effective_unsafe_fixes = (
        cfg.unsafe_fixes if unsafe_fixes is None else unsafe_fixes
    )
    if safe_only:
        # The convenience flag always wins so users can override a permissive
        # project config from the command line.
        effective_unsafe_fixes = False

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
    skipped_unsafe = sum(
        1
        for i in all_issues
        if i.fix is not None and not i.fix.safe and not effective_unsafe_fixes
    )
    skipped_low_confidence = sum(
        1
        for i in all_issues
        if i.fix is not None
        and i.fix.safe
        and i.fix.confidence < effective_min_confidence
    )
    mode = "dry-run" if dry_run else "applied"
    console.print(
        f"[bold]{mode}[/bold]: "
        f"{len(changed)} file(s) would change, "
        f"{len(all_issues)} issue(s) detected, "
        f"{actionable} actionable under current gates "
        f"(min-confidence={effective_min_confidence}, unsafe-fixes={effective_unsafe_fixes})."
    )
    if skipped_unsafe or skipped_low_confidence:
        console.print(
            f"  [yellow]skipped:[/yellow] {skipped_unsafe} unsafe fix(es), "
            f"{skipped_low_confidence} below confidence threshold. "
            "Re-run with --unsafe-fixes or --min-confidence to include them."
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
            help="Output format. One of: markdown, sarif.",
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
    fmt_normalized = fmt.lower()
    if fmt_normalized not in {"markdown", "sarif"}:
        err_console.print(f"[red]Unsupported format:[/red] {fmt}")
        raise typer.Exit(code=2)

    cfg = load_config(path)
    target = _resolve_target(target, cfg)

    if fmt_normalized == "sarif":
        # SARIF is a flat list of issues -- diffs are out of scope for the
        # format, so ``--with-diff`` is silently ignored here.
        issues = scan_path(path, target, ignore_codes=cfg.ignore)
        text = render_issues_sarif(issues, base_path=path if path.is_dir() else path.parent)
    elif include_diff:
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
def discover(
    path: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=True,
            readable=True,
            resolve_path=True,
            help="File or directory to scan for missing imports.",
        ),
    ],
    package: Annotated[
        list[str],
        typer.Option(
            "--package",
            "-p",
            help="Package name to introspect (repeat to validate several). "
            "The locally installed version is read via griffe.",
        ),
    ],
    fix: Annotated[
        bool,
        typer.Option(
            "--fix/--no-fix",
            help=(
                "Apply known DSC002 replacements in place (np.float -> float, "
                "np.NaN -> np.nan, ...). Pairs with --dry-run to preview."
            ),
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run/--write",
            help="When combined with --fix, show diffs without modifying files.",
        ),
    ] = True,
    unsafe_fixes: Annotated[
        bool,
        typer.Option(
            "--unsafe-fixes/--safe-only",
            help=(
                "Also apply cross-package DSC002 rewrites that may require "
                "an extra import (e.g. django.utils.timezone.utc -> "
                "datetime.timezone.utc). Off by default."
            ),
        ),
    ] = False,
) -> None:
    """Flag imports that point to symbols missing from the installed package.

    Run inside an environment where the *target* version of the package is
    installed (typically the upgraded virtualenv). Every ``from pkg import X``
    whose ``pkg.X`` is no longer present in the loaded API is reported as a
    ``DSC001`` issue, which usually signals a rename or removal that the
    hand-written plugins do not yet cover.

    With ``--fix``, known removals listed in
    :mod:`pycomprepair.discovery.known_fixes` are rewritten in place using
    libcst. Shadowed names and unrelated references are left alone.
    """
    from pycomprepair.discovery import (
        APIIndex,
        PackageNotInstalledError,
        load_api,
        rewrite_file,
        scan_missing_attributes,
        scan_missing_imports,
    )

    real_indexes: dict[str, APIIndex] = {}
    for pkg in package:
        try:
            real_indexes[pkg] = load_api(pkg)
        except PackageNotInstalledError as exc:
            err_console.print(f"[red]error:[/red] {exc}")
            raise typer.Exit(code=2) from exc

    from pycomprepair.core.engine import _iter_python_files

    issues: list[Issue] = []
    for file in _iter_python_files(path):
        source = file.read_text(encoding="utf-8")
        issues.extend(scan_missing_imports(file, source, real_indexes))
        issues.extend(scan_missing_attributes(file, source, real_indexes))

    _print_issue_table(issues)

    applied_total = 0
    changed_files = 0
    if fix:
        for file in _iter_python_files(path):
            result = rewrite_file(file, allow_unsafe=unsafe_fixes)
            if result.changed:
                changed_files += 1
                applied_total += result.applied
                if not dry_run:
                    file.write_text(result.new_source, encoding="utf-8")
                _print_fix_diff(result.file, result.original_source, result.new_source)
        mode = "would change" if dry_run else "rewrote"
        console.print(
            f"\n[bold]fix:[/bold] {mode} {changed_files} file(s) "
            f"({applied_total} replacement(s); "
            f"unsafe-fixes={'on' if unsafe_fixes else 'off'})"
        )

    if issues and not (fix and not dry_run and applied_total > 0):
        # In write+fix mode where every issue had a known fix we exit 0;
        # otherwise the presence of issues fails the run.
        unresolved = [
            i for i in issues if i.code != "DSC002" or i.fix is None or not i.fix.safe
        ]
        if unresolved or not fix:
            raise typer.Exit(code=1)


@app.command()
def init(
    path: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            resolve_path=True,
            help="Project root that will receive the pycomprepair.toml.",
        ),
    ] = Path("."),
    target: Annotated[
        list[str] | None,
        typer.Option(
            "--target",
            "-t",
            help=(
                "Pin a target manually (repeatable). When omitted, the wizard "
                "inspects installed distributions and proposes targets for "
                "every package that has a known plugin."
            ),
        ),
    ] = None,
    non_interactive: Annotated[
        bool,
        typer.Option(
            "--non-interactive",
            help="Skip prompts and write whatever the auto-detect produces.",
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Overwrite an existing pycomprepair.toml.",
        ),
    ] = False,
) -> None:
    """Create a ``pycomprepair.toml`` for the project.

    The wizard cross-references the project's installed distributions with
    the set of packages PyCompatRepair has plugins for, and suggests a
    target requirement for each match (e.g. ``numpy>=2.0`` if ``numpy`` is
    installed). The user confirms each suggestion before it is written.
    """
    from importlib import metadata as _metadata

    config_path = path / "pycomprepair.toml"
    if config_path.exists() and not force:
        err_console.print(
            f"[red]error[/red]: {config_path} already exists. "
            "Re-run with --force to overwrite."
        )
        raise typer.Exit(code=2)

    # Build the candidate set of (dist, plugin-suggested target version).
    suggestions: list[tuple[str, str]] = []
    if target:
        for raw in target:
            suggestions.append((raw.split("[")[0].split(">")[0].split("=")[0].strip(), raw))
    else:
        # Map each plugin's `targets` tuple to a "ge next-major" recommendation.
        plugin_targets: dict[str, str] = {
            "pydantic": ">=2.0",
            "fastapi": ">=0.100",
            "sqlalchemy": ">=2.0",
            "django": ">=5.0",
            "numpy": ">=2.0",
            "pandas": ">=2.0",
        }
        for dist_name, spec in plugin_targets.items():
            try:
                _metadata.version(dist_name)
            except _metadata.PackageNotFoundError:
                continue
            except Exception:
                continue
            suggestions.append((dist_name, f"{dist_name}{spec}"))

    if not suggestions:
        console.print(
            "[yellow]No supported packages detected.[/yellow] "
            "Install one of: pydantic, fastapi, sqlalchemy, django, numpy, pandas — "
            "or pass --target explicitly."
        )
        raise typer.Exit(code=1)

    accepted: list[str] = []
    for _dist_name, requirement in suggestions:
        if non_interactive:
            accepted.append(requirement)
            console.print(f"  [green]+[/green] {requirement}")
            continue
        if typer.confirm(f"Add target '{requirement}'?", default=True):
            accepted.append(requirement)

    if not accepted:
        console.print("[yellow]No targets selected; nothing to write.[/yellow]")
        raise typer.Exit(code=1)

    # Emit a single 'target' if there's one accepted entry, else a TOML list.
    if len(accepted) == 1:
        body = f'target = "{accepted[0]}"\n'
    else:
        joined = ",\n  ".join(f'"{t}"' for t in accepted)
        body = f"target = [\n  {joined}\n]\n"

    config_path.write_text(body, encoding="utf-8")
    console.print(f"[green]Wrote[/green] {config_path}")


cache_app = typer.Typer(help="Manage the on-disk griffe cache.")
app.add_typer(cache_app, name="cache")


@cache_app.command("clear")
def cache_clear() -> None:
    """Remove every cached griffe snapshot from disk."""
    from pycomprepair.discovery.cache import cache_dir, clear_cache

    removed = clear_cache()
    console.print(f"Removed {removed} cached snapshot(s) from {cache_dir()}.")


@cache_app.command("path")
def cache_path_cmd() -> None:
    """Print the directory where cached snapshots are stored."""
    from pycomprepair.discovery.cache import cache_dir

    console.print(str(cache_dir()))


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


def _print_fix_diff(file: Path, original: str, updated: str) -> None:
    """Render the unified diff produced by ``discover --fix``."""
    diff = difflib.unified_diff(
        original.splitlines(keepends=True),
        updated.splitlines(keepends=True),
        fromfile=f"a/{file}",
        tofile=f"b/{file}",
    )
    console.print(f"\n[bold]{file}[/bold]")
    sys.stdout.writelines(diff)


def main() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
