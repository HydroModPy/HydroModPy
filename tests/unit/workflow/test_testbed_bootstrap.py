"""Unit tests for the workflow testbed provider bootstrap hooks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hydromodpy.analysis.testbed import contracts as testbed_contracts
from hydromodpy.core.exceptions import PipelineError
from hydromodpy.workflow import testbed as workflow_testbed


class _StubProvider:
    """Minimal TestbedRunnerProvider implementation for tests."""

    def run_simulation(self, config_path: Path, *, no_display: bool) -> dict[str, Any]:
        return {"kind": "simulation", "path": config_path, "no_display": no_display}

    def run_comparison(self, config_path: Path) -> dict[str, Any]:
        return {"kind": "comparison", "path": config_path}


@pytest.fixture(autouse=True)
def _reset_registries():
    """Snapshot and restore module-level state mutated by the bootstrap hooks."""
    factory_snapshot = workflow_testbed._default_provider_factory
    provider_snapshot = testbed_contracts._provider
    try:
        workflow_testbed._default_provider_factory = None
        testbed_contracts._provider = None
        yield
    finally:
        workflow_testbed._default_provider_factory = factory_snapshot
        testbed_contracts._provider = provider_snapshot


def test_set_factory_then_register_installs_provider() -> None:
    """A factory set via the setter is consumed and installs its provider."""
    instance = _StubProvider()
    calls = {"count": 0}

    def factory() -> _StubProvider:
        calls["count"] += 1
        return instance

    workflow_testbed.set_default_testbed_runner_provider_factory(factory)
    assert workflow_testbed._default_provider_factory is factory

    workflow_testbed.register_default_testbed_runner_provider()
    assert calls["count"] == 1
    assert testbed_contracts.get_testbed_runner_provider() is instance


def test_register_is_idempotent_for_repeated_calls() -> None:
    """Calling the registration twice does not raise and keeps a valid provider."""

    def factory() -> _StubProvider:
        return _StubProvider()

    workflow_testbed.set_default_testbed_runner_provider_factory(factory)
    workflow_testbed.register_default_testbed_runner_provider()
    first = testbed_contracts.get_testbed_runner_provider()

    workflow_testbed.register_default_testbed_runner_provider()
    second = testbed_contracts.get_testbed_runner_provider()

    assert isinstance(first, _StubProvider)
    assert isinstance(second, _StubProvider)


def test_register_without_factory_raises_pipeline_error() -> None:
    """Without an injected factory, registration raises a clear PipelineError."""
    assert workflow_testbed._default_provider_factory is None

    with pytest.raises(PipelineError, match="Default testbed provider factory"):
        workflow_testbed.register_default_testbed_runner_provider()


def test_set_factory_overrides_previous_factory() -> None:
    """The setter replaces a previously injected factory."""
    first_instance = _StubProvider()
    second_instance = _StubProvider()

    workflow_testbed.set_default_testbed_runner_provider_factory(lambda: first_instance)
    workflow_testbed.set_default_testbed_runner_provider_factory(lambda: second_instance)
    workflow_testbed.register_default_testbed_runner_provider()

    assert testbed_contracts.get_testbed_runner_provider() is second_instance
