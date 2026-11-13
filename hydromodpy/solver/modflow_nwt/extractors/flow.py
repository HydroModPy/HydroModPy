"""Output adapter for MODFLOW-NWT flow solver results.

The flow extractor takes the dry-cell sentinels from the options of the run, and the
start date and the vertical layout from its ``Model``.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.core.budget.terms import BudgetKeep
from hydromodpy.core.exceptions import (
    ExtractError,
    IncompatibleMeshError,
    MeshError,
    NothingThereError,
)
from hydromodpy.core.fields.vertical_column import (
    VERTICAL_LAYOUT_COLUMN_FRACTIONS,
    layer_interfaces,
)
from hydromodpy.core.logging import get_logger
from hydromodpy.core.scope import CATCHMENT, DOMAIN
from hydromodpy.core.time.window import time_grid_start
from hydromodpy.core.units.time import (
    CF_EPOCH,
    CF_TIME_UNITS,
    cf_time_axis_seconds,
)
from hydromodpy.results.field_registry import CONNECTION_CELLS, FACE_FLOW
from hydromodpy.results.storage.final_state import FinalState, write_final_state
from hydromodpy.results.storage.kept import Retention
from hydromodpy.solver.base.plan import SolverRun
from hydromodpy.solver.modflow_common.budget_components import (
    canonical_budget_component,
    is_scalar_budget_component,
)
from hydromodpy.solver.modflow_common.budget_policy import record_budget_policy
from hydromodpy.solver.modflow_common.calibration_extractors import open_cell_budget
from hydromodpy.solver.modflow_common.descent_store import (
    descent_sidecar_path,
    read_descent_sidecar,
    write_descent_sidecar_to_store,
)
from hydromodpy.solver.modflow_common.field_slab import slab_steps
from hydromodpy.solver.modflow_common.flow_run import end_of_last_period, final_state_head
from hydromodpy.solver.modflow_common.period_steps import (
    budget_file_steps,
    group_steps_by_stamp,
    period_end_positions,
    period_mean_balance,
    weighted_period_mean,
    weighted_period_scalar,
)
from hydromodpy.solver.modflow_common.time_units import (
    read_itmuni_from_dis,
    seconds_per_itmuni,
)

logger = get_logger(__name__)

# Reading the IBOUND back loads the DIS and BAS6 packages by their bare ``mfnwt`` name,
# and flopy says that the program is not on the PATH. The solver binary is not run here.
warnings.filterwarnings(
    "ignore",
    message="The program .* does not exist or is not executable",
    category=UserWarning,
    module=r"flopy\.mbase",
)


# The DIS arrays are written with six significant digits (E15.6), so the grid the
# solver read is the stored one to this share of the larger grid side.
_DIS_GRID_TOLERANCE = 1e-6

# The three intercell flux records of a MODFLOW-NWT CBC file, in the direction
# their face points: right along a row, front along a column, lower along a layer.
_FACE_RECORDS = ("FLOW RIGHT FACE", "FLOW FRONT FACE", "FLOW LOWER FACE")


def face_connections(
    right: np.ndarray, front: np.ndarray, lower: np.ndarray, *, active: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Pair the cells each face record links and return the flux of the step.

    ``right``, ``front`` and ``lower`` are one step of the three CBC records,
    each shaped like ``active``. A value sits at the cell it leaves and is
    positive towards the larger flat index ``k * nrow * ncol + i * ncol + j``,
    so the flow from the right of ``(k, i, j)`` reaches ``(k, i, j+1)``, the
    flow from its front reaches ``(k, i+1, j)`` and the flow below it reaches
    ``(k+1, i, j)``. ``cells`` is ``(connection, 2)``, the smaller flat index
    first and sorted by pair; ``flows`` holds the value of each pair with that
    sign. The last column, row and layer carry no face, and a pair that touches
    an inactive cell is left out.
    """
    shape = np.shape(active)
    nlay, nrow, ncol = shape
    is_active = np.asarray(active, dtype=bool).reshape(-1)
    right_mask = np.ones(shape, dtype=bool)
    right_mask[:, :, -1] = False
    front_mask = np.ones(shape, dtype=bool)
    front_mask[:, -1, :] = False
    lower_mask = np.ones(shape, dtype=bool)
    lower_mask[-1, :, :] = False
    pairs = []
    for record, mask, offset in (
        (right, right_mask, 1),
        (front, front_mask, ncol),
        (lower, lower_mask, nrow * ncol),
    ):
        mask = mask.reshape(-1)
        values = np.asarray(record, dtype="float64")
        if values.shape != shape:
            raise ExtractError(
                f"A face record holds {values.shape} and the grid {shape}; the face "
                "flows of this run cannot be read"
            )
        values = values.reshape(-1)
        first = np.flatnonzero(mask)
        second = first + offset
        kept = is_active[first] & is_active[second]
        pairs.append((first[kept], second[kept], values[first[kept]]))
    first = np.concatenate([pair[0] for pair in pairs])
    second = np.concatenate([pair[1] for pair in pairs])
    flows = np.concatenate([pair[2] for pair in pairs])
    order = np.lexsort((second, first))
    cells = np.stack((first[order], second[order]), axis=1).astype(np.int32)
    return cells, flows[order]


