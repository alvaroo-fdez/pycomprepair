from __future__ import annotations

import pytest

from pycomprepair.core.plugin import PluginRegistry, reset_registry
from pycomprepair.plugins.fastapi_migration import plugin as fastapi_plugin
from pycomprepair.plugins.pydantic_v2 import plugin as pydantic_plugin


@pytest.fixture
def registry() -> PluginRegistry:
    """Return a registry pre-loaded with the built-in plugins.

    Used by tests that prefer explicit registration over relying on entry
    points (which may not be installed in editable test environments).
    """
    reg = PluginRegistry()
    reg.register(pydantic_plugin)
    reg.register(fastapi_plugin)
    return reg


@pytest.fixture(autouse=True)
def _reset_global_registry() -> None:
    """Reset the singleton between tests so that they can register plugins
    deterministically."""
    reset_registry()
    yield
    reset_registry()
