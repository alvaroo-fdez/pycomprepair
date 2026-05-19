from __future__ import annotations

import textwrap
from pathlib import Path

from pycomprepair.core.engine import scan_path
from pycomprepair.core.plugin import PluginRegistry


def _write(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "app.py"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


def test_detects_on_event_startup(tmp_path: Path, registry: PluginRegistry) -> None:
    _write(
        tmp_path,
        """
        from fastapi import FastAPI

        app = FastAPI()

        @app.on_event("startup")
        async def boot():
            ...
        """,
    )
    issues = scan_path(tmp_path, "fastapi>=0.110", registry=registry)
    assert [i.code for i in issues] == ["FAS001"]
    assert issues[0].context["event"] == "startup"


def test_detects_on_event_shutdown(tmp_path: Path, registry: PluginRegistry) -> None:
    _write(
        tmp_path,
        """
        from fastapi import FastAPI

        app = FastAPI()

        @app.on_event("shutdown")
        async def bye():
            ...
        """,
    )
    issues = scan_path(tmp_path, "fastapi>=0.110", registry=registry)
    assert any(i.code == "FAS001" for i in issues)


def test_ignores_unrelated_decorator(tmp_path: Path, registry: PluginRegistry) -> None:
    _write(
        tmp_path,
        """
        @app.get("/")
        async def root():
            return {}
        """,
    )
    issues = scan_path(tmp_path, "fastapi>=0.110", registry=registry)
    assert [i for i in issues if i.code == "FAS001"] == []
