"""Output adapter for MODFLOW 6 flow solver results."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.core.budget.terms import BudgetKeep
from hydromodpy.core.console import progress
from hydromodpy.core.exceptions import MeshError, SolverInputError
from hydromodpy.core.fields.vertical_column import (
    VERTICAL_LAYOUT_COLUMN_FRACTIONS,
    layer_interfaces,
)
from hydromodpy.core.logging import get_logger
from hydromodpy.core.scope import CATCHMENT
from hydromodpy.core.units.time import (
    CF_EPOCH,
    CF_TIME_UNITS,
    cf_time_axis_seconds,
    factor_to_seconds,
)
from hydromodpy.solver.modflow6.build import FLOW_PROPERTY_SIDECAR_SUFFIX
from hydromodpy.solver.modflow6.extractors.budget import extract_budget
from hydromodpy.solver.modflow6.extractors.grid_check import (
    grb_geometry,
    verify_grid_against_store,
)
from hydromodpy.solver.modflow6.extractors.lake import (
    build_lake_records,
    final_lake_stages,
    read_lake_abacus,
    read_lake_meta,
)
from hydromodpy.solver.modflow6.extractors.sfr import (
    SfrObsSpec,
    SfrReachGeometry,
    build_sfr_columns,
    reach_number,
    read_sfr_meta,
    sfr_station_id,
)
from hydromodpy.solver.modflow6.support.computational_top import read_ground_sidecar
from hydromodpy.solver.modflow6.support.names import mf6_safe_name
from hydromodpy.solver.modflow_common.boundary_roles import read_constant_head_roles
from hydromodpy.solver.modflow_common.budget_policy import record_budget_policy
from hydromodpy.solver.modflow_common.descent_store import (
    DescentRecord,
    descent_sidecar_path,
    read_descent_sidecar,
    write_descent_sidecar_to_store,
)
from hydromodpy.solver.modflow_common.field_slab import slab_steps
from hydromodpy.solver.modflow_common.period_steps import (
    group_steps_by_stamp,
    period_mean_balance,
)
from hydromodpy.solver.modflow_common.time_units import resolve_solver_time_unit

logger = get_logger(__name__)


def _listing_path(solver_output_dir: Path, model_name: str) -> Path:
    """Return the model listing file MF6 wrote for ``model_name``.

    MF6 names the listing after the model name it was given, which
    ``mf6_safe_name`` truncates past 16 characters, while the head and budget
    files keep the full run name. Deriving the listing from the raw name loses
    the mass balance on every long ``[simulation] name``.
    """
    return Path(solver_output_dir) / f"{mf6_safe_name(model_name)}.lst"


def _streambed_face_arrays(
    solver_output_dir: Path, model_name: str, n_cells: int
) -> tuple[np.ndarray, np.ndarray] | None:
    """Return the per-face streambed top and connection threshold, or None.

    A cross-section drawn against the land surface alone cannot say whether a
    reach is connected: MODFLOW switches on ``rtp - streambed_thickness``, which
    sits meters lower. These two arrays put that threshold in the store.
    """
    spec = read_sfr_meta(solver_output_dir / f"{model_name}.sfr.meta.json")
    if spec is None or not spec.reaches:
        return None
    top = np.full(n_cells, np.nan, dtype="float64")
    threshold = np.full(n_cells, np.nan, dtype="float64")
    for reach in spec.reaches:
        cell = reach.cell2d
        if cell is None or not 0 <= cell < n_cells:
            continue
        # A cell can carry two reaches; the lower bed is the one that drains it.
        if np.isnan(top[cell]) or reach.rtp < top[cell]:
            top[cell] = reach.rtp
            threshold[cell] = reach.rtp - reach.rbth
    if not np.isfinite(top).any():
        return None
    return top, threshold


def _reach_row(network_id: str, reach: SfrReachGeometry) -> dict[str, Any]:
    """One row of ``sfr_reaches``: the reach under the number the TOML writes for it."""
    row = asdict(reach)
    number = reach_number(row.pop("ifno"))
    return {
        "reach_id": sfr_station_id(network_id, reach.ifno),
        "network_id": network_id,
        "reach": number,
        **row,
        "downstream": [reach_number(ifno) for ifno in reach.downstream],
    }


def _write_sfr_reach_geometry(sim_id: str, store: Any, spec: SfrObsSpec) -> None:
    """Persist the resolved reach geometry the MODFLOW scratch files take away.

    A run is sealed without its solver workspace, so this table is the only
    record of which cell carries which reach and where its connection threshold
    ``rtp - rbth`` sits.
    """
    if not spec.reaches:
        return
    rows = [_reach_row(spec.network_id, reach) for reach in spec.reaches]
    try:
        store.write_view(sim_id, "sfr_reaches", rows)
    except Exception:
        # Nothing else records it: the MODFLOW files are scratch, so losing this
        # write loses the geometry for good. Say so out loud.
        logger.warning(
            "Could not persist the SFR reach geometry for sim %s; the sealed run "
            "will not say which cell carries which reach.",
            sim_id,
            exc_info=True,
        )


def _budget_field(row: Any, names: tuple[str, ...] | None, key: str) -> float:
    """Return one MF6 listing-budget field, or 0.0 when the field is absent."""
    return float(row[key]) if names is not None and key in names else 0.0


def _basin_the_build_left(
    solver_output_dir: Path, *, n_cells: int
) -> tuple[DescentRecord | None, str]:
    """The descent record holding the build's basin, else None and why there is none."""
    sidecar = descent_sidecar_path(solver_output_dir)
    if sidecar is None:
        return None, "no descent sidecar"
    try:
        record = read_descent_sidecar(sidecar)
    except ValueError as exc:
        return None, f"an unreadable descent sidecar: {exc}"
    if record is None or record.basin is None:
        return None, "a sidecar written before the basin was stored"
    if int(record.basin.size) != int(n_cells):
        return None, f"a basin of {int(record.basin.size)} cells on a mesh of {int(n_cells)}"
    return record, ""


