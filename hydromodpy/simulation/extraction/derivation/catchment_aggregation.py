"""Catchment-aggregated timeseries from the spatial fields of one run."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from hydromodpy.core.exceptions import ExtractError
from hydromodpy.core.field_routing import CATCHMENT_BUDGET_ZONE
from hydromodpy.core.logging import get_logger
from hydromodpy.core.time.period_aggregation import period_end_stamps, period_mean_on_index

logger = get_logger(__name__)

_CATCHMENT_STATION = "_catchment"

_SLAB_TARGET_BYTES = 64 * 1024 * 1024

_BASIN_ARRAY = "descent_basin"
_LARGEST_BASIN_RULE = "largest_basin"


@dataclass(frozen=True, slots=True)
class _StoredBasin:
    """The basin of D a run stored under ``mesh/descent_basin``."""

    mask: np.ndarray
    area_m2: float
    rule: str

    @property
    def is_catchment(self) -> bool:
        """False for the largest basin of a domain with neither outlet nor polygon."""
        return self.rule != _LARGEST_BASIN_RULE


def _stored_basin(mesh: Any) -> _StoredBasin | None:
    """The basin of D stored with the mesh, None for a run that stored none."""
    if mesh is None or _BASIN_ARRAY not in mesh:
        return None
    node = mesh[_BASIN_ARRAY]
    attrs = node.attrs
    return _StoredBasin(
        mask=np.asarray(node[:], dtype=bool).ravel(),
        area_m2=float(attrs["basin_area_m2"]),
        rule=str(attrs["basin_rule"]),
    )


VARIABLE_UNITS: dict[str, str] = {
    "discharge": "m3/s",
    "well_pumping": "m3/s",
}

# (source_variable, output_variable, reducer)
# source_variable is looked up in derived/ then budget/ then root.
#
# The run only materialises timeseries that downstream figures and
# calibration pipelines consume as-is. Catchment-scale reductions of
# spatial fields (drainage density, saturated fraction, water-table
# means, recharge means) are computed lazily on demand through
# ``hydromodpy.core.metrics`` / ``Run`` methods, so the
# timeseries table stays focused on observation-comparable point series.
_AGGREGATION_SPEC: list[tuple[str, str, str]] = [
    # Direct drain outflow (m3/s) - sum of |drain flux| over the catchment.
    # The MVR-routed share lives in the separate DRN-TO-MVR budget record and
    # is therefore excluded: it re-enters the model through SFR and surfaces
    # in the routed ext_outflow series instead.
    ("drain", "discharge", "abs_sum"),
    # Well pumping total (m3/s).
    ("well", "well_pumping", "sum"),
]


def aggregate_catchment_timeseries(
    sim_id: str,
    store: Any,
    *,
    time_index: pd.DatetimeIndex | None = None,
    drainage_outside_routed: bool = False,
) -> None:
    """Read spatial fields from the store and write catchment-aggregated timeseries.

    The ``discharge`` series is the surface water leaving the catchment. When
    the run carries SFR / LAK extracted series, the discharge IS the routed
    outflow (``ext_outflow`` at terminal reaches and lake outlets), which already
    carries the in-watershed drainage (routed through DRN-TO-MVR) and the runoff
    injected into the network; the residual plain-DRN record is buffer drainage
    from neighbouring basins and is excluded. Without a stream network the series
    falls back to the lumped accounting: sum of |DRN| plus the watershed runoff
    forcing read from Zarr ``forcing/``.

    Parameters
    ----------
    sim_id : str
        Simulation UUID.
    store : RunStore
        Store of the run, holding the fields of the extract phase.
    time_index : pd.DatetimeIndex, optional
        Datetime labels for each timestep. When None, integer indices are used.
    drainage_outside_routed : bool
        True when the network does not route the hillslope drainage
        (``route_drainage = false``). The catchment drain budget then holds water
        the routed series leaves out, so it is added to the routed series.
    """
    sz = store.open_zarr(sim_id)
    try:
        grp = sz.root

        n_timesteps = _detect_n_timesteps(grp)
        if n_timesteps == 0:
            raise RuntimeError(f"No timesteps found for sim {sim_id}; cannot aggregate catchment")

        domain_mask = _build_active_mask(grp)
        active_mask = _build_catchment_mask(store, sim_id, grp, domain_mask)

        pending: list[tuple[str, list[float]]] = []
        for store_var, output_var, reducer in _AGGREGATION_SPEC:
            # The lumped row of the catchment zone is the float64 budget of the
            # solver; the per-cell field is stored rounded to 16 mantissa bits.
            # MODFLOW 6 writes the row, so it wins where it exists.
            values = _aggregate_from_lumped_budget(
                store,
                sim_id,
                store_var,
                reducer,
                n_timesteps,
                catchment_only=True,
            )
            if values is None:
                values = _aggregate_variable(
                    store, sim_id, grp, store_var, n_timesteps, active_mask, reducer
                )
            if values is None:
                # The run kept no per-cell field for this term: the lumped
                # per-component budget still carries it.
                values = _aggregate_from_lumped_budget(
                    store,
                    sim_id,
                    store_var,
                    reducer,
                    n_timesteps,
                    catchment_fraction=_catchment_fraction(active_mask, domain_mask),
                )
            if values is None:
                continue
            pending.append((output_var, values))

        routed = _routed_outflow_by_timestep(store, sim_id, n_timesteps)
        if not pending and routed is None:
            return

        if time_index is not None and len(time_index) == n_timesteps:
            ts_index = time_index
        else:
            try:
                ts_index = _resolve_time_index(store, sim_id, n_timesteps)
            except RuntimeError as exc:
                logger.warning("Skipping catchment timeseries for sim %s: %s", sim_id, exc)
                return

        series_by_var: dict[str, pd.Series] = {
            output_var: pd.Series(values, index=ts_index, name=output_var, dtype="float64")
            for output_var, values in pending
        }
        if routed is not None:
            # The routed SFR/LAK ext_outflow already carries the in-watershed
            # drainage (moved into the DRN-TO-MVR record by route_drainage, whose
            # plain-DRN residual is ~0). The remaining plain-DRN outflow is the
            # buffer (neighbouring-basin) drainage, which must NOT feed this
            # catchment, so it is dropped instead of added.
            routed_series = pd.Series(routed, index=ts_index, name="discharge", dtype="float64")
            if drainage_outside_routed and "discharge" in series_by_var:
                # Without route_drainage the hillslope drainage stays in DRAIN: it
                # is not the buffer drainage, and the routed series does not hold it.
                routed_series = routed_series + series_by_var["discharge"]
            series_by_var["discharge"] = routed_series
            _warn_routed_without_runoff(store, sim_id, grp)
            logger.debug("Catchment discharge for sim %s uses routed SFR/LAK outflow", sim_id)
        elif "discharge" in series_by_var:
            series_by_var["discharge"] = _add_runoff_to_discharge_series(
                series_by_var["discharge"],
                sim_id,
                store,
                grp,
                start=_read_period_start(store, sim_id, ts_index),
            )

        # One batched write, not one write_timeseries per variable: the latter
        # re-reads and rewrites the whole timeseries.parquet each call (O(K^2)).
        records: list[dict[str, Any]] = []
        for output_var, ts in series_by_var.items():
            unit = VARIABLE_UNITS.get(output_var, "")
            index = pd.DatetimeIndex(ts.index)
            index = index.tz_localize("UTC") if index.tz is None else index.tz_convert("UTC")
            for step, (when, value) in enumerate(
                zip(index.to_pydatetime(), ts.to_numpy(dtype="float64"), strict=False)
            ):
                records.append(
                    {
                        "sim_id": str(sim_id),
                        "station_id": _CATCHMENT_STATION,
                        "variable": output_var,
                        "component": None,
                        "timestep": step,
                        "time": when,
                        "value": float(value),
                        "unit": unit,
                        "qflag": "simulated",
                    }
                )
        if records:
            store.write_timeseries_batch(sim_id, records)
        written = len(series_by_var)
    finally:
        sz.close()

    if written:
        logger.debug("Wrote %d catchment-aggregated timeseries for sim %s", written, sim_id)


_ROUTED_RUNOFF_WARNING_EMITTED: set[str] = set()


def _run_window(store: Any) -> tuple[pd.Timestamp, pd.Timestamp, Any] | None:
    """Return ``(period_start, period_end, time_unit)`` from the facts of the run.

    The bounds are stored in UTC; they come back as naive UTC, the clock of
    the stored series.
    """
    facts = store.facts
    if facts.period_start is None or facts.period_end is None:
        return None
    return _naive_utc(facts.period_start), _naive_utc(facts.period_end), facts.time_unit


def _naive_utc(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_convert("UTC").tz_localize(None) if ts.tz is not None else ts


def _station_rows(frame: pd.DataFrame, variable: str) -> pd.DataFrame:
    """Rows of one variable at the SFR reaches and the lake outlets."""
    if frame.empty:
        return frame
    stations = frame["station_id"].astype(str)
    network = stations.str.startswith("sfr:") | stations.str.startswith("lake:")
    return frame[(frame["variable"] == variable) & network]


def _read_period_start(store: Any, sim_id: str, index: pd.DatetimeIndex) -> pd.Timestamp | None:
    """Return the run window start when it precedes the first stamp, else None."""
    window = _run_window(store)
    if window is None or len(index) == 0:
        return None
    first_stamp = pd.Timestamp(index.min())
    if first_stamp.tz is not None:
        first_stamp = first_stamp.tz_convert("UTC").tz_localize(None)
    start = window[0]
    return start if start < first_stamp else None


def _warn_routed_without_runoff(store: Any, sim_id: str, grp: Any) -> None:
    """Warn once if runoff forcing exists but was not routed into SFR/LAK.

    The routed discharge assumes the runoff was injected into the network; if a
    run carries runoff forcing in Zarr but no runoff was wired to any SFR/lake
    station, the routed discharge silently omits it.
    """
    if sim_id in _ROUTED_RUNOFF_WARNING_EMITTED:
        return
    forcing = grp.get("forcing")
    if forcing is None or "runoff" not in forcing:
        return
    if _station_rows(store.read_table("timeseries"), "runoff").empty:
        logger.warning(
            "catchment discharge: runoff forcing is present for sim %s but no runoff was "
            "routed into SFR/LAK; the routed discharge excludes the runoff component.",
            sim_id,
        )
        _ROUTED_RUNOFF_WARNING_EMITTED.add(sim_id)


def _routed_outflow_by_timestep(
    store: Any,
    sim_id: str,
    n_timesteps: int,
) -> np.ndarray | None:
    """Sum of ext_outflow over SFR reaches and lake outlets, per timestep.

    ``ext_outflow`` is the surface water leaving the model at a terminal reach or
    a lake outlet (stations ``sfr:*`` / ``lake:*``, extracted from the MF6 obs
    CSVs in m3/s). Both extractors store it with the same positive-outflow
    convention. Returns None when no such series exists (no SFR / LAK run).

    Same definition as ``routed_outflow_series`` in the MODFLOW 6 SFR extractor
    (reach ext-outflow plus lake-outlet ext-outflow): one routed discharge, two
    readers (the run files for the calibration, the store here).
    """
    outflow = _station_rows(store.read_table("timeseries"), "ext_outflow")
    if outflow.empty:
        return None
    totals = outflow.groupby("timestep")["value"].sum(min_count=1)
    # NaN, not zero, for timesteps with no ext_outflow row: a genuine zero
    # outflow still arrives as a row (total=0.0), so only true gaps stay missing
    # and are excluded from metrics instead of biasing them toward zero flow.
    values = np.full(n_timesteps, np.nan, dtype="float64")
    for timestep, total in totals.items():
        t = int(timestep)
        if 0 <= t < n_timesteps and pd.notna(total):
            values[t] = float(total)
    return values


def _add_runoff_to_discharge_series(
    discharge: pd.Series,
    sim_id: str,
    store: Any,
    grp: Any,
    *,
    start: pd.Timestamp | None = None,
) -> pd.Series:
    """Add the surface-runoff forcing (m³/s) to a baseflow series.

    The forcing is read from the Zarr ``forcing/runoff/<station>/values``
    arrays persisted by ``step_persist_forcings``. Stations are averaged
    in mm/day, resampled to the simulation index, then converted to m³/s
    using the catchment area read from ``geographic_metadata``. When no
    runoff forcing is found, a one-shot warning is emitted and the
    baseflow is returned unchanged. ``start`` is the start of the first
    stress period, the run window start, when it is known.
    """
    runoff_grp = None
    forcing = grp.get("forcing")
    if forcing is not None and "runoff" in forcing:
        runoff_grp = forcing["runoff"]
    if runoff_grp is None:
        if sim_id not in _RUNOFF_WARNING_EMITTED:
            logger.warning(
                "Simulated discharge is baseflow only: the run has no runoff forcing, "
                "so it underestimates a gauged total streamflow."
            )
            logger.debug("No forcing/runoff group in the fields store of run %s.", sim_id)
            _RUNOFF_WARNING_EMITTED.add(sim_id)
        return discharge

    catch_area_m2 = _runoff_area_m2(store, sim_id, grp)
    if catch_area_m2 <= 0.0:
        logger.warning(
            "catchment discharge: catchment area unavailable for sim %s — "
            "skipping runoff addition.",
            sim_id,
        )
        return discharge

    series_list: list[pd.Series] = []
    for station_key in list(runoff_grp.array_keys()) + list(runoff_grp.group_keys()):
        node = runoff_grp[station_key]
        if hasattr(node, "shape"):
            # Flat array case (older layout); skip without timestamps.
            continue
        if "values" not in node or "timestamps" not in node:
            continue
        values_arr = np.asarray(node["values"][:], dtype="float64")
        timestamps_arr = np.asarray(node["timestamps"][:])
        if values_arr.size == 0:
            continue
        idx = pd.DatetimeIndex(pd.to_datetime(timestamps_arr))
        series_list.append(pd.Series(values_arr, index=idx))
    if not series_list:
        return discharge

    runoff_mm_per_d = pd.concat(series_list, axis=1).mean(axis=1)
    target_index = pd.DatetimeIndex(discharge.index)
    # AVERAGE the daily forcing over each stress period, never sample it.
    # ``reindex(method="nearest")`` handed a whole period the value of the one
    # day closest to its stamp: on a yearly steady step the Nancon received the
    # 1.36 mm of 1 January instead of the 0.33 mm the year averaged, and the
    # reported discharge came out 67 per cent above what its own water balance
    # allowed. ``period_mean_on_index`` is the one place that rule is written,
    # and the calibration metric calls it directly, so what a run is scored on
    # is what it reports. The window start bounds the first period, which a
    # single steady stamp cannot tell on its own.
    aligned = period_mean_on_index(runoff_mm_per_d, target_index, start=start)
    runoff_m3_per_s = aligned * 1e-3 * catch_area_m2 / 86400.0
    return discharge.add(runoff_m3_per_s, fill_value=0.0)


_RUNOFF_WARNING_EMITTED: set[str] = set()


def _runoff_area_m2(store: Any, sim_id: str, grp: Any) -> float:
    """Area the runoff forcing is scaled by: the stored basin of D, else ``catch_area``.

    The runoff is added to a discharge summed over the basin, so it covers the
    same surface. A run that stored no basin keeps the old support
    ``catch_area`` (the area of the delineated polygon raster) and says so.
    """
    basin = _stored_basin(grp.get("mesh"))
    if basin is not None and basin.is_catchment:
        return basin.area_m2
    area_m2 = _read_catchment_area_m2(store, sim_id)
    if basin is None:
        logger.info(
            "Catchment discharge for sim %s: the run stores no basin of D, so the runoff is "
            "scaled by the old support 'catch_area' (%.3f km2).",
            sim_id,
            area_m2 / 1.0e6,
        )
    return area_m2


def _read_catchment_area_m2(store: Any, sim_id: str) -> float:
    """Return the catchment area in m² from the geographic metadata of the run."""
    value = store.read_geographic_metadata(sim_id).get("catch_area")
    if not value:
        return 0.0
    return float(value) * 1e6


def _aggregate_variable(
    store: Any,
    sim_id: str,
    grp,
    store_var: str,
    n_timesteps: int,
    active_mask: np.ndarray | None,
    reducer: str,
) -> list[float] | None:
    """Try to read *store_var* for all timesteps, aggregate, and return scalar list."""
    # Locate the variable in derived/, budget/, or root.
    # store_var may contain "|" alternatives (e.g., "drains|drn|drain").
    candidates = [s.strip() for s in store_var.split("|")]
    derived_grp = grp.get("derived")
    budget_grp = grp.get("budget")

    target_grp = None
    resolved_key = None
    for key in candidates:
        if derived_grp is not None and key in derived_grp:
            target_grp, resolved_key = derived_grp, key
            break
        if budget_grp is not None and key in budget_grp:
            target_grp, resolved_key = budget_grp, key
            break
        if key in grp:
            target_grp, resolved_key = grp, key
            break

    if target_grp is None or resolved_key is None:
        return None

    arr = target_grp[resolved_key]
    if arr.shape[0] < n_timesteps:
        return None

    # Slab reads: one Zarr selection per block instead of one per timestep.
    bytes_per_step = max(int(np.prod(arr.shape[1:])) * 8, 1)
    block = max(1, min(n_timesteps, _SLAB_TARGET_BYTES // bytes_per_step))

    values: list[float] = []
    for t0 in range(0, n_timesteps, block):
        t1 = min(t0 + block, n_timesteps)
        fields = np.asarray(arr[t0:t1], dtype="float64")
        for field in fields:
            values.append(_reduce(field, active_mask, reducer))

    return values


def _lumped_budget_rows(
    budgets: pd.DataFrame,
    component: str,
    zone: str | None,
) -> list[tuple[Any, Any, Any]]:
    """One component's lumped budget, restricted to one zone when asked."""
    if budgets.empty:
        return []
    rows = budgets[budgets["component"] == component]
    if zone is not None:
        rows = rows[rows["zone_id"] == zone]
    if rows.empty:
        return []
    sums = rows.groupby("timestep")[["flux_in", "flux_out"]].sum(min_count=1)
    return [
        (timestep, None if pd.isna(fin) else fin, None if pd.isna(fout) else fout)
        for timestep, fin, fout in sums.itertuples(name=None)
    ]


