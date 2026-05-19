# PyCompatRepair (`pycomprepair`)

[![CI](https://github.com/alvaroo-fdez/pycomprepair/actions/workflows/ci.yml/badge.svg)](https://github.com/alvaroo-fdez/pycomprepair/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python versions](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/downloads/)
[![Code style: ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Checked with mypy](https://www.mypy-lang.org/static/mypy_badge.svg)](https://mypy-lang.org/)
<!-- Re-enable once published on PyPI:
[![PyPI version](https://img.shields.io/pypi/v/pycomprepair.svg)](https://pypi.org/project/pycomprepair/)
[![PyPI downloads](https://img.shields.io/pypi/dm/pycomprepair.svg)](https://pypi.org/project/pycomprepair/)
-->

> Asistente de upgrades semánticos y codemods de compatibilidad para dependencias Python.

`pycomprepair` analiza el código de tu proyecto frente a una versión **actual** y una versión **objetivo** de una librería, detecta call-sites incompatibles y aplica codemods verificables con `--dry-run`, diff legible y posibilidad de rollback.

A diferencia de herramientas como `pyupgrade` (solo sintaxis del lenguaje) o `bump-pydantic` (solo Pydantic v1→v2), `pycomprepair` está pensado como un **núcleo extensible** con un sistema de plugins por ecosistema. El MVP incluye:

- **Núcleo**: extracción de firmas con `griffe`, detección de incompatibilidades, motor de codemods sobre `libcst`.
- **Plugin Pydantic v2**: `BaseSettings`, `Config` → `model_config`, `@validator` → `@field_validator`, `.dict()` → `.model_dump()`, `.parse_obj()` → `.model_validate()`, etc.
- **Plugin FastAPI**: deprecated `on_event` → `lifespan`, `Depends` con `use_cache` deprecated, etc.
- **Plugin SQLAlchemy 2.0**: `from sqlalchemy.ext.declarative import declarative_base` → `sqlalchemy.orm`, `session.query(M).get(pk)` → `session.get(M, pk)`, avisos sobre `declarative_base()` y `Query.update/delete`.
- **Plugin Django 5.0**: `smart_text`/`force_text` → `smart_str`/`force_str`, `ugettext*` → `gettext*`, aviso sobre `django.utils.timezone.utc` y `Meta.index_together`.
- **CLI** (`pycomprepair`) con `scan`, `repair`, `report`.

## Estado

Pre-alpha. Estamos construyendo el MVP.

## Instalación (desde fuente, mientras no esté en PyPI)

```bash
uv venv
uv pip install -e ".[dev]"
```

## Uso rápido

```bash
# Escanear el proyecto y detectar incompatibilidades
pycomprepair scan ./src --target "pydantic>=2.0,<3.0"

# Aplicar codemods en modo dry-run (muestra diff, no escribe)
pycomprepair repair ./src --target "pydantic>=2.0,<3.0" --dry-run

# Aplicar de verdad
pycomprepair repair ./src --target "pydantic>=2.0,<3.0"

# Generar reporte HTML/Markdown
pycomprepair report ./src --target "pydantic>=2.0,<3.0" --format markdown
```

## Úsalo como GitHub Action

PyCompatRepair se distribuye también como _composite action_, así que puedes
añadir un job de compatibilidad a cualquier repositorio Python en cinco líneas:

```yaml
# .github/workflows/pycomprepair.yml
name: Compatibility check
on: [pull_request]
permissions:
  contents: read
  pull-requests: write  # solo si activas comment-on-pr

jobs:
  pycomprepair:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: alvaroo-fdez/pycomprepair@main
        with:
          path: src
          target: "pydantic>=2.0,<3.0"
          mode: scan            # "scan" (default) o "repair"
          fail-on-issues: "true"
          comment-on-pr: "true" # publica/actualiza un comentario idempotente
```

Inputs principales:

| Input            | Default | Descripción                                                              |
| ---------------- | ------- | ------------------------------------------------------------------------ |
| `path`           | `.`     | Ruta a escanear/reparar.                                                 |
| `target`         | —       | Requisito objetivo, p.ej. `"pydantic>=2.0,<3.0"`.                        |
| `mode`           | `scan`  | `scan` solo detecta; `repair` además incluye diffs en el reporte.        |
| `fail-on-issues` | `true`  | Falla el job si se detectan incompatibilidades.                          |
| `comment-on-pr`  | `false` | Publica/actualiza un comentario en el PR con el reporte (idempotente).   |
| `version`        | —       | Especificador opcional, p.ej. `==0.1.0` para fijar versión.              |
| `git-ref`        | —       | Instala desde un ref del repo (útil para probar cambios sin publicar).   |
| `skip-install`   | `false` | Salta la instalación si ya tienes `pycomprepair` en el `PATH`.           |

El reporte siempre se publica en el _step summary_ del job; los outputs
`issues-count` y `report-path` quedan disponibles para pasos posteriores.

## Arquitectura

```
src/pycomprepair/
├── core/           # Diff de firmas, registro de plugins, modelos de issue
├── codemods/       # Helpers libcst reutilizables
├── plugins/        # Plugins por ecosistema (pydantic, fastapi, ...)
├── report/         # Renderers Markdown/HTML
└── cli.py          # CLI Typer
```

## Licencia

Apache-2.0. Ver [LICENSE](LICENSE).