def _stream_constant_head_mask(
    solver_output_dir: Path, model_name: str, *, n_cells: int
) -> np.ndarray | None:
    """Cells whose constant head carries the stream role, from the build sidecar.

    None when the run built no stream-role constant head, or when the sidecar
    does not describe this grid.
    """
    roles = read_constant_head_roles(solver_output_dir, model_name)
    if roles is None or not roles.has_role("stream") or int(roles.n_cells) != int(n_cells):
        return None
    return roles.mask_for("stream")


def _read_start_datetime(tdis_path: Path) -> str | None:
    """Return the MF6 TDIS START_DATE_TIME option, or None when absent."""
    if not tdis_path.is_file():
        return None
    try:
        with tdis_path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                tokens = raw.strip().split()
                if len(tokens) >= 2 and tokens[0].upper() == "START_DATE_TIME":
                    return tokens[1]
    except OSError:
        return None
    return None


def _write_time_coordinate(
    store: Any,
    sim_id: str,
    times: list[float],
    time_units: str,
    tdis_path: Path,
    start_datetime: object | None = None,
) -> None:
    """Persist solver times as a CF axis at field-array resolution.

    MF6 reports relative ``totim`` on the TDIS clock, one value per saved output
    time, so the axis must keep the same length as the head/budget arrays. We
    anchor it to the model START_DATE_TIME (TDIS, else the launcher start) so the
    CF ``/time`` axis decodes to real calendar dates; writing relative totim under
    a 'seconds since 1970' label would decode ~33 years too early. With no
    calendar anchor the relative seconds are kept (reference epoch 1970).
    """
    writer = getattr(store, "write_time", None)
    if writer is None:
        raise TypeError("Simulation store must implement write_time().")
    start = _read_start_datetime(tdis_path) or start_datetime
    factor = factor_to_seconds(time_units)
    relative = np.asarray(times, dtype=float) * factor
    values = cf_time_axis_seconds(relative, start)
    writer(sim_id, values, epoch=CF_EPOCH, units=CF_TIME_UNITS)


