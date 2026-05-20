# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] — 2026-05-21

PyCompatRepair reaches 1.0 with safety controls, the DSC002 auto-fix
pipeline, a pandas plugin, on-disk griffe caching, an `init` wizard, a
public Plugin SDK documentation, and an optional LSP server.

### Added

- **Safety levels**. `pycomprepair repair` now accepts `--safe-only`,
  a convenience alias that always wins over project configuration. The
  repair summary surfaces the number of fixes skipped because they were
  marked unsafe or fell below the configured confidence threshold so
  users can re-run with the relevant gates lifted.
- **DSC002 auto-fix**. `pycomprepair discover --fix` rewrites the
  attribute-access incompatibilities surfaced by `DSC002` using the
  shared `KNOWN_FIXES` registry. Two rewrite strategies are supported:
  `RENAME_ATTR` swaps just the final attribute (preserving the user's
  alias) and `REPLACE_EXPRESSION` substitutes the whole dotted chain
  (used for cross-package rewrites such as
  `django.utils.timezone.utc` -> `datetime.timezone.utc`). Unsafe
  rewrites require `--unsafe-fixes`; `--dry-run` is the default.
- **Pandas 2.x plugin** (`pycomprepair.plugins.pandas_v2`). Ships three
  codes: `PDS001` (detect-only) for removed `DataFrame.append` /
  `Series.append` calls; `PDS002` for the safe `.iteritems()` ->
  `.items()` rename; `PDS003` (detect-only) for removed `pd.np` access.
- **Griffe cache**. Discovery snapshots are persisted under
  `~/.cache/pycomprepair/<package>-<version>.json` and reused
  transparently on subsequent runs. Cache directory is configurable via
  `PYCOMPREPAIR_CACHE_DIR` and can be disabled with
  `PYCOMPREPAIR_DISABLE_CACHE=1`. Two new CLI commands manage it:
  `pycomprepair cache path` and `pycomprepair cache clear`.
- **`pycomprepair init` wizard**. Detects installed distributions, maps
  them to known plugin targets, and writes a `pycomprepair.toml`
  prepopulated with the detected target requirements. Use
  `--non-interactive` for CI scenarios and `--target` to pin manually.
- **Plugin SDK documentation** (`docs/plugins.md`). End-to-end cookbook
  with a worked example, entry-point registration, testing harness and
  optional `KNOWN_FIXES` integration so third-party plugins can plug
  into `discover --fix`.
- **LSP server** (`pycomprepair-lsp`). Optional, gated behind the
  `pycomprepair[lsp]` extra. Implements `textDocument/didOpen`,
  `didSave` and `didChange`, publishing detected incompatibilities as
  LSP diagnostics with the issue code as the `Diagnostic.code` so
  editors can link to documentation. Compatible with pygls 1.x and 2.x.

### Changed

- `pycomprepair discover` gained `--fix / --no-fix`,
  `--dry-run / --write` and `--unsafe-fixes / --safe-only` flags.
- Built-in plugin registry now includes the `pandas` plugin alongside
  `pydantic`, `fastapi`, `sqlalchemy`, `django` and `numpy`.
- `action.yml` author updated to "Álvaro Fernández".

## [0.3.0] — 2026-05-20

### Added

- **NumPy 1.x -> 2.x plugin** (`pycomprepair.plugins.numpy_v2`). Covers
  the mechanical removals in NumPy 2.0:
  - `NPY001` — scalar aliases `np.float`, `np.int`, `np.bool`,
    `np.complex`, `np.object`, `np.long`, `np.unicode`. Rewritten to the
    equivalent Python builtin (`np.float` -> `float`, ...).
  - `NPY002` — constant aliases `np.NaN`, `np.NAN`, `np.Inf`, `np.PINF`,
    `np.Infinity`, `np.infty` -> `np.nan` / `np.inf`.
  - `NPY003` — function renames `np.product` -> `np.prod`,
    `np.cumproduct` -> `np.cumprod`, `np.alltrue` -> `np.all`,
    `np.sometrue` -> `np.any`, `np.round_` -> `np.round`.

  All three codes are conservative: they only fire on attribute access
  through a name bound by `import numpy [as ...]`, so a local
  `np.float` (with `np` shadowed by something else) is left alone.

