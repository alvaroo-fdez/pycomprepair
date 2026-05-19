# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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
