"""The delineation backend registry: names, aliases, cache and custom entries."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.catchment.delineation.registry import (
    available_backends,
    backend_has_callables,
    clear_backend_cache,
    get_backend,
    register_backend,
    resolve_delineation_backend,
)
from hydromodpy.catchment.delineation.whitebox_workflows_backend import WhiteboxWorkflowsBackend


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_backend_cache()
    yield
    clear_backend_cache()


@pytest.mark.parametrize(
    "alias", [None, "whitebox_workflows", "workflows", "wbw", "WBW", "whitebox-workflows"]
)
def test_every_alias_resolves_to_the_workflows_backend(alias):
    assert "whitebox_workflows" in available_backends()
    assert isinstance(get_backend(alias), WhiteboxWorkflowsBackend)


def test_get_backend_caches_instances_until_the_cache_is_cleared():
    first = get_backend("whitebox_workflows")
    assert get_backend("wbw") is first
    clear_backend_cache()
    assert get_backend("wbw") is not first


@pytest.mark.parametrize(
    "name", ["does_not_exist", "pysheds", "whitebox_cli", "synthetic", "synthetic_bv"]
)
def test_an_unknown_or_retired_backend_is_refused(name):
    """The synthetic backend answered NotImplementedError to three of its four methods."""
    assert name not in available_backends()
    with pytest.raises(ValueError, match="Unknown delineation backend"):
        get_backend(name)


def test_register_backend_can_add_custom_entry(monkeypatch):
    from hydromodpy.catchment.delineation import registry

    monkeypatch.setattr(registry, "_BACKEND_LOADERS", dict(registry._BACKEND_LOADERS))

    def _missing():
        raise ImportError("No module named 'fake_engine'")

    register_backend(" Fake ", lambda: type("_FakeBackend", (), {"name": "fake"}))
    register_backend("absent", _missing)

    assert {"fake", "absent"} <= set(available_backends())
    assert get_backend("FAKE").name == "fake"
    with pytest.raises(ImportError, match="'absent' is not available: missing optional dependency"):
        get_backend("absent")


def test_an_injected_backend_wins_over_the_registry() -> None:
    injected = object()
    assert resolve_delineation_backend(injected) is injected
    assert resolve_delineation_backend() is get_backend()


_READ = SimpleNamespace(read=lambda: None, write=None)


@pytest.mark.parametrize(
    ("backend", "methods", "expected"),
    [
        (SimpleNamespace(), ("read",), False),
        (SimpleNamespace(raster=_READ), ("read",), True),
        (SimpleNamespace(raster=_READ), ("read", "write"), False),
    ],
    ids=["no-component", "every-method", "a-method-is-not-callable"],
)
def test_a_backend_has_a_capability_only_when_every_method_is_callable(
    backend, methods, expected
) -> None:
    assert backend_has_callables(backend, "raster", *methods) is expected
