"""Project-level configuration loading.

PyCompatRepair reads its settings from one of two places:

1. A standalone ``pycomprepair.toml`` next to the project root, or
2. A ``[tool.pycomprepair]`` table inside ``pyproject.toml``.

Discovery walks up from the ``path`` argument (or from the current working
directory) until either file is found, or the filesystem root is reached.

The CLI is the canonical consumer: command-line flags override file values,
which override built-in defaults.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - only exercised on 3.10
    import tomli as tomllib


CONFIG_FILENAME = "pycomprepair.toml"
PYPROJECT_FILENAME = "pyproject.toml"
PYPROJECT_TABLE = "tool.pycomprepair"


@dataclass(frozen=True)
class Config:
    """Resolved project configuration.

    All fields are optional; the CLI only consults them when the user did
    not pass an explicit flag. ``source`` records the file we loaded so
    that error messages can be specific.
    """

    target: str | None = None
    min_confidence: float = 0.0
    unsafe_fixes: bool = False
    ignore: frozenset[str] = field(default_factory=frozenset)
    source: Path | None = None

    @classmethod
    def empty(cls) -> Config:
        return cls()


def find_config(start: Path) -> Path | None:
    """Walk up from ``start`` looking for a PyCompatRepair config file.

    Returns the first matching ``pycomprepair.toml`` or ``pyproject.toml``
    (when the latter contains a ``[tool.pycomprepair]`` table). Returns
    ``None`` if neither is found before the filesystem root.
    """
    here = start.resolve()
    if here.is_file():
        here = here.parent
    for directory in [here, *here.parents]:
        candidate = directory / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
        pyproject = directory / PYPROJECT_FILENAME
        if pyproject.is_file() and _has_pycomprepair_table(pyproject):
            return pyproject
    return None


def load_config(start: Path | str | None = None) -> Config:
    """Locate and parse the project configuration.

    Returns :meth:`Config.empty` when no config file is found, which keeps
    the CLI working as a zero-config tool.
    """
    base = Path(start) if start is not None else Path.cwd()
    found = find_config(base)
    if found is None:
        return Config.empty()
    data = _read_table(found)
    return _build_config(data, source=found)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _has_pycomprepair_table(pyproject: Path) -> bool:
    try:
        with pyproject.open("rb") as fp:
            data = tomllib.load(fp)
    except (OSError, tomllib.TOMLDecodeError):
        return False
    tool = data.get("tool")
    return isinstance(tool, dict) and isinstance(tool.get("pycomprepair"), dict)


def _read_table(path: Path) -> dict[str, Any]:
    with path.open("rb") as fp:
        data = tomllib.load(fp)
    if path.name == PYPROJECT_FILENAME:
        tool = data.get("tool", {})
        section = tool.get("pycomprepair", {})
        return section if isinstance(section, dict) else {}
    return dict(data)


def _build_config(data: dict[str, Any], source: Path) -> Config:
    target = data.get("target")
    if target is not None and not isinstance(target, str):
        raise ValueError(
            f"{source}: `target` must be a string (got {type(target).__name__})"
        )

    min_confidence = data.get("min_confidence", 0.0)
    if not isinstance(min_confidence, (int, float)):
        raise ValueError(
            f"{source}: `min_confidence` must be a number between 0.0 and 1.0"
        )
    min_confidence = float(min_confidence)
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError(
            f"{source}: `min_confidence` must be between 0.0 and 1.0, got {min_confidence}"
        )

    unsafe_fixes = data.get("unsafe_fixes", False)
    if not isinstance(unsafe_fixes, bool):
        raise ValueError(f"{source}: `unsafe_fixes` must be a boolean")

    raw_ignore = data.get("ignore", [])
    if not isinstance(raw_ignore, list) or not all(isinstance(x, str) for x in raw_ignore):
        raise ValueError(f"{source}: `ignore` must be a list of rule codes (strings)")

    return Config(
        target=target,
        min_confidence=min_confidence,
        unsafe_fixes=unsafe_fixes,
        ignore=frozenset(raw_ignore),
        source=source,
    )
