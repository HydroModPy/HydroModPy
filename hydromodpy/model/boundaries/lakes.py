"""Geometry, abacus, bathymetry, cutoff wall and forcings put on the lakes of a Flow.

It puts on each lake its geometry, abacus, bathymetry, cutoff wall, inflow and
withdrawal, and its meteo forcings. It reads ``streams.py``, because a runoff routed by
an active SFR is not given to a lake twice, ``barriers.py`` for the wall trace, and
``climate.py``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger
from hydromodpy.model.boundaries.barriers import resolve_barrier_line
from hydromodpy.model.boundaries.binder_payloads import payloads_as_mappings
from hydromodpy.model.boundaries.climate import watershed_mean_rates
from hydromodpy.model.boundaries.cutoff_wall_shore import auto_dam_axis
from hydromodpy.model.boundaries.streams import sfr_routes_catchment_runoff
from hydromodpy.model.contracts import LoadResultProto
from hydromodpy.model.forcing.time_forcing import aggregate_forcing_series

if TYPE_CHECKING:
    from hydromodpy.core.time.window import ResolvedSimulationTimeWindow
    from hydromodpy.model.flow import Flow

logger = get_logger(__name__)


def _attach_to_lakes(
    flow: Flow, payloads: dict[str, dict[str, object]], key: str, by_lake: Mapping[str, object]
) -> bool:
    """Set ``payload[key]`` on each lake ``by_lake`` names; True if at least one was set."""
    attached = False
    for lake_id, payload in payloads.items():
        value = by_lake.get(lake_id)
        if value is None:
            continue
        payload[key] = value
        attached = True
    if attached:
        flow.sinks_sources["lakes"] = payloads
    return attached


def apply_lake_geometry_to_flow(
    *,
    flow: Flow,
    polygons: Mapping[str, object] | None = None,
    lake_geometry: object | None = None,
) -> bool:
    """Attach lake-geometry polygons onto each flow lake payload.

    ``polygons`` is a mapping from lake id to shapely geometry, as returned by
    :func:`hydromodpy.data.variables.lake_geometry.read.lake_polygons`.

    Returns True if at least one polygon was attached, False otherwise.
    """
    resolved_polygons = (
        polygons
        if polygons is not None
        else (lake_geometry if isinstance(lake_geometry, Mapping) else None)
    )
    if not resolved_polygons:
        return False

    payloads = payloads_as_mappings(flow, "lakes")
    if not payloads:
        return False

    return _attach_to_lakes(flow, payloads, "polygon", dict(resolved_polygons))


def apply_cutoff_wall_to_flow(
    *,
    flow: Flow,
    project_crs: object = None,
    outlet_xy: tuple[float, float] | None = None,
    data_dir: object = None,
    cutoff_wall_traces: Mapping[str, Any] | None = None,
    wall_traces: Mapping[str, Any] | None = None,
) -> bool:
    """Resolve each lake's cutoff_wall trace into a shapely line on its payload.

    The wall trace is declared on ``FlowLakeConfig.cutoff_wall`` in any of four
    forms: inline ``line`` coordinates, a preloaded ``line_path`` vector / csv
    LineString in ``cutoff_wall_traces``, or ``auto`` (derived from the reservoir
    footprint + the catchment ``outlet_xy``). This attaches it as
    ``payload['cutoff_wall_line']`` so the HFB builder and the mesh dam
    refinement both map it onto the faces.

    The trace is then laid on the lake shore (:func:`snap_wall_to_shore`):
    ``cutoff_wall_line`` is the wall on the shore, ``cutoff_wall_shore`` the
    shore section it follows and ``cutoff_wall_trace`` the declared trace, whose
    vertices carry the depths. A trace that crosses the lake cuts the footprint,
    and ``polygon`` becomes the cut footprint. Without a footprint (lake geometry
    not loaded) the trace stays as declared.

    Returns True if at least one wall line was attached, False otherwise.
    """
    payloads = payloads_as_mappings(flow, "lakes")
    if not payloads:
        return False

    attached = False
    for lake_id, payload in payloads.items():
        cfg = payload.get("cutoff_wall")
        if cfg is None:
            continue
        where = f"flow.sinks_sources.lakes.{lake_id}.cutoff_wall"
        polygon = payload.get("polygon")
        if bool(getattr(cfg, "auto", False)):
            if polygon is None:
                raise ValueError(
                    f"{where} auto needs the lake footprint; bind lake geometry first."
                )
            if outlet_xy is None:
                raise ValueError(
                    f"{where} auto needs the catchment outlet; only from_outlet_coord catchments "
                    "expose x_outlet/y_outlet. Give an explicit line instead."
                )
            trace = auto_dam_axis(polygon, outlet_xy)
        else:
            traces_map = cutoff_wall_traces or wall_traces or {}
            line_trace = traces_map.get(lake_id)
            trace = resolve_barrier_line(
                cfg,
                where=where,
                project_crs=project_crs,
                line_trace=line_trace,
                data_dir=data_dir,
            )
        payload["cutoff_wall_trace"] = trace
        payload["cutoff_wall_line"] = trace
        if polygon is None:
            logger.warning(
                "%s: no lake footprint is bound, so the wall stays on the declared trace "
                "instead of the lake shore.",
                where,
            )
        else:
            _lay_wall_on_shore(payload, polygon, trace, cfg, where=where)
        attached = True

    if not attached:
        return False
    flow.sinks_sources["lakes"] = payloads
    return True


def _lay_wall_on_shore(
    payload: dict[str, object], polygon: object, trace: object, cfg: object, *, where: str
) -> None:
    """Snap one lake's wall trace on its shore and record the wall on the payload."""
    from hydromodpy.model.boundaries.cutoff_wall_shore import snap_wall_to_shore

    tolerance = float(getattr(cfg, "snap_tolerance", 50.0))
    try:
        wall = snap_wall_to_shore(polygon, trace, tolerance)
    except ValueError as exc:
        raise ConfigError(f"{where}: {exc}.") from exc
    payload["cutoff_wall_line"] = wall.line
    payload["cutoff_wall_shore"] = wall.shore
    payload["polygon"] = wall.polygon
    if wall.cut_area_m2 > 0.0:
        logger.warning(
            "%s crosses the lake footprint: the %.0f m2 downstream of the trace are "
            "dropped from the lake, and the wall lies on the new shore.",
            where,
            wall.cut_area_m2,
        )
    logger.info(
        "%s laid on the lake shore: gap %.1f m closed, %.1f m of shore, wall %.1f m long.",
        where,
        wall.gap_m,
        wall.shore.length,
        wall.line.length,
    )


