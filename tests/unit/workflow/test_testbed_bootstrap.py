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

    def run_calibration(self, config_path: Path) -> dict[str, Any]:
        return {"kind": "calibration", "path": config_path}


@pytest.fixture(autouse=True)
def _reset_registries():
    """Snapshot and restore module-level state mutated by the bootstrap hooks."""
    factory_snapshot = workflow_testbed._default_provider_factory
    provider_snapshot = testbed_contracts._provider
    adapters_snapshot = dict(testbed_contracts._workflow_adapters)
    try:
        workflow_testbed._default_provider_factory = None
        testbed_contracts._provider = None
        yield
    finally:
        workflow_testbed._default_provider_factory = factory_snapshot
        testbed_contracts._provider = provider_snapshot
        testbed_contracts._workflow_adapters.clear()
        testbed_contracts._workflow_adapters.update(adapters_snapshot)


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


def test_default_workflow_adapters_delegate_to_provider(tmp_path: Path) -> None:
    provider = _StubProvider()
    testbed_contracts.register_testbed_runner_provider(provider)
    config_path = tmp_path / "child.toml"

    simulation = testbed_contracts.run_testbed_child_workflow(
        runner_type="simulation",
        config_path=config_path,
        no_display=True,
    )
    comparison = testbed_contracts.run_testbed_child_workflow(
        runner_type="comparison",
        config_path=config_path,
    )
    calibration = testbed_contracts.run_testbed_child_workflow(
        runner_type="calibration",
        config_path=config_path,
    )

    assert testbed_contracts.testbed_runner_workflow("simulation") == "simulation"
    assert testbed_contracts.testbed_runner_workflow("comparison") == "comparison"
    assert testbed_contracts.testbed_runner_workflow("calibration") == "calibration"
    assert simulation == {"kind": "simulation", "path": config_path, "no_display": True}
    assert comparison == {"kind": "comparison", "path": config_path}
    assert calibration == {"kind": "calibration", "path": config_path}


def test_custom_workflow_adapter_can_be_registered(tmp_path: Path) -> None:
    class _CustomAdapter:
        runner_type = "custom"
        workflow = "custom_workflow"

        def run(
            self,
            provider: testbed_contracts.TestbedRunnerProvider,
            config_path: Path,
            *,
            no_display: bool,
        ) -> dict[str, Any]:
            return {
                "kind": "custom",
                "provider": type(provider).__name__,
                "path": config_path,
                "no_display": no_display,
            }

    testbed_contracts.register_testbed_runner_provider(_StubProvider())
    testbed_contracts.register_testbed_workflow_adapter(_CustomAdapter())

    config_path = tmp_path / "child.toml"
    result = testbed_contracts.run_testbed_child_workflow(
        runner_type="custom",
        config_path=config_path,
        no_display=True,
    )

    assert testbed_contracts.testbed_runner_workflow("custom") == "custom_workflow"
    assert result == {
        "kind": "custom",
        "provider": "_StubProvider",
        "path": config_path,
        "no_display": True,
    }
