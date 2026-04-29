"""Unit tests for the ``SolverAdapter`` Protocol and ``RunResult`` dataclass."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.solver.base.protocol import RunResult, SolverAdapter


class DummyAdapter:
    """Minimal structural conformer used to exercise the Protocol."""

    process_type = "flow"
    solver_name = "dummy"
    requires: tuple[tuple[str, str], ...] = ()

    def __init__(self) -> None:
        self.calls: list[str] = []

    def validate(self, ctx: object) -> None:
        self.calls.append("validate")

    def execute(self, ctx: object) -> object:
        self.calls.append("execute")
        return object()

    def cleanup(self, ctx: object) -> None:
        self.calls.append("cleanup")


class PartialAdapter:
    """Missing ``execute`` on purpose to check structural conformance."""

    process_type = "flow"
    solver_name = "partial"
    requires: tuple[tuple[str, str], ...] = ()

    def validate(self, ctx: object) -> None:  # pragma: no cover - not exercised
        pass

    def cleanup(self, ctx: object) -> None:  # pragma: no cover
        pass


def test_dummy_adapter_is_recognised_as_solver_adapter() -> None:
    assert isinstance(DummyAdapter(), SolverAdapter)


def test_partial_adapter_fails_structural_check() -> None:
    assert not isinstance(PartialAdapter(), SolverAdapter)


def test_lifecycle_order_on_dummy_adapter() -> None:
    adapter = DummyAdapter()
    adapter.validate(ctx=None)
    adapter.execute(ctx=None)
    adapter.cleanup(ctx=None)

    assert adapter.calls == ["validate", "execute", "cleanup"]


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
