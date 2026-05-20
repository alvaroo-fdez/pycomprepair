# PyCompatRepair (`pycomprepair`)

[![CI](https://github.com/alvaroo-fdez/pycomprepair/actions/workflows/ci.yml/badge.svg)](https://github.com/alvaroo-fdez/pycomprepair/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/pycomprepair.svg)](https://pypi.org/project/pycomprepair/)
[![PyPI downloads](https://static.pepy.tech/badge/pycomprepair)](https://pepy.tech/project/pycomprepair)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python versions](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/downloads/)
[![Code style: ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Checked with mypy](https://www.mypy-lang.org/static/mypy_badge.svg)](https://mypy-lang.org/)

> Asistente de upgrades semánticos y codemods de compatibilidad para dependencias Python.

`pycomprepair` analiza el código de tu proyecto frente a una versión **actual** y una versión **objetivo** de una librería, detecta call-sites incompatibles y aplica codemods verificables con `--dry-run`, diff legible y posibilidad de rollback.

A diferencia de herramientas como `pyupgrade` (solo sintaxis del lenguaje) o `bump-pydantic` (solo Pydantic v1→v2), `pycomprepair` está pensado como un **núcleo extensible** con un sistema de plugins por ecosistema. El MVP incluye:

- **Núcleo**: extracción de firmas con `griffe`, detección de incompatibilidades, motor de codemods sobre `libcst`.
- **Plugin Pydantic v2**: `BaseSettings`, `Config` → `model_config`, `@validator` → `@field_validator`, `.dict()` → `.model_dump()`, `.parse_obj()` → `.model_validate()`, etc.
- **Plugin FastAPI**: deprecated `on_event` → `lifespan`, `Depends` con `use_cache` deprecated, etc.
- **Plugin SQLAlchemy 2.0**: `from sqlalchemy.ext.declarative import declarative_base` → `sqlalchemy.orm`, `session.query(M).get(pk)` → `session.get(M, pk)`, avisos sobre `declarative_base()` y `Query.update/delete`.
- **Plugin Django 5.0**: `smart_text`/`force_text` → `smart_str`/`force_str`, `ugettext*` → `gettext*`, aviso sobre `django.utils.timezone.utc` y `Meta.index_together`.
- **Plugin NumPy 2.0**: alias escalares eliminados (`np.float` → `float`, `np.int` → `int`, …), constantes (`np.NaN` → `np.nan`, `np.Inf` → `np.inf`) y renombrados de funciones (`np.product` → `np.prod`, `np.alltrue` → `np.all`, `np.round_` → `np.round`, …).
- **CLI** (`pycomprepair`) con `scan`, `repair`, `report`.

## Instalación

```bash
pip install pycomprepair
```

o, si usas [uv](https://github.com/astral-sh/uv):

```bash
uv pip install pycomprepair
```

Requiere Python 3.10+.

Para desarrollo local sobre el repositorio:

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

## Configuración por proyecto

Para evitar repetir `--target` y demás flags en cada llamada, PyCompatRepair lee
configuración de un fichero `pycomprepair.toml` (o de una sección
`[tool.pycomprepair]` en tu `pyproject.toml`). La búsqueda sube por los
directorios padre desde la ruta que pases en la CLI, así que puedes ponerlo en
la raíz del repo:

```toml
# pycomprepair.toml
target = "pydantic>=2.0,<3.0"
min_confidence = 0.8
unsafe_fixes = false
ignore = ["PYD002", "DJA004"]  # códigos de regla que no quieres ver
```

Equivalente dentro de `pyproject.toml`:

```toml
[tool.pycomprepair]
target = "pydantic>=2.0,<3.0"
ignore = ["PYD002"]
```

Los flags de la CLI tienen prioridad sobre la configuración, y la configuración
sobre los valores por defecto. Con esto, `pycomprepair scan ./src` ya basta
una vez configurado el proyecto.

## Descubrimiento dinámico (`discover`)

Más allá de los plugins manuales, `pycomprepair` puede consultar la API
**real** de un paquete instalado mediante [griffe](https://mkdocstrings.github.io/griffe/)
y avisarte de imports que ya no existen en esa versión. Es la forma más rápida
de auditar tu código frente al venv objetivo:

```bash
# Crea un venv con la versión a la que quieres migrar
uv pip install "django==5.0.*"

# Encuentra imports rotos respecto a la Django instalada
pycomprepair discover ./src --package django
```

Cada importación cuyo símbolo no figura en la API cargada genera un issue
`DSC001`. A partir de la 0.2.0, `discover` además realiza un análisis ligero
de accesos a atributos (código `DSC002`) que detecta usos del tipo:

```python
import numpy as np
x = arr.astype(np.float)              # DSC002: numpy.float fue eliminado

import django
ts = django.utils.timezone.utc        # DSC002: removido en Django 5.0
```

El análisis es conservador: ignora nombres reasignados, parámetros de
función y cualquier cadena que pase por una función (su valor de retorno
es opaco), de modo que el ruido en CI es muy bajo. Esto convierte a
`discover` en un linter semántico de compatibilidad y no solo en un
verificador de imports.

## Salida SARIF para GitHub Code Scanning

`pycomprepair report` puede emitir [SARIF 2.1.0][sarif] para integrarse de
forma nativa con la pestaña **Security → Code scanning** de GitHub:

```bash
pycomprepair report ./src --target "django>=5.0,<5.1" \
  --format sarif --output pycomprepair.sarif
```

En el workflow:

```yaml
- run: pycomprepair report ./src --target "django>=5.0" --format sarif --output pcr.sarif
- uses: github/codeql-action/upload-sarif@v3
  with:
    sarif_file: pcr.sarif
    category: pycomprepair
```

Cada regla aparece deduplicada en `tool.driver.rules` con su severidad por
defecto y cada issue se sube como un *result* con `physicalLocation` que
apunta al fichero (ruta relativa al directorio escaneado) y la línea/columna
exacta.

[sarif]: https://docs.oasis-open.org/sarif/sarif/v2.1.0/os/sarif-v2.1.0-os.html

## Pre-commit

PyCompatRepair publica `pre-commit-hooks.yaml`, así que basta con añadirlo a
tu `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/alvaroo-fdez/pycomprepair
    rev: v0.2.0
    hooks:
      - id: pycomprepair-scan
      # Opcionalmente, valida también contra la API instalada:
      - id: pycomprepair-discover
        args: ["--package", "django"]
```

Hooks disponibles:

| Hook                         | Equivalente CLI                       |
| ---------------------------- | ------------------------------------- |
| `pycomprepair-scan`          | `pycomprepair scan .`                 |
| `pycomprepair-repair-check`  | `pycomprepair repair . --dry-run`     |
| `pycomprepair-discover`      | `pycomprepair discover .` (+ paquetes) |

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
