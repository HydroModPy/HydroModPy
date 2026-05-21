"""Bootstrap idempotence and hook-coverage tests."""

from __future__ import annotations

import importlib


def test_bootstrap_runs_once() -> None:
    """A first ``bootstrap()`` call wires every Protocol provider."""
    bootstrap_module = importlib.import_module("hydromodpy._bootstrap")
    bootstrap_module.bootstrap()

    from hydromodpy.core.config_kit import root_config_protocol
    from hydromodpy.core.contracts import solver_registry
    from hydromodpy.core.toml_io import dynamic_examples_protocol
    from hydromodpy.physics import contracts as physics_contracts
    from hydromodpy.spatial import protocols as spatial_protocols

    assert solver_registry._PROVIDER is not None
    assert root_config_protocol._PROVIDER is not None
    assert dynamic_examples_protocol._PROVIDER is not None
    assert physics_contracts._FIELD_PARAM_FACTORY is not None
    assert spatial_protocols._geology_data_source is not None


def test_bootstrap_idempotent() -> None:
    """Repeated ``bootstrap()`` calls do not replace already-installed providers."""
    bootstrap_module = importlib.import_module("hydromodpy._bootstrap")
    bootstrap_module.bootstrap()

    from hydromodpy.core.contracts import solver_registry

    first = solver_registry._PROVIDER
    bootstrap_module.bootstrap()
    bootstrap_module.bootstrap()

    assert solver_registry._PROVIDER is first


def test_bootstrap_hooks_listed() -> None:
    """The declarative hook table covers at least 5 register hooks."""
    bootstrap_module = importlib.import_module("hydromodpy._bootstrap")
    hooks = bootstrap_module._BOOTSTRAP_HOOKS
    assert isinstance(hooks, tuple)
    assert len(hooks) >= 5
    for hook in hooks:
        assert callable(hook)
    names = {hook.__name__ for hook in hooks}
    assert "_register_solver_registry_provider" in names
    assert "_rebuild_forward_refs" in names
