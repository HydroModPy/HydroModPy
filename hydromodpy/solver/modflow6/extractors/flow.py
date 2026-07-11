"""Output adapter for MODFLOW 6 flow solver results."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.core import progress
from hydromodpy.core.logging import get_logger
from hydromodpy.core.units.time import (
    CF_EPOCH,
    CF_TIME_UNITS,
    cf_time_axis_seconds,
    factor_to_seconds,
)
from hydromodpy.solver.modflow_common.budget_components import is_scalar_budget_component
from hydromodpy.solver.modflow_common.field_slab import slab_steps

logger = get_logger(__name__)


def _seconds_per_time_unit(time_units: str) -> float:
    """Seconds per MF6 TDIS TIME_UNITS token; UNKNOWN/blank means seconds (1.0)."""
    token = (time_units or "").strip().upper()
    if token in ("", "UNKNOWN"):
        return 1.0
    return factor_to_seconds(token)


def _budget_field(row: Any, names: tuple[str, ...] | None, key: str) -> float:
    """Return one MF6 listing-budget field, or 0.0 when the field is absent."""
    return float(row[key]) if names is not None and key in names else 0.0


def _read_time_units(tdis_path: Path) -> str:
    """Return the MF6 TDIS TIME_UNITS option."""
    if not tdis_path.is_file():
        return "SECONDS"
    try:
        with tdis_path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                tokens = raw.strip().split()
                if len(tokens) >= 2 and tokens[0].upper() == "TIME_UNITS":
                    return tokens[1].upper()
    except OSError:
        return "SECONDS"
    return "SECONDS"


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
    factor = _seconds_per_time_unit(time_units)
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
        budget_spatial_fields: bool = False,
        start_datetime: object | None = None,
    ) -> None:
        """Read MF6 .hds and .cbc files and write into the store."""
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
        time_units = _read_time_units(tdis_path)
        # MF6 emits fluxes in length^3 per TDIS time unit; convert to m3/s.
        seconds_per_time_unit = _seconds_per_time_unit(time_units)
        _write_time_coordinate(store, sim_id, times, time_units, tdis_path, start_datetime)

        try:
            head0 = head_file.get_data(totim=times[0])
            grid_shape: tuple[int, int] | None = None
            if head0.ndim == 3:
                nlay, nrow, ncol = head0.shape
                n_cells = nrow * ncol
                grid_shape = (int(nrow), int(ncol))
            elif head0.ndim == 2:
                nlay = 1
                n_cells = int(head0.size)
                grid_shape = tuple(int(v) for v in head0.shape)
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
                    slab[np.abs(slab) > 1e20] = np.nan
                    store.write_field_stack(
                        sim_id,
                        "head",
                        slab,
                        n_timesteps=n_timesteps,
                        timestep_offset=t0,
                    )
                    handle.update(completed=t1)

            if cbc_path.exists():
                self._extract_budget(
                    sim_id,
                    store,
                    cbc_path,
                    times,
                    kstpkpers,
                    spatial_fields=budget_spatial_fields,
                    nlay=nlay,
                    n_cells=n_cells,
                    seconds_per_time_unit=seconds_per_time_unit,
                )

            lst_path = solver_output_dir / f"{model_name}.lst"
            if lst_path.exists():
                self._extract_mass_balance(
                    sim_id, store, lst_path, seconds_per_time_unit=seconds_per_time_unit
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
            grid_shape=grid_shape,
        )

    def _extract_budget(
        self,
        sim_id: str,
        store: Any,
        cbc_path: Path,
        times: list,
        kstpkpers: list,
        *,
        spatial_fields: bool = False,
        nlay: int = 1,
        n_cells: int = 0,
        seconds_per_time_unit: float = 1.0,
    ) -> None:
        """Extract cell budget data from MF6 .cbc file.

        Fluxes are divided by ``seconds_per_time_unit`` so the stored values are
        m3/s regardless of the TDIS time unit (m3/s = flux / seconds_per_time_unit).
        """
        from hydromodpy.solver.modflow6.extractors.cbc_reader import Mf6CellBudgetReader

        cbb = Mf6CellBudgetReader(cbc_path)
        try:
            # Intercell face flows and the specific-discharge velocity are not
            # scalar budget terms; skip them before reading or summing.
            components = [
                name for name in cbb.unique_record_names() if is_scalar_budget_component(name)
            ]
            component_rank = {name: rank for rank, name in enumerate(components)}

            n_timesteps = len(times)
            # One sequential pass over the file-order record index. Per-record
            # get_data(text, kstpkper, totim) calls rebuild a full boolean mask of
            # the index each time, which is quadratic over a long chronicle.
            timestep_by_kstpkper = {
                (int(kstp) + 1, int(kper) + 1): t for t, (kstp, kper) in enumerate(kstpkpers)
            }
            # The cbc file is time-major, so budget spatial fields are streamed in
            # time slabs shared across the components: the slab is sized so all
            # components together stay under one field-slab budget rather than
            # holding every component's full (nper, nlay, ncpl) stack in RAM.
            budget_slab = max(1, slab_steps(nlay, n_cells) // max(1, len(components)))
            seen: set[tuple[str, int]] = set()
            warned_duplicate: set[str] = set()
            created_fields: set[str] = set()
            ranked_records: list[tuple[int, int, dict]] = []
            slab_stacks: dict[str, np.ndarray] = {}
            window_t0 = 0

            def _flush_window(t0: int) -> None:
                for comp, stack in slab_stacks.items():
                    comp_key = comp.lower().strip()
                    try:
                        if comp not in created_fields and t0 != 0:
                            # First write of a variable must start at offset 0;
                            # prime the full array for a component that only
                            # appears past the first slab (rare for per-step terms).
                            primer = np.full((1, *stack.shape[1:]), np.nan, dtype="float64")
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
                            stack,
                            n_timesteps=n_timesteps,
                            timestep_offset=t0,
                            subgroup="budget",
                        )
                        created_fields.add(comp)
                    except Exception:
                        logger.debug(
                            "Skipped write_field_stack for MF6 budget '%s'", comp, exc_info=True
                        )
                slab_stacks.clear()

            with progress.task("Extracting budget terms", total=len(cbb.records)) as handle:
                for idx, record in enumerate(cbb.records):
                    handle.advance()
                    component = record.text
                    rank = component_rank.get(component)
                    if rank is None:
                        continue
                    t = timestep_by_kstpkper.get((record.kstp, record.kper))
                    if t is None:
                        continue
                    key = (component, t)
                    if key in seen:
                        # Several packages of one type share the record name; keep
                        # the first record like the historical data[0] read did.
                        if component not in warned_duplicate:
                            logger.warning(
                                "MF6 budget has multiple '%s' package records per timestep; "
                                "keeping the first (aggregate views may undercount).",
                                component,
                            )
                            warned_duplicate.add(component)
                        continue
                    if spatial_fields and t >= window_t0 + budget_slab:
                        _flush_window(window_t0)
                        window_t0 = (t // budget_slab) * budget_slab
                    try:
                        arr = cbb.read_record(idx)
                    except Exception as exc:
                        logger.debug(
                            "Could not read MF6 budget '%s' at t=%d: %s", component, t, exc
                        )
                        continue
                    seen.add(key)
                    if hasattr(arr, "dtype") and arr.dtype.names is not None:
                        arr = self._recarray_to_grid(arr, nlay, n_cells)
                    if hasattr(arr, "shape") and arr.ndim >= 1:
                        flux_in = float(np.maximum(arr, 0).sum()) / seconds_per_time_unit
                        flux_out = float(np.minimum(arr, 0).sum()) / seconds_per_time_unit
                    else:
                        flux_in = 0.0
                        flux_out = 0.0
                    ranked_records.append(
                        (
                            t,
                            rank,
                            {
                                "timestep": t,
                                "zone_id": "0",
                                "component": component.lower().strip(),
                                "flux_in": flux_in,
                                "flux_out": abs(flux_out),
                                "unit": "m3/s",
                            },
                        )
                    )
                    if spatial_fields and hasattr(arr, "shape") and arr.ndim >= 1:
                        if arr.size == nlay * n_cells:
                            field = np.asarray(arr).reshape(nlay, n_cells)
                        elif arr.ndim == 1 and arr.size == n_cells:
                            field = np.asarray(arr).reshape(1, n_cells)
                        else:
                            field = None
                        if field is not None:
                            stack = slab_stacks.get(component)
                            if stack is None:
                                slab_len = min(budget_slab, n_timesteps - window_t0)
                                stack = np.full((slab_len, *field.shape), np.nan, dtype="float64")
                                slab_stacks[component] = stack
                            if stack.shape[1:] == field.shape:
                                stack[t - window_t0] = field / seconds_per_time_unit

            _flush_window(window_t0)

            # Keep the historical order: time-major, then component declaration order.
            ranked_records.sort(key=lambda item: (item[0], item[1]))
            budget_records = [record for _, _, record in ranked_records]
            if budget_records:
                store.write_budgets(sim_id, budget_records)
        finally:
            cbb.close()

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
        from hydromodpy.solver.modflow6.extractors.lake import (
            build_lake_records,
            final_lake_stages,
            read_lake_meta,
        )

        spec = read_lake_meta(solver_output_dir / f"{model_name}.lak.meta.json")
        if spec is None:
            return
        with progress.status("Building lake timeseries"):
            obs_path = solver_output_dir / spec.obs_csv
            calendar_anchor = _read_start_datetime(tdis_path) or start_datetime
            factor = _seconds_per_time_unit(time_units)
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
                if final_stages:
                    store.write_lake_restart_state(sim_id, final_stages)
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
        from hydromodpy.solver.modflow6.extractors.lake import read_lake_abacus

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
        from hydromodpy.solver.modflow6.extractors.sfr import (
            build_sfr_columns,
            read_sfr_meta,
        )

        spec = read_sfr_meta(solver_output_dir / f"{model_name}.sfr.meta.json")
        if spec is None:
            return
        with progress.status("Building SFR timeseries"):
            obs_path = solver_output_dir / spec.obs_csv
            calendar_anchor = _read_start_datetime(tdis_path) or start_datetime
            factor = _seconds_per_time_unit(time_units)
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

    @staticmethod
    def _recarray_to_grid(
        rec: np.ndarray,
        nlay: int,
        n_cells: int,
    ) -> np.ndarray:
        """Convert a MF6 stress-package recarray to a full grid array.

        MF6 stress packages store sparse records with 1-based ``node``
        IDs and ``q`` flux values.  This scatters them into a dense
        ``(nlay, n_cells)`` array. Vector records (DATA-SPDIS) are excluded
        upstream by ``is_scalar_budget_component`` and never reach here.
        """
        names = rec.dtype.names
        q = np.asarray(
            rec["q"] if names is not None and "q" in names else rec[names[-1]], dtype="float64"
        )

        if n_cells == 0:
            return q

        nodes = np.asarray(rec["node"], dtype="int64") if "node" in names else None
        out = np.zeros((nlay, n_cells), dtype="float64")
        if nodes is not None:
            idx = nodes - 1
            lay = idx // n_cells
            cell = idx % n_cells
            valid = (lay >= 0) & (lay < nlay) & (cell >= 0) & (cell < n_cells)
            np.add.at(out, (lay[valid], cell[valid]), q[valid])
        else:
            n = min(len(q), n_cells)
            out[0, :n] = q[:n]
        return out

    def _extract_mass_balance(
        self,
        sim_id: str,
        store: Any,
        lst_path: Path,
        *,
        seconds_per_time_unit: float = 1.0,
    ) -> None:
        """Parse MODFLOW 6 listing file for mass balance summary.

        MF6 splits storage into specific storage (STO-SS, confined) and specific
        yield (STO-SY, unconfined); total storage flux = STO-SS + STO-SY. Totals
        and storage scale to m3/s like the budget fluxes; PERCENT_DISCREPANCY is
        unitless and must not be scaled.
        """
        try:
            from flopy.utils import Mf6ListBudget

            mf6_list = Mf6ListBudget(str(lst_path))
            inc, cum = mf6_list.get_budget()
            if inc is not None:
                names = inc.dtype.names
                spt = seconds_per_time_unit
                records = []
                for t in range(len(inc)):
                    row = inc[t]
                    storage_in = (
                        _budget_field(row, names, "STO-SS_IN")
                        + _budget_field(row, names, "STO-SY_IN")
                    ) / spt
                    storage_out = (
                        _budget_field(row, names, "STO-SS_OUT")
                        + _budget_field(row, names, "STO-SY_OUT")
                    ) / spt
                    records.append(
                        {
                            "timestep": t,
                            "total_in": _budget_field(row, names, "TOTAL_IN") / spt,
                            "total_out": _budget_field(row, names, "TOTAL_OUT") / spt,
                            "storage_in": storage_in,
                            "storage_out": storage_out,
                            "percent_error": _budget_field(row, names, "PERCENT_DISCREPANCY"),
                        }
                    )
                store.write_mass_balances(sim_id, records)
        except Exception:
            logger.warning("Could not parse MF6 listing file %s", lst_path)

    def _write_surface_elevation(
        self,
        sim_id: str,
        store: Any,
        solver_output_dir: Path,
        model_name: str,
        nlay: int,
        n_cells: int,
        *,
        grid_shape: tuple[int, int] | None = None,
    ) -> None:
        """Write mesh topology and surface elevation for derived variables."""
        try:
            grb_files = list(solver_output_dir.glob("*.dis.grb")) + list(
                solver_output_dir.glob("*.disv.grb")
            )
            grid_type = None
            vertices = None
            face_node_connectivity = None
            if grb_files:
                from flopy.mf6.utils import MfGrdFile

                grd = MfGrdFile(str(grb_files[0]))
                grid_type = str(getattr(grd, "grid_type", "") or "").lower() or None
                top_raw = getattr(grd, "top1d", None)
                if top_raw is None:
                    top_raw = grd.top
                bot_raw = getattr(grd, "bot1d", None)
                if bot_raw is None:
                    bot_raw = grd.bot
                top = np.asarray(top_raw, dtype="float64").ravel()[:n_cells]
                botm = np.asarray(bot_raw, dtype="float64")
                botm_per_layer = (
                    botm.reshape(nlay, n_cells) if botm.size == nlay * n_cells else None
                )
                if botm_per_layer is not None:
                    z_flat = np.concatenate([top[:1], botm_per_layer[:, 0]])
                else:
                    z_flat = np.array([float(top.mean()), float(top.mean()) - 10.0])
                geometry = self._mesh_geometry_from_grid(grd, n_cells=n_cells)
                if geometry is not None:
                    vertices, face_node_connectivity = geometry
            else:
                return

            if face_node_connectivity is None:
                geometry = self._structured_mesh_geometry_from_shape(
                    store,
                    sim_id,
                    n_cells=n_cells,
                    grid_shape=grid_shape,
                )
                if geometry is not None:
                    vertices, face_node_connectivity = geometry

            if vertices is None or face_node_connectivity is None:
                return
            structured_shape = self._structured_shape_from_vertices(vertices, n_cells=n_cells)
            # Only fall back to a real 2D rectangle. For DISV the head array is
            # (nlay, 1, ncpl), so grid_shape is the degenerate (1, ncpl); applying
            # it would persist a bogus structured_shape=(1, ncpl) for genuinely
            # unstructured meshes. Leaving it None makes them persist as null.
            if (
                structured_shape is None
                and grid_shape is not None
                and int(grid_shape[0]) > 1
                and int(grid_shape[1]) > 1
                and int(grid_shape[0]) * int(grid_shape[1]) == int(n_cells)
            ):
                structured_shape = (int(grid_shape[0]), int(grid_shape[1]))
            # Pre-conditioning top (written by the builder as a sidecar) lets the
            # conditioning-impact map show how much the fill/breach moved the top.
            topography_reference = None
            ref_files = list(solver_output_dir.glob("*.conditioning_ref.npy"))
            if ref_files:
                ref = np.asarray(np.load(ref_files[0]), dtype="float64").ravel()[:n_cells]
                if ref.size == top.size:
                    topography_reference = ref

            sz = store.open_zarr(sim_id)
            try:
                sz.write_mesh(
                    vertices=vertices,
                    face_node_connectivity=face_node_connectivity,
                    z_interfaces=z_flat,
                    topography=top,
                    topography_reference=topography_reference,
                    grid_type=grid_type,
                    structured_shape=structured_shape,
                )
            finally:
                sz.close()
        except Exception:
            logger.debug("Could not write surface elevation for sim %s", sim_id, exc_info=True)

    @staticmethod
    def _mesh_geometry_from_grid(
        grid: Any,
        *,
        n_cells: int,
    ) -> tuple[np.ndarray, np.ndarray] | None:
        """Return UGRID vertices/connectivity from a FloPy MfGrdFile."""
        verts = getattr(grid, "verts", None)
        iverts = getattr(grid, "iverts", None)
        if verts is not None and iverts is not None:
            vertices = np.asarray(verts, dtype="float64")
            if vertices.ndim == 2 and vertices.shape[1] == 2:
                vertices = np.column_stack([vertices, np.zeros(vertices.shape[0])])
            connectivity = Modflow6OutputAdapter._padded_face_connectivity(
                iverts,
                n_cells=n_cells,
            )
            if connectivity is not None:
                return vertices, connectivity

        try:
            modelgrid = grid.modelgrid
            xvertices = np.asarray(modelgrid.xvertices, dtype="float64")
            yvertices = np.asarray(modelgrid.yvertices, dtype="float64")
        except Exception:
            return None

        if xvertices.ndim != 2 or yvertices.shape != xvertices.shape:
            return None
        nrow = int(xvertices.shape[0] - 1)
        ncol = int(xvertices.shape[1] - 1)
        if nrow <= 0 or ncol <= 0 or nrow * ncol != int(n_cells):
            return None
        vertices = np.column_stack(
            [
                xvertices.ravel(),
                yvertices.ravel(),
                np.zeros(xvertices.size, dtype="float64"),
            ]
        )
        return vertices, Modflow6OutputAdapter._structured_face_connectivity(nrow, ncol)

    @staticmethod
    def _padded_face_connectivity(
        iverts: Any,
        *,
        n_cells: int,
    ) -> np.ndarray | None:
        """Convert ragged MF6 iverts lists to padded UGRID connectivity."""
        rows: list[list[int]] = []
        for row in list(iverts)[: int(n_cells)]:
            cleaned = [int(node) for node in row if int(node) >= 0]
            if len(cleaned) > 1 and cleaned[0] == cleaned[-1]:
                cleaned = cleaned[:-1]
            if len(cleaned) < 3:
                rows.append([])
            else:
                rows.append(cleaned)
        if len(rows) != int(n_cells) or not any(rows):
            return None
        width = max(len(row) for row in rows)
        connectivity = np.full((int(n_cells), width), -1, dtype="int32")
        for cell_id, row in enumerate(rows):
            if row:
                connectivity[cell_id, : len(row)] = row
        return connectivity

    @staticmethod
    def _structured_face_connectivity(nrow: int, ncol: int) -> np.ndarray:
        """Return quadrilateral face connectivity for a structured grid."""
        nc = int(ncol) + 1
        connectivity = np.empty((int(nrow) * int(ncol), 4), dtype="int32")
        for row in range(int(nrow)):
            for col in range(int(ncol)):
                cell_id = row * int(ncol) + col
                node_id = row * nc + col
                connectivity[cell_id] = (
                    node_id,
                    node_id + 1,
                    node_id + nc + 1,
                    node_id + nc,
                )
        return connectivity

    @staticmethod
    def _structured_shape_from_vertices(
        vertices: np.ndarray | None,
        *,
        n_cells: int,
    ) -> tuple[int, int] | None:
        """Infer a regular grid shape from rectangular UGRID vertices."""
        if vertices is None:
            return None
        values = np.asarray(vertices, dtype="float64")
        if values.ndim != 2 or values.shape[0] == 0 or values.shape[1] < 2:
            return None
        unique_x = np.unique(np.round(values[:, 0], decimals=9))
        unique_y = np.unique(np.round(values[:, 1], decimals=9))
        ncol = int(unique_x.size - 1)
        nrow = int(unique_y.size - 1)
        if nrow > 0 and ncol > 0 and nrow * ncol == int(n_cells):
            return nrow, ncol
        return None

    @staticmethod
    def _structured_mesh_geometry_from_shape(
        store: Any,
        sim_id: str,
        *,
        n_cells: int,
        grid_shape: tuple[int, int] | None,
    ) -> tuple[np.ndarray, np.ndarray] | None:
        """Build rectangular UGRID geometry when the GRB lacks vertices."""
        shape = grid_shape
        if shape is None or int(shape[0]) * int(shape[1]) != int(n_cells):
            side = int(np.sqrt(int(n_cells)))
            shape = (side, side) if side * side == int(n_cells) else None
        if shape is None:
            return None

        nrow, ncol = int(shape[0]), int(shape[1])
        try:
            sz = store.open_zarr(sim_id)
            try:
                _, meta = sz.read_geographic_raster("watershed_dem")
            finally:
                sz.close()
            transform = meta["transform"]
            geographic_metadata = store.read_geographic_metadata(sim_id)
            geo_rows = int(geographic_metadata.get("nrow", nrow))
            geo_cols = int(geographic_metadata.get("ncol", ncol))
            xmin = float(transform[2])
            xmax = xmin + geo_cols * float(transform[0])
            ymax = float(transform[5])
            ymin = ymax + geo_rows * float(transform[4])
        except Exception:
            xmin, xmax = 0.0, float(ncol)
            ymin, ymax = 0.0, float(nrow)

        x_edges = np.linspace(xmin, xmax, ncol + 1, dtype="float64")
        y_edges = np.linspace(ymax, ymin, nrow + 1, dtype="float64")
        xx, yy = np.meshgrid(x_edges, y_edges)
        vertices = np.column_stack(
            [
                xx.ravel(),
                yy.ravel(),
                np.zeros(xx.size, dtype="float64"),
            ]
        )
        return vertices, Modflow6OutputAdapter._structured_face_connectivity(nrow, ncol)

    def derive(
        self,
        sim_id: str,
        store: Any,
        config: dict | None = None,
    ) -> None:
        """Compute derived variables from stored head fields."""
        from hydromodpy.simulation.extraction.derivation.derived import compute_derived

        cfg = config or {}
        compute_derived(sim_id, store, cfg)
