"""The ``discharge`` and ``well_pumping`` series of a run, written under the ``catchment`` station.

Each budget term comes from the float64 ``catchment`` row of ``budgets``, else
from its per-cell field over the catchment cells, else from the ``domain`` row.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from hydromodpy.core.budget.flux import inflow_outflow
from hydromodpy.core.exceptions import ExtractError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.scope import CATCHMENT, OBSERVED, SIMULATED
from hydromodpy.core.time.period_aggregation import period_end_stamps, runoff_m3_s_on_index
from hydromodpy.results.derive.config_flags import KEEP_BUDGET_OPTION, enable_options_hint
from hydromodpy.results.field_registry import series_unit
from hydromodpy.results.run.descent import basin_of_group
from hydromodpy.results.storage.kept import level_of

logger = get_logger(__name__)

_SLAB_TARGET_BYTES = 64 * 1024 * 1024

#: Terms whose outflow reaches the surface, summed into ``discharge``: the drains
#: and the Boussinesq surface excess. DRN-TO-MVR re-enters through SFR instead.
SURFACE_TERMS = ("drain", "surface_excess")


def aggregate_catchment_timeseries(
    sim_id: str,
    store: Any,
    *,
    time_index: pd.DatetimeIndex | None = None,
    drainage_outside_routed: bool = False,
) -> None:
    """Write the :func:`catchment_series` of a run in one batch."""
    series = catchment_series(
        sim_id, store, time_index=time_index, drainage_outside_routed=drainage_outside_routed
    )
    if series.empty:
        return
    index = pd.DatetimeIndex(series.index)
    index = index.tz_localize("UTC") if index.tz is None else index.tz_convert("UTC")
    times = index.to_pydatetime()
    base = {"sim_id": str(sim_id), "station_id": CATCHMENT, "component": None}
    rows = [
        {**base, "variable": v, "timestep": i, "time": times[i], "value": x, "source": SIMULATED}
        for v in series.columns
        for i, x in enumerate(series[v].to_numpy(dtype="float64").tolist())
    ]
    store.write_timeseries_batch(
        sim_id, [row | {"unit": series_unit(row["variable"])} for row in rows]
    )


def catchment_series(
    sim_id: str,
    store: Any,
    *,
    time_index: pd.DatetimeIndex | None = None,
    drainage_outside_routed: bool = False,
) -> pd.DataFrame:
    """Return the ``discharge`` and ``well_pumping`` series of a run, empty when it has none.

    With SFR or LAK series the discharge is their routed ``ext_outflow``: the plain
    drains left beside DRN-TO-MVR are the buffer. ``drainage_outside_routed`` (no
    network routes the drainage) adds the catchment drains to it. Without routed
    series the discharge is the surface outflow plus the runoff (:func:`with_runoff`).
    """
    sz = store.open_zarr(sim_id)
    try:
        grp = sz.root
        n = _n_steps(grp)
        if n == 0:
            raise RuntimeError(f"No timesteps found for sim {sim_id}; cannot aggregate catchment")
        support = catchment_support(store, sim_id, grp, _active_cells(grp))
        terms = {t: catchment_term(store, sim_id, grp, t, n, support) for t in SURFACE_TERMS}
        columns = {}
        if any(split is not None for split in terms.values()):
            columns["discharge"] = np.sum([s[1] for s in terms.values() if s is not None], axis=0)
        if (well := catchment_term(store, sim_id, grp, "well", n, support)) is not None:
            columns["well_pumping"] = well[0] - well[1]
        routed = _routed_outflow(store, n)
        if not columns and routed is None:
            return pd.DataFrame()
        try:
            index = time_index
            if index is None or len(index) != n:
                index = series_time_index(store, sim_id, n)
        except RuntimeError as exc:
            logger.warning("Skipping catchment timeseries for sim %s: %s", sim_id, exc)
            return pd.DataFrame()
        frame = pd.DataFrame(columns, index=index, dtype="float64")
        if routed is not None:
            if drainage_outside_routed and "discharge" in frame:
                routed = routed + frame["discharge"].to_numpy()
            frame["discharge"] = routed
            forcing = grp.get("forcing")
            if forcing is not None and "runoff" in forcing and _rows(store, "runoff").empty:
                logger.warning(
                    "catchment discharge: runoff forcing is present for sim %s but no runoff was "
                    "routed into SFR/LAK; the routed discharge excludes the runoff component.",
                    sim_id,
                )
        elif "discharge" in frame:
            start = (_run_window(store) or (None,))[0]
            frame["discharge"] = with_runoff(frame["discharge"], sim_id, store, grp, start=start)
    finally:
        sz.close()
    return frame


def catchment_term(
    store: Any, sim_id: str, grp: Any, term: str, n: int, support: np.ndarray | None
) -> tuple[np.ndarray, np.ndarray] | None:
    """Inflow and outflow of one budget term over the catchment, None when the run holds none.

    The float64 ``catchment`` row beats the per-cell field, rounded to 16 bits. The
    ``domain`` row comes last, warned about and never rescaled. A gap is NaN.
    """
    try:
        budgets = store.read_table("budgets")
    except Exception as exc:
        # The last source once the per-cell budget is not kept: an unreadable
        # table would empty the discharge without a word.
        raise ExtractError(
            f"Cannot read the lumped budget of sim {sim_id}: the catchment "
            f"'{term}' series cannot be built ({exc})."
        ) from exc
    split = _lumped(budgets, term, n, CATCHMENT)
    if split is None:
        split = _from_field(grp, term, n, support)
    if split is None and (split := _lumped(budgets, term, n, None)) is not None:
        active = _active_cells(grp)
        if support is not None and active is not None and support.size == active.size:
            share = float(support.sum()) / float(max(active.sum(), 1))
            if active.any() and share < 1.0:
                hint = enable_options_hint(
                    (KEEP_BUDGET_OPTION,), level=level_of(store.facts.lineage)
                )
                logger.warning(
                    _DOMAIN_WIDE, sim_id, term, CATCHMENT, CATCHMENT, 100.0 * share, hint
                )
    return split


_DOMAIN_WIDE = (
    "Catchment timeseries for sim %s: the '%s' budget carries no zone_id='%s' "
    "row and no per-cell field, so the '%s' series is the whole model domain, "
    "of which the catchment covers %.0f%% of the active cells. The value is "
    "NOT rescaled: it is a domain total, not what a gauge at the outlet sees. "
    "The run kept no per-cell drain. %s"
)


def _lumped(budgets: pd.DataFrame, term: str, n: int, zone: str | None):
    """Inflow and outflow of one component in one zone, or in every zone when None."""
    if budgets.empty:
        return None
    rows = budgets[budgets["component"] == term]
    rows = rows if zone is None else rows[rows["zone_id"] == zone]
    if rows.empty:
        return None
    split = (np.full(n, np.nan), np.full(n, np.nan))
    sums = rows.groupby("timestep")[["flux_in", "flux_out"]].sum(min_count=1)
    for timestep, *fluxes in sums.itertuples(name=None):
        for side, flux in zip(split, fluxes, strict=True):
            if 0 <= int(timestep) < n:
                side[int(timestep)] = 0.0 if pd.isna(flux) else float(flux)
    return split


def _from_field(grp: Any, term: str, n: int, support: np.ndarray | None):
    """Inflow and outflow of the per-cell field of derived/, budget/ or the root, by slabs."""
    groups = (grp.get("derived"), grp.get("budget"), grp)
    array = next((g[term] for g in groups if g is not None and term in g), None)
    if array is None or array.shape[0] < n:
        return None
    cells = support if support is not None and support.size == array.shape[-1] else None
    block = max(1, min(n, _SLAB_TARGET_BYTES // max(int(np.prod(array.shape[1:])) * 8, 1)))
    parts = [inflow_outflow(array[t0 : min(t0 + block, n)], cells) for t0 in range(0, n, block)]
    return np.concatenate([p[0] for p in parts]), np.concatenate([p[1] for p in parts])


def _rows(store: Any, variable: str, source: str = SIMULATED) -> pd.DataFrame:
    """Rows of one variable and source in the ``timeseries`` table of the run."""
    frame = store.read_table("timeseries")
    if frame.empty:
        return frame
    return frame[(frame["variable"] == variable) & (frame["source"] == source)]


def _routed_outflow(store: Any, n: int) -> np.ndarray | None:
    """``ext_outflow`` of reaches and lake outlets per step, as ``routed_outflow_series``.

    Only the SFR and LAK extractors write it. None without any. A step with no
    row is NaN, since a true zero outflow arrives as a row.
    """
    outflow = _rows(store, "ext_outflow")
    if outflow.empty:
        return None
    values = np.full(n, np.nan, dtype="float64")
    for timestep, total in outflow.groupby("timestep")["value"].sum(min_count=1).items():
        if 0 <= int(timestep) < n and pd.notna(total):
            values[int(timestep)] = float(total)
    return values


def with_runoff(
    discharge: pd.Series, sim_id: str, store: Any, grp: Any, *, start: pd.Timestamp | None = None
) -> pd.Series:
    """Add the mean runoff of ``forcing/runoff/<station>`` (mm/day) to a baseflow, in m3/s.

    ``runoff_m3_s_on_index`` converts it, as in a trial, on the area of the basin
    of D, else ``catch_area``, from ``start``, the start of the first period.
    """
    forcing = grp.get("forcing")
    if forcing is None or "runoff" not in forcing:
        if not _rows(store, "discharge", OBSERVED).empty:
            logger.warning(
                "Simulated discharge is baseflow only: the run has no runoff forcing, "
                "so it underestimates a gauged total streamflow."
            )
        return discharge
    area_m2 = _runoff_area_m2(store, sim_id, grp)
    if area_m2 <= 0.0:
        logger.warning(
            "catchment discharge: catchment area unavailable for sim %s — "
            "skipping runoff addition.",
            sim_id,
        )
        return discharge
    runoff, stations = forcing["runoff"], []
    for key in list(runoff.array_keys()) + list(runoff.group_keys()):
        node = runoff[key]
        if hasattr(node, "shape") or "values" not in node or "timestamps" not in node:
            continue
        values = np.asarray(node["values"][:], dtype="float64")
        if values.size:
            stamps = pd.DatetimeIndex(pd.to_datetime(np.asarray(node["timestamps"][:])))
            stations.append(pd.Series(values, index=stamps))
    if not stations:
        return discharge
    mm_per_day = pd.concat(stations, axis=1).mean(axis=1)
    index = pd.DatetimeIndex(discharge.index)
    return discharge.add(runoff_m3_s_on_index(mm_per_day, index, area_m2=area_m2, start=start))


def _runoff_area_m2(store: Any, sim_id: str, grp: Any) -> float:
    """Area of the stored basin of D, else ``catch_area`` (km2 in the store), in m2."""
    basin = basin_of_group(grp.get("mesh"))
    if basin is not None and basin.is_catchment:
        if not np.isfinite(basin.area_m2):
            raise ExtractError(
                f"the basin of D stored by run {sim_id} states no area (basin_area_m2), "
                "so the runoff has no surface to be scaled by."
            )
        return basin.area_m2
    value = store.read_geographic_metadata(sim_id).get("catch_area")
    area_m2 = float(value) * 1e6 if value else 0.0
    if basin is None:
        logger.info(
            "Catchment discharge for sim %s: the run stores no basin of D, so the runoff is "
            "scaled by the old support 'catch_area' (%.3f km2).",
            sim_id,
            area_m2 / 1.0e6,
        )
    return area_m2


def series_time_index(store: Any, sim_id: str, n: int) -> pd.DatetimeIndex:
    """The CF ``/time`` axis the solver wrote, else the run window stamped at period ends."""
    try:
        with store.open_zarr(sim_id) as sz:
            times = sz.read_time()
    except Exception:  # A store that cannot give its axis falls back on the window.
        times = None
    if times is not None and len(times) == n:
        return pd.DatetimeIndex(times)
    if (window := _run_window(store)) is None:
        raise RuntimeError(
            f"Simulation {sim_id} is missing period_start/period_end; "
            "cannot write catchment timeseries with synthetic timestamps."
        )
    return period_end_stamps(window[0], window[1], n, step_unit=window[2])


def _run_window(store: Any) -> tuple[pd.Timestamp, pd.Timestamp, Any] | None:
    """``(period_start, period_end, time_unit)`` of the facts, bounds as naive UTC."""
    facts = store.facts
    if facts.period_start is None or facts.period_end is None:
        return None
    bounds = [pd.Timestamp(v) for v in (facts.period_start, facts.period_end)]
    bounds = [t if t.tz is None else t.tz_convert("UTC").tz_localize(None) for t in bounds]
    return bounds[0], bounds[1], facts.time_unit


def _n_steps(grp: Any) -> int:
    """Number of steps of ``head``, else of the first derived array, else 0."""
    derived = grp.get("derived")
    arrays = [grp["head"]] if "head" in grp else [derived[k] for k in derived or ()]
    return int(arrays[0].shape[0]) if arrays else 0


def _active_cells(grp: Any) -> np.ndarray | None:
    """Cells with a finite model top above the sentinel, None without a topography."""
    mesh = grp.get("mesh")
    if mesh is None or "topography" not in mesh:
        return None
    top = np.asarray(mesh["topography"][:], dtype="float64").ravel()
    return np.isfinite(top) & (top > -9000)


def catchment_support(store: Any, sim_id: str, grp: Any, active: np.ndarray | None):
    """Cells the catchment series sum over: the basin of D, else the watershed, else the domain.

    On the Nancon at 25 m the buffered domain is 152.2 km2 and the catchment
    64.6 km2. A run with no basin of D keeps the cells whose centre the watershed
    covers (``polygon_centroid``), and a synthetic domain keeps the active cells.
    """
    mesh = grp.get("mesh")
    basin = basin_of_group(mesh)
    if basin is not None and basin.is_catchment:
        mask = basin.mask
        mask = mask & active if active is not None and mask.size == active.size else mask
        if not mask.any():
            raise ExtractError(
                f"the basin of D stored by run {sim_id} holds no active cell, so the "
                "catchment series have no support."
            )
        n_active = int(active.sum()) if active is not None else int(mask.size)
        logger.info(
            "Catchment timeseries for sim %s: the basin of D, %d of %d active cells (%.3f km2).",
            *(sim_id, int(mask.sum()), n_active, basin.area_m2 / 1.0e6),
        )
        return mask
    if mesh is None or "vertices" not in mesh or "face_node_connectivity" not in mesh:
        return active
    if basin is None:
        logger.info(
            "Catchment timeseries for sim %s: the run stores no basin of D, so the "
            "catchment series keep the old support 'polygon_centroid'.",
            sim_id,
        )
    try:
        watershed = store.read_geographic_feature(sim_id, "watershed")
    except Exception:  # A store without the layer has no watershed: the domain is kept.
        watershed = None
    crs, mask, why = _mesh_crs(grp), None, "no delineated watershed is in the store"
    if watershed is not None and not watershed.empty and crs is None:
        # Never guessed: on the wrong frame the watershed lands elsewhere.
        why = "the store declares no CRS, so the watershed cannot be placed on the mesh"
    elif watershed is not None and not watershed.empty:
        from hydromodpy.mesh.cells.in_polygons import watershed_cell_mask

        vertices, faces = mesh["vertices"][:], mesh["face_node_connectivity"][:]
        mask = watershed_cell_mask(vertices, faces, watershed, mesh_crs=crs)
        mask = mask & active if active is not None and mask.size == active.size else mask
        why = "the watershed covers no cell centre (does it share the CRS of the mesh?)"
    if mask is None or not mask.any():
        logger.warning(
            "Catchment timeseries for sim %s: %s, so the series are summed over the whole "
            "active domain, which on a buffered grid takes in the neighbouring basins.",
            sim_id,
            why,
        )
        return active
    return mask


def _mesh_crs(grp: Any) -> str | None:
    """CRS of the mesh, the ``crs_wkt`` of the CF grid-mapping scalar at the root."""
    try:
        value = grp["crs"].attrs.get("crs_wkt")
    except (KeyError, TypeError, AttributeError):
        return None
    return str(value) if value else None
