"""Tests for the NumPy 1.x -> 2.x migration plugin."""

from __future__ import annotations

import textwrap
from pathlib import Path

from pycomprepair.core.engine import repair_path, scan_path
from pycomprepair.core.plugin import PluginRegistry


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Activation gating
# ---------------------------------------------------------------------------


def test_plugin_skips_when_target_below_2_0(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    _write(tmp_path, "m.py", "import numpy as np\nx = np.float(1)\n")
    issues = scan_path(tmp_path, "numpy<2.0", registry=registry)
    assert [i for i in issues if i.plugin == "numpy"] == []


def test_plugin_fires_with_open_upper_bound(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    _write(tmp_path, "m.py", "import numpy as np\nx = np.float(1)\n")
    issues = scan_path(tmp_path, "numpy>=2.0", registry=registry)
    assert any(i.code == "NPY001" for i in issues)


# ---------------------------------------------------------------------------
# NPY001 — scalar aliases
# ---------------------------------------------------------------------------


def test_detects_scalar_aliases(tmp_path: Path, registry: PluginRegistry) -> None:
    _write(
        tmp_path,
        "m.py",
        """
        import numpy as np
        a = np.float(1)
        b = np.int(2)
        c = np.bool(True)
        """,
    )
    issues = scan_path(tmp_path, "numpy>=2.0", registry=registry)
    codes = sorted(i.code for i in issues if i.plugin == "numpy")
    assert codes == ["NPY001", "NPY001", "NPY001"]


def test_repairs_scalar_aliases_to_builtins(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    f = _write(
        tmp_path,
        "m.py",
        """
        import numpy as np
        a = np.float(1)
        b = np.int(2)
        """,
    )
    repair_path(tmp_path, "numpy>=2.0", registry=registry, dry_run=False)
    out = f.read_text(encoding="utf-8")
    assert "float(1)" in out
    assert "int(2)" in out
    assert "np.float" not in out
    assert "np.int" not in out


def test_skips_attribute_access_when_alias_unrelated(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    _write(
        tmp_path,
        "m.py",
        """
        class _NS:
            float = float
        np = _NS()
        x = np.float(1)
        """,
    )
    issues = scan_path(tmp_path, "numpy>=2.0", registry=registry)
    assert [i for i in issues if i.plugin == "numpy"] == []


def test_handles_plain_import_numpy(tmp_path: Path, registry: PluginRegistry) -> None:
    f = _write(
        tmp_path,
        "m.py",
        """
        import numpy
        x = numpy.float(1)
        """,
    )
    repair_path(tmp_path, "numpy>=2.0", registry=registry, dry_run=False)
    out = f.read_text(encoding="utf-8")
    assert "float(1)" in out
    assert "numpy.float" not in out


# ---------------------------------------------------------------------------
# NPY002 — constant aliases
# ---------------------------------------------------------------------------


def test_detects_and_repairs_constant_aliases(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    f = _write(
        tmp_path,
        "m.py",
        """
        import numpy as np
        a = np.NaN
        b = np.Inf
        c = np.infty
        """,
    )
    issues = scan_path(tmp_path, "numpy>=2.0", registry=registry)
    assert sum(1 for i in issues if i.code == "NPY002") == 3

    repair_path(tmp_path, "numpy>=2.0", registry=registry, dry_run=False)
    out = f.read_text(encoding="utf-8")
    assert "np.nan" in out
    assert "np.inf" in out
    assert "np.NaN" not in out
    assert "np.Inf" not in out
    assert "np.infty" not in out


# ---------------------------------------------------------------------------
# NPY003 — function renames
# ---------------------------------------------------------------------------


def test_detects_and_repairs_function_renames(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    f = _write(
        tmp_path,
        "m.py",
        """
        import numpy as np
        s = np.product([1, 2, 3])
        c = np.cumproduct([1, 2, 3])
        a = np.alltrue([True, True])
        b = np.sometrue([True, False])
        r = np.round_(1.5)
        """,
    )
    issues = scan_path(tmp_path, "numpy>=2.0", registry=registry)
    assert sum(1 for i in issues if i.code == "NPY003") == 5

    repair_path(tmp_path, "numpy>=2.0", registry=registry, dry_run=False)
    out = f.read_text(encoding="utf-8")
    assert "np.prod(" in out
    assert "np.cumprod(" in out
    assert "np.all(" in out
    assert "np.any(" in out
    assert "np.round(" in out
    for old in ("np.product", "np.cumproduct", "np.alltrue", "np.sometrue", "np.round_"):
        assert old not in out, f"{old} should have been rewritten"


# ---------------------------------------------------------------------------
# Sanity: untouched code stays untouched
# ---------------------------------------------------------------------------


def test_unrelated_numpy_usage_is_not_flagged(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    _write(
        tmp_path,
        "m.py",
        """
        import numpy as np
        x = np.array([1.0, 2.0])
        y = np.mean(x)
        z = np.float64(1.0)  # the typed dtypes remain
        """,
    )
    issues = scan_path(tmp_path, "numpy>=2.0", registry=registry)
    assert [i for i in issues if i.plugin == "numpy"] == []
