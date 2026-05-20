"""Tests for the pandas 2.x migration plugin."""

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
    _write(tmp_path, "m.py", "import pandas as pd\nfor k, v in df.iteritems(): pass\n")
    issues = scan_path(tmp_path, "pandas<2.0", registry=registry)
    assert [i for i in issues if i.plugin == "pandas"] == []


def test_plugin_fires_for_pandas_2(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    _write(tmp_path, "m.py", "import pandas as pd\nfor k, v in df.iteritems(): pass\n")
    issues = scan_path(tmp_path, "pandas>=2.0", registry=registry)
    assert any(i.code == "PDS002" for i in issues)


# ---------------------------------------------------------------------------
# PDS002 — iteritems -> items (safe rewrite)
# ---------------------------------------------------------------------------


def test_detects_iteritems_call(tmp_path: Path, registry: PluginRegistry) -> None:
    _write(
        tmp_path,
        "m.py",
        """
        import pandas as pd
        df = pd.DataFrame()
        for k, v in df.iteritems():
            print(k, v)
        """,
    )
    issues = scan_path(tmp_path, "pandas>=2.0", registry=registry)
    pds002 = [i for i in issues if i.code == "PDS002"]
    assert len(pds002) == 1
    assert pds002[0].fix is not None
    assert pds002[0].fix.safe is True


def test_repairs_iteritems_to_items(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    file = _write(
        tmp_path,
        "m.py",
        """
        import pandas as pd
        df = pd.DataFrame()
        for k, v in df.iteritems():
            print(k, v)
        """,
    )
    results = repair_path(tmp_path, "pandas>=2.0", registry=registry, dry_run=False)
    assert any(r.changed for r in results)
    out = file.read_text(encoding="utf-8")
    assert ".items()" in out
    assert ".iteritems()" not in out


# ---------------------------------------------------------------------------
# PDS001 — DataFrame.append (detect-only)
# ---------------------------------------------------------------------------


def test_detects_dataframe_append_but_emits_no_fix(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    _write(
        tmp_path,
        "m.py",
        """
        import pandas as pd
        df = pd.DataFrame()
        df.append(other)
        """,
    )
    issues = scan_path(tmp_path, "pandas>=2.0", registry=registry)
    pds001 = [i for i in issues if i.code == "PDS001"]
    assert pds001, "expected a PDS001 detection"
    assert pds001[0].fix is None


def test_ignores_append_without_pandas_alias(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    """Plain list.append shouldn't be flagged when pandas isn't imported."""
    _write(
        tmp_path,
        "m.py",
        """
        items = []
        items.append(1)
        """,
    )
    issues = scan_path(tmp_path, "pandas>=2.0", registry=registry)
    assert [i for i in issues if i.code == "PDS001"] == []


# ---------------------------------------------------------------------------
# PDS003 — pd.np (detect-only)
# ---------------------------------------------------------------------------


def test_detects_pd_np_access(tmp_path: Path, registry: PluginRegistry) -> None:
    _write(
        tmp_path,
        "m.py",
        """
        import pandas as pd
        arr = pd.np.array([1, 2, 3])
        """,
    )
    issues = scan_path(tmp_path, "pandas>=2.0", registry=registry)
    pds003 = [i for i in issues if i.code == "PDS003"]
    assert len(pds003) == 1
    assert pds003[0].fix is None


def test_does_not_rewrite_pd_np(tmp_path: Path, registry: PluginRegistry) -> None:
    file = _write(
        tmp_path,
        "m.py",
        """
        import pandas as pd
        arr = pd.np.array([1, 2, 3])
        """,
    )
    original = file.read_text(encoding="utf-8")
    repair_path(tmp_path, "pandas>=2.0", registry=registry, dry_run=False)
    assert file.read_text(encoding="utf-8") == original
