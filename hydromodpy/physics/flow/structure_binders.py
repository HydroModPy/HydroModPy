"""Flow-side binders for data-to-structure updates."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from hydromodpy.core.logging import get_logger
from hydromodpy.core.time import (
    ResolvedSimulationTimeWindow,
    build_simulation_time_boundaries,
)
from hydromodpy.core.units import convert_payload_to_m, normalize_length_unit
from hydromodpy.core.units.volumetric_flow import (
    convert_to_m3_per_s,
    normalize_m3_per_s_unit,
)
from hydromodpy.physics.contracts import LoadResultProto
from hydromodpy.physics.flow.boundary_condition_registry import (
    boundary_conditions_mapping_from_flow,
)
from hydromodpy.physics.flow.sinks_sources import (
    FlowEtpConfig,
    FlowRechargeConfig,
    FlowSinksSourcesConfig,
)
from hydromodpy.physics.flow.time_forcing import (
    aggregate_forcing_series,
    resolve_period_values_from_forcing,
)

if TYPE_CHECKING:
    from hydromodpy.core.time import ResolvedSimulationTimeWindow
    from hydromodpy.physics.flow import Flow

logger = get_logger(__name__)


def apply_oceanic_to_flow(
    *,
    flow: Flow,
    oceanic: LoadResultProto | None,
) -> None:
    """Inject mean sea-level value into the active ocean boundary condition."""
    if oceanic is None:
        return
    ocean_bc = boundary_conditions_mapping_from_flow(flow).get("ocean")
    if ocean_bc is None:
        return
    # Priority 1: constant MSL record
    msl = [
        r
        for r in oceanic.points
        if r.variable == "mean_sea_level" and getattr(r, "is_constant", False)
    ]
    if msl:
        ocean_bc.value = msl[0].data["value"].iloc[0]
        return
    # Priority 2: mean of tide gauge time series
    sea = [r for r in oceanic.points if r.variable in ("sea_level", "oceanic")]
    if sea:
        ocean_bc.value = float(sea[0].data["value"].mean())


def apply_recharge_load_result_to_flow(
    *,
    flow: Flow,
    recharge_result: LoadResultProto | None,
    simulation_window: ResolvedSimulationTimeWindow | None = None,
) -> bool:
    """Inject recharge from a data-manager LoadResult into flow.

    Uses the generic :func:`forcing_bridge.resolve_forcing` to handle
    spatial_mode dispatch (auto / homogeneous / heterogeneous).

    Preserves solver-side recharge policy (first_clim, negative_to_evt,
    spatial_mode, interpolation_method) from the existing flow configuration.

    Returns True if recharge was successfully injected, False otherwise.
    """
    if recharge_result is None:
        return False

    from hydromodpy.core.units.hydraulic_conductivity import factor_to_m_per_s
    from hydromodpy.physics.forcing.forcing_bridge import resolve_forcing

    sinks_sources = getattr(flow, "sinks_sources", {})
    recharge_cfg = sinks_sources.get("recharge") if isinstance(sinks_sources, dict) else None

    first_clim = "mean"
    spatial_mode = "auto"
    interpolation_method = "nearest"
    negative_to_evt = True
    if recharge_cfg is not None:
        first_clim = getattr(recharge_cfg, "first_clim", "mean")
        spatial_mode = getattr(recharge_cfg, "spatial_mode", "auto")
        interpolation_method = getattr(recharge_cfg, "interpolation_method", "nearest")
        negative_to_evt = bool(getattr(recharge_cfg, "negative_to_evt", True))

    # Data-manager output is always in mm/day (internal convention).
    # Flow._normalize_recharge_config has already converted recharge_cfg.units
    # to "m/s", so we cannot rely on it for the source unit here.
    unit_conversion_factor = factor_to_m_per_s("mm/day")

    resolved = resolve_forcing(
        recharge_result,
        unit_conversion_factor=unit_conversion_factor,
        simulation_window=simulation_window,
        spatial_mode=spatial_mode,
        interpolation_method=interpolation_method,
        label="recharge",
    )
    if resolved is None:
        return False

    flow.set_recharge(
        FlowRechargeConfig(
            values=resolved.series if resolved.series is not None else 0.0,
            first_clim=first_clim,
            units="m/s",
            heterogeneous_source=resolved.heterogeneous_source,
            spatial_mode=resolved.spatial_mode,
            interpolation_method=resolved.interpolation_method,
            negative_to_evt=negative_to_evt,
        )
    )
    return True


def apply_etp_load_result_to_flow(
    *,
    flow: Flow,
    etp_result: LoadResultProto | None,
    simulation_window: ResolvedSimulationTimeWindow | None = None,
) -> bool:
    """Inject ETP from a data-manager LoadResult into flow.

    Mirrors :func:`apply_recharge_load_result_to_flow` for the ETP
    forcing. Reuses :func:`forcing_bridge.resolve_forcing` for spatial
    mode dispatch and the same ``mm/day → m/s`` conversion path.

    The runtime keeps any user-defined ETP policy (``surface_offset``,
    ``extinction_depth``, ``first_clim``, ``spatial_mode``, etc.) when
    a base ``flow.sinks_sources['etp']`` already exists; otherwise the
    typed config is created from scratch with sensible defaults that
    reproduce the legacy behaviour (``DEM - 2 m`` ET surface, 1 m
    extinction depth).

    Returns True if ETP was successfully injected, False otherwise.
    """
    if etp_result is None:
        return False

    from hydromodpy.core.units.hydraulic_conductivity import factor_to_m_per_s
    from hydromodpy.physics.forcing.forcing_bridge import resolve_forcing

    sinks_sources = getattr(flow, "sinks_sources", {})
    etp_cfg = sinks_sources.get("etp") if isinstance(sinks_sources, dict) else None

    first_clim = "mean"
    spatial_mode = "auto"
    interpolation_method = "nearest"
    surface_offset = 2.0
    extinction_depth = 1.0
    if etp_cfg is not None:
        first_clim = getattr(etp_cfg, "first_clim", first_clim)
        spatial_mode = getattr(etp_cfg, "spatial_mode", spatial_mode)
        interpolation_method = getattr(etp_cfg, "interpolation_method", interpolation_method)
        surface_offset_q = getattr(etp_cfg, "surface_offset", None)
        if surface_offset_q is not None:
            surface_offset = float(surface_offset_q.to("m").magnitude)
        extinction_depth_q = getattr(etp_cfg, "extinction_depth", None)
        if extinction_depth_q is not None:
            extinction_depth = float(extinction_depth_q.to("m").magnitude)

    unit_conversion_factor = factor_to_m_per_s("mm/day")

    resolved = resolve_forcing(
        etp_result,
        unit_conversion_factor=unit_conversion_factor,
        simulation_window=simulation_window,
        spatial_mode=spatial_mode,
        interpolation_method=interpolation_method,
        label="etp",
    )
    if resolved is None:
        return False

    flow.set_etp(
        FlowEtpConfig(
            values=resolved.series if resolved.series is not None else 0.0,
            first_clim=first_clim,
            units="m/s",
            heterogeneous_source=resolved.heterogeneous_source,
            spatial_mode=resolved.spatial_mode,
            interpolation_method=resolved.interpolation_method,
            surface_offset=surface_offset,
            extinction_depth=extinction_depth,
        )
    )
    return True


def _lake_payloads_as_mappings(flow: Flow) -> dict[str, dict[str, object]]:
    """Return the flow lake payloads as mutable dicts keyed by lake id.

    The runtime stores typed ``FlowLakeConfig`` objects (or already-enriched
    dicts) under ``flow.sinks_sources['lakes']``. The data binders attach the
    loaded polygon / abacus onto each payload, so they are normalized to plain
    dicts that the LAK builder reads through its ``_lake_attr`` lookup.
    """
    sinks_sources = getattr(flow, "sinks_sources", {})
    lakes = sinks_sources.get("lakes") if isinstance(sinks_sources, Mapping) else None
    if not isinstance(lakes, Mapping) or not lakes:
        return {}

    payloads: dict[str, dict[str, object]] = {}
    for lake_id, payload in lakes.items():
        if isinstance(payload, Mapping):
            payloads[str(lake_id)] = dict(payload)
        else:
            # Snapshot every declared config field so a new field (e.g.
            # fill_enclosed_cells) never silently drops out of the payload.
            payloads[str(lake_id)] = {
                name: getattr(payload, name, None) for name in type(payload).model_fields
            }
    return payloads


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

    payloads = _lake_payloads_as_mappings(flow)
    if not payloads:
        return False

    polygons_by_lake = _resolve_lake_polygons(records, lake_ids=list(payloads))
    if not polygons_by_lake:
        return False

    attached = False
    for lake_id, payload in payloads.items():
        polygon = polygons_by_lake.get(lake_id)
        if polygon is None:
            continue
        payload["polygon"] = polygon
        attached = True

    if not attached:
        return False
    flow.sinks_sources["lakes"] = payloads
    return True


def _read_barrier_csv(path, where):
    """Read a bare x,y (optionally z) CSV of ordered polyline vertices."""
    import pandas as pd
    from shapely.geometry import LineString

    df = pd.read_csv(path)
    cols = {c.strip().lower(): c for c in df.columns}
    xcol = cols.get("x") or cols.get("lon") or cols.get("easting") or df.columns[0]
    ycol = cols.get("y") or cols.get("lat") or cols.get("northing") or df.columns[1]
    coords = [(float(x), float(y)) for x, y in zip(df[xcol], df[ycol], strict=False)]
    if len(coords) < 2:
        raise ValueError(f"{where} CSV '{path}' needs at least two (x, y) rows.")
    return LineString(coords)


def _resolve_barrier_line(cfg: object, *, where: str, project_crs: object = None, data_dir=None):
    """Build the shapely barrier trace from a FlowBarrierConfig.

    Four input formats, so the user can pick whatever they have:
    * inline ``line`` coordinates (a list of (x, y) vertices, multi-segment OK);
    * ``line_path`` to a vector file (.gpkg / .shp / .geojson), reprojected to the
      project CRS and line-merged into a single (possibly multi-vertex) LineString;
    * ``line_path`` to a bare ``.csv`` of ordered x,y (or lon,lat) vertices, taken
      in the project CRS;
    * (``auto`` is handled by the caller, not here).

    A bare ``line_path`` filename resolves against ``<workspace>/data/cutoff_wall/``.
    A genuinely multi-part or non-line geometry raises a typed error naming the file.
    """
    from pathlib import Path

    from shapely.geometry import LineString
    from shapely.ops import linemerge

    line = cfg.get("line") if isinstance(cfg, Mapping) else getattr(cfg, "line", None)
    line_path = (
        cfg.get("line_path") if isinstance(cfg, Mapping) else getattr(cfg, "line_path", None)
    )
    if line:
        return LineString([(float(x), float(y)) for x, y in line])
    if line_path:
        resolved = Path(str(line_path)).expanduser()
        if not resolved.is_absolute() and data_dir is not None:
            from hydromodpy.core.toml_io.paths import resolve_declared_path

            resolved = resolve_declared_path(
                line_path, base_dir=Path(data_dir) / "cutoff_wall", fallback_dirs=[Path(data_dir)]
            )
        if str(resolved).lower().endswith(".csv"):
            return _read_barrier_csv(resolved, where)

        import geopandas as gpd

        gdf = gpd.read_file(str(resolved))
        if gdf.empty:
            raise ValueError(f"{where} line_path '{resolved}' has no geometry.")
        if gdf.crs is None:
            logger.warning(
                "%s line_path '%s' has no CRS; assuming it is already in the project CRS.",
                where,
                resolved,
            )
        elif project_crs is not None:
            gdf = gdf.to_crs(project_crs)
        unioned = gdf.union_all()
        # linemerge stitches a MultiLineString into one; a lone LineString it rejects.
        merged = linemerge(unioned) if unioned.geom_type == "MultiLineString" else unioned
        if isinstance(merged, LineString) and not merged.is_empty:
            return merged
        raise ValueError(
            f"{where} line_path '{resolved}' resolves to a {merged.geom_type}, not a single "
            "LineString; provide one contiguous polyline (a branching or multi-part trace is "
            "not supported)."
        )
    raise ValueError(f"{where} has neither auto, line, nor line_path.")


def auto_dam_axis(
    polygon: object,
    outlet_xy: tuple[float, float],
    *,
    width_probe: float = 15.0,
    extend: float = 1.12,
) -> object:
    """Auto-derive the dam cutoff-wall axis at the reservoir's DOWNSTREAM EDGE.

    The dam is where the reservoir drains toward the catchment outlet: the
    footprint boundary point nearest the outlet (the spill point). The axis is
    CENTRED ON that boundary point (so the wall sits at the lake edge and leaves
    essentially no lake cells behind it), oriented PERPENDICULAR to the outlet
    flow (spill -> outlet), with the local reservoir width taken from a chord a
    short ``width_probe`` inside the neck (the tip itself is degenerate), and
    extended a little past both banks so the HFB reaches into the abutments.
    Pure shapely so it can bind before the mesh exists.
    """
    import numpy as np
    from shapely.geometry import LineString, Point
    from shapely.ops import nearest_points

    o = Point(float(outlet_xy[0]), float(outlet_xy[1]))
    spill = nearest_points(polygon.exterior, o)[0]
    u = np.array([o.x - spill.x, o.y - spill.y], dtype=float)
    norm = float(np.hypot(*u)) or 1.0
    u /= norm
    n = np.array([-u[1], u[0]])
    # Local width from a chord a short step inside the neck (the tip is degenerate).
    anchor = np.array([spill.x, spill.y]) - u * float(width_probe)
    probe = LineString([tuple(anchor - n * 8000.0), tuple(anchor + n * 8000.0)])
    inter = probe.intersection(polygon)
    segments = [inter] if inter.geom_type == "LineString" else list(getattr(inter, "geoms", []))
    segments = [s for s in segments if s.geom_type == "LineString" and not s.is_empty]
    if not segments:
        raise ValueError(
            "cutoff_wall auto: the perpendicular probe does not cross the reservoir "
            "footprint; give an explicit line instead."
        )
    seg = min(segments, key=lambda s: s.distance(Point(*anchor)))
    axis_dir = np.array(seg.coords[-1]) - np.array(seg.coords[0])
    axis_dir /= float(np.hypot(*axis_dir)) or 1.0
    half = axis_dir * (seg.length / 2.0) * float(extend)
    center = np.array([spill.x, spill.y])  # sit the wall ON the downstream edge
    return LineString([tuple(center - half), tuple(center + half)])


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

    Returns True if at least one wall line was attached, False otherwise.
    """
    payloads = _lake_payloads_as_mappings(flow)
    if not payloads:
        return False

    attached = False
    for lake_id, payload in payloads.items():
        cfg = payload.get("cutoff_wall")
        if cfg is None:
            continue
        where = f"flow.sinks_sources.lakes.{lake_id}.cutoff_wall"
        if bool(getattr(cfg, "auto", False)):
            polygon = payload.get("polygon")
            if polygon is None:
                raise ValueError(
                    f"{where} auto needs the lake footprint; bind lake geometry first."
                )
            if outlet_xy is None:
                raise ValueError(
                    f"{where} auto needs the catchment outlet; only from_outlet_coord catchments "
                    "expose x_outlet/y_outlet. Give an explicit line instead."
                )
            payload["cutoff_wall_line"] = auto_dam_axis(polygon, outlet_xy)
        else:
            payload["cutoff_wall_line"] = _resolve_barrier_line(
                cfg, where=where, project_crs=project_crs, data_dir=data_dir
            )
        attached = True

    if not attached:
        return False
    flow.sinks_sources["lakes"] = payloads
    return True