def _catchment_fraction(
    catchment: np.ndarray | None,
    domain: np.ndarray | None,
) -> float | None:
    """Share of the active domain the delineated catchment covers."""
    if catchment is None or domain is None or catchment.size != domain.size:
        return None
    n_domain = int(domain.sum())
    if n_domain == 0:
        return None
    return float(int(catchment.sum())) / float(n_domain)


_DOMAIN_BUDGET_WARNING_EMITTED: set[tuple[str, str]] = set()


def _warn_lumped_budget_is_domain_wide(
    sim_id: str,
    component: str,
    catchment_fraction: float | None,
) -> None:
    """Say once that a '_catchment' series is carrying a domain-wide budget.

    Silent when the catchment covers the whole active domain: a MODFLOW-NWT run
    meshes the delineated basin, so its domain row already has the catchment for
    support and there is nothing to warn about. Silent too when the share is
    unknown, because ``_build_catchment_mask`` has already said why it could not
    place the watershed.
    """
    if catchment_fraction is None or catchment_fraction >= 1.0:
        return
    key = (str(sim_id), component)
    if key in _DOMAIN_BUDGET_WARNING_EMITTED:
        return
    _DOMAIN_BUDGET_WARNING_EMITTED.add(key)
    logger.warning(
        "Catchment timeseries for sim %s: the '%s' budget carries no zone_id='%s' "
        "row and no per-cell field, so the '%s' series is the whole model domain, "
        "of which the catchment covers %.0f%% of the active cells. The value is "
        "NOT rescaled: it is a domain total, not what a gauge at the outlet sees. "
        "The run kept no per-cell drain: set [simulation.results] "
        "keep_per_cell_budget = true (the default) to get the catchment "
        "support back.",
        sim_id,
        component,
        CATCHMENT_BUDGET_ZONE,
        _CATCHMENT_STATION,
        100.0 * catchment_fraction,
    )


