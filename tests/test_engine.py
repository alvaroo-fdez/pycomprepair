from __future__ import annotations

from pathlib import Path

from pycomprepair.core.engine import repair_path, scan_path
from pycomprepair.core.plugin import PluginRegistry


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def test_engine_skips_syntax_errors(tmp_path: Path, registry: PluginRegistry) -> None:
    _write(tmp_path, "broken.py", "def oops(:\n")
    _write(
        tmp_path,
        "ok.py",
        "class M:\n    def go(self):\n        return self.dict()\n",
    )
    issues = scan_path(tmp_path, "pydantic>=2.0", registry=registry)
    assert any(i.code == "PYD001" for i in issues)


def test_engine_ignores_venv_dirs(tmp_path: Path, registry: PluginRegistry) -> None:
    venv = tmp_path / ".venv" / "lib"
    venv.mkdir(parents=True)
    _write(venv, "should_skip.py", "x = obj.dict()\n")
    _write(tmp_path, "include.py", "x = obj.dict()\n")

    issues = scan_path(tmp_path, "pydantic>=2.0", registry=registry)
    files = {str(i.file) for i in issues}
    assert any("include.py" in f for f in files)
    assert all(".venv" not in f for f in files)


def test_repair_dry_run_does_not_write(tmp_path: Path, registry: PluginRegistry) -> None:
    src = "x = obj.dict()\n"
    file = _write(tmp_path, "m.py", src)
    results = repair_path(tmp_path, "pydantic>=2.0", dry_run=True, registry=registry)
    assert len(results) == 1
    assert results[0].changed is True
    assert "model_dump" in results[0].new_source
    # Disk content is untouched.
    assert file.read_text(encoding="utf-8") == src


def test_repair_write_persists_changes(tmp_path: Path, registry: PluginRegistry) -> None:
    file = _write(tmp_path, "m.py", "x = obj.dict()\n")
    repair_path(tmp_path, "pydantic>=2.0", dry_run=False, registry=registry)
    assert "model_dump" in file.read_text(encoding="utf-8")


def test_plugin_does_not_match_v1_target(tmp_path: Path, registry: PluginRegistry) -> None:
    _write(tmp_path, "m.py", "x = obj.dict()\n")
    issues = scan_path(tmp_path, "pydantic>=1.0,<2.0", registry=registry)
    assert issues == []