class Modflow6OutputAdapter:
    """Read MODFLOW 6 binary outputs and inject them into a Catalog.

    Expects a solver output directory with ``{model_name}.hds`` and
    ``{model_name}.cbc`` in MODFLOW 6 format.
    """

    solver_name = "modflow6"
    category = "distributed"

    def extract(
        self,
        sim_id: str,
        solver_output_dir: Path,
        store: Any,
        *,
        model_name: str | None = None,
        budget_terms: BudgetKeep = BudgetKeep.everything(),
        start_datetime: object | None = None,
        vertical_layout: str = VERTICAL_LAYOUT_COLUMN_FRACTIONS,
    ) -> None:
        """Read MF6 .hds and .cbc files and write into the store.

        ``budget_terms`` says which per-cell budget terms go under
        ``budget/``. The lumped budget table holds every term whatever it says.
        ``vertical_layout`` says how the layers were built, as ``[domain.layers]``
        gives it; the store keeps it on ``mesh/``.
        """
        import flopy.utils.binaryfile as bf

        solver_output_dir = Path(solver_output_dir)
        if model_name is None:
            hds_files = list(solver_output_dir.glob("*.hds"))
            if not hds_files:
                raise FileNotFoundError(f"No .hds file in {solver_output_dir}")
            model_name = hds_files[0].stem

        hds_path = solver_output_dir / f"{model_name}.hds"
        cbc_path = solver_output_dir / f"{model_name}.cbc"

        head_file = bf.HeadFile(str(hds_path))
        times = head_file.get_times()
        kstpkpers = head_file.get_kstpkper()
        n_timesteps = len(times)
        tdis_path = solver_output_dir / f"{model_name}.tdis"
        if not tdis_path.is_file():
            tdis_path = next(iter(solver_output_dir.glob("*.tdis")), tdis_path)
        time_units = resolve_solver_time_unit(solver_output_dir, model_name)
        # MF6 emits fluxes in length^3 per TDIS time unit; convert to m3/s.
        seconds_per_time_unit = factor_to_seconds(time_units)
        _write_time_coordinate(store, sim_id, times, time_units, tdis_path, start_datetime)

        try:
            head0 = head_file.get_data(totim=times[0])
            if head0.ndim == 3:
                nlay, nrow, ncol = head0.shape
                n_cells = nrow * ncol
            elif head0.ndim == 2:
                nlay = 1
                n_cells = int(head0.size)
            else:
                nlay = 1
                n_cells = head0.size

            logger.debug(
                "Extracting MODFLOW 6 results: %d timesteps, %d layers, %d cells",
                n_timesteps,
                nlay,
                n_cells,
            )

            # Batched stack writes: per-timestep writes into a sharded Zarr array
            # cost one whole-shard read-modify-write per timestep.
            head_slab_steps = slab_steps(nlay, n_cells)
            with progress.task("Extracting heads", total=n_timesteps) as handle:
                for t0 in range(0, n_timesteps, head_slab_steps):
                    t1 = min(t0 + head_slab_steps, n_timesteps)
                    slab = np.empty((t1 - t0, nlay, n_cells), dtype="float64")
                    for t in range(t0, t1):
                        head = head_file.get_data(totim=times[t])
                        slab[t - t0] = head.reshape(nlay, n_cells)
                    store.write_field_stack(
                        sim_id,
                        "head",
                        slab,
                        n_timesteps=n_timesteps,
                        timestep_offset=t0,
                    )
                    handle.update(completed=t1)

            if cbc_path.exists():
                extract_budget(
                    sim_id,
                    store,
                    cbc_path,
                    times,
                    kstpkpers,
                    budget_terms=budget_terms,
                    nlay=nlay,
                    n_cells=n_cells,
                    seconds_per_time_unit=seconds_per_time_unit,
                    catchment_mask=self._catchment_cell_mask(
                        sim_id, store, solver_output_dir, n_cells=n_cells
                    ),
                    stream_constant_head_mask=_stream_constant_head_mask(
                        solver_output_dir, model_name, n_cells=n_cells
                    ),
                )
            else:
                record_budget_policy(store, sim_id, budget_terms, ())

            lst_path = _listing_path(solver_output_dir, model_name)
            if lst_path.exists():
                self._extract_mass_balance(
                    sim_id,
                    store,
                    lst_path,
                    stamp_keys=[(int(kstp), int(kper)) for kstp, kper in kstpkpers],
                    seconds_per_time_unit=seconds_per_time_unit,
                )

            self._extract_lake_series(
                sim_id,
                store,
                solver_output_dir,
                model_name,
                times=times,
                tdis_path=tdis_path,
                time_units=time_units,
                seconds_per_time_unit=seconds_per_time_unit,
                start_datetime=start_datetime,
            )

            self._extract_lake_abacus(sim_id, store, solver_output_dir, model_name)

            self._extract_sfr_series(
                sim_id,
                store,
                solver_output_dir,
                model_name,
                times=times,
                tdis_path=tdis_path,
                time_units=time_units,
                seconds_per_time_unit=seconds_per_time_unit,
                start_datetime=start_datetime,
            )
        finally:
            head_file.close()

        self._write_surface_elevation(
            sim_id,
            store,
            solver_output_dir,
            model_name,
            nlay,
            n_cells,
            vertical_layout=vertical_layout,
        )

    def _extract_lake_series(
        self,
        sim_id: str,
        store: Any,
        solver_output_dir: Path,
        model_name: str,
        *,
        times: list,
        tdis_path: Path,
        time_units: str,
        seconds_per_time_unit: float,
        start_datetime: object | None = None,
    ) -> None:
        """Read the LAK obs CSV into per-lake (lake_id, totim) timeseries.

        Per-lake stage / volume / surface-area, the lake-aquifer exchange and the
        rest of the lake water balance come from the LAK observation CSV described
        by the build-time ``{model}.lak.meta.json`` sidecar; the spatial per-cell
        seepage stays in the GWF ``.cbc`` ``LAK`` record handled by
        ``_extract_budget``. Stage / volume / surface-area keep their native units;
        rate terms are scaled to m3/s. Without the sidecar the model has no lake
        and this is a no-op.
        """
        spec = read_lake_meta(solver_output_dir / f"{model_name}.lak.meta.json")
        if spec is None:
            return
        with progress.status("Building lake timeseries"):
            obs_path = solver_output_dir / spec.obs_csv
            calendar_anchor = _read_start_datetime(tdis_path) or start_datetime
            factor = factor_to_seconds(time_units)
            calendar_times: np.ndarray | None = None
            if calendar_anchor is not None:
                relative = np.asarray(times, dtype=float) * factor
                axis = cf_time_axis_seconds(relative, calendar_anchor)
                calendar_times = (
                    np.asarray(axis)
                    .astype("int64")
                    .astype("datetime64[s]")
                    .astype("datetime64[ms]")
                )
            timeseries, budgets = build_lake_records(
                spec,
                obs_path,
                times=times,
                seconds_per_time_unit=seconds_per_time_unit,
                calendar_times=calendar_times,
            )
            if timeseries:
                store.write_timeseries_batch(sim_id, timeseries)
                final_stages = final_lake_stages(timeseries)
                # Persist each lake's final stage for [flow] restart_from. Written
                # through open_zarr (guarded by save_zarr, like the write_* verbs)
                # rather than a dedicated Catalog verb, to keep the facade bounded.
                if final_stages and getattr(store, "save_zarr", True):
                    lake_zarr = store.open_zarr(sim_id)
                    try:
                        lake_zarr.write_lake_restart_state(final_stages)
                    finally:
                        lake_zarr.close()
            if budgets:
                store.write_budgets(sim_id, budgets)

    def _extract_lake_abacus(
        self,
        sim_id: str,
        store: Any,
        solver_output_dir: Path,
        model_name: str,
    ) -> None:
        """Land the bed-reconstruction abacus comparison sidecar into the Zarr.

        Reads ``{model}.lake_abacus.json`` (reference + simulated stage-volume-area
        per lake) and persists each lake under the per-sim Zarr ``lake_abacus``
        group for the comparison figure. A no-op when the model has no carved lake.
        """
        spec = read_lake_abacus(solver_output_dir / f"{model_name}.lake_abacus.json")
        if spec is None:
            return
        for entry in spec.entries:
            store.write_lake_abacus(
                sim_id,
                entry.lake_id,
                stage=entry.stage,
                real_volume=entry.real_volume,
                real_sarea=entry.real_sarea,
                sim_volume=entry.sim_volume,
                sim_sarea=entry.sim_sarea,
                stage_unit=entry.stage_unit,
                volume_unit=entry.volume_unit,
                area_unit=entry.area_unit,
            )

    def _extract_sfr_series(
        self,
        sim_id: str,
        store: Any,
        solver_output_dir: Path,
        model_name: str,
        *,
        times: list,
        tdis_path: Path,
        time_units: str,
        seconds_per_time_unit: float,
        start_datetime: object | None = None,
    ) -> None:
        """Read the SFR obs CSV into per-reach (reach_ifno, totim) timeseries.

        Per-reach stage / depth / downstream-flow / reach-aquifer exchange and
        the external in/outflows come from the SFR observation CSV described by
        the build-time ``{model}.sfr.meta.json`` sidecar; the spatial per-cell
        seepage stays in the GWF ``.cbc`` ``SFR`` record handled by
        ``_extract_budget``. Stage / depth keep meters; rate terms are scaled to
        m3/s. Without the sidecar the model has no stream network and this is a
        no-op.
        """
        spec = read_sfr_meta(solver_output_dir / f"{model_name}.sfr.meta.json")
        if spec is None:
            return
        with progress.status("Building SFR timeseries"):
            obs_path = solver_output_dir / spec.obs_csv
            calendar_anchor = _read_start_datetime(tdis_path) or start_datetime
            factor = factor_to_seconds(time_units)
            calendar_times: np.ndarray | None = None
            if calendar_anchor is not None:
                relative = np.asarray(times, dtype=float) * factor
                axis = cf_time_axis_seconds(relative, calendar_anchor)
                calendar_times = (
                    np.asarray(axis)
                    .astype("int64")
                    .astype("datetime64[s]")
                    .astype("datetime64[ms]")
                )
            columns, budgets = build_sfr_columns(
                spec,
                obs_path,
                times=times,
                seconds_per_time_unit=seconds_per_time_unit,
                calendar_times=calendar_times,
            )
            if columns:
                store.write_timeseries_columns(sim_id, columns)
            if budgets:
                store.write_budgets(sim_id, budgets)
            _write_sfr_reach_geometry(sim_id, store, spec)

    def _extract_mass_balance(
        self,
        sim_id: str,
        store: Any,
        lst_path: Path,
        *,
        stamp_keys: Sequence[tuple[int, int]],
        seconds_per_time_unit: float = 1.0,
    ) -> None:
        """Parse MODFLOW 6 listing file for mass balance summary.

        MF6 splits storage into specific storage (STO-SS, confined) and specific
        yield (STO-SY, unconfined); total storage flux = STO-SS + STO-SY. Totals
        and storage scale to m3/s like the budget fluxes; PERCENT_DISCREPANCY is
        unitless and must not be scaled.

        The build prints the budget of every time step. ``stamp_keys`` are the
        0-based ``(kstp, kper)`` of the saved heads: each stamp takes the mean
        of the steps it closes, weighted by their length, and its discrepancy
        is recomputed from those means, as MF6 does,
        ``100 (in - out) / ((in + out) / 2)``. A stamp that closes one step
        keeps that step's row.
        """
        try:
            from flopy.utils import Mf6ListBudget

            mf6_list = Mf6ListBudget(str(lst_path))
            inc, cum = mf6_list.get_budget()
            if inc is not None:
                names = inc.dtype.names
                spt = seconds_per_time_unit
                rows = [
                    {
                        "total_in": _budget_field(row, names, "TOTAL_IN"),
                        "total_out": _budget_field(row, names, "TOTAL_OUT"),
                        "storage_in": _budget_field(row, names, "STO-SS_IN")
                        + _budget_field(row, names, "STO-SY_IN"),
                        "storage_out": _budget_field(row, names, "STO-SS_OUT")
                        + _budget_field(row, names, "STO-SY_OUT"),
                        "in_minus_out": _budget_field(row, names, "IN-OUT"),
                        "percent_error": _budget_field(row, names, "PERCENT_DISCREPANCY"),
                    }
                    for row in inc
                ]
                groups = group_steps_by_stamp(
                    [(int(row["time_step"]), int(row["stress_period"])) for row in inc],
                    [float(row["tslen"]) for row in inc],
                    stamp_keys,
                )
                records = []
                for group in groups:
                    if not group.positions:
                        continue
                    mean = period_mean_balance([rows[i] for i in group.positions], group.weights)
                    records.append(
                        {
                            "timestep": group.stamp,
                            "total_in": mean["total_in"] / spt,
                            "total_out": mean["total_out"] / spt,
                            "storage_in": mean["storage_in"] / spt,
                            "storage_out": mean["storage_out"] / spt,
                            "percent_error": mean["percent_error"],
                        }
                    )
                store.write_mass_balances(sim_id, records)
        except Exception:
            logger.warning("Could not parse MF6 listing file %s", lst_path)

    def _catchment_cell_mask(
        self,
        sim_id: str,
        store: Any,
        solver_output_dir: Path,
        *,
        n_cells: int,
    ) -> np.ndarray | None:
        """Cells of the catchment budget zone, None when it cannot be placed.

        The zone is the basin of D the build left in the descent sidecar. The
        budget is computed before the Zarr store is written, so the sidecar is
        the one place the basin can be read from at this point. A basin that is
        only the largest one of a domain with neither outlet nor polygon is no
        catchment: the domain-wide row stands alone, as on any synthetic
        domain.

        A build that left no basin (no sidecar, a sidecar written before the
        basin was stored, an unreadable one) keeps the old support
        ``polygon_centroid`` and says so: the cells whose center the delineated
        watershed covers, read from the GRB rather than from the persisted mesh.
        The extractor checks the two against each other afterwards, so the mask
        agrees with the stored cells. A run without a watershed or a CRS keeps
        the domain-wide row alone.
        """
        record, reason = _basin_the_build_left(solver_output_dir, n_cells=n_cells)
        if record is not None:
            if record.basin_rule == "largest_basin":
                return None
            logger.info(
                "Budget zone '%s' for sim %s: the basin of D, %d of %d cells (%.3f km2).",
                CATCHMENT,
                sim_id,
                int(record.basin.sum()),
                n_cells,
                float(record.basin_area_m2) / 1.0e6,
            )
            return np.asarray(record.basin, dtype=bool)
        logger.warning(
            "Budget zone '%s' for sim %s: the build left no basin of D (%s), so the zone "
            "keeps the old support 'polygon_centroid'.",
            CATCHMENT,
            sim_id,
            reason,
        )
        try:
            from hydromodpy.mesh.cells.in_polygons import vector_cell_mask
            from hydromodpy.mesh.planar.geometry import cell_polygons

            watershed = store.read_geographic_feature(sim_id, "watershed")
            if watershed is None or watershed.empty:
                return None
            crs = store.open_zarr(sim_id).root["crs"].attrs.get("crs_wkt")
            if not crs:
                # Never guessed: the wrong frame lands the catchment somewhere
                # else entirely and the budget row would look plausible.
                return None
            grb_files = list(solver_output_dir.glob("*.dis.grb")) + list(
                solver_output_dir.glob("*.disv.grb")
            )
            if not grb_files:
                return None
            from flopy.mf6.utils import MfGrdFile

            geometry = self._mesh_geometry_from_grid(MfGrdFile(str(grb_files[0])), n_cells=n_cells)
            if geometry is None:
                return None
            vertices, connectivity = geometry
            mask = np.asarray(
                vector_cell_mask(
                    cell_polygons(vertices, connectivity),
                    list(watershed.geometry),
                    mesh_crs=str(crs),
                    geometry_crs=watershed.crs,
                    rule="centroid",
                ),
                dtype=bool,
            ).ravel()
        except Exception as exc:
            logger.debug("No catchment budget zone for sim %s: %s", sim_id, exc)
            return None
        if mask.size != n_cells or not mask.any():
            return None
        logger.info(
            "Budget zone '%s' for sim %s: %d of %d cells.",
            CATCHMENT,
            sim_id,
            int(mask.sum()),
            n_cells,
        )
        return mask

    def _write_surface_elevation(
        self,
        sim_id: str,
        store: Any,
        solver_output_dir: Path,
        model_name: str,
        nlay: int,
        n_cells: int,
        *,
        vertical_layout: str = VERTICAL_LAYOUT_COLUMN_FRACTIONS,
    ) -> None:
        """Check the solved grid against the stored mesh and add the vertical geometry.

        The mesh itself was written once, before the run. The grid file is
        compared with it and a difference stops the run: nothing is sealed on
        cells it does not belong to. What is added is what the solved model
        knows: ``topography``, the interfaces of every cell (``z_interfaces``,
        ``(n_layers + 1, n_cells)``), ``layer_thickness`` and the ``idomain`` of
        the grid file, lake mask included. The top of the grid file is the
        computational top, so the interfaces start from the ground the build
        left beside the model; a missing ground file is an error.
        """
        if not getattr(store, "save_zarr", True):
            return
        try:
            grb_files = list(solver_output_dir.glob("*.dis.grb")) + list(
                solver_output_dir.glob("*.disv.grb")
            )
            if not grb_files:
                return
            from flopy.mf6.utils import MfGrdFile

            grd = MfGrdFile(str(grb_files[0]))
            grid_type = str(getattr(grd, "grid_type", "") or "").lower() or None
            top_raw = getattr(grd, "top1d", None)
            if top_raw is None:
                top_raw = grd.top
            bot_raw = getattr(grd, "bot1d", None)
            if bot_raw is None:
                bot_raw = grd.bot
            top = read_ground_sidecar(
                solver_output_dir,
                written_top=np.asarray(top_raw, dtype="float64").ravel()[:n_cells],
            )
            botm = np.asarray(bot_raw, dtype="float64")
            if botm.size != nlay * n_cells:
                raise SolverInputError(
                    f"the grid file of sim {sim_id} holds {botm.size} cell bottoms, "
                    f"not {nlay} layers of {n_cells} cells."
                )
            interfaces = layer_interfaces(top, botm.reshape(nlay, n_cells))
            idomain = np.asarray(grd.idomain).reshape(nlay, n_cells)

            sz = store.open_zarr(sim_id)
            try:
                verify_grid_against_store(grd, sz.root, sim_id=sim_id)
                streambed = _streambed_face_arrays(solver_output_dir, model_name, n_cells)
                sz.write_topography(
                    topography=top,
                    z_interfaces=interfaces,
                    n_cells=n_cells,
                    n_layers=nlay,
                    layer_thickness=interfaces[:-1] - interfaces[1:],
                    idomain=idomain,
                    vertical_layout=vertical_layout,
                    streambed_top=None if streambed is None else streambed[0],
                    streambed_connection=None if streambed is None else streambed[1],
                    grid_type=grid_type,
                )
                _write_flow_properties(sz, solver_output_dir, n_cells=n_cells)
                write_descent_sidecar_to_store(
                    sz, solver_output_dir, sim_id=sim_id, n_cells=n_cells
                )
            finally:
                sz.close()
        except (SolverInputError, MeshError):
            raise
        except Exception:
            logger.warning(
                "Could not write the surface elevation for sim %s; every map, "
                "section and water-table depth of this run reads it.",
                sim_id,
                exc_info=True,
            )

    @staticmethod
    def _mesh_geometry_from_grid(
        grid: Any,
        *,
        n_cells: int,
    ) -> tuple[np.ndarray, np.ndarray] | None:
        """Return UGRID vertices and padded connectivity from a FloPy MfGrdFile, None if it has none."""
        try:
            vertices_xy, connectivity = grb_geometry(grid)
        except MeshError:
            return None
        if connectivity.shape[0] != int(n_cells):
            return None
        vertices = np.column_stack([vertices_xy, np.zeros(vertices_xy.shape[0])])
        return vertices, connectivity


def _write_flow_properties(sz: Any, solver_output_dir: Path, *, n_cells: int) -> None:
    """Persist the conductivity and storage fields the builder left behind.

    They are inputs, not results, and MODFLOW writes none of them back out.
    Storing them next to the heads is what lets a section or a map show the
    aquifer the run was actually given, and lets two runs be compared on the
    parameters and not only on the answer.
    """
    sidecars = sorted(solver_output_dir.glob(f"*{FLOW_PROPERTY_SIDECAR_SUFFIX}"))
    if not sidecars:
        return
    with np.load(sidecars[0]) as payload:
        for variable in payload.files:
            values = np.asarray(payload[variable], dtype="float64")
            if values.ndim != 2 or values.shape[1] != n_cells:
                continue
            sz.write_static_field(variable, values, subgroup="derived")