def _aggregate_from_lumped_budget(
    store: Any,
    sim_id: str,
    store_var: str,
    reducer: str,
    n_timesteps: int,
    *,
    catchment_fraction: float | None = None,
    catchment_only: bool = False,
) -> list[float] | None:
    """Catchment scalar from the lumped per-component budget table.

    Used when the run kept no per-cell field for the term, or, with
    ``catchment_only``, to prefer the float64 catchment row over the rounded
    per-cell field. The lumped in/out fluxes (m3/s) land in the ``budgets``
    table whatever the per-cell budget kept. For a single-sign outflow term the spatial ``abs_sum`` (drain)
    equals ``flux_out``; a signed term's spatial ``sum`` (well) equals
    ``flux_in - flux_out``. Returns None for other reducers or when no component
    row matches.

    A ``zone_id = 'catchment'`` row is the only lumped row whose support is the
    catchment, so it wins. Any other zone spans the model domain, which on a
    buffered grid takes in the neighbouring basins; such a row is still used,
    because a run carrying nothing else must report something, but it is warned
    about once and never rescaled. ``catchment_only`` skips every other zone and
    returns None when no catchment row exists.
    """
    if reducer not in ("abs_sum", "sum"):
        return None
    try:
        budgets = store.read_table("budgets")
    except Exception as exc:
        # The lumped budget is the only source left once the per-cell budget
        # stopped being persisted: an unreadable table silently empties
        # discharge, so it must fail loudly.
        raise ExtractError(
            f"Cannot read the lumped budget of sim {sim_id}: the catchment "
            f"'{store_var}' series cannot be built ({exc})."
        ) from exc
    for candidate in (s.strip() for s in store_var.split("|")):
        rows = _lumped_budget_rows(budgets, candidate, CATCHMENT_BUDGET_ZONE)
        on_catchment = bool(rows)
        if not rows and catchment_only:
            continue
        if not rows:
            rows = _lumped_budget_rows(budgets, candidate, None)
        if not rows:
            continue
        if not on_catchment:
            _warn_lumped_budget_is_domain_wide(sim_id, candidate, catchment_fraction)
        # NaN, not zero, for timesteps with no budget row: a gap must stay
        # missing instead of biasing the metrics toward a null flux.
        values = [float("nan")] * n_timesteps
        for timestep, flux_in, flux_out in rows:
            t = int(timestep)
            if not (0 <= t < n_timesteps):
                continue
            fout = float(flux_out or 0.0)
            fin = float(flux_in or 0.0)
            values[t] = fout if reducer == "abs_sum" else fin - fout
        return values
    return None


