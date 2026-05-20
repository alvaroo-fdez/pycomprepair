from __future__ import annotations

import pytest

from pycomprepair.core.plugin import PluginRegistry, reset_registry
from pycomprepair.plugins.django_v5 import plugin as django_plugin
from pycomprepair.plugins.fastapi_migration import plugin as fastapi_plugin
from pycomprepair.plugins.numpy_v2 import plugin as numpy_plugin
from pycomprepair.plugins.pydantic_v2 import plugin as pydantic_plugin
from pycomprepair.plugins.sqlalchemy_v2 import plugin as sqlalchemy_plugin


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register CLI flags consumed by individual tests."""
    parser.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help="Rewrite golden fixtures with the current codemod output.",
    )


@pytest.fixture
def registry() -> PluginRegistry:
    """Return a registry pre-loaded with the built-in plugins.

    Used by tests that prefer explicit registration over relying on entry
    points (which may not be installed in editable test environments).
    """
    reg = PluginRegistry()
    reg.register(pydantic_plugin)
    reg.register(fastapi_plugin)
    reg.register(sqlalchemy_plugin)
    reg.register(django_plugin)
    reg.register(numpy_plugin)
    return reg


@pytest.fixture(autouse=True)
def _reset_global_registry() -> None:
    """Reset the singleton between tests so that they can register plugins
    deterministically."""
    reset_registry()
    yield
    reset_registry()
