"""The ``SolverAdapter`` Protocol, and the attributes a backend registers with.

Every backend (MODFLOW-NWT, MODFLOW 6, Boussinesq, a third-party plugin) meets
this one contract, so the simulation runner stays solver-agnostic. Adapters
conform structurally: there is no base class to inherit from. A backend writes
the twelve attributes of the Protocol on its class and the four methods the
runner calls. ``solvers`` in ``solver/base/registry.py`` refuses a class that
lacks one, naming it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Protocol, runtime_checkable

import pandas as pd
from pydantic import BaseModel

from hydromodpy.core.contracts.observables import ObservableRequest, ObservableResult
from hydromodpy.solver.base.plan import RunContext, RunExecutionResult

GEOMETRIES: tuple[str, ...] = ("cells", "raster")
"""The members of ``Model.geometry`` a backend can build its grid on.

``cells`` is the planar cell mesh, ``raster`` the DEM grid. The word names where
the grid comes from, not everything the backend reads: NWT builds on ``raster``
and also reads ``cells``.
"""

CATEGORIES: tuple[str, ...] = ("distributed", "integrated", "lumped")
"""How a backend resolves space: per cell, per cell with an integrated store, or one store."""

NULLABLE_ATTRIBUTES: tuple[str, ...] = ("options", "native_step")
"""The two attributes a backend may set to ``None``. Their presence is checked on the class."""


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
    """One adapter serves one ``(process_type, name)`` key.

    ``ctx.state`` is a :class:`~hydromodpy.core.state.run_state.RunState`: the
    setup scope, the configuration and the run identity (``sim_id``), and
    nothing else of the pipeline the run belongs to. An adapter
    that needs something the view does not carry is asking for something a run
    invoked from outside would not have.

    A flow adapter reads what it solves from ``ctx.state.setup.model``, the frozen
    :class:`~hydromodpy.model.model.Model` the ``prepare_solver`` step built for
    the run, and never from the ``Flow``, the domain, the cell mesh, the
    delineation or the configuration it was built from. It does not change the
    ``Model``: a solve leaves it as it found it, and an auxiliary solve runs on
    a variant that is a new object. The folder, the run id and the trial keys of
    ``setup.flow_runtime_overrides`` stay on ``setup``.
    """

    name: ClassVar[str]
    """The solver name a TOML writes in ``solver.backend``, for example ``modflow6``."""

    process_type: ClassVar[str]
    """What the backend computes, ``flow`` or ``transport``. With ``name`` it makes the key."""

    accepted_meshes: ClassVar[frozenset[str]]
    """The mesh engine ids whose cells the backend reads.

    ``ANY_PLANAR_ENGINE`` of ``mesh/port.py`` stands for every engine whose cells
    are planar. A transport declares none: it reads the mesh of the flow it follows.
    """

    geometry: ClassVar[str]
    """The member of ``Model.geometry`` the backend builds its grid on, one of ``GEOMETRIES``.

    A transport declares the value of the flow it follows.
    """

    writes: ClassVar[tuple[str, ...]]
    """The fields, tables and series the extractor writes, by their stored names.

    A field is its Zarr path (``head``, ``budget/drain``), a table its view name
    (``budgets``). A ``*`` stands only for a part the user names, such as a
    species, a lake or a station. The geometry the extractor adds to the mesh
    group (``z_interfaces``, the descent arrays) belongs to the mesh layout and
    is not listed.
    """

    reads: ClassVar[tuple[str, ...]]
    """The products of an earlier run the backend reads: ``face_flow`` for a transport, none for a flow."""

    supports: ClassVar[frozenset[str]]
    """The traits of the ``Model`` the backend honours, from the closed set of ``model/supports.py``.

    A boundary kind, an option of ``ModelOptions`` or an initial state. A trait
    left out is refused before the run rather than ignored by the solve.
    """

    options: ClassVar[type[BaseModel] | None]
    """The Pydantic class of the backend's own table, or ``None`` when it reads none."""

    category: ClassVar[str]
    """How the backend resolves space, one of ``CATEGORIES``. The seal writes it to the manifest."""

    native_step: ClassVar[str | None]
    """The step the solver advances at, as a pandas frequency alias.

    ``None`` means it advances at the step of ``Model.time``.
    """

    mutable: ClassVar[frozenset[str]]
    """The calibration parameters the backend can change between two solves of one model."""

    requires: ClassVar[tuple[tuple[str, str], ...]]
    """The ``(process_type, name)`` keys an earlier run of the plan must have run."""

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


def solver_members() -> tuple[str, ...]:
    """Return the members a backend class must carry, neither absent nor ``None``.

    The attributes of :class:`SolverAdapter` except ``NULLABLE_ATTRIBUTES``, then
    its four methods. The registry hook checks the two nullable ones.
    """
    attributes = tuple(
        name for name in SolverAdapter.__annotations__ if name not in NULLABLE_ATTRIBUTES
    )
    methods = tuple(
        name
        for name, value in vars(SolverAdapter).items()
        if callable(value) and not name.startswith("_")
    )
    return attributes + methods


__all__ = [
    "CATEGORIES",
    "GEOMETRIES",
    "NULLABLE_ATTRIBUTES",
    "CellLocator",
    "RunResult",
    "SolverAdapter",
    "solver_members",
]