def _resolve_time_index(store: Any, sim_id: str, n_timesteps: int) -> pd.DatetimeIndex:
    """Return the catchment series time axis, sharing the solver's clock.

    The aggregation reduces the Zarr field arrays, so it reuses their CF
    ``/time`` axis: the exact stress-period timestamps the solver wrote. This
    keeps the derived catchment series on the same clock as the native solver
    series (head, stage, budgets) instead of re-deriving a
    ``date_range(..., periods=n)`` that drifts (n-1 intervals over the window).
    Falls back to the ``period_start/period_end`` of the run facts only when
    the axis is unavailable, and then stamps each period at its end, as the
    solvers do.
    """
    times = _read_solver_time_axis(store, sim_id)
    if times is not None and len(times) == n_timesteps:
        return pd.DatetimeIndex(times)

    window = _run_window(store)
    if window is not None:
        start, end, unit = window
        return period_end_stamps(start, end, n_timesteps, step_unit=unit)
    raise RuntimeError(
        f"Simulation {sim_id} is missing period_start/period_end; "
        "cannot write catchment timeseries with synthetic timestamps."
    )


def _read_solver_time_axis(store: Any, sim_id: str) -> np.ndarray | None:
    """Read the persisted CF ``/time`` axis via the injected store (duck-typed)."""
    opener = getattr(store, "open_zarr", None)
    if not callable(opener):
        return None
    try:
        with opener(sim_id) as store_zarr:
            return store_zarr.read_time()
    except Exception:
        return None


