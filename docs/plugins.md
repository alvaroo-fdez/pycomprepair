# Plugin SDK

PyCompatRepair ships with first-class support for third-party plugins so
you can teach it about migrations specific to your codebase, your private
libraries, or upstream packages that aren't yet covered by the built-in
plugins.

This document is a hands-on cookbook. By the end you will have:

* A working plugin that detects and (optionally) rewrites attribute
  accesses for a fictional ``acme`` package.
* An entry-point declaration so ``pycomprepair`` discovers it after
  ``pip install``.
* A pytest harness that mirrors the layout of the built-in tests.

---

## 1. The plugin protocol

A PyCompatRepair plugin is an object that implements three callables:

```python
class MyPlugin:
    name: str = "acme"
    targets: tuple[str, ...] = ("acme",)

    def matches(self, context: PluginContext) -> bool: ...
    def scan(self, context: PluginContext) -> list[Issue]: ...
    def repair(self, context: PluginContext, issues: list[Issue]) -> cst.Module: ...
```

* ``matches`` is a fast gate that returns ``True`` when the plugin should
  run against the given target requirement (e.g. ``acme>=2.0``). It
  receives a ``PluginContext`` carrying the parsed target spec and a
  reference to the current source file.

* ``scan`` returns a list of ``Issue`` objects describing
  incompatibilities found in ``context.module`` (a parsed ``libcst.Module``).
  Each issue can optionally carry a ``Fix`` describing a safe rewrite.

* ``repair`` applies the codemod. It receives the issues produced by
  ``scan`` and must return a (possibly new) ``cst.Module``. The engine
  serialises the returned module back to source.

The full dataclasses live in:

* ``pycomprepair.core.issue`` — ``Issue``, ``Fix``, ``Severity``
* ``pycomprepair.core.plugin`` — ``PluginContext``, ``PluginRegistry``

---

## 2. A minimal worked example: ``acme`` 2.0

Suppose ``acme`` 2.0 removed ``acme.legacy_helper`` in favour of
``acme.helper``. We want to:

1. Detect every ``acme.legacy_helper(...)`` call site (``ACME001``).
2. Offer a safe, auto-applicable rewrite to ``acme.helper(...)``.

### 2.1. The module layout

```
src/pycomprepair_acme/
├── __init__.py
└── plugin.py
```

### 2.2. ``plugin.py``

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider
from packaging.requirements import Requirement
from packaging.version import Version

from pycomprepair.core.issue import Fix, Issue, Severity
from pycomprepair.core.plugin import PluginContext


PLUGIN_NAME = "acme"


@dataclass
class _AcmePlugin:
    name: str = PLUGIN_NAME
    targets: tuple[str, ...] = ("acme",)

    def matches(self, context: PluginContext) -> bool:
        if context.target.name.lower() not in self.targets:
            return False
        return _targets_version_ge(context.target, "2.0")

    def scan(self, context: PluginContext) -> list[Issue]:
        wrapper = MetadataWrapper(context.module, unsafe_skip_copy=True)
        positions = wrapper.resolve(PositionProvider)
        visitor = _AcmeVisitor(positions=positions, file=context.file)
        wrapper.visit(visitor)
        return visitor.issues

    def repair(self, context: PluginContext, issues: list[Issue]) -> cst.Module:
        relevant = [i for i in issues if i.plugin == PLUGIN_NAME and i.fix and i.fix.safe]
        if not relevant:
            return context.module
        return context.module.visit(_AcmeRenameTransformer())


class _AcmeVisitor(cst.CSTVisitor):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, positions, file: Path) -> None:
        super().__init__()
        self._positions = positions
        self._file = file
        self.issues: list[Issue] = []

    def visit_Attribute(self, node: cst.Attribute) -> None:
        if (
            isinstance(node.value, cst.Name)
            and node.value.value == "acme"
            and node.attr.value == "legacy_helper"
        ):
            pos = self._positions.get(node)
            line, col = (pos.start.line, pos.start.column) if pos else (1, 0)
            self.issues.append(
                Issue(
                    plugin=PLUGIN_NAME,
                    code="ACME001",
                    message=(
                        "`acme.legacy_helper` was removed in acme 2.0; "
                        "use `acme.helper` instead."
                    ),
                    file=self._file,
                    line=line,
                    column=col,
                    severity=Severity.ERROR,
                    fix=Fix(
                        description="Rename `legacy_helper` to `helper`",
                        confidence=1.0,
                        safe=True,
                    ),
                )
            )


