"""Tests for the v0.4.0 safety controls and DSC002 auto-fix flow."""

from __future__ import annotations

import textwrap
from pathlib import Path

from typer.testing import CliRunner

from pycomprepair.cli import app
from pycomprepair.core.plugin import get_registry
from pycomprepair.discovery import KNOWN_FIXES, APIIndex, rewrite_source
from pycomprepair.discovery.attr_check import scan_missing_attributes


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


def _index(package: str, *, symbols: set[str], containers: set[str]) -> APIIndex:
    kinds = {s: ("module" if s in containers else "function") for s in symbols}
    return APIIndex(package=package, symbols=frozenset(symbols), kinds=kinds)


# ---------------------------------------------------------------------------
# 1) DSC002 issues now carry a Fix when the symbol is in KNOWN_FIXES.
# ---------------------------------------------------------------------------


def test_dsc002_attaches_fix_metadata_for_known_symbol(tmp_path: Path) -> None:
    src = "import numpy as np\nx = np.float\n"
    file = _write(tmp_path, "m.py", src)
    idx = _index("numpy", symbols={"numpy"}, containers={"numpy"})
    issues = scan_missing_attributes(file, src, {"numpy": idx})
    assert len(issues) == 1
    assert issues[0].fix is not None
    assert issues[0].fix.safe is True
    assert "float" in issues[0].fix.description.lower()


def test_dsc002_no_fix_for_unknown_symbol(tmp_path: Path) -> None:
    src = "import numpy as np\nx = np.totallyNotAThing\n"
    file = _write(tmp_path, "m.py", src)
    idx = _index("numpy", symbols={"numpy"}, containers={"numpy"})
    issues = scan_missing_attributes(file, src, {"numpy": idx})
    assert len(issues) == 1
    assert issues[0].fix is None


def test_dsc002_django_fix_is_unsafe(tmp_path: Path) -> None:
    src = "import django\nutc = django.utils.timezone.utc\n"
    file = _write(tmp_path, "m.py", src)
    idx = _index(
        "django",
        symbols={"django", "django.utils", "django.utils.timezone"},
        containers={"django", "django.utils", "django.utils.timezone"},
    )
    issues = scan_missing_attributes(file, src, {"django": idx})
    assert issues
    fix = issues[0].fix
    assert fix is not None
    # Cross-package rewrites must not auto-apply without --unsafe-fixes.
    assert fix.safe is False


# ---------------------------------------------------------------------------
# 2) rewrite_source applies safe known fixes, leaves unsafe ones alone.
# ---------------------------------------------------------------------------


def test_rewrite_source_renames_attr_in_place() -> None:
    src = "import numpy as np\na = np.NaN\nb = np.Inf\n"
    out, applied = rewrite_source(src)
    assert applied == 2
    assert "np.nan" in out
    assert "np.inf" in out
    assert "np.NaN" not in out


def test_rewrite_source_replaces_expression_for_scalars() -> None:
    src = "import numpy as np\nx = np.float\ny = np.int\n"
    out, applied = rewrite_source(src)
    assert applied == 2
    assert "float" in out and "np.float" not in out
    assert "int" in out and "np.int" not in out


def test_rewrite_source_preserves_user_alias_on_rename_attr() -> None:
    src = "import numpy as my_np\nx = my_np.NaN\n"
    out, applied = rewrite_source(src)
    assert applied == 1
    # The user's alias must survive: np.NaN -> np.nan, my_np.NaN -> my_np.nan.
    assert "my_np.nan" in out
    assert "my_np.NaN" not in out


def test_rewrite_source_skips_shadowed_name() -> None:
    src = textwrap.dedent(
        """
        import numpy as np
        def f(np):  # shadows the import
            return np.NaN  # must NOT be rewritten
        """
    )
    out, applied = rewrite_source(src)
    assert applied == 0
    assert "np.NaN" in out


def test_rewrite_source_skips_unsafe_by_default() -> None:
    src = "import django\nutc = django.utils.timezone.utc\n"
    out, applied = rewrite_source(src)
    assert applied == 0
    assert "django.utils.timezone.utc" in out