def _detect_n_timesteps(grp) -> int:
    """Detect number of timesteps from head or derived arrays."""
    if "head" in grp:
        return grp["head"].shape[0]
    derived = grp.get("derived")
    if derived is not None:
        for key in derived:
            return derived[key].shape[0]
    return 0


def _build_active_mask(grp) -> np.ndarray | None:
    """Build boolean mask of active cells from mesh topography."""
    mesh = grp.get("mesh")
    if mesh is None:
        return None
    if "topography" in mesh:
        top = np.asarray(mesh["topography"][:], dtype="float64").ravel()
        return np.isfinite(top) & (top > -9000)
    return None


def _build_catchment_mask(store: Any, sim_id: str, grp, active: np.ndarray | None):
    """Cells of the catchment: the basin of D the run stored, else the delineated polygon.

    These series are written under the ``_catchment`` station, so the support
    has to be the catchment. It is not the same surface as the model domain:
    MODFLOW-NWT meshes the delineated basin, so the two coincide, while
    MODFLOW 6 meshes the buffered box. Measured on the Nancon at 25 m, 152.2
    km2 of domain against 64.6 km2 of catchment, and 2.119 m3/s of drain
    outflow against 0.888 m3/s inside the basin: summed over the domain, a
    series compared to a gauge carries 2.4 times the water that gauge sees.

    The support is ``mesh/descent_basin`` restricted to the active cells. A
    run that stored none (sealed before the basin was kept, or a solver that
    builds no D) keeps the old support ``polygon_centroid``: the cells whose
    centre the delineated watershed covers. A run that carries no watershed
    either keeps the active domain and says so with both areas, because a
    synthetic domain legitimately has no catchment and refusing would abort it.
    """
    mesh = grp.get("mesh")
    basin = _stored_basin(mesh)
    if basin is not None and basin.is_catchment:
        mask = basin.mask
        if active is not None and mask.size == active.size:
            mask = mask & active
        if not mask.any():
            raise ExtractError(
                f"the basin of D stored by run {sim_id} holds no active cell, so the "
                "'_catchment' series have no support."
            )
        logger.info(
            "Catchment timeseries for sim %s: the basin of D, %d of %d active cells (%.3f km2).",
            sim_id,
            int(mask.sum()),
            int(active.sum()) if active is not None else int(mask.size),
            basin.area_m2 / 1.0e6,
        )
        return mask
    if mesh is None or "vertices" not in mesh or "face_node_connectivity" not in mesh:
        return active
    if basin is None:
        logger.info(
            "Catchment timeseries for sim %s: the run stores no basin of D, so the "
            "'_catchment' series keep the old support 'polygon_centroid'.",
            sim_id,
        )
    try:
        watershed = store.read_geographic_feature(sim_id, "watershed")
    except Exception:
        watershed = None
    if watershed is None or watershed.empty:
        logger.warning(
            "Catchment timeseries for sim %s: no delineated watershed in the store, so "
            "the '_catchment' series are summed over the whole active domain. On a "
            "buffered grid that takes in the neighbouring basins.",
            sim_id,
        )
        return active

    from hydromodpy.spatial.mesh.model.derived_geometry import cell_polygons
    from hydromodpy.spatial.mesh.ops.vector_cell_mask import vector_cell_mask

    polygons = cell_polygons(
        np.asarray(mesh["vertices"][:], dtype="float64"),
        np.asarray(mesh["face_node_connectivity"][:]),
    )
    crs = _mesh_crs(grp)
    if crs is None:
        # Never guessed: an overlay run on the wrong frame lands the catchment
        # somewhere else entirely and the series would look plausible.
        logger.warning(
            "Catchment timeseries for sim %s: the store declares no CRS, so the "
            "delineated watershed cannot be placed on the mesh and the '_catchment' "
            "series stay on the whole active domain.",
            sim_id,
        )
        return active
    mask = np.asarray(
        vector_cell_mask(
            polygons,
            list(watershed.geometry),
            mesh_crs=crs,
            geometry_crs=watershed.crs,
            rule="centroid",
        ),
        dtype=bool,
    )
    if active is not None and mask.size == active.size:
        mask = mask & active
    if not mask.any():
        logger.warning(
            "Catchment timeseries for sim %s: the delineated watershed covers no cell "
            "centre, so the '_catchment' series fall back to the active domain. Check "
            "that the watershed and the mesh share a CRS.",
            sim_id,
        )
        return active
    if active is not None and mask.size == active.size and int(mask.sum()) < int(active.sum()):
        logger.info(
            "Catchment timeseries for sim %s: summed over %d of %d active cells, the "
            "%.1f%% of the domain the catchment covers.",
            sim_id,
            int(mask.sum()),
            int(active.sum()),
            100.0 * mask.sum() / max(1, active.sum()),
        )
    return mask


