"""Adapter for the ``flow/modflow6`` solver pair.

This module holds what is specific to MODFLOW 6: the construction of the
``Modflow6`` object, the metrics of its wells and of its steady start, its lake
observables, and ``rerun``, which solves a model again for a new K or Sy
without a build (``solver/modflow6/rerun.py``). The shared flow lifecycle lives
in ``hydromodpy.solver.modflow_common.flow_adapter_helpers``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any, ClassVar

import pandas as pd
from pydantic import BaseModel

from hydromodpy.core.contracts.observables import ObservableRequest, ObservableResult
from hydromodpy.core.exceptions import ObservableNotAvailableError
from hydromodpy.mesh.port import ANY_PLANAR_ENGINE
from hydromodpy.model.sinks_sources.wells import WELLS_PUMPED_METRIC
from hydromodpy.results.storage.kept import Retention
from hydromodpy.solver.base.cell_lookup import (
    locate_cell_on_solver_mesh,
    top_active_layer_on_solver_mesh,
)
from hydromodpy.solver.base.cleanup import cleanup_solver_files
from hydromodpy.solver.base.observables import (
    ObservableSupport,
    series_observable,
    servable,
    under_condition,
)
from hydromodpy.solver.base.plan import RunSlot, SolverRun
from hydromodpy.solver.base.registry import extractors
from hydromodpy.solver.modflow6.extractors.lake import extract_lake_series
from hydromodpy.solver.modflow6.modflow6 import Modflow6
from hydromodpy.solver.modflow6.modflow6_config import Modflow6Config
from hydromodpy.solver.modflow6.rerun import rerun_modflow6
from hydromodpy.solver.modflow_common.flow_adapter_helpers import (
    build_flow_model,
    build_preprocess_options,
    resolve_solver_run_output,
    run_flow_model,
)
from hydromodpy.solver.modflow_common.observable_extraction import (
    extract_common_modflow_observables,
)

# LAK observation states this adapter serves, and the unit each carries. The
# request names the state directly now that it also carries the lake in its
# ``key``, so there is no composed ``lake_<quantity>`` variable any more.
_LAKE_STATE_UNITS: dict[str, str] = {
    "stage": "m",
    "volume": "m3",
    "surface_area": "m2",
}


def _collapse_to_disv_cells(
    station_cells: Mapping[str, tuple[int, int, int]],
    model: Any,
) -> dict[str, tuple[int, int, int]]:
    """Map structured ``(layer, row, col)`` station cells to DISV ``(layer, 0, id)``.

    MF6 always writes DISV, whose head array is ``(nlay, 1, ncpl)``. A station that
    a record places by its row and column on a regular grid arrives as
    ``(layer, row, col)``, so the ``(row, col)`` is collapsed to the flat row-major
    ``cell2d`` id and the head is read as ``head[layer, 0, id]``. Without this,
    ``head[layer, row, col]`` indexes the size-1 middle axis and raises for any
    station off the first grid row. A station located by coordinates arrives as
    ``(layer, 0, id)`` already, which the collapse leaves as it is, and so are the
    cells of an unstructured mesh.
    """
    mesh = getattr(model, "solver_mesh", None)
    if mesh is None or not getattr(mesh, "is_structured", False):
        return dict(station_cells)
    ncol = int(mesh.ncol)
    return {sid: (int(k), 0, int(i) * ncol + int(j)) for sid, (k, i, j) in station_cells.items()}


class Modflow6FlowAdapter:
    """Bridge one planned ``flow/modflow6`` run to the ``Modflow6`` API."""

    name: ClassVar[str] = "modflow6"
    process_type: ClassVar[str] = "flow"
    accepted_meshes: ClassVar[frozenset[str]] = frozenset(
        {"regular", "triangle", "voronoi", ANY_PLANAR_ENGINE}
    )
    geometry: ClassVar[str] = "cells"
    writes: ClassVar[tuple[str, ...]] = (
        "face_flow",
        "head",
        "budget/constant_head",
        "budget/constant_head_stream",
        "budget/drain",
        "budget/drain_to_mover",
        "budget/evapotranspiration",
        "budget/lake",
        "budget/lake_to_mover",
        "budget/mover",
        "budget/recharge",
        "budget/storage_ss",
        "budget/storage_sy",
        "budget/stream",
        "budget/stream_to_mover",
        "budget/well",
        "derived/hydraulic_conductivity",
        "derived/hydraulic_conductivity_k22",
        "derived/hydraulic_conductivity_k33",
        "derived/conductivity_tensor_angle1",
        "derived/conductivity_tensor_angle2",
        "derived/conductivity_tensor_angle3",
        "derived/specific_storage",
        "derived/specific_yield",
        "mesh/idomain",
        "mesh/layer_thickness",
        "mesh/streambed_connection",
        "mesh/streambed_top",
        "mesh/topography",
        "lake_state_final/stage",
        "lake_abacus/*/stage",
        "lake_abacus/*/real_volume",
        "lake_abacus/*/real_sarea",
        "lake_abacus/*/sim_volume",
        "lake_abacus/*/sim_sarea",
        "budgets",
        "mass_balance",
        "sfr_reaches",
        "timeseries",
    )
    reads: ClassVar[tuple[str, ...]] = ()
    supports: ClassVar[frozenset[str]] = frozenset(
        {
            "west_side",
            "east_side",
            "north_side",
            "south_side",
            "ocean",
            "drainage",
            "stream",
            "lake",
            "sfr",
            "sink_fill",
            "drain_band_depth_m",
            "drain_bed_thickness_m",
            "drain_conductance_floor_m2_s",
            "head_rule",
            "steady_start",
            "cyclic_start",
            "prior_state",
            "recharge",
            "wells",
            "etp",
            "flow_barriers",
            "cutoff_wall",
            "soil",
            "k_tensor",
            "properties",
            "layers",
            "pass_through",
        }
    )
    options: ClassVar[type[BaseModel] | None] = Modflow6Config
    category: ClassVar[str] = "distributed"
    native_step: ClassVar[str | None] = None
    mutable: ClassVar[frozenset[str]] = frozenset({"K", "Sy"})
    requires: ClassVar[tuple[tuple[str, str], ...]] = ()

    def validate(self, model: Any, options: BaseModel | None, slot: RunSlot) -> None:
        """No precondition checks for MODFLOW 6 flow runs."""

    def build(
        self,
        model: Any,
        options: BaseModel | None,
        slot: RunSlot,
        upstream: tuple[SolverRun, ...] = (),
    ) -> SolverRun:
        """Build the MODFLOW 6 model of ``model`` in memory, under ``slot``.

        A flow follows no run, so ``upstream`` stays empty: the runner refuses a
        flow build that names one, and nothing past ``slot`` decides where the
        model goes. The method is intentionally thin:

        - resolve the shared preprocessing options from the ``Model``,
        - build the concrete ``Modflow6`` object in the folder and under the
          name the slot gives, with the binaries of the slot and the options,
        - delegate the rest to ``build_flow_model``, which hands the ``Model``
          and the slot to ``Modflow6.pre_processing``.
        """
        preprocess_options = build_preprocess_options(model)
        solver_model = Modflow6(
            model_folder=slot.folder,
            model_name=slot.name,
            bin_path=slot.bin_dir,
            modflow_config=options,
            preprocess_options=preprocess_options,
        )
        solver_model.link_mt3dms = "face_flow" in slot.hand_off
        return build_flow_model(solver_model, model, options, slot, preprocess_options)

    def run(self, solver_run: SolverRun) -> SolverRun:
        """Write the input files unless they are written, start, solve, and return the solved run.

        On top of the shared lifecycle, the run carries the share of the asked
        pumping its wells delivered, as a metric, and whether the steady solve
        it started from converged, which the runner reads before a transport.
        """
        result = run_flow_model(solver_run, solver_name=self.name)
        solver_model = result.solver_model
        handed_back: dict[str, Any] = {}
        pumped = getattr(solver_model, "well_pumped_percent", None)
        if pumped is not None:
            handed_back["metrics"] = {**result.metrics, WELLS_PUMPED_METRIC: float(pumped)}
        # Set by the auxiliary steady solve of a steady start, None for any other start.
        converged = getattr(solver_model, "initial_state_converged", None)
        if converged is not None:
            handed_back["initial_state_converged"] = bool(converged)
        return replace(result, **handed_back) if handed_back else result

    def rerun(self, previous: SolverRun, model: Any, slot: RunSlot) -> SolverRun | None:
        """Solve ``model`` again from the solved run ``previous``, for a new K or Sy.

        It copies the input files of ``previous`` into the folder of ``slot`` and
        rewrites NPF and DRN for K, STO for Sy, and the file of the properties.
        It consumes ``previous`` and returns ``None``, touching nothing, when the
        change needs a build (see :func:`~hydromodpy.solver.modflow6.rerun.rerun_modflow6`).
        """
        return rerun_modflow6(previous, model, slot, mutable=self.mutable)

    def extract(self, solver_run: SolverRun, store: Any, retention: Retention) -> None:
        """Write the fields and tables of a solved run through its registered extractor."""
        extractors.create(self.process_type, self.name).extract(solver_run, store, retention)

    def declared_observables(self, active: frozenset[str]) -> tuple[ObservableSupport, ...]:
        """Say what a run can serve, given the ids of the active conditions of ``[flow]``.

        MODFLOW 6 builds LAK and SFR when the file asks for them, so a lake stage
        and a routed reach discharge are one declaration away rather than out of
        reach. Everything else is served from the head and budget files this
        backend always writes.
        """
        active = {str(name).lower() for name in active}
        lake_declared = "lake" in active
        sfr_declared = "sfr" in active
        return (
            servable("head", "read at any cell from the head file"),
            servable("discharge", "integrated over the domain from the budget file"),
            servable("release_flux", "per-cell surface release, from the budget file"),
            servable("water_budget_percent_discrepancy", "reported by the listing file"),
            (
                servable("stage", "read from the LAK observation file")
                if lake_declared
                else under_condition(
                    "stage",
                    "declare the lake under flow.sinks_sources.lakes; MODFLOW 6 builds LAK "
                    "on that.",
                )
            ),
            (
                servable("routed_discharge", "read from the SFR reach outflow")
                if sfr_declared
                else under_condition(
                    "routed_discharge",
                    "declare the network under flow.sinks_sources.sfr; without it the "
                    "discharge at a cell is the "
                    "upstream accumulation of the release flux instead.",
                )
            ),
        )

    def locate_cell(self, solver_run: SolverRun, x: float, y: float) -> tuple[int, int, int] | None:
        """Return the cell that holds ``(x, y)`` on the mesh this run actually wrote."""
        return locate_cell_on_solver_mesh(solver_run, x, y)

    def top_active_layer(self, solver_run: SolverRun, row: int, col: int) -> int | None:
        """Return the top active layer of the column at ``(row, col)``, from the run's idomain."""
        return top_active_layer_on_solver_mesh(solver_run, row, col)

    def cleanup(self, solver_run: SolverRun) -> None:
        """Remove the scratch directory written by this run, if any."""
        if solver_run.output_dir is not None:
            cleanup_solver_files(solver_run.output_dir)

    def observables(
        self,
        solver_run: SolverRun,
        requests: Sequence[ObservableRequest],
        *,
        time_index: pd.DatetimeIndex | None = None,
    ) -> dict[str, ObservableResult]:
        """Read observables from the scratch CBC, HDS and LAK observation files of a run.

        MF6 binaries share the FloPy-readable format MODFLOW-NWT uses, so
        discharge, head and the per-cell fields come out of the shared helper.
        Lake states are MF6-only: the request names the state in ``name`` and
        the lake in ``key``, and they are read from the LAK observation CSV.
        A trial reads straight from ``solver_run.output_dir``.
        """
        if not requests:
            return {}
        output_dir, model, model_name = resolve_solver_run_output(
            solver_run, name_attributes=("model_output_name", "model_name", "name")
        )
        served, unserved = extract_common_modflow_observables(
            output_dir,
            model_name,
            model,
            requests,
            time_index=time_index,
            station_cell_mapper=lambda cells: _collapse_to_disv_cells(cells, model),
            routed_discharge_reader=_routed_discharge_series,
            reach_flow_reader=_reach_flow_by_cell,
        )
        for request in unserved:
            if request.support != "lake" or request.name not in _LAKE_STATE_UNITS:
                raise ObservableNotAvailableError(
                    f"MODFLOW 6 does not produce observable {request.name!r} on support "
                    f"{request.support!r}."
                )
            series = extract_lake_series(
                output_dir,
                model_name,
                lake_id=str(request.key),
                times=_saved_head_times(output_dir, model_name),
                quantity=request.name,
                time_index=time_index,
            )
            served[request.id] = series_observable(
                request, series, units=_LAKE_STATE_UNITS[request.name]
            )
        return served