def apply_flow_barriers_to_flow(*, flow: Flow, project_crs: object = None) -> bool:
    """Resolve the general ``[flow.sinks_sources.flow_barriers]`` traces.

    Each barrier is a :class:`FlowBarrierConfig`. This normalizes the mapping to
    payload dicts ``{'barrier': cfg, 'line': shapely}`` so the HFB builder reads
    the resolved trace and parameters. Idempotent: an already-resolved payload is
    kept as-is. Returns True if at least one barrier line was attached.
    """
    sinks_sources = getattr(flow, "sinks_sources", {})
    barriers = sinks_sources.get("flow_barriers") if isinstance(sinks_sources, Mapping) else None
    if not isinstance(barriers, Mapping) or not barriers:
        return False

    out: dict[str, dict[str, object]] = {}
    attached = False
    for barrier_id, cfg in barriers.items():
        bid = str(barrier_id)
        if isinstance(cfg, Mapping) and "line" in cfg and "barrier" in cfg:
            out[bid] = dict(cfg)
            continue
        line = _resolve_barrier_line(
            cfg, where=f"flow.sinks_sources.flow_barriers.{bid}", project_crs=project_crs
        )
        out[bid] = {"barrier": cfg, "line": line}
        attached = True

    if not attached:
        return False
    flow.sinks_sources["flow_barriers"] = out
    return True