def _mesh_crs(grp) -> str | None:
    """CRS the mesh was written in, read from the CF grid-mapping variable.

    A run stores its frame once, as the ``crs`` scalar variable carrying
    ``crs_wkt``, which is where every other reader looks. The mesh group holds
    bare coordinates and no frame of its own, so reading it would always come
    back empty and the catchment overlay would compare two different frames.
    """
    try:
        node = grp["crs"]
    except (KeyError, TypeError):
        return None
    try:
        value = node.attrs.get("crs_wkt")
    except (AttributeError, TypeError):
        return None
    return str(value) if value else None


def _reduce(field: np.ndarray, mask: np.ndarray | None, reducer: str) -> float:
    """Reduce a spatial field to a single scalar."""
    # Flatten multi-layer fields to single layer
    if field.ndim == 2:
        field = field.sum(axis=0) if reducer in ("abs_sum", "sum") else field[0]
    field = field.ravel().astype("float64")

    if mask is not None and mask.size == field.size:
        field = np.where(mask, field, np.nan)
    else:
        field = np.where(field > -9000, field, np.nan)

    valid = field[np.isfinite(field)]
    if valid.size == 0:
        return float("nan")

    if reducer == "mean_active":
        return float(np.nanmean(valid))
    elif reducer == "percent_positive":
        n_positive = np.count_nonzero(valid > 0)
        return float(n_positive / valid.size * 100)
    elif reducer == "abs_sum":
        return float(np.nansum(np.abs(valid)))
    elif reducer == "max":
        return float(np.nanmax(valid))
    elif reducer == "sum":
        return float(np.nansum(valid))
    else:
        return float(np.nanmean(valid))