def _step_face_records(
    read: Any, records: dict[tuple[str, Any], int], key: Any, shape: tuple[int, int, int]
) -> list[np.ndarray] | None:
    """Return the three face records of one saved step, or ``None`` when it saved none.

    MODFLOW-NWT writes no ``FLOW LOWER FACE`` on one layer, no ``FLOW FRONT
    FACE`` on one row and no ``FLOW RIGHT FACE`` on one column: that axis has
    no face, so its record is zero. A record missing on an axis longer than one
    is a budget file this code cannot read, and it raises. ``read`` returns the
    record at an index of the file, shaped like the grid.
    """
    nlay, nrow, ncol = shape
    found = [records.get((name, key)) for name in _FACE_RECORDS]
    if all(index is None for index in found):
        return None
    arrays: list[np.ndarray] = []
    for name, index, length in zip(_FACE_RECORDS, found, (ncol, nrow, nlay), strict=True):
        if index is not None:
            arrays.append(np.asarray(read(index), dtype="float64"))
        elif length == 1:
            arrays.append(np.zeros(shape, dtype="float64"))
        else:
            raise ExtractError(
                f"The budget file saved no {name!r} at step {key} of a grid {shape}; "
                "the face flows of this run cannot be read"
            )
    return arrays


def _active_cells(
    solver_output_dir: Path, model_name: str, nlay: int, nrow: int, ncol: int
) -> np.ndarray:
    """Return the active mask of the grid, read from the IBOUND of BAS6.

    IBOUND < 0 is a constant-head cell, which carries a face like any active
    cell, so the mask is ``ibound != 0``.
    """
    import flopy

    nam_path = Path(solver_output_dir) / f"{model_name}.nam"
    try:
        model = flopy.modflow.Modflow.load(
            str(nam_path),
            model_ws=str(solver_output_dir),
            load_only=["DIS", "BAS6"],
            check=False,
            verbose=False,
            exe_name="mfnwt",
        )
        ibound = np.asarray(model.bas6.ibound.array, dtype=np.int64).reshape(nlay, nrow, ncol)
    except Exception as exc:
        raise ExtractError(
            f"Could not read the IBOUND of {nam_path}; the face flows of this run cannot be read"
        ) from exc
    return ibound != 0