class _AcmeRenameTransformer(cst.CSTTransformer):
    def leave_Attribute(self, original, updated):
        if (
            isinstance(updated.value, cst.Name)
            and updated.value.value == "acme"
            and updated.attr.value == "legacy_helper"
        ):
            return updated.with_changes(attr=cst.Name("helper"))
        return updated


def _targets_version_ge(req: Requirement, version: str) -> bool:
    spec = req.specifier
    if not spec:
        return True
    target = Version(version)
    if target in spec:
        return True
    return any(
        s.operator in (">=", "==", "~=") and Version(s.version) >= target
        for s in spec
    )


plugin = _AcmePlugin()
```

### 2.3. Entry-point declaration (``pyproject.toml``)

```toml
[project.entry-points."pycomprepair.plugins"]
acme = "pycomprepair_acme.plugin:plugin"
```

Once your package is installed (``pip install pycomprepair-acme``),
running ``pycomprepair scan --target 'acme>=2.0' .`` will pick it up
automatically.

---

## 3. Testing your plugin

PyCompatRepair's built-in plugins use a tiny harness: a fixture that
returns a pre-populated ``PluginRegistry``, plus the high-level
``scan_path`` / ``repair_path`` helpers.

```python
import textwrap
from pathlib import Path

import pytest
from pycomprepair.core.engine import repair_path, scan_path
from pycomprepair.core.plugin import PluginRegistry

from pycomprepair_acme.plugin import plugin as acme_plugin


@pytest.fixture
def registry() -> PluginRegistry:
    reg = PluginRegistry()
    reg.register(acme_plugin)
    return reg


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


def test_detects_legacy_helper(tmp_path, registry):
    _write(tmp_path, "m.py", "import acme\nacme.legacy_helper()\n")
    issues = scan_path(tmp_path, "acme>=2.0", registry=registry)
    assert any(i.code == "ACME001" for i in issues)


def test_repairs_legacy_helper(tmp_path, registry):
    file = _write(tmp_path, "m.py", "import acme\nacme.legacy_helper()\n")
    repair_path(tmp_path, "acme>=2.0", registry=registry, dry_run=False)
    assert "acme.helper()" in file.read_text()
```

---

## 4. Optional: registering with the DSC002 auto-fix engine

When a missing attribute on a package's public surface is detected by
``pycomprepair discover``, the engine consults a shared registry of
*known fixes* (``pycomprepair.discovery.known_fixes.KNOWN_FIXES``). Each
entry maps a qualified dotted name to a ``KnownFix`` describing whether
the fix is a *rename* or a full *expression replacement*, and whether it
is safe enough to be applied without ``--unsafe-fixes``.

To make your migration knowledge available to ``discover --fix`` users,
register entries at import time:

```python
from pycomprepair.discovery.known_fixes import (
    KnownFix, RENAME_ATTR, REPLACE_EXPRESSION, register,
)

register(
    "acme.legacy_helper",
    KnownFix(
        mode=RENAME_ATTR,
        value="helper",
        description="Rename `legacy_helper` to `helper`",
        safe=True,
        confidence=1.0,
    ),
)
```

* Use ``RENAME_ATTR`` when you only need to swap the final attribute
  name. The user's import alias is preserved.

* Use ``REPLACE_EXPRESSION`` when the whole dotted chain must change
  (e.g. ``django.utils.timezone.utc`` -> ``datetime.timezone.utc``). Mark
  it ``safe=False`` if it requires an import the user may not have.

---

## 5. Distributing your plugin

A plugin is just a Python package. Once you have a working plugin and
tests:

```bash
python -m pip install --upgrade build twine
python -m build
python -m twine upload dist/*
```

Tag your plugin's PyPI keywords with ``pycomprepair-plugin`` so users
can discover it via search.

---

## 6. Checklist before publishing

* [ ] ``matches`` is gated on both ``name`` and version
* [ ] ``scan`` emits ``Severity.ERROR`` only for true incompatibilities;
      use ``WARNING`` for deprecations and ``INFO`` for advisories
* [ ] Every ``Fix`` has a clear ``description`` and explicit
      ``confidence`` / ``safe`` values
* [ ] ``repair`` is idempotent — running it twice produces the same output
* [ ] Unit tests cover both detection and rewriting, plus at least one
      negative case (shadowed alias, unrelated code)
* [ ] ``KNOWN_FIXES`` entries (if any) are registered at import time so
      they are visible to ``discover --fix``