def apply_lake_abacus_to_flow(
    *,
    flow: Flow,
    abacus: Mapping[str, dict[str, list[float]]] | None = None,
    lake_abacus: object | None = None,
) -> bool:
    """Attach loaded stage-volume-area abacus mappings onto each flow lake payload.

    ``abacus`` is a mapping from lake id to ``{stage, volume, sarea}`` column dicts,
    as returned by :func:`hydromodpy.data.variables.lake_abacus.read.lake_abacus`.

    Returns True if at least one abacus was attached, False otherwise.
    """
    resolved_abacus = (
        abacus
        if abacus is not None
        else (lake_abacus if isinstance(lake_abacus, Mapping) else None)
    )
    if not resolved_abacus:
        return False

    payloads = payloads_as_mappings(flow, "lakes")
    if not payloads:
        return False

    return _attach_to_lakes(flow, payloads, "abacus", dict(resolved_abacus))


def apply_lake_bathymetry_to_flow(
    *,
    flow: Flow,
    bathymetry: Mapping[str, Any] | None = None,
    lake_bathymetry: object | None = None,
) -> bool:
    """Attach the loaded lake-bathymetry raster path onto each flow lake payload.

    ``bathymetry`` is a mapping from lake id to raster Path, as returned by
    :func:`hydromodpy.data.variables.lake_bathymetry.read.lake_bathymetry`.

    Returns True if at least one raster was attached, False otherwise.
    """
    resolved_bathy = (
        bathymetry
        if bathymetry is not None
        else (lake_bathymetry if isinstance(lake_bathymetry, Mapping) else None)
    )
    if not resolved_bathy:
        return False

    payloads = payloads_as_mappings(flow, "lakes")
    if not payloads:
        return False

    return _attach_to_lakes(flow, payloads, "bathymetry", dict(resolved_bathy))


