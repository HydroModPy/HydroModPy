"""MODFLOW 6 PRT particle-tracking solver class."""

from __future__ import annotations

import os
import warnings
from collections.abc import Mapping, Sequence

import flopy
import numpy as np

from hydromodpy.core.units.time import SECONDS_PER_DAY, factor_to_seconds
from hydromodpy.solver.base.protocols import DomainLike, FlowModelLike, TransportLike
from hydromodpy.solver.modflow6.build import mf6_safe_name


def _as_float_list(values: Sequence[float] | None) -> list[float] | None:
    if values is None:
        return None
    parsed = [float(v) for v in values]
    return parsed or None


def _regular_track_times_days(
    *,
    stop_time_days: object | None,
    track_time_step_days: object | None,
) -> list[float] | None:
    if track_time_step_days is None:
        return None
    if stop_time_days is None:
        raise ValueError("track_time_step_days requires stop_time_days.")
    step = float(track_time_step_days)
    stop = float(stop_time_days)
    if step <= 0.0:
        raise ValueError("track_time_step_days must be positive.")
    if stop <= 0.0:
        raise ValueError("stop_time_days must be positive when track_time_step_days is used.")

    values = np.arange(0.0, stop + 0.5 * step, step, dtype=float)
    values = values[values <= stop + _TRACK_TIME_TOLERANCE_DAYS]
    if values.size == 0 or not np.isclose(values[-1], stop):
        values = np.append(values, stop)
    return [float(value) for value in values]


# Numerical tolerance (days) used to clip the last regular track time to
# stop_time_days without losing it to floating-point rounding.
_TRACK_TIME_TOLERANCE_DAYS = 1.0e-9

# Last-resort porosity when no transport porosity is set and specific yield is
# non-positive. 0.30 is a generic unconsolidated-aquifer placeholder.
_PRT_DEFAULT_POROSITY = 0.30


