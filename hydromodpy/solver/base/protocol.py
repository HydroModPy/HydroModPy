"""Structural Protocol describing the solver adapter lifecycle.

Every concrete backend (MODFLOW-NWT, MODFLOW 6, Boussinesq, or any third
party plugin) implements the same five-step contract so that the
orchestration layer stays solver-agnostic:

``setup`` → ``build`` → ``run`` → ``extract`` → ``cleanup``

Adapters conform *structurally*: there is no base class to inherit from.
The runner checks conformance via ``isinstance(obj, SolverAdapter)`` at
``@runtime_checkable`` time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class RunResult:
    """Outcome of a single ``SolverAdapter.run`` invocation."""

    converged: bool
    output_dir: Path | None = None
    wall_time_s: float | None = None
    iterations: int | None = None
    residual: float | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class SolverAdapter(Protocol):
    """Five-step lifecycle any HydroModPy solver backend must honour."""

    process_type: str
    solver_name: str

    def setup(self, config: Any) -> None:
        """Prepare the adapter from a resolved solver configuration."""

    def build(self, plan: Any) -> None:
        """Materialise solver inputs (packages, matrices, files)."""

    def run(self) -> RunResult:
        """Execute the numerical solver and return a ``RunResult``."""

    def extract(self, store: Any) -> None:
        """Push results into the simulation catalog / result store."""

    def cleanup(self) -> None:
        """Release handles, close binaries, delete scratch as needed."""


__all__ = ["RunResult", "SolverAdapter"]