def _sfr_payloads_as_mappings(flow: Flow) -> dict[str, dict[str, object]]:
    """Return the flow SFR payloads as mutable dicts keyed by network id.

    The runtime stores typed ``FlowReachNetworkConfig`` objects (or already
    enriched dicts) under ``flow.sinks_sources['sfr']``; the binder attaches the
    delineated ``reach_trace`` onto each payload, so they are normalized to
    plain dicts the SFR builder reads through its ``_attr`` lookup.
    """
    sinks_sources = getattr(flow, "sinks_sources", {})
    sfr = sinks_sources.get("sfr") if isinstance(sinks_sources, Mapping) else None
    if not isinstance(sfr, Mapping) or not sfr:
        return {}

    payloads: dict[str, dict[str, object]] = {}
    for network_id, payload in sfr.items():
        if isinstance(payload, Mapping):
            payloads[str(network_id)] = dict(payload)
        else:
            # Snapshot every declared config field so a new field never drops out.
            payloads[str(network_id)] = {
                name: getattr(payload, name, None) for name in type(payload).model_fields
            }
    return payloads


def apply_sfr_network_to_flow(
    *,
    flow: Flow,
    reach_traces: Mapping[str, object] | None,
) -> bool:
    """Attach delineated SFR reach traces onto each flow SFR network payload.

    ``reach_traces`` maps a network id to its spatial ``SfrReachTrace`` (an
    opaque payload at this layer; the geometry was computed by the spatial
    delineation step). A network carrying an explicit ``reaches`` table keeps it
    and needs no trace. The solver builder then intersects each trace polyline
    with the DISV mesh.

    Returns True if at least one trace was attached, False otherwise.
    """
    if not reach_traces:
        return False
    payloads = _sfr_payloads_as_mappings(flow)
    if not payloads:
        return False

    attached = False
    for network_id, payload in payloads.items():
        trace = reach_traces.get(network_id)
        if trace is None or payload.get("reaches") is not None:
            continue
        payload["reach_trace"] = trace
        attached = True

    if not attached:
        return False
    flow.sinks_sources["sfr"] = payloads
    return True


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

    payloads = _lake_payloads_as_mappings(flow)
    if not payloads:
        return False

    abacus_by_lake = _resolve_lake_abacus(records, lake_ids=list(payloads))
    if not abacus_by_lake:
        return False

    attached = False
    for lake_id, payload in payloads.items():
        abacus = abacus_by_lake.get(lake_id)
        if abacus is None:
            continue
        payload["abacus"] = abacus
        attached = True

    if not attached:
        return False
    flow.sinks_sources["lakes"] = payloads
    return True


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

    payloads = _lake_payloads_as_mappings(flow)
    if not payloads:
        return False

    bathy_by_lake = _resolve_lake_bathymetry(records, lake_ids=list(payloads))
    if not bathy_by_lake:
        return False

    attached = False
    for lake_id, payload in payloads.items():
        raster = bathy_by_lake.get(lake_id)
        if raster is None:
            continue
        payload["bathymetry"] = raster
        attached = True

    if not attached:
        return False
    flow.sinks_sources["lakes"] = payloads
    return True


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

    payloads = _lake_payloads_as_mappings(flow)
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


