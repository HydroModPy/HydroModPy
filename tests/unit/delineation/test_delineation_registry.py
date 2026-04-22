"""Tests for the delineation backend registry."""

from __future__ import annotations

import pytest

from hydromodpy.spatial.delineation import registry
from hydromodpy.spatial.delineation.registry import (
    available_backends,
    clear_backend_cache,
    get_backend,
    register_backend,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_backend_cache()
    yield
    clear_backend_cache()


def test_available_backends_contains_known_names() -> None:
    names = set(available_backends())
    assert {"whitebox_workflows", "whitebox_cli", "pysheds", "synthetic"}.issubset(names)


def test_get_backend_unknown_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Unknown delineation backend"):
        get_backend("does_not_exist")


def test_get_backend_accepts_aliases() -> None:
    # default resolves to workflows
    default = get_backend()
    assert default.__class__.__name__ == "WhiteboxWorkflowsBackend"

    for alias in ("whitebox_workflows", "workflows", "wbw", "WBW"):
        clear_backend_cache()
        backend = get_backend(alias)
        assert backend.__class__.__name__ == "WhiteboxWorkflowsBackend"


def test_get_backend_caches_instances() -> None:
    first = get_backend("whitebox_workflows")
    second = get_backend("whitebox_workflows")
    assert first is second


def test_get_backend_for_stub_raises_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        get_backend("pysheds")
    with pytest.raises(NotImplementedError):
        get_backend("whitebox_cli")


def test_synthetic_backend_resolves() -> None:
    backend = get_backend("synthetic")
    assert backend.name == "synthetic"


def test_register_backend_can_add_custom_entry() -> None:
    class _FakeBackend:
        name = "fake"

    register_backend("fake", lambda: _FakeBackend)
    # Alias set is static, so the name must be registered via
    # register_backend's own slot; attempting to resolve via get_backend
    # will fail on the alias check — we exercise only the registry side.
    assert "fake" in available_backends()

    # Clean up for other tests.
    registry._BACKEND_LOADERS.pop("fake", None)
    clear_backend_cache()
