# PyCompatRepair (`pycomprepair`)

> Asistente de upgrades semánticos y codemods de compatibilidad para dependencias Python.

`pycomprepair` analiza el código de tu proyecto frente a una versión **actual** y una versión **objetivo** de una librería, detecta call-sites incompatibles y aplica codemods verificables con `--dry-run`, diff legible y posibilidad de rollback.

A diferencia de herramientas como `pyupgrade` (solo sintaxis del lenguaje) o `bump-pydantic` (solo Pydantic v1→v2), `pycomprepair` está pensado como un **núcleo extensible** con un sistema de plugins por ecosistema. El MVP incluye:

- **Núcleo**: extracción de firmas con `griffe`, detección de incompatibilidades, motor de codemods sobre `libcst`.
- **Plugin Pydantic v2**: `BaseSettings`, `Config` → `model_config`, `@validator` → `@field_validator`, `.dict()` → `.model_dump()`, `.parse_obj()` → `.model_validate()`, etc.
- **Plugin FastAPI**: deprecated `on_event` → `lifespan`, `Depends` con `use_cache` deprecated, etc.
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
