"""The ``SolverAdapter`` Protocol, and the attributes a backend registers with.

Every backend (MODFLOW-NWT, MODFLOW 6, Boussinesq, a third-party plugin) meets
this one contract, so the simulation runner stays solver-agnostic. Adapters
conform structurally: there is no base class to inherit from. A backend writes
the twelve attributes of the Protocol on its class and the five members the
runner calls, ``validate``, ``build``, ``run``, ``cleanup`` and ``extract``.
``solvers`` in ``solver/base/registry.py`` refuses a class that lacks one,
naming it.

Three members are optional and live outside the body of the Protocol, because
the registry requires every member of the body. ``rerun`` is present if and
only if ``mutable`` is not empty. ``observables`` and ``declared_observables``
come together or not at all. The conformance suite of ``tests/ports/test_solver.py`` reads
``RERUN_MEMBERS`` and ``OPTIONAL_MEMBERS`` to check both rules. A flow backend
also answers :class:`CellLocator`. The extractor a backend registers apart
answers :class:`OutputAdapter`.
"""

from __future__ import annotations

from typing import Any, ClassVar, Protocol, runtime_checkable

from pydantic import BaseModel

from hydromodpy.results.storage.kept import Retention
from hydromodpy.solver.base.plan import RunSlot, SolverRun

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

RERUN_MEMBERS: tuple[str, ...] = ("rerun",)
"""The members a backend carries if and only if its ``mutable`` is not empty.

``rerun(previous, model, slot) -> SolverRun | None`` solves ``model`` again from
the solved run ``previous`` when ``model`` differs from ``previous.model`` only by
properties named in ``mutable``. It writes into ``slot`` and rewrites only the
input files those properties touch. It consumes ``previous``: the solver model
of ``previous`` then describes the new run, and only the returned ``SolverRun``
serves as a parent afterwards. It returns ``None``, without touching anything,
when the change needs a new build, and the runner builds. The runner calls it
only when :func:`hydromodpy.solver.base.rerun.chooses_rerun` says so. This
``rerun`` has nothing to do with ``hmp catalog rerun``, which replays a sealed
run from its configuration.
"""

OPTIONAL_MEMBERS: tuple[str, ...] = ("observables", "declared_observables")
"""The members a flow backend carries together or not at all, for calibration.

``observables(solver_run, requests, *, time_index=None) -> dict[str, ObservableResult]``
reads every requested observable of a solved run, keyed by request id. The whole
batch arrives at once so a backend opens each binary file once, and a backend
driven through an API knows before the solve which timesteps to keep. A trial
reads straight from ``solver_run.output_dir``. A backend that cannot produce a
requested observable raises
:class:`~hydromodpy.core.exceptions.ObservableNotAvailableError` naming it: a
caller never reads a signature to find out what a backend supports.

``declared_observables(active) -> tuple[ObservableSupport, ...]`` says what a
run of the backend can serve before any run, given ``active``, the lowercase
ids of the active conditions of ``[flow]`` (``config.flow.active_bc``) as a
``frozenset[str]``. The adapter never reads the configuration itself.
"""


