"""Geometry, abacus, bathymetry, cutoff wall and forcings put on the lakes of a Flow."""

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
    from hydromodpy.core.time import ResolvedSimulationTimeWindow
    from hydromodpy.model.model import Flow

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
    lake_geometry: object | None,
) -> bool:
    """Attach loaded lake-geometry polygons onto each flow lake payload.

    ``lake_geometry`` is the ``LoadResult`` of the ``lake_geometry`` data family:
    its ``fields`` carry ``FieldRecord`` objects whose ``data`` is a GeoParquet
    path. The polygon is matched to a lake id by the ``lake_id`` column when
    present, otherwise the single record feeds the single declared lake. The LAK
    builder then intersects the polygon with the mesh to resolve the lake cells.

    Returns True if at least one polygon was attached, False otherwise.
    """
    if lake_geometry is None:
        return False
    records = list(getattr(lake_geometry, "fields", []) or [])
    if not records:
        return False

    payloads = payloads_as_mappings(flow, "lakes")
    if not payloads:
        return False

    polygons_by_lake = _resolve_lake_polygons(records, lake_ids=list(payloads))
    if not polygons_by_lake:
        return False

    return _attach_to_lakes(flow, payloads, "polygon", polygons_by_lake)


def apply_cutoff_wall_to_flow(
    *,
    flow: Flow,
    project_crs: object = None,
    outlet_xy: tuple[float, float] | None = None,
    data_dir: object = None,
) -> bool:
    """Resolve each lake's cutoff_wall trace into a shapely line on its payload.

    The wall trace is declared on ``FlowLakeConfig.cutoff_wall`` in any of four
    forms: inline ``line`` coordinates, a ``line_path`` vector file (.gpkg / .shp
    / .geojson), a ``line_path`` .csv of x,y vertices, or ``auto`` (derived from
    the reservoir footprint + the catchment ``outlet_xy``). A bare ``line_path``
    resolves against ``<data_dir>/cutoff_wall/``. This reads / derives it into a
    shapely LineString and attaches it as ``payload['cutoff_wall_line']`` so the
    HFB builder and the mesh dam refinement both map it onto the faces.

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
            trace = resolve_barrier_line(
                cfg, where=where, project_crs=project_crs, data_dir=data_dir
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
    lake_abacus: object | None,
) -> bool:
    """Attach loaded stage-volume-area abacus rows onto each flow lake payload.

    ``lake_abacus`` is the ``LoadResult`` of the ``lake_abacus`` data family: its
    ``tables`` carry ``TableRecord`` objects whose ``data`` is a Parquet table of
    ``lake_id, stage, volume, sarea`` rows, keyed by ``table_id``. The abacus is
    attached as a ``{stage, volume, sarea}`` column mapping that the LAK builder
    turns into the ``ModflowUtllaktab`` table.

    Returns True if at least one abacus was attached, False otherwise.
    """
    if lake_abacus is None:
        return False
    records = list(getattr(lake_abacus, "tables", []) or [])
    if not records:
        return False

    payloads = payloads_as_mappings(flow, "lakes")
    if not payloads:
        return False

    abacus_by_lake = _resolve_lake_abacus(records, lake_ids=list(payloads))
    if not abacus_by_lake:
        return False

    return _attach_to_lakes(flow, payloads, "abacus", abacus_by_lake)


def apply_lake_bathymetry_to_flow(
    *,
    flow: Flow,
    lake_bathymetry: object | None,
) -> bool:
    """Attach the loaded lake-bathymetry raster path onto each flow lake payload.

    ``lake_bathymetry`` is the ``LoadResult`` of the ``lake_bathymetry`` data
    family: its ``fields`` carry ``FieldRecord`` objects whose ``data`` is a
    GeoTIFF path. The raster is matched to a lake id (single record feeds the
    single declared lake; otherwise the file stem must contain the lake id) and
    attached as ``payload['bathymetry']`` so the LAK builder can carve the bed.

    Returns True if at least one raster was attached, False otherwise.
    """
    if lake_bathymetry is None:
        return False
    records = list(getattr(lake_bathymetry, "fields", []) or [])
    if not records:
        return False

    payloads = payloads_as_mappings(flow, "lakes")
    if not payloads:
        return False

    bathy_by_lake = _resolve_lake_bathymetry(records, lake_ids=list(payloads))
    if not bathy_by_lake:
        return False

    return _attach_to_lakes(flow, payloads, "bathymetry", bathy_by_lake)


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


def _resolve_lake_polygons(
    records: list[Any],
    *,
    lake_ids: list[str],
) -> dict[str, object]:
    """Match each lake-geometry record's footprint polygon to a lake id."""
    import geopandas as gpd

    polygons_by_lake: dict[str, object] = {}
    for record in records:
        gdf = gpd.read_parquet(str(record.data))
        if gdf.empty:
            continue
        if "lake_id" in gdf.columns:
            for lake_id, group in gdf.groupby("lake_id"):
                polygons_by_lake[str(lake_id)] = group.union_all()
        elif len(lake_ids) == 1:
            polygons_by_lake[lake_ids[0]] = gdf.union_all()
    return polygons_by_lake


def _resolve_lake_abacus(
    records: list[Any],
    *,
    lake_ids: list[str],
) -> dict[str, dict[str, list[float]]]:
    """Match each abacus record's stage-volume-area rows to a lake id."""
    import pandas as pd

    abacus_by_lake: dict[str, dict[str, list[float]]] = {}
    for record in records:
        frame = pd.read_parquet(str(record.data))
        if "lake_id" in frame.columns:
            for lake_id, group in frame.groupby("lake_id"):
                abacus_by_lake[str(lake_id)] = _abacus_columns(group)
        else:
            table_id = str(getattr(record, "table_id", "") or "")
            target = table_id if table_id in lake_ids else (lake_ids[0] if lake_ids else None)
            if target is not None:
                abacus_by_lake[target] = _abacus_columns(frame)
    return abacus_by_lake


def _resolve_lake_bathymetry(
    records: list[Any],
    *,
    lake_ids: list[str],
) -> dict[str, str]:
    """Match each bathymetry raster path to a lake id.

    A single record feeds the single declared lake. With several records or
    lakes, a record is matched to a lake id when its file stem contains that id
    (e.g. ``lake_bathymetry_custom_lac0.tif`` -> ``lac0``).
    """
    from pathlib import Path

    paths = [str(getattr(rec, "data", "")) for rec in records if getattr(rec, "data", None)]
    bathy_by_lake: dict[str, str] = {}
    if len(paths) == 1 and len(lake_ids) == 1:
        bathy_by_lake[lake_ids[0]] = paths[0]
        return bathy_by_lake
    for path in paths:
        stem = Path(path).stem
        for lake_id in lake_ids:
            if lake_id in stem:
                bathy_by_lake[lake_id] = path
    return bathy_by_lake


def _abacus_columns(frame: Any) -> dict[str, list[float]]:
    """Return the ``{stage, volume, sarea}`` column mapping from an abacus frame."""
    return {
        column: [float(value) for value in frame[column].tolist()]
        for column in ("stage", "volume", "sarea")
    }
