"""Single ``SolverAdapter`` Protocol.

Every concrete backend (MODFLOW-NWT, MODFLOW 6, Boussinesq, third-party
plugin) implements this same contract so the simulation runner stays
solver-agnostic. Adapters conform *structurally*: there is no base class to
inherit from, just four method signatures plus three ``ClassVar`` attributes
that identify the supported pair and its dependencies.
"""

from __future__ import annotations

import inspect
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Protocol, runtime_checkable

import pandas as pd

from hydromodpy.core.contracts.observables import ObservableRequest, ObservableResult
from hydromodpy.solver.base.plan import RunContext, RunExecutionResult


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


STOP_BEFORE_THE_SOLVE = "stop_before_the_solve"
"""Key of ``setup.flow_runtime_overrides``: build the model of this run and do not solve it.

``execute`` then returns the model alone, which is what a check that needs the model
before the first solve reads. An adapter that does not know the key solves, which
costs one solve and changes nothing else.
"""


@runtime_checkable
class SolverAdapter(Protocol):
    """One adapter binds one ``(process_type, solver_name)`` pair.

    ``ctx.state`` is a :class:`~hydromodpy.core.state.run_state.RunState`: the
    setup scope, the configuration and the run identity (``sim_id``), and
    nothing else of the pipeline the run belongs to. An adapter
    that needs something the view does not carry is asking for something a run
    invoked from outside would not have.
    """

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
        dir via ``ctx.output_dir``; ``store`` is the cold-path
        :class:`Catalog` reserved for backends that already wrote results
        to it.

        An adapter that cannot produce a requested observable raises
        :class:`~hydromodpy.core.exceptions.ObservableNotAvailableError` naming
        it. That refusal is the contract: a caller never reads a signature to
        find out what a backend supports.
        """


@runtime_checkable
class CellLocator(Protocol):
    """A backend that can turn coordinates into one of its own cell selectors.

    Separate from :class:`SolverAdapter` because it is a flow-adapter capability,
    not a property of every adapter: a transport adapter has no grid of its own
    to look on, and folding this into the base protocol would make it fail a
    structural check for a method it has no business having.

    A gauge, a piezometer and a lake staff are given as coordinates, and only the
    backend knows the grid it wrote: the cells of a solver mesh, or a flopy model
    grid. Answering here is what keeps a caller that must
    serve every solver from reading the internals of one.
    """

    def locate_cell(self, ctx: RunContext, x: float, y: float) -> tuple[int, int, int] | None:
        """Return the selector of the cell that holds ``(x, y)``, or ``None``.

        The selector is the same triple the observable extractors take. A MODFLOW 6
        run answers ``(layer, 0, cell_id)`` on every mesh, the flat selector of a DISV
        head array at the top active layer of the column; a point outside every
        cell takes the nearest center. ``None``
        means the run holds no grid to look on yet, which a caller reports rather
        than replacing with a guess.
        """
        ...

    def top_active_layer(self, ctx: RunContext, row: int, col: int) -> int | None:
        """Return the top active layer of the column at ``(row, col)``, or ``None``.

        It is the layer a cell given without one is read at. A regular grid names
        the column by its row and column, any other mesh by row 0 and the cell id
        in ``col``. A column with no active cell answers 0. ``None`` means the run
        holds no grid to look on yet. A cell outside the grid raises ValueError.
        """
        ...


@runtime_checkable
class MeshReadingAdapter(Protocol):
    """A flow adapter that names the mesh engines whose cells it can read.

    Separate from :class:`SolverAdapter` because a transport adapter reads the
    mesh of the flow it follows and declares none. The names are mesh engine ids,
    or :data:`~hydromodpy.spatial.mesh.port.ANY_PLANAR_ENGINE` for every engine
    whose cells are planar ones. A configuration that pairs the solver with
    another engine is refused before any meshing.
    """

    accepted_meshes: ClassVar[frozenset[str]]


def missing_adapter_members(candidate: object) -> tuple[str, ...]:
    """Return the members *candidate* has no attribute for.

    Presence only. Members are looked up with ``inspect.getattr_static``, as
    ``isinstance`` against a runtime Protocol does from Python 3.12, so a
    metaclass ``__getattr__`` that answers every name does not supply them.
    Python 3.11 still uses ``hasattr`` there. A member bound to ``None`` counts
    as present, so an empty tuple does not mean the candidate conforms.
    """
    missing = object()
    annotated = set(SolverAdapter.__annotations__)
    defined = {
        name
        for name, value in vars(SolverAdapter).items()
        if callable(value) and not name.startswith("_")
    }
    return tuple(
        name
        for name in sorted(annotated | defined)
        if inspect.getattr_static(candidate, name, missing) is missing
    )


__all__ = [
    "CellLocator",
    "MeshReadingAdapter",
    "RunResult",
    "SolverAdapter",
    "missing_adapter_members",
]
