# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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
