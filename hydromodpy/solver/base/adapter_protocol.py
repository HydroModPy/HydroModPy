"""Single ``SolverAdapter`` Protocol.

Every concrete backend (MODFLOW-NWT, MODFLOW 6, Boussinesq, third-party
plugin) implements this same contract so the simulation runner stays
solver-agnostic. Adapters conform *structurally*: there is no base class to
inherit from, just four method signatures plus three ``ClassVar`` attributes
that identify the supported pair and its dependencies.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Protocol, runtime_checkable

import pandas as pd

from hydromodpy.core.contracts.observables import ObservableRequest, ObservableResult
from hydromodpy.simulation.planning.plan import RunContext, RunExecutionResult


@dataclass(frozen=True)
class RunResult:
    """Generic outcome dataclass for plugin authors that need richer payloads
    than ``RunExecutionResult``.

    Not part of the canonical adapter signature: ``execute`` returns
    ``RunExecutionResult``. Reserved for diagnostics layers and external
    integrations that wrap the simulation runner.
    """

    converged: bool
    output_dir: Path | None = None
    wall_time_s: float | None = None
    iterations: int | None = None
    residual: float | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class SolverAdapter(Protocol):
    """One adapter binds one ``(process_type, solver_name)`` pair."""

    process_type: ClassVar[str]
    solver_name: ClassVar[str]
    requires: ClassVar[tuple[tuple[str, str], ...]]

    def validate(self, ctx: RunContext) -> None:
        """Fail-fast precondition checks before ``execute``."""

    def execute(self, ctx: RunContext) -> RunExecutionResult:
        """Run the concrete solver for ``ctx.run`` and return its outputs."""

    def cleanup(self, ctx: RunContext) -> None:
        """Release temporary scratch files after extraction completes."""

    def extract_observables(
        self,
        ctx: RunContext,
        store: Any,
        requests: Sequence[ObservableRequest],
        *,
        time_index: pd.DatetimeIndex | None = None,
    ) -> dict[str, ObservableResult]:
        """Read every requested observable from this run, keyed by request id.

        The whole batch arrives at once so a backend opens each binary file
        once instead of once per request, and a backend driven through an API
        knows before the solve which timesteps it has to keep.

        Lightweight calibration trials read straight from the solver scratch
        dir via ``ctx.state.execution.output_dirs_by_run_id``; ``store`` is the
        cold-path :class:`Catalog` reserved for backends that already wrote
        results to it.

        An adapter that cannot produce a requested observable raises
        :class:`~hydromodpy.core.exceptions.ObservableNotAvailableError` naming
        it. That refusal is the contract: a caller never reads a signature to
        find out what a backend supports.
        """


__all__ = ["RunResult", "SolverAdapter"]