@runtime_checkable
class SolverAdapter(Protocol):
    """One adapter serves one ``(process_type, name)`` key.

    An adapter receives the frozen ``Model`` of the run
    (:class:`hydromodpy.model.model.Model`, the model of its flow for a
    transport), its validated options (an instance of ``options``, or ``None``)
    and the :class:`~hydromodpy.solver.base.plan.RunSlot` the runner filled. It
    returns a :class:`~hydromodpy.solver.base.plan.SolverRun`. It never changes
    the ``Model``: a solve leaves it as it found it, and an auxiliary solve runs
    on a variant that is a new object. An adapter reads nothing of the setup,
    the configuration or the store. ``build`` also receives the ``SolverRun``
    objects the runs it depends on produced, ``upstream``: empty for a flow,
    one run of the family its ``requires`` names for a transport, which reads
    the ``Model`` and the folder of that flow and takes ``face_flow`` from it.

    The runner calls ``validate``, then ``build``, then ``run`` unless
    ``slot.stop_before_solve``. The extract step calls ``extract``, and the
    export step calls ``cleanup`` when the run keeps no solver files.
    """

    name: ClassVar[str]
    """The solver name a TOML writes in ``solver.backend``, for example ``modflow6``."""

    process_type: ClassVar[str]
    """What the backend computes, ``flow`` or ``transport``. With ``name`` it makes the key."""

    accepted_meshes: ClassVar[frozenset[str]]
    """The mesh engine ids whose cells the backend reads.

    ``ANY_PLANAR_ENGINE`` of ``mesh/port.py`` stands for every engine whose cells
    are planar and that is not lumped; ``engine_accepted`` of ``mesh/registry.py``
    is the rule. A transport declares none: it reads the mesh of the flow it follows.
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
    """The products of an earlier run the backend reads: ``face_flow`` for a transport, none for a flow.

    Every name is one :data:`hydromodpy.results.field_registry.FIELD_REGISTRY`
    describes, and ``face_flow`` comes with ``connection_cells`` beside it in
    the store. A transport reads the flow of the run that precedes it.
    """

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

    def validate(self, model: Any, options: BaseModel | None, slot: RunSlot) -> None:
        """Refuse a run this backend cannot solve, before anything is built."""

    def build(
        self,
        model: Any,
        options: BaseModel | None,
        slot: RunSlot,
        upstream: tuple[SolverRun, ...] = (),
    ) -> SolverRun:
        """Build the solver model of ``model`` in memory, under ``slot``.

        A flow follows no run, so ``upstream`` stays empty. A transport receives
        exactly one run, of the family its ``requires`` names, and works in the
        folder of that flow. Nothing is written and nothing is solved: the
        result has ``written`` and ``solved`` false and carries the solver model.
        """

    def run(self, solver_run: SolverRun) -> SolverRun:
        """Write the input files unless ``solver_run.written``, solve, and return the solved run.

        The result lists the input files written in ``input_files``, has
        ``written`` and ``solved`` true, and names the folder the solver wrote in
        as ``output_dir``. A solve that fails raises a
        :class:`~hydromodpy.core.exceptions.SolverError` naming the run by
        ``solver_run.slot.name``; the runner sets its ``run_id``.
        """

    def cleanup(self, solver_run: SolverRun) -> None:
        """Remove the scratch files of a run once its results are stored."""

    def extract(self, solver_run: SolverRun, store: Any, retention: Retention) -> None:
        """Write the fields, tables and series of a solved run into its ``RunStore``.

        ``retention`` says which per-cell budget terms the run keeps. Every
        name written is one ``writes`` declares.
        """


@runtime_checkable
class OutputAdapter(Protocol):
    """The extractor of one backend, the port of the ``hydromodpy.solver.extractor`` group.

    The ``extract`` member of an adapter delegates to the extractor registered
    under the same key, ``<process_type>_<solver_name>``, which a plugin
    publishes through that entry point group. ``extractors`` in
    ``solver/base/registry.py`` refuses a class that lacks one of the members.
    """

    process_type: ClassVar[str]
    """What the run computed, ``flow`` or ``transport``, as the ``process_type`` of the adapter."""

    solver_name: ClassVar[str]
    """The ``name`` of the adapter whose run this extractor reads."""

    def extract(self, solver_run: SolverRun, store: Any, retention: Retention) -> None:
        """Write the fields, tables and series of ``solver_run`` into the ``RunStore`` ``store``.

        ``retention`` says which per-cell budget terms the run keeps. The run is
        found by its ``output_dir``, never by its name.
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

    def locate_cell(self, solver_run: SolverRun, x: float, y: float) -> tuple[int, int, int] | None:
        """Return the selector of the cell that holds ``(x, y)``, or ``None``.

        The selector is the same triple the observable extractors take. A MODFLOW 6
        run answers ``(layer, 0, cell_id)`` on every mesh, the flat selector of a DISV
        head array at the top active layer of the column; a point outside every
        cell takes the nearest center. ``None``
        means the run holds no solver model to look on, which a caller reports
        rather than replacing with a guess.
        """
        ...

    def top_active_layer(self, solver_run: SolverRun, row: int, col: int) -> int | None:
        """Return the top active layer of the column at ``(row, col)``, or ``None``.

        It is the layer a cell given without one is read at. A regular grid names
        the column by its row and column, any other mesh by row 0 and the cell id
        in ``col``. A column with no active cell answers 0. ``None`` means the run
        holds no solver model to look on. A cell outside the grid raises ValueError.
        """
        ...


def solver_members() -> tuple[str, ...]:
    """Return the members a backend class must carry, neither absent nor ``None``.

    The attributes of :class:`SolverAdapter` except ``NULLABLE_ATTRIBUTES``, then
    its five methods. The registry hook checks the two nullable ones. The
    optional members of ``RERUN_MEMBERS`` and ``OPTIONAL_MEMBERS`` are not here.
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


def extractor_members() -> tuple[str, ...]:
    """Return the members an extractor class must carry, those of :class:`OutputAdapter`."""
    attributes = tuple(OutputAdapter.__annotations__)
    methods = tuple(
        name
        for name, value in vars(OutputAdapter).items()
        if callable(value) and not name.startswith("_")
    )
    return attributes + methods


__all__ = [
    "CATEGORIES",
    "GEOMETRIES",
    "NULLABLE_ATTRIBUTES",
    "OPTIONAL_MEMBERS",
    "RERUN_MEMBERS",
    "CellLocator",
    "OutputAdapter",
    "SolverAdapter",
    "extractor_members",
    "solver_members",
]
