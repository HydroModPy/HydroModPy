"""Unit tests for the ``SolverRunner`` Protocol and ``RunResult`` dataclass."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.solver.base.protocol import RunResult, SolverRunner


class DummyAdapter:
    """Minimal structural conformer used to exercise the Protocol."""

    process_type = "flow"
    solver_name = "dummy"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def setup(self, config: object) -> None:
        self.calls.append("setup")

    def build(self, plan: object) -> None:
        self.calls.append("build")

    def run(self) -> RunResult:
        self.calls.append("run")
        return RunResult(converged=True, iterations=1, wall_time_s=0.01)

    def extract(self, store: object) -> None:
        self.calls.append("extract")

    def cleanup(self) -> None:
        self.calls.append("cleanup")


class PartialAdapter:
    """Missing ``extract`` on purpose to check structural conformance."""

    process_type = "flow"
    solver_name = "partial"

    def setup(self, config: object) -> None:  # pragma: no cover - not exercised
        pass

    def build(self, plan: object) -> None:  # pragma: no cover
        pass

    def run(self) -> RunResult:  # pragma: no cover
        return RunResult(converged=False)

    def cleanup(self) -> None:  # pragma: no cover
        pass


def test_dummy_adapter_is_recognised_as_solver_adapter() -> None:
    assert isinstance(DummyAdapter(), SolverRunner)


def test_partial_adapter_fails_structural_check() -> None:
    assert not isinstance(PartialAdapter(), SolverRunner)


def test_lifecycle_order_on_dummy_adapter() -> None:
    adapter = DummyAdapter()
    adapter.setup(config=None)
    adapter.build(plan=None)
    result = adapter.run()
    adapter.extract(store=None)
    adapter.cleanup()

    assert adapter.calls == ["setup", "build", "run", "extract", "cleanup"]
    assert result.converged is True
    assert result.iterations == 1


def test_run_result_defaults() -> None:
    result = RunResult(converged=True)
    assert result.output_dir is None
    assert result.iterations is None
    assert result.residual is None
    assert result.diagnostics == {}


def test_run_result_accepts_output_dir(tmp_path: Path) -> None:
    result = RunResult(converged=True, output_dir=tmp_path)
    assert result.output_dir == tmp_path


def test_run_result_is_frozen() -> None:
    result = RunResult(converged=True)
    with pytest.raises(Exception):
        result.converged = False  # type: ignore[misc]
