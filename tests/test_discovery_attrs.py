"""Tests for the attribute-access discovery check (``DSC002``)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from pycomprepair.cli import app
from pycomprepair.discovery import APIIndex, scan_missing_attributes


def _index(
    package: str,
    *,
    symbols: tuple[str, ...] = (),
    containers: tuple[str, ...] = (),
    functions: tuple[str, ...] = (),
    attributes: tuple[str, ...] = (),
) -> APIIndex:
    """Build a synthetic APIIndex for tests with explicit kinds."""
    kinds: dict[str, str] = {}
    all_symbols: set[str] = set(symbols)
    for path in containers:
        all_symbols.add(path)
        # Crude heuristic: anything ending in a capitalised final segment
        # is treated as a class; everything else as a module.
        last = path.rsplit(".", 1)[-1]
        kinds[path] = "class" if last[:1].isupper() else "module"
    for path in functions:
        all_symbols.add(path)
        kinds[path] = "function"
    for path in attributes:
        all_symbols.add(path)
        kinds[path] = "attribute"
    return APIIndex(package=package, symbols=frozenset(all_symbols), kinds=kinds)


# ---------------------------------------------------------------------------
# Direct unit tests
# ---------------------------------------------------------------------------


def test_flags_removed_module_attribute(tmp_path: Path) -> None:
    src = "import numpy as np\nx = np.float\n"
    index = _index(
        "numpy",
        containers=("numpy",),
        attributes=("numpy.int64",),
    )
    issues = scan_missing_attributes(tmp_path / "f.py", src, {"numpy": index})
    assert len(issues) == 1
    issue = issues[0]
    assert issue.code == "DSC002"
    assert issue.plugin == "discover"
    assert issue.context["symbol"] == "numpy.float"
    assert issue.line == 2


def test_accepts_existing_module_attribute(tmp_path: Path) -> None:
    src = "import numpy as np\nx = np.int64\n"
    index = _index(
        "numpy",
        containers=("numpy",),
        attributes=("numpy.int64",),
    )
    issues = scan_missing_attributes(tmp_path / "f.py", src, {"numpy": index})
    assert issues == []


def test_flags_deep_dotted_chain(tmp_path: Path) -> None:
    src = "import django\nx = django.utils.timezone.utc\n"
    index = _index(
        "django",
        containers=("django", "django.utils", "django.utils.timezone"),
    )
    issues = scan_missing_attributes(tmp_path / "f.py", src, {"django": index})
    assert len(issues) == 1
    assert issues[0].context["symbol"] == "django.utils.timezone.utc"


def test_chain_stops_at_function(tmp_path: Path) -> None:
    """Attribute access after a function call site is opaque -- skip silently."""
    src = "import acme\nx = acme.builder.field\n"
    index = _index(
        "acme",
        containers=("acme",),
        functions=("acme.builder",),
    )
    issues = scan_missing_attributes(tmp_path / "f.py", src, {"acme": index})
    assert issues == []


def test_resolves_from_import(tmp_path: Path) -> None:
    src = "from numpy import random\nx = random.deprecated_func()\n"
    index = _index(
        "numpy",
        containers=("numpy", "numpy.random"),
        functions=("numpy.random.rand",),
    )
    issues = scan_missing_attributes(tmp_path / "f.py", src, {"numpy": index})
    assert len(issues) == 1
    assert issues[0].context["symbol"] == "numpy.random.deprecated_func"


def test_resolves_from_import_alias(tmp_path: Path) -> None:
    src = "from numpy import random as rng\nx = rng.removed\n"
    index = _index("numpy", containers=("numpy", "numpy.random"))
    issues = scan_missing_attributes(tmp_path / "f.py", src, {"numpy": index})
    assert len(issues) == 1
    assert issues[0].context["symbol"] == "numpy.random.removed"


def test_skips_shadowed_name(tmp_path: Path) -> None:
    """Reassigning the imported name disables the check (no false positives)."""
    src = (
        "import numpy as np\n"
        "np = SomeWrapper()\n"
        "x = np.float\n"
    )
    index = _index("numpy", containers=("numpy",))
    issues = scan_missing_attributes(tmp_path / "f.py", src, {"numpy": index})
    assert issues == []


def test_skips_function_parameter_shadow(tmp_path: Path) -> None:
    src = (
        "import numpy as np\n"
        "def f(np):\n"
        "    return np.float\n"
    )
    index = _index("numpy", containers=("numpy",))
    issues = scan_missing_attributes(tmp_path / "f.py", src, {"numpy": index})
    assert issues == []


def test_skips_for_target_shadow(tmp_path: Path) -> None:
    src = (
        "import numpy as np\n"
        "for np in range(3):\n"
        "    use(np.float)\n"
    )
    index = _index("numpy", containers=("numpy",))
    issues = scan_missing_attributes(tmp_path / "f.py", src, {"numpy": index})
    assert issues == []


def test_skips_unrelated_packages(tmp_path: Path) -> None:
    src = "import other\nx = other.thing\n"
    index = _index("numpy", containers=("numpy",))
    issues = scan_missing_attributes(tmp_path / "f.py", src, {"numpy": index})
    assert issues == []


def test_skips_local_variables(tmp_path: Path) -> None:
    src = "session = make_session()\nx = session.query(User).get(1)\n"
    index = _index("sqlalchemy", containers=("sqlalchemy",))
    issues = scan_missing_attributes(tmp_path / "f.py", src, {"sqlalchemy": index})
    assert issues == []


def test_only_reports_outermost_attribute_in_chain(tmp_path: Path) -> None:
    """A removed parent must only generate one issue, not one per nested step."""
    src = "import acme\nx = acme.removed.then_something_else\n"
    index = _index("acme", containers=("acme",))
    issues = scan_missing_attributes(tmp_path / "f.py", src, {"acme": index})
    assert len(issues) == 1
    assert issues[0].context["symbol"] == "acme.removed"


def test_returns_empty_on_syntax_error(tmp_path: Path) -> None:
    issues = scan_missing_attributes(
        tmp_path / "f.py",
        "import numpy as np\nnp.(broken\n",
        {"numpy": _index("numpy", containers=("numpy",))},
    )
    assert issues == []


def test_returns_empty_without_indexes(tmp_path: Path) -> None:
    assert scan_missing_attributes(tmp_path / "f.py", "import numpy\n", {}) == []


# ---------------------------------------------------------------------------
# Integration with the real packaging library
# ---------------------------------------------------------------------------


def test_cli_discover_attr_real_packaging(tmp_path: Path) -> None:
    """End-to-end: ``discover`` flags a non-existent attribute on a real package."""
    file = tmp_path / "uses_pkg.py"
    file.write_text(
        "import packaging\n"
        "v = packaging.version.Version('1.0')\n"
        "x = packaging.version.NoLongerExists\n",
        encoding="utf-8",
    )
    result = CliRunner().invoke(app, ["discover", str(file), "--package", "packaging"])
    assert result.exit_code == 1
    assert "DSC002" in result.stdout
    assert "NoLongerExists" in result.stdout