def test_rewrite_source_applies_unsafe_when_opted_in() -> None:
    src = "import django\nutc = django.utils.timezone.utc\n"
    out, applied = rewrite_source(src, allow_unsafe=True)
    assert applied == 1
    assert "datetime.timezone.utc" in out


def test_rewrite_source_is_idempotent() -> None:
    src = "import numpy as np\nx = np.float\n"
    out1, applied1 = rewrite_source(src)
    out2, applied2 = rewrite_source(out1)
    assert applied1 == 1
    assert applied2 == 0
    assert out1 == out2


def test_rewrite_source_handles_syntax_error_gracefully() -> None:
    src = "import numpy as np\nx = np.float ((( broken"
    out, applied = rewrite_source(src)
    assert applied == 0
    assert out == src


# ---------------------------------------------------------------------------
# 3) ``discover --fix`` end-to-end via the CLI.
# ---------------------------------------------------------------------------


def test_cli_discover_fix_writes_file(tmp_path: Path) -> None:
    file = _write(tmp_path, "m.py", "import numpy as np\nx = np.NaN\n")
    runner = CliRunner()
    # ``packaging`` is always installed in the dev env; it only acts as
    # the index-loading anchor for the discover scan. The actual --fix
    # rewrite is driven by KNOWN_FIXES + source bindings, not by which
    # indexes were loaded, so the numpy rewrite still fires.
    result = runner.invoke(
        app,
        ["discover", str(tmp_path), "--package", "packaging", "--fix", "--write"],
    )
    assert result.exit_code in (0, 1)
    out = file.read_text(encoding="utf-8")
    assert "np.nan" in out
    assert "np.NaN" not in out


def test_cli_discover_fix_dry_run_does_not_modify(tmp_path: Path) -> None:
    file = _write(tmp_path, "m.py", "import numpy as np\nx = np.NaN\n")
    original = file.read_text(encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["discover", str(tmp_path), "--package", "packaging", "--fix"],
    )
    # Dry-run is the default for --fix.
    assert file.read_text(encoding="utf-8") == original
    assert "would change" in result.stdout or "np.NaN" in result.stdout


# ---------------------------------------------------------------------------
# 4) ``repair --safe-only`` overrides project config.
# ---------------------------------------------------------------------------


def test_repair_safe_only_overrides_config(tmp_path: Path) -> None:
    """The --safe-only flag forces safe behaviour even when config opts in."""
    _write(
        tmp_path,
        "pycomprepair.toml",
        'target = "django>=5.0"\nunsafe_fixes = true\n',
    )
    _write(
        tmp_path,
        "m.py",
        "from django.utils.encoding import smart_text\n",
    )
    # Register django plugin manually (entry-points may be stale in dev env).
    from pycomprepair.plugins.django_v5 import plugin as django_plugin

    get_registry().register(django_plugin)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["repair", str(tmp_path), "--safe-only", "--dry-run"],
    )
    assert "unsafe-fixes=False" in result.stdout


def test_repair_skipped_unsafe_summary_when_unsafe_fixes_exist(
    tmp_path: Path,
) -> None:
    """The summary surfaces the count of skipped unsafe fixes."""
    _write(
        tmp_path,
        "m.py",
        "from django.utils.timezone import utc\n",
    )
    from pycomprepair.plugins.django_v5 import plugin as django_plugin

    get_registry().register(django_plugin)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["repair", str(tmp_path), "--target", "django>=5.0", "--dry-run"],
    )
    # DJA001 emits an unsafe Fix; with default safe-only, it is skipped.
    assert "skipped" in result.stdout.lower()


# ---------------------------------------------------------------------------
# 5) KNOWN_FIXES registry is well-formed (basic sanity).
# ---------------------------------------------------------------------------


def test_known_fixes_registry_covers_numpy_basics() -> None:
    for symbol in (
        "numpy.float",
        "numpy.int",
        "numpy.bool",
        "numpy.NaN",
        "numpy.product",
    ):
        assert symbol in KNOWN_FIXES, f"missing entry for {symbol}"