def _active_sfr_payloads(flow: Flow) -> dict[str, dict[str, object]]:
    """Return the SFR payload dicts when the ``sfr`` boundary is active, else {}."""
    active_bc = {str(name).lower() for name in getattr(flow, "active_bc", []) or []}
    if "sfr" not in active_bc:
        return {}
    return _sfr_payloads_as_mappings(flow)


def sfr_routes_catchment_runoff(flow: Flow) -> bool:
    """Return whether an active SFR network takes the catchment runoff.

    With an active stream network the catchment runoff is ROUTED: it enters the
    reaches (distributed by length), travels downstream, and reaches a coupled
    lake through MVR instead of being dumped directly onto the lake surface.
    The lake meteo binder uses this to skip its legacy direct ``runoff * area``
    feed, so the same water is never counted twice.
    """
    return bool(_active_sfr_payloads(flow))


def apply_runoff_to_sfr_networks(
    *,
    flow: Flow,
    runoff: LoadResultProto | None = None,
    simulation_window: ResolvedSimulationTimeWindow | None = None,
    catchment_area_m2: float | None = None,
) -> bool:
    """Attach the catchment runoff as the routed SFR ``runoff`` forcing.

    The catchment-scale runoff data family (e.g. SIM2, internal unit mm/day) is
    reduced to a watershed-mean per-period rate in m/s and multiplied by the
    catchment area: the volumetric (m3/s) overland inflow entering the stream
    network, which the SFR builder distributes over the reaches by length. A
    ``runoff`` forcing already declared in config wins, so the data family is
    only the default source.

    Returns True if at least one forcing was attached, False otherwise.
    """
    if runoff is None or simulation_window is None or not catchment_area_m2:
        return False
    payloads = _active_sfr_payloads(flow)
    if not payloads:
        return False

    rate = _watershed_mean_rates(runoff, "sfr_runoff", simulation_window)
    if rate is None:
        return False
    area = float(catchment_area_m2)
    values = [float(v) * area for v in rate]

    attached = False
    for payload in payloads.values():
        if payload.get("runoff") is not None:
            continue  # config already declares the forcing
        payload["runoff"] = {"kind": "values", "values": values, "units": "m3/s"}
        attached = True

    if not attached:
        return False
    flow.sinks_sources["sfr"] = payloads
    return True