class Modflow6Prt:
    """Particle tracking based on MODFLOW 6 PRT and `transport.modflow6prt`.

    The class attaches a PRT model to an existing MODFLOW 6 GWF simulation. It
    intentionally keeps the first implementation narrow: DISV grids, forward
    tracking, centroid-based release points, and CSV track output for ingestion
    into the HydroModPy catalog.
    """

    def __init__(
        self,
        domain: DomainLike,
        transport: TransportLike,
        model_modflow: FlowModelLike,
        model_folder: str = "HydroModPy_outputs",
        model_name: str = "Default_modflow6",
        suffix_name: str = "_prt",
        bin_path: str | None = None,
        **kwargs: object,
    ) -> None:
        del bin_path
        self.domain = domain
        self.transport = transport
        self.model_modflow = model_modflow
        self.model_folder = model_folder
        self.model_name = model_name
        self.suffix_name = suffix_name
        self.model_name_prt = model_name + suffix_name
        self.model_name_prt_mf6 = mf6_safe_name(self.model_name_prt)
        self.full_path = os.path.join(model_folder, model_name)
        self.exe = getattr(model_modflow, "exe", "mf6")

        prt_params: dict[str, object] = {}
        comp = transport.modflow6prt
        if isinstance(getattr(comp, "parameters", None), Mapping):
            prt_params = dict(comp.parameters)
        prt_params.update(kwargs)

        self.release_zone = str(prt_params.get("release_zone", "domain"))
        self.upstream_top_quantile = float(prt_params.get("upstream_top_quantile", 0.90))
        self.outlet_bottom_quantile = float(prt_params.get("outlet_bottom_quantile", 0.10))
        self.track_dir = str(prt_params.get("track_dir", "forward"))
        self.porosity = prt_params.get("porosity")
        self.local_z = float(prt_params.get("local_z", 0.5))
        self.particle_cell_ids = prt_params.get("particle_cell_ids")
        self.max_particles = prt_params.get("max_particles")
        self.sel_slice = prt_params.get("sel_slice")
        self.release_times_days = _as_float_list(prt_params.get("release_times_days"))
        self.track_times_days = _as_float_list(prt_params.get("track_times_days"))
        self.track_time_step_days = prt_params.get("track_time_step_days")
        self.stop_time_days = prt_params.get("stop_time_days")
        self.stop_travel_time_days = prt_params.get("stop_travel_time_days")
        self.extend_tracking = bool(prt_params.get("extend_tracking", True))
        self.dry_tracking_method = str(prt_params.get("dry_tracking_method", "drop"))
        self.exit_solve_tolerance = float(prt_params.get("exit_solve_tolerance", 1.0e-5))
        self.write_track_csv = bool(prt_params.get("write_track_csv", True))
        self.write_track_binary = bool(prt_params.get("write_track_binary", True))

    def _model_time_unit_seconds(self) -> float:
        """Seconds per model TDIS time unit. Defaults to DAYS when TDIS is absent."""
        raw_units = "DAYS"
        tdis = getattr(self.model_modflow, "tdis", None)
        units = getattr(tdis, "time_units", None)
        if hasattr(units, "get_data"):
            raw_units = str(units.get_data())
        elif units is not None:
            raw_units = str(units)
        token = raw_units.strip().upper()
        if token == "UNKNOWN":
            return 1.0
        try:
            return factor_to_seconds(token)
        except ValueError:
            return SECONDS_PER_DAY

    def _days_to_model_time(self, value: float | None) -> float | None:
        if value is None:
            return None
        return float(value) * SECONDS_PER_DAY / self._model_time_unit_seconds()

    def _build_track_times_days(self) -> list[float] | None:
        if self.track_times_days is not None:
            return self.track_times_days
        return _regular_track_times_days(
            stop_time_days=self.stop_time_days,
            track_time_step_days=self.track_time_step_days,
        )

    def _build_porosity(self) -> np.ndarray:
        """Return PRT MIP porosity. Pore velocity v = q / porosity needs total
        porosity, not specific yield; the Sy fallback warns and is a placeholder."""
        nlay = int(self.model_modflow.nlay)
        ncpl = int(self.model_modflow.ncpl)
        if self.porosity is not None:
            return np.full((nlay, ncpl), float(self.porosity), dtype=float)

        warnings.warn(
            "No PRT porosity set; falling back to the flow specific yield "
            f"(or {_PRT_DEFAULT_POROSITY} where non-positive), which overstates particle "
            "speed. Set transport.modflow6prt.parameters.porosity.",
            UserWarning,
            stacklevel=2,
        )
        sy = np.asarray(getattr(self.model_modflow, "sy", _PRT_DEFAULT_POROSITY), dtype=float)
        if sy.size == 1:
            sy = np.full((nlay, ncpl), float(sy.reshape(-1)[0]), dtype=float)
        else:
            sy = sy.reshape(nlay, ncpl)
        return np.where(sy > 0.0, sy, _PRT_DEFAULT_POROSITY).astype(float)

    def _active_planar_mask(self) -> np.ndarray:
        solver_mesh = self.model_modflow.solver_mesh
        active = ~np.asarray(solver_mesh.inactive_mask, dtype=bool)
        if active.ndim == 2:
            return np.any(active, axis=0)
        return np.asarray(active, dtype=bool).reshape(-1)

    def _stream_support_mask(self) -> np.ndarray:
        ncpl = int(self.model_modflow.ncpl)
        mask = np.asarray(
            getattr(self.model_modflow, "_stream_support_mask", np.zeros(ncpl, dtype=bool)),
            dtype=bool,
        ).reshape(-1)
        if mask.size != ncpl:
            raise ValueError(
                "MODFLOW 6 PRT stream support mask size does not match the DISV cell count."
            )
        return mask

    def _upstream_planar_mask(self, active: np.ndarray) -> np.ndarray:
        top = np.asarray(self.model_modflow.solver_mesh.top, dtype=float).reshape(-1)
        valid = active & np.isfinite(top)
        if not np.any(valid):
            raise ValueError("MODFLOW 6 PRT upstream release zone has no finite active top cells.")
        # ``np.nanpercentile`` expects [0, 100]; convert the [0, 1] user quantile.
        percentile = 100.0 * float(self.upstream_top_quantile)
        cutoff = np.nanpercentile(top[valid], percentile)
        return active & (top >= cutoff)

    def _spatially_sample_release_cells(self, selected: np.ndarray, max_count: int) -> np.ndarray:
        """Select a deterministic, spatially spread subset of release cells."""

        if selected.size <= max_count:
            return selected
        centroids = np.asarray(
            self.model_modflow.solver_mesh.cell_centroids(), dtype=float
        ).reshape(int(self.model_modflow.ncpl), 2)
        coords = centroids[selected]
        finite = np.all(np.isfinite(coords), axis=1)
        if np.count_nonzero(finite) < max_count:
            keep = np.linspace(0, selected.size - 1, max_count, dtype=int)
            return selected[keep]

        finite_positions = np.flatnonzero(finite)
        finite_coords = coords[finite_positions]
        center = np.nanmean(finite_coords, axis=0)
        first = int(np.argmin(np.sum((finite_coords - center) ** 2, axis=1)))
        chosen_positions = [int(finite_positions[first])]
        min_dist2 = np.sum((coords - coords[chosen_positions[0]]) ** 2, axis=1)

        while len(chosen_positions) < max_count:
            min_dist2[chosen_positions] = -np.inf
            next_pos = int(np.nanargmax(min_dist2))
            if not np.isfinite(min_dist2[next_pos]):
                break
            chosen_positions.append(next_pos)
            candidate_dist2 = np.sum((coords - coords[next_pos]) ** 2, axis=1)
            min_dist2 = np.minimum(min_dist2, candidate_dist2)

        if len(chosen_positions) < max_count:
            remaining = [idx for idx in range(selected.size) if idx not in set(chosen_positions)]
            chosen_positions.extend(remaining[: max_count - len(chosen_positions)])
        return selected[np.asarray(chosen_positions[:max_count], dtype=int)]

    def _select_release_cells(self) -> np.ndarray:
        solver_mesh = self.model_modflow.solver_mesh
        ncpl = int(self.model_modflow.ncpl)
        active = self._active_planar_mask()
        all_active = np.flatnonzero(active)
        zone = self.release_zone.strip().lower()

        if zone == "custom":
            if self.particle_cell_ids is None:
                raise ValueError("release_zone='custom' requires particle_cell_ids.")
            selected = np.asarray(self.particle_cell_ids, dtype=int).reshape(-1)
        elif zone == "river":
            selected = np.flatnonzero(self._stream_support_mask() & active)
        elif zone == "upstream":
            selected = np.flatnonzero(self._upstream_planar_mask(active))
        elif zone in {"upstream_nonriver", "upstream_non_river", "upstream_land"}:
            selected = np.flatnonzero(
                self._upstream_planar_mask(active) & ~self._stream_support_mask()
            )
        elif zone in {"domain_nonriver", "domain_non_river", "nonriver", "land"}:
            selected = np.flatnonzero(active & ~self._stream_support_mask())
        elif zone == "outlet":
            top = np.asarray(solver_mesh.top, dtype=float).reshape(-1)
            river_mask = self._stream_support_mask()
            candidate = active & river_mask
            if not np.any(candidate):
                candidate = active
            # ``np.nanpercentile`` expects [0, 100]; convert the [0, 1] user quantile.
            percentile = 100.0 * float(self.outlet_bottom_quantile)
            cutoff = np.nanpercentile(top[candidate], percentile)
            selected = np.flatnonzero(candidate & (top <= cutoff))
        elif zone == "domain":
            selected = all_active
        else:
            raise ValueError(
                "Unsupported modflow6prt release_zone "
                f"{self.release_zone!r}; expected domain, domain_nonriver, upstream, "
                "upstream_nonriver, river, outlet, or custom."
            )

        selected = np.asarray(selected, dtype=int)
        selected = selected[(selected >= 0) & (selected < ncpl) & active[selected]]
        selected = np.unique(selected)
        if self.sel_slice is not None:
            selected = selected[:: int(self.sel_slice)]
        if self.max_particles is not None and selected.size > int(self.max_particles):
            selected = self._spatially_sample_release_cells(selected, int(self.max_particles))
        if selected.size == 0:
            raise ValueError(f"MODFLOW 6 PRT release zone {self.release_zone!r} selected no cells.")
        return selected

    def _topmost_active_layer(self, cell_id: int) -> int:
        """Return the highest (smallest index) active layer for a planar cell.

        Releasing in layer 0 fails when layer 0 is inactive (idomain<=0) but a
        deeper layer is active, so the release layer follows the cell column.
        """
        inactive = np.asarray(self.model_modflow.solver_mesh.inactive_mask, dtype=bool)
        if inactive.ndim == 2:
            active_layers = np.flatnonzero(~inactive[:, int(cell_id)])
            if active_layers.size:
                return int(active_layers[0])
        return 0

    def _build_packagedata(self) -> list[tuple]:
        centroids = np.asarray(
            self.model_modflow.solver_mesh.cell_centroids(), dtype=float
        ).reshape(int(self.model_modflow.ncpl), 2)
        cells = self._select_release_cells()
        packagedata: list[tuple] = []
        for iprt, cell_id in enumerate(cells):
            x, y = centroids[int(cell_id)]
            lay = self._topmost_active_layer(int(cell_id))
            packagedata.append(
                (
                    int(iprt),
                    (lay, int(cell_id)),
                    float(x),
                    float(y),
                    float(self.local_z),
                    f"prt_{int(cell_id)}",
                )
            )
        return packagedata

    def pre_processing(self) -> None:
        if self.track_dir != "forward":
            raise NotImplementedError(
                "MODFLOW 6 PRT integration currently supports forward tracking."
            )
        if not hasattr(self.model_modflow, "sim") or self.model_modflow.sim is None:
            raise RuntimeError("Modflow6Prt requires a preprocessed MODFLOW 6 flow model.")

        sim = self.model_modflow.sim
        self.gwf = self.model_modflow.gwf
        solver_mesh = self.model_modflow.solver_mesh
        idomain = solver_mesh.idomain()

        self.prt = flopy.mf6.ModflowPrt(
            sim,
            modelname=self.model_name_prt_mf6,
            save_flows=True,
        )
        disv_kwargs = solver_mesh.to_disv_kwargs()
        # DISV vertices already hold absolute model coordinates (UTM/Lambert meters),
        # so the package origin must be 0. Passing solver_mesh.xoffset here would shift
        # the whole grid by one full origin (double offset). PRP release points use
        # absolute centroids, so they only line up with an un-offset grid.
        self.prtdis = flopy.mf6.ModflowPrtdisv(
            self.prt,
            nlay=self.model_modflow.nlay,
            **disv_kwargs,
            idomain=idomain,
            xorigin=0.0,
            yorigin=0.0,
            length_units="METERS",
        )
        self.mip = flopy.mf6.ModflowPrtmip(self.prt, porosity=self._build_porosity())
        self.ems = flopy.mf6.ModflowEms(
            sim,
            filename=f"{self.model_name_prt}.ems",
        )
        sim.register_solution_package(self.ems, [self.prt.name])

        packagedata = self._build_packagedata()
        releasetimes = (
            [(float(self._days_to_model_time(time)),) for time in self.release_times_days]
            if self.release_times_days is not None
            else None
        )
        perioddata = None if releasetimes is not None else {0: [("FIRST",)]}

        track_file = f"{self.model_name_prt}.trk" if self.write_track_binary else None
        track_csv_file = f"{self.model_name_prt}.trk.csv" if self.write_track_csv else None

        self.prp = flopy.mf6.ModflowPrtprp(
            self.prt,
            boundnames=True,
            local_z=True,
            extend_tracking=self.extend_tracking,
            stoptime=self._days_to_model_time(float(self.stop_time_days))
            if self.stop_time_days is not None
            else None,
            stoptraveltime=self._days_to_model_time(float(self.stop_travel_time_days))
            if self.stop_travel_time_days is not None
            else None,
            dry_tracking_method=self.dry_tracking_method,
            exit_solve_tolerance=self.exit_solve_tolerance,
            # COORDINATE_CHECK_METHOD is a regular PRP option in MF6 6.7.0
            # (prt-prp.dfn) but was added after 6.6.3, so the installed release
            # binary rejects it. flopy defaults this option to "eager" and writes
            # the tag, so an explicit None is required to suppress it.
            coordinate_check_method=None,
            nreleasepts=len(packagedata),
            nreleasetimes=len(releasetimes) if releasetimes is not None else None,
            packagedata=packagedata,
            releasetimes=releasetimes,
            perioddata=perioddata,
            pname="PRP",
        )

        track_times_days = self._build_track_times_days()
        tracktimes = (
            [(float(self._days_to_model_time(time)),) for time in track_times_days]
            if track_times_days is not None
            else None
        )
        self.oc = flopy.mf6.ModflowPrtoc(
            self.prt,
            budget_filerecord=f"{self.model_name_prt}.bud",
            budgetcsv_filerecord=f"{self.model_name_prt}.bud.csv",
            track_filerecord=track_file,
            trackcsv_filerecord=track_csv_file,
            track_release=True,
            track_exit=True,
            track_timestep=True,
            track_terminate=True,
            track_usertime=tracktimes is not None,
            ntracktimes=len(tracktimes) if tracktimes is not None else None,
            tracktimes=tracktimes,
            saverecord=[("BUDGET", "ALL")],
        )
        self.gwfprt = flopy.mf6.ModflowGwfprt(
            sim,
            exgtype="GWF6-PRT6",
            exgmnamea=self.gwf.name,
            exgmnameb=self.prt.name,
        )

    def processing(
        self,
        write_model: bool = True,
        run_model: bool = False,
        verbose: bool = True,
    ) -> bool:
        if write_model:
            self.model_modflow.sim.write_simulation(silent=not verbose)
        success = False
        if run_model:
            success, _ = self.model_modflow.sim.run_simulation(silent=not verbose)
        return success


__all__ = ["Modflow6Prt"]