### Changed

- Built-in plugin registry now includes `numpy` next to `pydantic`,
  `fastapi`, `sqlalchemy` and `django`.

## [0.2.0] — 2026-05-19

Major upgrade of the discovery layer plus first-class SARIF output and a
shipped pre-commit hook.

### Added

- **`DSC002` — attribute access check (`discover` v2).** The `discover`
  command now performs a two-pass analysis on every Python file: it
  records top-level imports and shadowed names, then validates every
  attribute chain rooted in a tracked import against the installed
  API. Removed members like `numpy.float`, `django.utils.timezone.utc`
  or `pandas.DataFrame.append` are caught even when no hand-written
  plugin covers them. Analysis is intentionally conservative
  (no false positives on shadowed names or chains that pass through a
  function call) and stops walking as soon as it reaches a non-container
  symbol whose surface is unknowable.
- **SARIF 2.1.0 reporter.** `pycomprepair report ... --format sarif`
  emits a conformant SARIF document with a deduplicated `rules` array,
  per-result `level`/`message`/`locations`, optional `fixes` metadata,
  and repo-relative `artifactLocation.uri`. The output can be uploaded
  directly with `github/codeql-action/upload-sarif@v3` so PyCompatRepair
  findings appear under **Security → Code scanning** on GitHub.
- **`APIIndex.kinds` mapping + `is_container` / `kind_of` helpers.**
  Symbols loaded via griffe now carry their griffe kind (`module`,
  `class`, `function`, `attribute`, `alias`). This unlocks the attribute
  walker — only modules and classes have a known public surface — and
  is also useful for future plugins.
- **`.pre-commit-hooks.yaml`** with three ready-to-use hooks
  (`pycomprepair-scan`, `pycomprepair-repair-check`,
  `pycomprepair-discover`) so consumers can wire PyCompatRepair into
  pre-commit with three lines of YAML.

### Changed

- `discovery.__init__` re-exports the new `scan_missing_attributes`
  helper next to `scan_missing_imports`.
- The `discover` CLI command now runs both checks in a single pass and
  reports their issues together.

## [0.1.1] — 2026-05-19

Metadata-only release: refreshes the PyPI project page after the first
publication.

### Changed

- Author metadata set to Álvaro Fernández (`alvaroo-fdez`) instead of the
  generic “PyCompatRepair contributors” placeholder.
- Project status moved from `Development Status :: 3 - Alpha` to
  `Development Status :: 4 - Beta` now that the package is published and the
  core flow (`scan` / `repair` / `report` / `discover`) is exercised against
  real-world projects.
- README rewritten to reflect installation from PyPI (`pip install
  pycomprepair`) instead of the pre-publication “install from source”
  instructions, and PyPI version / downloads badges re-enabled.
- Project URLs (`Homepage`, `Issues`, `Source`, …) point to the real
  `alvaroo-fdez/pycomprepair` repository, and a `Changelog` URL was added.

## [0.1.0] — 2026-05-19

First public release on PyPI.

### Fixed

- **Django plugin no longer leaves duplicate import aliases**. When a file
  already imported the new name next to the legacy one
  (`from django.utils.encoding import smart_text, smart_str`), the rename
  used to produce `smart_str, smart_str`. The codemod now deduplicates the
  alias list while preserving any `as` rebindings.

### Added

- **Dynamic API discovery via griffe**. New `pycomprepair.discovery` package
  loads the *installed* version of a third-party library and exposes its
  public surface as an `APIIndex`. The new `pycomprepair discover PATH
  --package NAME` CLI command flags any `from pkg import X` whose symbol no
  longer exists in the loaded API as a `DSC001` issue, providing a generic
  safety net for renames and removals that are not yet covered by a
  hand-written plugin.
- **Project configuration file** (`pycomprepair.toml` or `[tool.pycomprepair]`
  inside `pyproject.toml`). Discovery walks up from the scanned path; CLI flags
  win over file values, which win over built-in defaults. Supported keys:
  `target`, `min_confidence`, `unsafe_fixes`, `ignore` (list of rule codes).
  `--target` becomes optional on `scan` / `repair` / `report` when set in the
  config. The engine learns an `ignore_codes` parameter so library users get
  the same filtering for free.