def verify_dis_grid(
    modelgrid: Any,
    root: Any,
    *,
    nrow: int,
    ncol: int,
    sim_id: str,
) -> float | None:
    """Compare the DIS grid the solver read with the regular mesh the run stored.

    The shape, the cell rings (the pattern of the regular engine) and the
    vertices are compared; a difference raises ``IncompatibleMeshError``. The
    return value is the largest vertex shift in meters, ``None`` when the store
    holds no geometry (a warning, and nothing is checked).
    """
    mesh = root["mesh"] if "mesh" in root else {}
    if "vertices" not in mesh or "face_node_connectivity" not in mesh:
        logger.warning(
            "Run %s stores no mesh geometry: the solved grid is not checked and no vertex is written.",
            sim_id,
        )
        return None
    stored_shape = mesh.attrs.get("structured_shape")
    if stored_shape is None or tuple(int(v) for v in stored_shape) != (int(nrow), int(ncol)):
        raise IncompatibleMeshError(
            f"Run {sim_id}: the solver grid is {nrow} x {ncol} cells, the stored mesh is "
            f"{'not a regular grid' if stored_shape is None else tuple(stored_shape)}"
        )
    columns = int(ncol) + 1
    first = (np.arange(nrow)[:, None] * columns + np.arange(ncol)[None, :]).ravel()
    expected = np.column_stack([first, first + 1, first + columns + 1, first + columns])
    stored_rows = np.asarray(mesh["face_node_connectivity"][:])
    if stored_rows.shape != expected.shape or not np.array_equal(stored_rows, expected):
        raise IncompatibleMeshError(
            f"Run {sim_id}: the stored cell rings are not those of a regular {nrow} x {ncol} grid"
        )
    stored_xy = np.asarray(mesh["vertices"][:])[:, :2]
    solved_x = np.asarray(modelgrid.xvertices, dtype=np.float64).ravel()
    solved_y = np.asarray(modelgrid.yvertices, dtype=np.float64).ravel()
    if solved_x.size != stored_xy.shape[0]:
        raise IncompatibleMeshError(
            f"Run {sim_id}: the solver grid has {solved_x.size} vertices, the stored mesh "
            f"{stored_xy.shape[0]}"
        )
    shift = np.maximum(np.abs(solved_x - stored_xy[:, 0]), np.abs(solved_y - stored_xy[:, 1]))
    span = float(np.ptp(stored_xy, axis=0).max())
    if not (shift <= _DIS_GRID_TOLERANCE * span).all():
        vertex = int(np.argmax(shift))
        raise IncompatibleMeshError(
            f"Run {sim_id}: vertex {vertex} of the solver grid is {float(shift[vertex]):.3g} m "
            f"from the stored mesh (allowed {_DIS_GRID_TOLERANCE * span:.3g} m)"
        )
    logger.info(
        "Run %s: the solver grid matches the stored mesh (largest vertex shift %.3g m).",
        sim_id,
        float(shift.max()),
    )
    return float(shift.max())


def catchment_basin_the_build_left(solver_output_dir: Path, *, n_cells: int) -> np.ndarray | None:
    """Cells of the basin of D the build left beside the model, None without a catchment.

    The calibration trial sums the drains over this basin. The budget row of
    the catchment uses the same cells, so a saved run and its trial read the
    same water. A basin that is only the largest one of a domain with neither
    outlet nor polygon is no catchment.
    """
    sidecar = descent_sidecar_path(solver_output_dir)
    if sidecar is None:
        return None
    try:
        record = read_descent_sidecar(sidecar)
    except ValueError as exc:
        logger.warning("No catchment budget row: unreadable descent sidecar (%s).", exc)
        return None
    if record is None or record.basin is None or record.basin_rule == "largest_basin":
        return None
    basin = np.asarray(record.basin, dtype=bool).ravel()
    if basin.size != n_cells or not basin.any():
        return None
    return basin


def _write_time_coordinate(
    store: Any,
    sim_id: str,
    times: list[float],
    itmuni: int,
    start_datetime: object | None,
) -> None:
    """Persist solver times as a CF axis at field-array resolution."""
    writer = getattr(store, "write_time", None)
    if writer is None:
        raise TypeError("Simulation store must implement write_time().")
    relative = np.asarray(times, dtype=float) * seconds_per_itmuni(itmuni)
    values = cf_time_axis_seconds(relative, start_datetime)
    writer(sim_id, values, epoch=CF_EPOCH, units=CF_TIME_UNITS)


def _vertical_layout_of(model: Any) -> str:
    """Return how the layers of the ``Model`` were built, the default for a run without one."""
    if model is None:
        return VERTICAL_LAYOUT_COLUMN_FRACTIONS
    return model.geometry.domain.config.layers.vertical_layout


