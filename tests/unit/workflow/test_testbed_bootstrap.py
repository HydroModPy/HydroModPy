"""Unit tests for the testbed provider bootstrap hook."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hydromodpy import _bootstrap
from hydromodpy.analysis.testbed import contracts as testbed_contracts
from hydromodpy.project.dispatch.workflow import ProjectTestbedRunnerProvider


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
    """Snapshot and restore module-level state mutated by the bootstrap hook."""
    provider_snapshot = testbed_contracts._provider
    adapters_snapshot = dict(testbed_contracts._workflow_adapters)
    try:
        testbed_contracts._provider = None
        yield
    finally:
        testbed_contracts._provider = provider_snapshot
        testbed_contracts._workflow_adapters.clear()
        testbed_contracts._workflow_adapters.update(adapters_snapshot)


def test_bootstrap_analysis_contract_installs_project_provider() -> None:
    _bootstrap._register_analysis_contracts()

    provider = testbed_contracts.get_testbed_runner_provider()
    assert isinstance(provider, ProjectTestbedRunnerProvider)


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
