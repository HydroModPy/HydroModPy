"""Flow-side binders for data-to-structure updates."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

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
    resolve_period_values_from_forcing,
)

if TYPE_CHECKING:
    from hydromodpy.core.time import ResolvedSimulationTimeWindow
    from hydromodpy.physics.flow import Flow


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
            fields = ("bedleak", "stageinit", "outlets")
            forcings = ("rainfall", "evaporation", "runoff", "inflow", "withdrawal")
            payloads[str(lake_id)] = {
                name: getattr(payload, name, None) for name in (*fields, *forcings)
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
