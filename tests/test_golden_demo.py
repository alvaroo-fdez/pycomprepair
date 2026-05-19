"""End-to-end repair test against the demo file.

This guards the full Pydantic v1 -> v2 codemod pipeline against silent
regressions: any change in plugin behaviour that alters the final source
must be matched by an explicit update to the golden fixture.

Run with ``pytest -k golden -vv`` for a focused signal. To regenerate the
fixture after an intentional behaviour change, run::

    pytest tests/test_golden_demo.py --update-golden
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from pycomprepair.core.engine import repair_path
from pycomprepair.core.plugin import PluginRegistry

REPO_ROOT = Path(__file__).resolve().parent.parent
DEMO_SOURCE = REPO_ROOT / "examples" / "demo.py"
GOLDEN_PATH = Path(__file__).parent / "fixtures" / "demo_pydantic_v2.expected.py"


@pytest.fixture
def update_golden(request: pytest.FixtureRequest) -> bool:
    return bool(request.config.getoption("--update-golden", default=False))


def test_demo_pydantic_v2_golden(
    tmp_path: Path, registry: PluginRegistry, update_golden: bool
) -> None:
    """Repair ``examples/demo.py`` and assert it matches the stored golden.

    The demo is copied into ``tmp_path`` so the repository's own example file
    is never mutated by the test.
    """
    assert DEMO_SOURCE.exists(), f"missing demo source at {DEMO_SOURCE}"
    work_file = tmp_path / "demo.py"
    shutil.copyfile(DEMO_SOURCE, work_file)

    results = repair_path(tmp_path, "pydantic>=2.0", dry_run=True, registry=registry)
    assert len(results) == 1
    result = results[0]
    assert result.changed, "expected the demo to require at least one codemod"

    actual = result.new_source

    if update_golden:
        GOLDEN_PATH.write_text(actual, encoding="utf-8")
        pytest.skip(f"Updated golden fixture: {GOLDEN_PATH}")

    assert GOLDEN_PATH.exists(), (
        f"Golden fixture missing at {GOLDEN_PATH}. "
        "Run `pytest tests/test_golden_demo.py --update-golden` to create it."
    )
    expected = GOLDEN_PATH.read_text(encoding="utf-8")

    assert actual == expected, _diff_message(expected, actual)

    # And every expected migration must be present (defence in depth: catches
    # accidental fixture overwrites that would otherwise mask regressions).
    assert "from pydantic import field_validator" in actual
    assert "@field_validator(\"name\")" in actual
    assert "User.model_validate(" in actual
    assert "u.model_dump()" in actual
    assert "u.model_dump_json()" in actual
    assert "u.model_copy()" in actual


def test_demo_issue_codes_are_stable(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    """The demo must exercise the full curated set of v1 -> v2 rules."""
    work_file = tmp_path / "demo.py"
    shutil.copyfile(DEMO_SOURCE, work_file)

    results = repair_path(tmp_path, "pydantic>=2.0", dry_run=True, registry=registry)
    codes = sorted({i.code for i in results[0].issues})
    assert codes == ["PYD001", "PYD002", "PYD003", "PYD005", "PYD006", "PYD008"]


def _diff_message(expected: str, actual: str) -> str:
    import difflib

    diff = difflib.unified_diff(
        expected.splitlines(keepends=True),
        actual.splitlines(keepends=True),
        fromfile="expected (golden)",
        tofile="actual (codemod output)",
    )
    return "Codemod output does not match the golden fixture:\n" + "".join(diff)
