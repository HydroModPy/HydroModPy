"""Fixtures shared by the data-source tests of this directory.

The registry is process-global by design -- a name resolves to one class for
everything running in that interpreter -- so a test that registers a plugin
has to put the mappings back, and two modules need the same undoing.
"""

from __future__ import annotations

import pytest

from hydromodpy.data.source import registry


@pytest.fixture
def isolated_registry(monkeypatch: pytest.MonkeyPatch):
    """Give one test its own registry state, restored afterwards."""
    monkeypatch.setattr(registry, "_REGISTRY", dict(registry._REGISTRY))
    monkeypatch.setattr(registry, "_BUILTIN_PATHS", dict(registry._BUILTIN_PATHS))
    monkeypatch.setattr(registry, "_PLUGINS_LOADED", False)
    return registry