def apply_lake_flux_forcings_to_flow(
    *,
    flow: Flow,
    lake_inflow: LoadResultProto | None = None,
    lake_withdrawal: LoadResultProto | None = None,
    simulation_window: ResolvedSimulationTimeWindow | None = None,
) -> bool:
    """Attach file-loaded inflow / withdrawal timeseries as LAK forcings.

    Each loaded family carries one ``PointRecord`` per lake (``station_id`` =
    lake id) with values already in m3/s. The series is aggregated to the
    simulation stress periods and attached to the matching lake payload as a
    per-period ``values`` forcing. A forcing already declared in config wins, so
    the data file is the alternative source, never an override.

    Returns True if at least one forcing was attached, False otherwise.
    """
    sources = (("inflow", lake_inflow), ("withdrawal", lake_withdrawal))
    if simulation_window is None or all(result is None for _, result in sources):
        return False

    payloads = payloads_as_mappings(flow, "lakes")
    if not payloads:
        return False

    attached = False
    for keyword, result in sources:
        if result is None:
            continue
        for record in getattr(result, "points", []) or []:
            lake_id = str(getattr(record, "station_id", ""))
            payload = payloads.get(lake_id)
            if payload is None or payload.get(keyword) is not None:
                continue  # unknown lake, or config already declares the forcing
            series = _point_record_series(record)
            if series.empty:
                continue
            values = aggregate_forcing_series(
                series,
                simulation_window=simulation_window,
                label=f"flow.sinks_sources.lakes.{lake_id}.{keyword}",
                aggregate="mean",
            )
            payload[keyword] = {
                "kind": "values",
                "values": [float(v) for v in values],
                "units": "m3/s",
            }
            attached = True

    if not attached:
        return False
    flow.sinks_sources["lakes"] = payloads
    return True


def _lake_runoff_areas_m2(
    lake_ids: list[str],
    catchment_area_m2: float,
    contributing_areas_m2: Mapping[str, float] | None,
) -> dict[str, float]:
    """Return the area whose runoff each lake receives, summing to the basin at most."""
    if not lake_ids or catchment_area_m2 <= 0.0:
        return {}
    known = dict(contributing_areas_m2 or {})
    if all(lake_id in known for lake_id in lake_ids):
        areas = {lake_id: max(float(known[lake_id]), 0.0) for lake_id in lake_ids}
        total = sum(areas.values())
        if total > catchment_area_m2:
            scale = catchment_area_m2 / total
            areas = {lake_id: area * scale for lake_id, area in areas.items()}
        return areas
    share = catchment_area_m2 / len(lake_ids)
    if len(lake_ids) > 1:
        logger.warning(
            "No contributing area per lake: the basin runoff is split evenly between %d lakes.",
            len(lake_ids),
        )
    return dict.fromkeys(lake_ids, share)