def _listing_path(solver_output_dir: Path, model_name: str) -> Path:
    """Return the listing file MODFLOW-NWT wrote for ``model_name``.

    FloPy declares the LIST unit with the ``.list`` extension, so the listing
    never shares the ``.lst`` suffix MODFLOW 6 uses. Deriving it from the
    ``.hds`` stem with the wrong suffix silently skips the mass balance.
    """
    return Path(solver_output_dir) / f"{model_name}.list"


def _budget_field(row: np.void, names: tuple[str, ...] | None, key: str) -> float:
    """Return one listing-budget field, or 0.0 when the column is absent.

    FloPy already normalizes the listing column names (``TOTAL IN`` becomes
    ``TOTAL_IN``), so the canonical key is the only spelling to look up.
    """
    return float(row[key]) if names is not None and key in names else 0.0


class ModflowNwtOutputAdapter:
    """Read MODFLOW-NWT binary outputs and inject them into a Catalog.

    Expects a solver output directory containing ``{model_name}.hds``,
    ``{model_name}.cbc``, and optionally ``{model_name}.list``.
    """

    process_type = "flow"
    solver_name = "modflow_nwt"

    def extract(self, solver_run: SolverRun, store: Any, retention: Retention) -> None:
        """Read the ``.hds`` and ``.cbc`` files of a solved run and write its fields into the store.

        ``hdry`` and ``hnoflo`` are the sentinels the run was configured with
        (``[solver.modflow_nwt.runtime.upw] hdry`` and
        ``[solver.modflow_nwt.runtime.bas] hnoflo``), read on the options of the
        run. They carry no default: masking a user's heads against the stock
        -100 / -9999 would silently keep sentinel values in the field, or blank
        out real heads that happen to sit near them.

        ``retention.budget`` says which per-cell budget terms go under
        ``budget/``. The lumped budget table holds every term whatever it says.
        The vertical layout, as ``[domain.layers]`` gives it, and the start date
        come from the ``Model`` of the run; the store keeps the layout on
        ``mesh/``. A run without a ``Model`` takes the default layout and no date.

        The extraction ends by writing ``final_state/`` of the run folder: the
        head of the last period, read in double precision, with the two
        sentinels masked. MODFLOW-NWT has no lake or reach stage to keep.
        """
        import flopy.utils.binaryfile as bf

        sim_id = store.sim_id
        runtime = solver_run.options.runtime
        hdry, hnoflo = float(runtime.upw.hdry), float(runtime.bas.hnoflo)
        budget_terms = retention.budget
        start_datetime = time_grid_start(
            None if solver_run.model is None else solver_run.model.time.grid
        )
        vertical_layout = _vertical_layout_of(solver_run.model)
        solver_output_dir = Path(solver_run.output_dir)
        hds_files = list(solver_output_dir.glob("*.hds"))
        if not hds_files:
            raise NothingThereError(f"No .hds file in {solver_output_dir}")
        model_name = hds_files[0].stem

        hds_path = solver_output_dir / f"{model_name}.hds"
        cbc_path = solver_output_dir / f"{model_name}.cbc"

        head_file = bf.HeadFile(str(hds_path))
        # The OC saves every time step of a period cut into several, which the
        # particle tracking reads. The store keeps one slice per stress period:
        # the head at the last step of each period, the stamp that closes it.
        saved_times = head_file.get_times()
        saved_kstpkpers = head_file.get_kstpkper()
        period_ends = period_end_positions(saved_kstpkpers)
        times = [saved_times[i] for i in period_ends]
        kstpkpers = [saved_kstpkpers[i] for i in period_ends]
        n_timesteps = len(times)
        itmuni = read_itmuni_from_dis(solver_output_dir / f"{model_name}.dis") or 0
        flux_scale_to_m3_s = 1.0 / seconds_per_itmuni(itmuni)
        # Write /time at field-array resolution. MODFLOW-2005/NWT output carries
        # no start date, so anchor to the launcher start_datetime so the CF axis
        # decodes to real dates instead of relative seconds since 1970.
        _write_time_coordinate(store, sim_id, times, itmuni, start_datetime)

        head0 = head_file.get_data(totim=times[0])
        nlay, nrow, ncol = head0.shape
        n_cells = nrow * ncol

        logger.info(
            "Extracting MODFLOW-NWT results: %d timesteps, %d layers, %d cells",
            n_timesteps,
            nlay,
            n_cells,
        )

        # Mask HDRY/HNOFLO sentinels to NaN so all downstream consumers
        # (watertable, seepage, cross-section, etc.) receive clean data.
        # Batched stack writes: per-timestep writes into a sharded Zarr array
        # cost one whole-shard read-modify-write per timestep.
        head_slab = slab_steps(nlay, n_cells)
        for t0 in range(0, n_timesteps, head_slab):
            t1 = min(t0 + head_slab, n_timesteps)
            slab = np.empty((t1 - t0, nlay, n_cells), dtype="float64")
            for t in range(t0, t1):
                head = head_file.get_data(totim=times[t])
                slab[t - t0] = head.reshape(nlay, n_cells)
            slab[np.isclose(slab, hdry, atol=1.0)] = np.nan
            slab[np.isclose(slab, hnoflo, atol=1.0)] = np.nan
            store.write_field_stack(
                sim_id,
                "head",
                slab,
                n_timesteps=n_timesteps,
                timestep_offset=t0,
            )

        if cbc_path.exists():
            self._extract_budget(
                sim_id,
                store,
                cbc_path,
                times,
                kstpkpers,
                nlay,
                nrow,
                ncol,
                budget_terms=budget_terms,
                flux_scale_to_m3_s=flux_scale_to_m3_s,
                catchment_mask=catchment_basin_the_build_left(solver_output_dir, n_cells=n_cells),
            )
            if retention.face_flows:
                self._extract_face_flows(
                    sim_id,
                    store,
                    cbc_path,
                    solver_output_dir,
                    model_name,
                    kstpkpers,
                    nlay,
                    nrow,
                    ncol,
                    flux_scale_to_m3_s=flux_scale_to_m3_s,
                )
        else:
            record_budget_policy(store, sim_id, budget_terms, ())

        lst_path = _listing_path(solver_output_dir, model_name)
        if lst_path.exists():
            self._extract_mass_balance(
                sim_id,
                store,
                lst_path,
                flux_scale_to_m3_s,
                stamp_keys=[(int(kstp), int(kper)) for kstp, kper in kstpkpers],
            )

        final_head = final_state_head(
            head_file.get_data(totim=times[-1]),
            nlay=nlay,
            n_cells=n_cells,
            sentinels=(hdry, hnoflo),
        )
        head_file.close()
        write_final_state(
            Path(store.run_dir_for(sim_id)),
            FinalState(
                head=final_head,
                at=end_of_last_period(
                    start_datetime, float(times[-1]) * seconds_per_itmuni(itmuni)
                ),
            ),
        )

        self._write_surface_elevation(
            sim_id,
            store,
            solver_output_dir,
            model_name,
            nlay,
            nrow,
            ncol,
            vertical_layout=vertical_layout,
        )

    def _extract_budget(
        self,
        sim_id: str,
        store: Any,
        cbc_path: Path,
        times: list,
        kstpkpers: list,
        nlay: int,
        nrow: int,
        ncol: int,
        *,
        budget_terms: BudgetKeep = BudgetKeep.everything(),
        flux_scale_to_m3_s: float = 1.0,
        catchment_mask: np.ndarray | None = None,
    ) -> None:
        """Extract the scalar stress and storage terms of the .cbc file.

        ``times`` and ``kstpkpers`` are the stamps, one per stress period at
        its last step. A stamp closes its period, so each flux is the mean of
        the saved steps since the previous stamp, weighted by their length
        (the ``delt`` of the compact record header). A stamp that closes one
        step keeps that step unchanged.

        FLOW RIGHT/FRONT/LOWER FACE are dropped here, as they already are on
        the MODFLOW 6 path: they are antisymmetric intercell fluxes that net
        to zero, so neither the scalar budget table nor a per-cell budget
        field means anything on them. Kept, they also write one full
        (n_steps, nlay, n_cells) array per direction that no field of the
        registry names and that every walk of ``budget/`` picks up. They feed
        ``face_flow`` instead, one value per connection, in
        ``_extract_face_flows``.

        The budget table holds every scalar record. A per-cell field is built
        and written only for a term ``budget_terms`` keeps. The ``budget/``
        attributes record the policy and the terms kept.

        ``catchment_mask`` adds a ``zone_id = 'catchment'`` row per record, the
        sum over those cells. The domain row spans the buffered box; without
        the catchment row, a run that keeps no per-cell drain has only it to
        build its catchment discharge from.
        """

        cbb = open_cell_budget(cbc_path)
        record_names = [
            name
            for name in (record.decode().strip() for record in cbb.get_unique_record_names())
            if is_scalar_budget_component(name)
        ]
        steps = budget_file_steps(cbb)
        groups = group_steps_by_stamp(
            steps.keys,
            steps.lengths,
            [(int(kstp), int(kper)) for kstp, kper in kstpkpers],
        )

        n_cells = nrow * ncol
        n_timesteps = len(times)
        catchment_cells = np.flatnonzero(catchment_mask) if catchment_mask is not None else None
        budget_records: list[dict] = []
        budget_slab = slab_steps(nlay, n_cells)
        written: set[str] = set()
        for component in record_names:
            comp_key = canonical_budget_component(component)
            # No synthetic term is built from an NWT record: a slab only for a kept term.
            per_cell = budget_terms.keeps(comp_key)
            slab_stack: np.ndarray | None = None
            window_t0 = 0
            spatial_written = False
            for group in groups:
                t = group.stamp
                arrays: list[np.ndarray] = []
                weights: list[float] = []
                for position, weight in zip(group.positions, group.weights, strict=True):
                    idx = steps.record.get((component, steps.keys[position]))
                    if idx is None:
                        continue
                    try:
                        data = cbb.get_record(idx, full3D=True)
                    except Exception as exc:
                        logger.debug(
                            "Could not read budget component '%s' at t=%d: %s",
                            component,
                            t,
                            exc,
                        )
                        continue
                    arrays.append(np.asarray(data, dtype="float64") * float(flux_scale_to_m3_s))
                    weights.append(weight)
                if not arrays:
                    continue
                if arrays[0].ndim >= 2:
                    flux_in = weighted_period_scalar(
                        [float(np.maximum(arr, 0).sum()) for arr in arrays], weights
                    )
                    flux_out = weighted_period_scalar(
                        [float(np.minimum(arr, 0).sum()) for arr in arrays], weights
                    )
                else:
                    flux_in = 0.0
                    flux_out = 0.0
                budget_records.append(
                    {
                        "timestep": t,
                        "zone_id": DOMAIN,
                        "component": comp_key,
                        "flux_in": flux_in,
                        "flux_out": abs(flux_out),
                        "unit": "m3 s-1",
                    }
                )
                if catchment_cells is not None and arrays[0].ndim >= 2:
                    in_basin = [arr.reshape(-1, n_cells)[:, catchment_cells] for arr in arrays]
                    budget_records.append(
                        {
                            "timestep": t,
                            "zone_id": CATCHMENT,
                            "component": comp_key,
                            "flux_in": weighted_period_scalar(
                                [float(np.maximum(cells, 0).sum()) for cells in in_basin], weights
                            ),
                            "flux_out": abs(
                                weighted_period_scalar(
                                    [float(np.minimum(cells, 0).sum()) for cells in in_basin],
                                    weights,
                                )
                            ),
                            "unit": "m3 s-1",
                        }
                    )
                if per_cell and arrays[0].ndim >= 2:
                    arr = weighted_period_mean(arrays, weights)
                    field = arr.reshape(nlay, n_cells) if arr.ndim == 3 else arr.reshape(1, n_cells)
                    if slab_stack is not None and t >= window_t0 + budget_slab:
                        store.write_field_stack(
                            sim_id,
                            comp_key,
                            slab_stack,
                            n_timesteps=n_timesteps,
                            timestep_offset=window_t0,
                            subgroup="budget",
                        )
                        spatial_written = True
                        slab_stack = None
                    if slab_stack is None:
                        window_t0 = (t // budget_slab) * budget_slab
                        slab_len = min(budget_slab, n_timesteps - window_t0)
                        slab_stack = np.full((slab_len, *field.shape), np.nan, dtype="float64")
                    if slab_stack.shape[1:] == field.shape:
                        slab_stack[t - window_t0] = field
            if slab_stack is not None:
                if not spatial_written and window_t0 != 0:
                    primer = np.full((1, *slab_stack.shape[1:]), np.nan, dtype="float64")
                    store.write_field_stack(
                        sim_id,
                        comp_key,
                        primer,
                        n_timesteps=n_timesteps,
                        timestep_offset=0,
                        subgroup="budget",
                    )
                store.write_field_stack(
                    sim_id,
                    comp_key,
                    slab_stack,
                    n_timesteps=n_timesteps,
                    timestep_offset=window_t0,
                    subgroup="budget",
                )
                spatial_written = True
            if spatial_written:
                written.add(comp_key)

        # Keep the historical time-major record order for downstream readers.
        budget_records.sort(key=lambda record: record["timestep"])
        if budget_records:
            store.write_budgets(sim_id, budget_records)
        cbb.close()
        record_budget_policy(store, sim_id, budget_terms, written)

    def _extract_face_flows(
        self,
        sim_id: str,
        store: Any,
        cbc_path: Path,
        solver_output_dir: Path,
        model_name: str,
        kstpkpers: list,
        nlay: int,
        nrow: int,
        ncol: int,
        *,
        flux_scale_to_m3_s: float = 1.0,
    ) -> int:
        """Write ``face_flow`` and ``connection_cells`` of a MODFLOW-NWT run.

        Each stamp gets the mean of the three face records of the steps it
        closes, weighted by their ``delt`` and multiplied by
        ``flux_scale_to_m3_s`` so the stored values are m3/s. A stamp no saved
        step reaches stays NaN, and a pair that touches an inactive cell is
        left out. Returns the number of connections written.
        """
        cbb = open_cell_budget(cbc_path)
        try:
            active = _active_cells(solver_output_dir, model_name, nlay, nrow, ncol)
            steps = budget_file_steps(cbb)
            groups = group_steps_by_stamp(
                steps.keys,
                steps.lengths,
                [(int(kstp), int(kper)) for kstp, kper in kstpkpers],
            )
            cells: np.ndarray | None = None
            stack: np.ndarray | None = None
            for group in groups:
                arrays: list[np.ndarray] = []
                weights: list[float] = []
                for position, weight in zip(group.positions, group.weights, strict=True):
                    flows = _step_face_records(
                        lambda index: cbb.get_record(index, full3D=True),
                        steps.record,
                        steps.keys[position],
                        (nlay, nrow, ncol),
                    )
                    if flows is None:
                        continue
                    pairs, values = face_connections(*flows, active=active)
                    if cells is None:
                        cells = pairs
                        stack = np.full((len(groups), pairs.shape[0]), np.nan, dtype="float64")
                    arrays.append(values * flux_scale_to_m3_s)
                    weights.append(weight)
                if arrays and stack is not None:
                    stack[group.stamp] = weighted_period_mean(arrays, weights)
        finally:
            cbb.close()
        if cells is None or stack is None:
            return 0
        store.write_field_stack(sim_id, FACE_FLOW, stack, n_timesteps=len(groups))
        zarr = store.open_zarr(sim_id)
        try:
            zarr.write_static_field(CONNECTION_CELLS, cells)
        finally:
            zarr.close()
        return int(cells.shape[0])

    def _extract_mass_balance(
        self,
        sim_id: str,
        store: Any,
        lst_path: Path,
        flux_scale_to_m3_s: float,
        *,
        stamp_keys: list[tuple[int, int]],
    ) -> None:
        """Parse the MODFLOW-NWT listing file for the mass balance summary.

        Volumetric rates scale to m3/s like the cell budget fluxes;
        PERCENT_DISCREPANCY is unitless and must not be scaled.

        A period cut into several steps prints the budget of each of them.
        ``stamp_keys`` are the 0-based ``(kstp, kper)`` of the stamps: each
        stamp takes the mean of the steps it closes, weighted by their
        length, and its discrepancy is recomputed from those means,
        ``100 (in - out) / ((in + out) / 2)``. A stamp that closes one step
        keeps that step's row.
        """
        from flopy.utils import MfListBudget

        try:
            incremental, _cumulative = MfListBudget(str(lst_path)).get_budget()
        except Exception as exc:
            raise ExtractError(
                f"Cannot read the MODFLOW-NWT mass balance from {lst_path}: {exc}"
            ) from exc
        if incremental is None:
            raise ExtractError(f"MODFLOW-NWT listing {lst_path} carries no volumetric budget.")

        names = incremental.dtype.names
        scale = float(flux_scale_to_m3_s)
        rows = [
            {
                "total_in": _budget_field(row, names, "TOTAL_IN") * scale,
                "total_out": _budget_field(row, names, "TOTAL_OUT") * scale,
                "storage_in": _budget_field(row, names, "STORAGE_IN") * scale,
                "storage_out": _budget_field(row, names, "STORAGE_OUT") * scale,
                "in_minus_out": _budget_field(row, names, "IN-OUT") * scale,
            }
            for row in incremental
        ]
        groups = group_steps_by_stamp(
            [(int(row["time_step"]), int(row["stress_period"])) for row in incremental],
            [float(row["tslen"]) for row in incremental],
            stamp_keys,
        )
        records = []
        for group in groups:
            if not group.positions:
                continue
            mean = period_mean_balance([rows[i] for i in group.positions], group.weights)
            records.append({"timestep": group.stamp, **mean})
        store.write_mass_balances(sim_id, records)

    def _write_surface_elevation(
        self,
        sim_id: str,
        store: Any,
        solver_output_dir: Path,
        model_name: str,
        nlay: int,
        nrow: int,
        ncol: int,
        *,
        vertical_layout: str = VERTICAL_LAYOUT_COLUMN_FRACTIONS,
    ) -> None:
        """Check the DIS grid against the stored mesh, then add the vertical geometry.

        The mesh was written once, before the run, from the regular grid. The
        grid the solver read is compared with it and a difference stops the run.
        What is added is the topography, the interfaces of every cell, the layer
        thicknesses and the ``idomain`` read from IBOUND (a constant-head cell,
        IBOUND < 0, is an active cell).
        """
        try:
            import flopy

            nam_path = solver_output_dir / f"{model_name}.nam"
            n_cells = nrow * ncol

            if not nam_path.exists():
                return

            m = flopy.modflow.Modflow.load(
                str(nam_path),
                model_ws=str(solver_output_dir),
                load_only=["DIS", "BAS6"],
                check=False,
                verbose=False,
                exe_name="mfnwt",
            )
            top = np.asarray(m.dis.top.array, dtype="float64").ravel()[:n_cells]
            botm = np.asarray(m.dis.botm.array, dtype="float64").reshape(-1, n_cells)
            interfaces = layer_interfaces(top, botm)
            ibound = np.asarray(m.bas6.ibound.array).reshape(botm.shape)
            idomain = np.where(ibound != 0, 1, 0)

            sz = store.open_zarr(sim_id)
            try:
                verify_dis_grid(m.modelgrid, sz.root, nrow=nrow, ncol=ncol, sim_id=sim_id)
                sz.write_topography(
                    topography=top,
                    z_interfaces=interfaces,
                    n_cells=n_cells,
                    n_layers=int(botm.shape[0]),
                    layer_thickness=interfaces[:-1] - interfaces[1:],
                    idomain=idomain,
                    vertical_layout=vertical_layout,
                    grid_type="dis",
                )
                write_descent_sidecar_to_store(
                    sz, solver_output_dir, sim_id=sim_id, n_cells=n_cells
                )
            finally:
                sz.close()
        except MeshError:
            raise
        except Exception:
            logger.debug("Could not write surface elevation for sim %s", sim_id)