- **Django 4.x → 5.x plugin** (`pycomprepair.plugins.django_v5`):
  - `DJA001` — flag `django.utils.timezone.utc` (removed in 5.0; use
    `datetime.timezone.utc`). Detection only — the safe rewrite depends
    on what is already imported in the file.
  - `DJA002` — rewrite `smart_text` / `force_text` to `smart_str` / `force_str`
    in both the `from django.utils.encoding import` line and bare-name call
    sites. Aliased imports (`... as _`) are preserved.
  - `DJA003` — rewrite `ugettext` / `ugettext_lazy` / `ugettext_noop` to
    their `gettext*` equivalents (same import + call-site rewrite).
  - `DJA004` — flag `Meta.index_together`; no auto-fix since merging into
    an existing `indexes = [...]` while preserving order is not a safe
    automatic transform.
  - Demo file at `examples/demo_django.py`.
- **`--min-confidence` / `--unsafe-fixes` flags** on `pycomprepair repair`:
  filter which fixes are auto-applied without hiding detection from the
  report. Each issue's `Fix` already exposes `confidence` and `safe`; the
  new `is_actionable()` helper centralizes the gate and is also plumbed
  through `repair_path()` for programmatic users. The CLI summary now
  prints how many issues are actionable under the active gates.
- **SQLAlchemy 1.4 → 2.0 plugin** (`pycomprepair.plugins.sqlalchemy_v2`):
  - `SQL001` — auto-fix `from sqlalchemy.ext.declarative import declarative_base`
    to `from sqlalchemy.orm import declarative_base` (single-name imports only;
    mixed imports keep the warning without rewrite).
  - `SQL002` — auto-fix `session.query(Model).get(pk)` to
    `session.get(Model, pk)`. Skips the Flask-SQLAlchemy `Model.query.get`
    idiom and `query(A, B).get(...)` to avoid unsafe rewrites.
  - `SQL003` — flag `declarative_base()` calls and suggest the new
    `DeclarativeBase` class style (no codemod, since the safe rewrite depends
    on mixins / naming conventions).
  - `SQL005` — informational note on `Query.update(...)` / `Query.delete()`:
    `synchronize_session` defaults to `'auto'` in 2.0.
  - Demo file at `examples/demo_sqlalchemy.py`.
- **Reusable GitHub Action** (`action.yml`): composite action that any project
  can wire in five lines (`uses: alvaroo-fdez/pycomprepair@main`). It installs
  PyCompatRepair, scans/repairs, publishes the Markdown report on the run
  summary, exposes `issues-count` / `report-path` outputs, and can upsert an
  idempotent PR comment (marker `<!-- pycomprepair-action -->`). Includes
  `version`, `git-ref` and `skip-install` inputs for fine control.
- Self-dogfood workflow (`.github/workflows/self-dogfood.yml`) that runs the
  local `action.yml` against `examples/` on every push/PR and pins the
  expected issue count, so a regression in the rules surfaces immediately.
- Markdown reporter contract tests (`tests/test_markdown_report.py`) that lock
  the canonical strings the GitHub Action parses to compute the issue count.
- Copy/paste workflow example at `examples/github-action.yml`.
- **PYD008 auto-fix**: inner `class Config` is now rewritten into
  `model_config = ConfigDict(...)` when the body contains only assignments
  with known v1 keys and literal-friendly values; unsupported shapes
  (unknown keys, removed-in-v2 keys, nested defs) keep the warning and
  leave the source untouched.
- Mapping of common v1 keys to v2 equivalents (`orm_mode → from_attributes`,
  `anystr_strip_whitespace → str_strip_whitespace`, `allow_mutation` →
  `frozen` with value negation, etc.).
- Compact, line-oriented CLI layout for terminals narrower than 140 columns.
- Golden integration test against `examples/demo.py` (`pytest --update-golden`
  to regenerate).
- Focused test suite for the `class Config` codemod (convertible and
  inconvertible scenarios).

### Changed

- CLI's non-TTY fallback console width: 200 → 120 (closer to typical CI logs).

## [0.1.0] — unreleased

Pre-alpha. Not yet published to PyPI.