def _watershed_mean_rates(
    result: LoadResultProto | None,
    label: str,
    simulation_window: ResolvedSimulationTimeWindow,
) -> list[float] | None:
    """Reduce one catchment data family to per-period watershed-mean rates [m/s]."""
    if result is None:
        return None
    from hydromodpy.core.units.hydraulic_conductivity import factor_to_m_per_s
    from hydromodpy.physics.forcing.forcing_bridge import resolve_forcing

    resolved = resolve_forcing(
        result,
        unit_conversion_factor=factor_to_m_per_s("mm/day"),
        simulation_window=simulation_window,
        spatial_mode="homogeneous",
        label=label,
    )
    if resolved is None or resolved.series is None:
        return None
    return [float(v) for v in resolved.series]


def apply_lake_meteo_forcings_to_flow(
    *,
    flow: Flow,
    precipitation: LoadResultProto | None = None,
    etp: LoadResultProto | None = None,
    runoff: LoadResultProto | None = None,
    simulation_window: ResolvedSimulationTimeWindow | None = None,
    catchment_area_m2: float | None = None,
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

    Returns True if at least one forcing was attached, False otherwise.
    """
    if simulation_window is None or all(r is None for r in (precipitation, etp, runoff)):
        return False
    payloads = _lake_payloads_as_mappings(flow)
    if not payloads:
        return False

    rain = _watershed_mean_rates(precipitation, "lake_rainfall", simulation_window)
    evap = _watershed_mean_rates(etp, "lake_evaporation", simulation_window)
    # The watershed-mean runoff RATE [m/s] is surfaced in every mode (even when SFR
    # routes the lumped volume) so the exposed-band marnage runoff can size itself
    # from the live stage. The lumped runoff VOLUME stays a direct lake feed only
    # when no SFR network routes it.
    runoff_rate = _watershed_mean_rates(runoff, "lake_runoff", simulation_window)
    runoff_vol: list[float] | None = None
    if not sfr_routes_catchment_runoff(flow) and runoff_rate is not None and catchment_area_m2:
        area = float(catchment_area_m2)
        runoff_vol = [v * area for v in runoff_rate]

    derived = (
        ("rainfall", rain, "m/s"),
        ("evaporation", evap, "m/s"),
        ("runoff", runoff_vol, "m3/s"),
    )
    attached = False
    for payload in payloads.values():
        for keyword, values, unit in derived:
            if values is not None and payload.get(keyword) is None:
                payload[keyword] = {"kind": "values", "values": values, "units": unit}
                attached = True
        # The watershed runoff RATE is only consumed by the exposed-band (marnage)
        # coupling, so surface it only for lakes that opt in (leaving the binder's
        # behaviour unchanged for every other lake).
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


def apply_simulation_time_to_flow_wells(
    *,
    flow: Flow,
    simulation_window: ResolvedSimulationTimeWindow | None,
) -> None:
    """Resolve flow well.forcing payloads to period-aligned well.flux values."""
    if simulation_window is None:
        return

    sinks_sources = getattr(flow, "sinks_sources", {})
    wells = sinks_sources.get("wells", {}) if isinstance(sinks_sources, Mapping) else {}
    if not wells:
        return

    updated_wells: dict[str, object] = {}
    changed = False
    for well_id, well_cfg in wells.items():
        forcing = getattr(well_cfg, "forcing", None)
        if forcing is None:
            updated_wells[well_id] = well_cfg
            continue

        label = f"flow.sinks_sources.wells.{well_id}.forcing"
        resolved_flux = resolve_period_values_from_forcing(
            forcing=forcing,
            simulation_window=simulation_window,
            nper=len(build_simulation_time_boundaries(simulation_window)) - 1,
            label=label,
        )
        source_units = normalize_m3_per_s_unit(
            str(getattr(forcing, "units", None) or getattr(well_cfg, "units", "m3/s"))
        )
        flux_si = [
            convert_to_m3_per_s(
                value,
                unit=source_units,
                label=f"{label}[{idx}]",
            )
            for idx, value in enumerate(resolved_flux)
        ]

        updated_wells[well_id] = well_cfg.model_copy(
            update={"flux": flux_si, "forcing": None, "units": "m3/s"}
        )
        changed = True

    if not changed:
        return

    flow.set_sinks_sources(
        FlowSinksSourcesConfig(
            wells=updated_wells,
            recharge=sinks_sources.get("recharge") if isinstance(sinks_sources, Mapping) else None,
        )
    )


def apply_simulation_time_to_flow_boundary_conditions(
    *,
    flow: Flow,
    simulation_window: ResolvedSimulationTimeWindow | None,
) -> None:
    """Resolve flow.bc.*.forcing payloads to period-aligned boundary.value series."""
    if simulation_window is None:
        return

    boundary_conditions = boundary_conditions_mapping_from_flow(flow)
    if not boundary_conditions:
        return

    updated_boundaries: dict[str, object] = {}
    changed = False
    for bc_id, boundary_cfg in boundary_conditions.items():
        forcing = getattr(boundary_cfg, "forcing", None)
        if forcing is None:
            updated_boundaries[bc_id] = boundary_cfg
            continue

        label = f"flow.bc.{bc_id}.forcing"
        resolved_values = resolve_period_values_from_forcing(
            forcing=forcing,
            simulation_window=simulation_window,
            nper=len(build_simulation_time_boundaries(simulation_window)) - 1,
            label=label,
        )
        updated_units = getattr(boundary_cfg, "units", "m")
        boundary_kind = str(getattr(boundary_cfg, "kind", "dirichlet")).strip().lower()
        if boundary_kind == "dirichlet":
            source_units = normalize_length_unit(
                str(getattr(forcing, "units", None) or updated_units or "m")
            )
            resolved_values = convert_payload_to_m(
                resolved_values,
                unit=source_units,
                label=f"{label}.values",
            )
            updated_units = "m"

        updated_boundaries[bc_id] = boundary_cfg.model_copy(
            update={"value": resolved_values, "forcing": None, "units": updated_units}
        )
        changed = True

    if not changed:
        return

    flow.set_boundary_conditions(
        boundary_conditions=updated_boundaries,
        application_domains=getattr(flow, "boundary_condition_application_domains", None),
    )