def apply_lake_meteo_forcings_to_flow(
    *,
    flow: Flow,
    precipitation: LoadResultProto | None = None,
    etp: LoadResultProto | None = None,
    runoff: LoadResultProto | None = None,
    simulation_window: ResolvedSimulationTimeWindow | None = None,
    catchment_area_m2: float | None = None,
    lake_contributing_areas_m2: Mapping[str, float] | None = None,
) -> bool:
    """Attach SIM2-derived rainfall / evaporation / runoff onto each lake payload.

    The catchment-scale precipitation / etp / runoff data families (e.g. SIM2,
    internal unit mm/day) are reduced to a watershed-mean per-period rate in m/s.
    Rainfall and evaporation are open-water rates applied to every lake surface
    (L/T); runoff is that catchment runoff rate times the catchment area, the
    volumetric (m3/s) overland inflow into the lake (mirrors the legacy
    ``runoff * area`` accumulation). A forcing already declared in config wins, so
    the SIM2 series is only the default source.

    When an active SFR network routes the catchment runoff
    (:func:`sfr_routes_catchment_runoff`), the lake's direct runoff feed is
    SKIPPED: the same water travels through the reaches and arrives via MVR when
    the network is coupled to the lake. Rainfall and evaporation stay on the
    lake surface in every mode.

    Without SFR, the basin runoff is fed once, not once per lake. Each lake
    takes the runoff of its own contributing area when
    ``lake_contributing_areas_m2`` gives it (scaled down when the areas sum
    above the basin). Otherwise the basin area is split evenly between the
    lakes, so the lakes together receive the basin runoff exactly once.

    Returns True if at least one forcing was attached, False otherwise.
    """
    if simulation_window is None or all(r is None for r in (precipitation, etp, runoff)):
        return False
    payloads = payloads_as_mappings(flow, "lakes")
    if not payloads:
        return False

    rain = watershed_mean_rates(precipitation, "lake_rainfall", simulation_window)
    evap = watershed_mean_rates(etp, "lake_evaporation", simulation_window)
    # The watershed-mean runoff RATE [m/s] is surfaced in every mode (even when SFR
    # routes the lumped volume) so the exposed-band marnage runoff can size itself
    # from the live stage. The lumped runoff VOLUME stays a direct lake feed only
    # when no SFR network routes it.
    runoff_rate = watershed_mean_rates(runoff, "lake_runoff", simulation_window)
    lake_areas: dict[str, float] = {}
    if not sfr_routes_catchment_runoff(flow) and runoff_rate is not None and catchment_area_m2:
        lake_areas = _lake_runoff_areas_m2(
            list(payloads), float(catchment_area_m2), lake_contributing_areas_m2
        )

    attached = False
    for lake_id, payload in payloads.items():
        runoff_vol = (
            [v * lake_areas[lake_id] for v in runoff_rate]
            if lake_id in lake_areas and runoff_rate is not None
            else None
        )
        derived = (
            ("rainfall", rain, "m/s"),
            ("evaporation", evap, "m/s"),
            ("runoff", runoff_vol, "m3/s"),
        )
        for keyword, values, unit in derived:
            if values is not None and payload.get(keyword) is None:
                payload[keyword] = {"kind": "values", "values": values, "units": unit}
                attached = True
        # The watershed runoff RATE is only consumed by the exposed-band (marnage)
        # coupling, so surface it only for lakes that opt in (leaving the binder's
        # behavior unchanged for every other lake).
        if (
            runoff_rate is not None
            and payload.get("runoff_rate") is None
            and getattr(payload.get("bed_reconstruction"), "exposed_band_runoff", False)
        ):
            payload["runoff_rate"] = {"kind": "values", "values": runoff_rate, "units": "m/s"}
            attached = True

    if not attached:
        return False
    flow.sinks_sources["lakes"] = payloads
    return True


def _point_record_series(record: Any):
    """Return a datetime-indexed float series from a loaded PointRecord."""
    import pandas as pd

    frame = record.data.dropna(subset=["datetime", "value"]).sort_values("datetime")
    return pd.Series(
        frame["value"].to_numpy(dtype=float),
        index=pd.DatetimeIndex(frame["datetime"]),
        dtype=float,
    )
