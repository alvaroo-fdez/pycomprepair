# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Initial scaffolding: core engine, plugin registry, CLI (`scan`, `repair`, `report`, `version`).
- Pydantic v1 → v2 plugin with rules `PYD001`–`PYD008`:
  method renames (`.dict`, `.json`, `.parse_obj`, `.parse_raw`, `.copy`),
  decorator renames (`validator`, `root_validator`) with auto-import, and
  inner `class Config` deprecation warning.
- FastAPI plugin with rule `FAS001` for deprecated `@app.on_event(...)`.
- Markdown reporter for CI artifacts and PR comments.
- Test suite covering engine, plugins and CLI flows.

## [0.1.0] — unreleased

Pre-alpha. Not yet published to PyPI.