def _saved_head_times(output_dir: Path, model_name: str) -> list[float]:
    """The stamps of the run: the times of its saved heads, one per stress period."""
    import flopy

    head_path = output_dir / f"{model_name}.hds"
    if not head_path.is_file():
        raise ObservableNotAvailableError(
            f"HDS file not found for model {model_name!r} in {output_dir}: the lake "
            "observations are put on the stress periods it stamps."
        )
    head_file = flopy.utils.HeadFile(str(head_path))
    try:
        return [float(value) for value in head_file.get_times()]
    finally:
        head_file.close()


def _reach_flow_by_cell(output_dir: Path, model_name: str) -> dict[int, Any] | None:
    """Routed streamflow per reach cell, or None when the run has no network.

    Injected the same way ``_routed_discharge_series`` is, and for the same
    reason: SFR exists only in this backend, and ``modflow_common`` must not
    import it.
    """
    import flopy

    from hydromodpy.solver.modflow6.extractors.sfr import reach_flow_by_cell
    from hydromodpy.solver.modflow_common.time_units import seconds_per_solver_time_unit

    head_path = output_dir / f"{model_name}.hds"
    if not head_path.is_file():
        return None
    times = flopy.utils.HeadFile(str(head_path)).get_times()
    return reach_flow_by_cell(
        output_dir,
        model_name,
        times=times,
        seconds_per_time_unit=seconds_per_solver_time_unit(output_dir, model_name),
    )


def _routed_discharge_series(
    output_dir: Path,
    model_name: str,
    time_index: pd.DatetimeIndex | None,
) -> pd.Series | None:
    """Discharge of a routed SFR network, or None when the run has no network.

    Injected into the shared observable extractor so ``modflow_common`` keeps no
    dependency on this backend: SFR exists only here.
    """
    import flopy

    from hydromodpy.solver.modflow6.extractors.sfr import routed_outflow_series
    from hydromodpy.solver.modflow_common.time_units import seconds_per_solver_time_unit

    head_path = output_dir / f"{model_name}.hds"
    if not head_path.is_file():
        return None
    times = flopy.utils.HeadFile(str(head_path)).get_times()
    values = routed_outflow_series(
        output_dir,
        model_name,
        times=times,
        seconds_per_time_unit=seconds_per_solver_time_unit(output_dir, model_name),
    )
    if values is None:
        return None
    if time_index is not None and len(time_index) >= len(values):
        return pd.Series(values, index=pd.DatetimeIndex(time_index[: len(values)]))
    return pd.Series(values)
