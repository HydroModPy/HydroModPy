"""Concern 1 of PrepareSolverStep: persistence helpers.

Hosts the helpers that write inputs to disk before the solver runs:

- parameter writes via :func:`step_persist_params`
- mesh persistence via :func:`step_persist_mesh`
- geographic raster persistence via :func:`step_persist_geographic`
- provenance fingerprints via :func:`step_write_provenance`
- forcings persistence via :func:`step_persist_forcings`

The functions stay free-standing so notebook helpers and the orchestrator
prepared-run path keep importing them by name.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.core.exceptions import MeshError, PipelineError
from hydromodpy.core.logging import get_logger
from hydromodpy.workflow.internals.data_description import (
    iter_loaded_records,
    read_data_description,
    record_source_path,
    sha256_file_or_none,
    source_digests,
)

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import WorkflowContext
    from hydromodpy.physics.flow import Flow
    from hydromodpy.results.catalog.protocol import SimulationStore
    from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr
    from hydromodpy.spatial.domain import Domain

logger = get_logger(__name__)


def step_persist_params(
    store: SimulationStore,
    sim_id: str,
    flow: Flow,
    *,
    domain: Domain | None = None,
) -> None:
    """Write hydraulic parameters from a Flow object into the catalog."""
    params: list[dict] = []

    params_dict = getattr(flow, "parameters", None)
    if params_dict:
        for pid, fp in params_dict.items():
            kind = getattr(fp, "kind", "homogeneous")
            if kind == "homogeneous":
                params.append(
                    {
                        "param_name": pid,
                        "zone_id": None,
                        "value": getattr(fp, "value", None),
                        "unit": getattr(fp, "unit", ""),
                        "parameterization": "homogeneous",
                    }
                )
            else:
                values_by_key = getattr(fp, "values_by_key", None) or {}
                for zone_key, val in values_by_key.items():
                    params.append(
                        {
                            "param_name": pid,
                            "zone_id": str(zone_key),
                            "value": val,
                            "unit": getattr(fp, "unit", ""),
                            "parameterization": "geology_mapped",
                        }
                    )

    if domain is not None:
        # Only a constant-thickness depth model carries one number for the
        # whole aquifer; a raster or a flat substratum has no scalar to write.
        thickness = getattr(domain.config.depth_model, "thickness", None)
        if thickness is not None:
            params.append(
                {
                    "param_name": "thickness",
                    "zone_id": None,
                    "value": float(thickness),
                    "unit": "m",
                    "parameterization": "homogeneous",
                }
            )

    if params:
        store.write_parameters(sim_id, params)


def step_persist_mesh(ctx: WorkflowContext, sim_id: str, *, store: SimulationStore) -> None:
    """Write mesh topology into the simulation's Zarr."""
    import numpy as np

    domain = ctx.setup.domain
    if domain is None:
        return

    z_intf = np.asarray(domain.z_interfaces, dtype=float)

    mesh_planar = ctx.setup.mesh_planar
    if mesh_planar is not None:
        vertices = mesh_planar.points_xy
        connectivity = mesh_planar.connectivity
    else:
        from hydromodpy.spatial.mesh.model.grid_wrappers import RegularGrid

        support = getattr(domain.surface_topo, "support", None)
        if support is None or support.nrows is None or support.ncols is None:
            raise MeshError(
                "step_persist_mesh: no Gmsh planar mesh and no raster support "
                "on domain.surface_topo - cannot materialise a HydroMesh"
            )
        regular = RegularGrid(
            shape=(int(support.nrows), int(support.ncols)),
            dx=float(support.dx),
            dy=float(support.dy),
            origin=(float(support.xmin), float(support.ymax)),
            n_layers=max(int(z_intf.size) - 1, 1),
            crs=str(support.crs) if support.crs is not None else None,
        )
        hydro_mesh = regular.to_hydro_mesh()
        vertices = hydro_mesh.vertices
        connectivity = hydro_mesh.flat_connectivity

    store.write_mesh(
        sim_id,
        vertices=vertices,
        face_node_connectivity=connectivity,
        z_interfaces=z_intf,
    )


def step_persist_geographic(ctx: WorkflowContext, sim_id: str, *, store: SimulationStore) -> None:
    """Persist the geographic rasters (DEM, watershed masks) into the Zarr."""
    from hydromodpy.spatial.geographic.store_ingestion import (
        persist_geographic_to_store,
    )

    if ctx.setup.geographic is None:
        return
    persist_geographic_to_store(ctx.setup.geographic, store, sim_id=sim_id)


# ---------------------------------------------------------------------------
# Provenance + forcings
# ---------------------------------------------------------------------------


def _field_data_array(record: object) -> np.ndarray | None:
    data = getattr(record, "data", None)
    if isinstance(data, (str, Path)):
        return None
    if hasattr(data, "data_vars"):
        metadata = getattr(record, "metadata", None)
        var_name = str(getattr(record, "variable", ""))
        if isinstance(metadata, dict):
            var_name = str(metadata.get("array_name") or var_name)
        if var_name in data.data_vars:
            return np.asarray(data[var_name].values, dtype="float64")
        if data.data_vars:
            first_name = next(iter(data.data_vars))
            return np.asarray(data[first_name].values, dtype="float64")
        return None
    if hasattr(data, "values"):
        return np.asarray(data.values, dtype="float64")
    return None


def _hydrography_field_record(load_result: object) -> object | None:
    from hydromodpy.spatial.geographic.core.hydrographic_network import (
        HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME,
    )

    for record in getattr(load_result, "fields", None) or ():
        if getattr(record, "variable", None) == HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME:
            return record
    return None


def _digests_the_load_already_computed(ctx: WorkflowContext) -> dict[str, str]:
    """Return the source digests ``load_data`` wrote, keyed by path.

    Hashing a 500 MB DEM twice per run buys nothing: the digest of a file is a
    function of the file, and the one the load computed describes the bytes it
    actually read. A run whose document is missing - a notebook calling this
    helper on its own, a pipeline that skipped the load - simply finds nothing
    here and hashes what it needs.
    """
    project_root = getattr(getattr(ctx.setup, "workspace", None), "project_root", None)
    run_id = getattr(ctx.setup, "run_id", None)
    if project_root is None or not run_id:
        return {}
    return source_digests(read_data_description(Path(project_root), str(run_id)))


def step_write_provenance(ctx: WorkflowContext, *, store: SimulationStore) -> None:
    """Record provenance fingerprints for each loaded data variable.

    The walk over the loaded scopes is the one ``load_data`` used to describe
    itself, and the source digests are the ones it computed, so the rows
    written here and the document it left cannot name a different set of inputs
    nor disagree on their bytes.
    """
    if ctx.sim_id is None:
        return

    import numpy as np

    known_digests = _digests_the_load_already_computed(ctx)
    written = 0
    for item in iter_loaded_records(ctx.loaded_data):
        rec = item.record
        label = f"{item.scope}:{item.variable}"
        try:
            source_path = record_source_path(rec)
            if item.kind == "point":
                arr = np.asarray(rec.data["value"].values, dtype="float64")
            else:
                arr = _field_data_array(rec)
                if arr is None and source_path is not None and source_path.is_file():
                    arr = np.frombuffer(source_path.read_bytes(), dtype="uint8")
                if arr is None:
                    continue
            digest = known_digests.get(str(source_path)) if source_path is not None else None
            store.write_provenance(
                ctx.sim_id,
                variable=label,
                source_ref=str(getattr(rec, "source", "")),
                data=arr,
                source_type="data_manager",
                source_sha256=digest or sha256_file_or_none(source_path),
                loader_name=item.loader_name,
                loader_version="v1",
                period_start=getattr(rec, "date_start", None),
                period_end=getattr(rec, "date_end", None),
            )
            written += 1
        except Exception as exc:
            prefix = (
                "Provenance failed for" if item.kind == "point" else "Provenance failed for field"
            )
            raise PipelineError(f"{prefix} {label}") from exc

    if written:
        logger.debug("Wrote %d provenance records for sim %s", written, ctx.sim_id)


# Gridded forcing families reduced to a watershed-mean station series at
# persist time. The catchment discharge derivation reads runoff back from
# Zarr forcing/ when no stream network routes it.
_WATERSHED_MEAN_FORCINGS = frozenset({"runoff"})
_WATERSHED_MEAN_STATION = "_watershed"


def _watershed_mean_series(load_result: object):
    """Reduce a gridded forcing family to one tz-naive watershed-mean series."""
    import pandas as pd

    from hydromodpy.spatial.field.aggregation import extract_homogeneous_series_from_fields

    try:
        series = extract_homogeneous_series_from_fields(load_result)
    except Exception:
        logger.debug("Watershed-mean reduction failed", exc_info=True)
        return None
    if series is None or len(series) == 0:
        return None
    idx = pd.DatetimeIndex(series.index)
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    series.index = idx
    return series


def step_persist_forcings(ctx: WorkflowContext, *, store: SimulationStore) -> None:
    """Persist input forcings into the Zarr ``forcing/`` group."""
    if ctx.sim_id is None:
        return

    import numpy as np
    import pandas as pd

    sz = store.open_zarr(ctx.sim_id)
    loaded = ctx.loaded_data
    written = 0

    # getattr, not ctx.setup.soil_forcings: some callers of this step (and a
    # few regression test doubles) hand it a context with no .setup at all.
    soil = getattr(getattr(ctx, "setup", None), "soil_forcings", None)
    sources = [(f.name, getattr(loaded, f.name, None)) for f in dataclasses.fields(loaded)]
    if soil is not None:
        # loaded.recharge and loaded.runoff are None in soil mode (R1, R2): no
        # duplicate key reaches the loop below.
        sources += [("recharge", soil.recharge), ("runoff", soil.runoff)]

    try:
        for name, obj in sources:
            if obj is None:
                continue

            if hasattr(obj, "encoded_codes") and hasattr(obj, "encoded_to_zone"):
                try:
                    codes = np.asarray(obj.encoded_codes)
                    sz.write_forcing_field(
                        "geology_codes",
                        codes,
                        unit="",
                        source=getattr(obj, "source_kind", "raster"),
                    )
                    forcing = sz.root.require_group("forcing")
                    geo_grp = forcing.require_group("geology_meta")
                    geo_grp.attrs["zone_mapping"] = json.dumps(
                        {str(k): str(v) for k, v in obj.encoded_to_zone.items()}
                    )
                    geo_grp.attrs["zone_keys"] = list(obj.zone_keys)
                    transform = getattr(obj, "transform", None)
                    if transform is not None:
                        geo_grp.attrs["transform"] = list(float(v) for v in transform)[:6]
                    if obj.crs is not None:
                        geo_grp.attrs["crs"] = str(obj.crs)
                    geo_grp.attrs["cell_samples_per_axis"] = int(
                        getattr(obj, "default_cell_samples_per_axis", 8)
                    )
                    geo_grp.attrs["source_kind"] = str(getattr(obj, "source_kind", "raster"))

                    mesh = getattr(ctx, "setup", None)
                    mesh_planar = getattr(mesh, "mesh_planar", None) if mesh else None
                    if mesh_planar is not None:
                        try:
                            disc = obj.on_mesh(mesh_planar)
                            fractions = getattr(disc, "fractions_by_zone", {})
                            for zone_key, frac_array in fractions.items():
                                safe_key = zone_key.replace("/", "_").replace(" ", "_")
                                sz.write_forcing_field(
                                    f"geology_frac_{safe_key}",
                                    np.asarray(frac_array, dtype="float64"),
                                    unit="fraction",
                                    source=f"geology:{zone_key}",
                                )
                            written += 1
                        except Exception:
                            logger.debug("Failed to persist geology zone fractions")

                    written += 1
                except Exception:
                    logger.debug("Failed to persist geology forcing")
                continue

            if name == "hydrography":
                try:
                    record = _hydrography_field_record(obj)
                    if record is not None:
                        arr = _field_data_array(record)
                        if arr is not None and arr.size > 0:
                            from hydromodpy.spatial.geographic.core.hydrographic_network import (
                                HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME,
                            )

                            sz.write_forcing_field(
                                HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME,
                                arr,
                                unit=getattr(record, "unit", ""),
                                source=getattr(record, "source", ""),
                            )
                            written += 1
                        _persist_reference_hydrographic_feature(ctx, obj, store=store)
                except Exception:
                    logger.debug("Failed to persist hydrography forcing")
                continue

            points = getattr(obj, "points", None)
            if points:
                for rec in points:
                    try:
                        df = rec.data
                        timestamps = pd.to_datetime(df["datetime"]).values
                        values = df["value"].values.astype("float64")
                        station = getattr(rec, "station_id", None) or name
                        sz.write_forcing_timeseries(
                            name,
                            station,
                            timestamps,
                            values,
                            unit=getattr(rec, "unit", ""),
                            source=getattr(rec, "source", ""),
                        )
                        written += 1
                    except Exception:
                        logger.debug(
                            "Failed to persist forcing %s:%s",
                            name,
                            getattr(rec, "station_id", "?"),
                        )

            fields_list = getattr(obj, "fields", None)
            if fields_list:
                for rec in fields_list:
                    try:
                        arr = _field_data_array(rec)
                        if arr is None:
                            continue
                        sz.write_forcing_field(
                            f"{name}_{rec.variable}",
                            arr,
                            unit=getattr(rec, "unit", ""),
                            source=getattr(rec, "source", ""),
                        )
                        written += 1
                    except Exception:
                        logger.debug(
                            "Failed to persist forcing field %s:%s",
                            name,
                            getattr(rec, "variable", "?"),
                        )

            # A gridded family has no station to land under
            # forcing/<var>/<station>; its watershed mean keeps a
            # station-shaped copy so post-processing (catchment discharge)
            # can read the forcing back. Same reduction as the SFR / LAK
            # forcing binders, so both accountings stay consistent.
            if name in _WATERSHED_MEAN_FORCINGS and fields_list and not points:
                series = _watershed_mean_series(obj)
                if series is not None:
                    try:
                        sz.write_forcing_timeseries(
                            name,
                            _WATERSHED_MEAN_STATION,
                            np.asarray(series.index.values, dtype="datetime64[ns]"),
                            series.to_numpy(dtype="float64"),
                            unit=getattr(fields_list[0], "unit", "") or "",
                            source="watershed_mean",
                        )
                        written += 1
                    except Exception:
                        logger.debug("Failed to persist watershed-mean forcing %s", name)

        # Not wrapped like the rest of the loop: a broken soil write is a bug
        # in this feature, not a flaky external source, and must not be
        # swallowed into a silent debug line.
        if soil is not None:
            _persist_soil_columns(sz, soil)
    finally:
        sz.close()

    if soil is not None:
        store.write_view(ctx.sim_id, "soil_budget", _soil_budget_rows(soil))

    if written:
        logger.debug("Persisted %d forcing datasets for sim %s", written, ctx.sim_id)


def _soil_budget_rows(soil: object) -> list[dict[str, object]]:
    """Build the ``soil_budget`` rows: one per column and year, plus a basin row."""
    from hydromodpy.physics.hydrology.soil_reservoir.kernel import annual_budget

    columns = soil.columns
    ru_mm = soil.parameters.ru_mm
    budget = annual_budget(
        soil.years, soil.precipitation, soil.etp, soil.fluxes, columns.basin_weight
    )
    n_years, n_columns = budget.precipitation.shape

    rows: list[dict[str, object]] = []
    for j in range(n_columns):
        column_id = f"{int(columns.cell_index[j])}.{int(columns.class_index[j])}"
        for i in range(n_years):
            rows.append(
                {
                    "column_id": column_id,
                    "cell_index": int(columns.cell_index[j]),
                    "class_index": int(columns.class_index[j]),
                    "x": float(columns.x[j]),
                    "y": float(columns.y[j]),
                    "ru_mm": float(ru_mm[j]),
                    "basin_weight": float(columns.basin_weight[j]),
                    "year": int(budget.years[i]),
                    "days": int(budget.days[i]),
                    "precipitation_mm": float(budget.precipitation[i, j]),
                    "etp_mm": float(budget.etp[i, j]),
                    "etr_mm": float(budget.etr[i, j]),
                    "residual_etp_mm": float(budget.residual_etp[i, j]),
                    "recharge_mm": float(budget.recharge[i, j]),
                    "runoff_mm": float(budget.runoff[i, j]),
                    "runoff_cn_mm": float(budget.runoff_cn[i, j]),
                    "soil_storage_change_mm": float(budget.soil_storage_change[i, j]),
                    "transit_storage_change_mm": float(budget.transit_storage_change[i, j]),
                    "cn_storage_change_mm": float(budget.cn_storage_change[i, j]),
                    "lag_storage_change_mm": float(budget.lag_storage_change[i, j]),
                    "balance_residual_mm": float(budget.residual[i, j]),
                }
            )

    basin_ru_mm = float(np.sum(ru_mm * columns.basin_weight))
    for i in range(n_years):
        rows.append(
            {
                "column_id": _WATERSHED_MEAN_STATION,
                "cell_index": None,
                "class_index": None,
                "x": None,
                "y": None,
                "ru_mm": basin_ru_mm,
                "basin_weight": 1.0,
                "year": int(budget.years[i]),
                "days": int(budget.days[i]),
                "precipitation_mm": float(budget.basin("precipitation")[i]),
                "etp_mm": float(budget.basin("etp")[i]),
                "etr_mm": float(budget.basin("etr")[i]),
                "residual_etp_mm": float(budget.basin("residual_etp")[i]),
                "recharge_mm": float(budget.basin("recharge")[i]),
                "runoff_mm": float(budget.basin("runoff")[i]),
                "runoff_cn_mm": float(budget.basin("runoff_cn")[i]),
                "soil_storage_change_mm": float(budget.basin("soil_storage_change")[i]),
                "transit_storage_change_mm": float(budget.basin("transit_storage_change")[i]),
                "cn_storage_change_mm": float(budget.basin("cn_storage_change")[i]),
                "lag_storage_change_mm": float(budget.basin("lag_storage_change")[i]),
                "balance_residual_mm": float(budget.basin("residual")[i]),
            }
        )
    return rows


def _persist_soil_columns(sz: SimulationZarr, soil: object) -> None:
    """Write the soil reservoir's daily columns under ``forcing/soil``."""
    fluxes = soil.fluxes
    config = soil.config
    columns = soil.columns
    series = {
        "etr": (fluxes.etr, "mm/day", "time: mean", "Actual evapotranspiration of the soil"),
        "residual_etp": (
            fluxes.residual_etp,
            "mm/day",
            "time: mean",
            "ETP the soil left unmet",
        ),
        "recharge": (
            fluxes.recharge,
            "mm/day",
            "time: mean",
            "Recharge sent to the water table",
        ),
        "runoff": (
            fluxes.runoff,
            "mm/day",
            "time: mean",
            "Runoff of the sealed share plus the routed curve-number share",
        ),
        "runoff_cn": (
            fluxes.runoff_cn,
            "mm/day",
            "time: mean",
            "Curve-number share of runoff alone",
        ),
        "soil_storage": (
            fluxes.soil_storage,
            "mm",
            "time: point",
            "Soil water storage at the end of the day",
        ),
        "transit_storage": (
            fluxes.transit_storage,
            "mm",
            "time: point",
            "Transit store at the end of the day",
        ),
        "cn_storage": (
            fluxes.cn_storage,
            "mm",
            "time: point",
            "Curve-number runoff routing store at the end of the day",
        ),
        "lag_storage": (
            fluxes.lag_storage,
            "mm",
            "time: point",
            "Routed curve-number runoff delayed by runoff_lag, not yet released, at "
            "the end of the day",
        ),
    }
    columns_arrays = {
        "cell_index": columns.cell_index,
        "class_index": columns.class_index,
        "x": columns.x,
        "y": columns.y,
        "ru_mm": soil.parameters.ru_mm,
        "cell_fraction": columns.cell_fraction,
        "basin_weight": columns.basin_weight,
    }
    attrs = {
        "source": "soil_reservoir",
        "crs": soil.crs,
        "ru_mm": config.ru,
        "alpha": config.alpha,
        "kc": config.kc,
        "impervious_fraction": config.impervious_fraction,
        "bypass_fraction": config.bypass_fraction,
        "transit_time_days": config.transit_time,
        "spinup": config.spinup,
        "spinup_cycles": int(soil.spinup_cycles),
        "never_full_columns": int(soil.never_full_columns),
        "n_cells": int(np.unique(columns.cell_index).size),
        "n_columns": int(columns.cell_index.shape[0]),
    }
    sz.write_soil_columns(
        timestamps=soil.days,
        series=series,
        columns=columns_arrays,
        attrs=attrs,
    )


def _persist_reference_hydrographic_feature(
    ctx: WorkflowContext,
    hydrography_load_result: object,
    *,
    store: SimulationStore,
) -> bool:
    """Persist the imported hydrography vector as one canonical feature.

    Its permanent part, when the loader wrote one, goes beside it under its own
    feature name, so a run read back later still has both.
    """
    if ctx.sim_id is None:
        return False

    from hydromodpy.spatial.geographic.core.hydrographic_network import (
        HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME,
        HYDROGRAPHIC_NETWORK_REFERENCE_PERMANENT_FEATURE_NAME,
        HydrographicNetwork,
    )

    features = getattr(getattr(ctx, "setup", None), "geographic_features", None)
    network = (
        getattr(features, "reference_hydrographic_network", None) if features is not None else None
    )
    if network is None:
        network = HydrographicNetwork.from_hydrography_load_result(hydrography_load_result)
    permanent = (
        getattr(features, "reference_permanent_hydrographic_network", None)
        if features is not None
        else None
    )
    if permanent is None:
        permanent = HydrographicNetwork.permanent_from_hydrography_load_result(
            hydrography_load_result
        )

    written = _persist_network_feature(
        ctx, network, HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME, store=store
    )
    if written and permanent is not None:
        _persist_network_feature(
            ctx, permanent, HYDROGRAPHIC_NETWORK_REFERENCE_PERMANENT_FEATURE_NAME, store=store
        )
    return written


def _persist_network_feature(
    ctx: WorkflowContext,
    network: object,
    feature_name: str,
    *,
    store: SimulationStore,
) -> bool:
    """Write one network's vector as the geographic feature *feature_name*."""
    vector_path = getattr(network, "vector_path", None)
    if vector_path in (None, "") or not Path(str(vector_path)).exists():
        return False

    try:
        gdf = network.read_vector()
        if gdf is None or gdf.empty:
            return False
        if gdf.crs is None and getattr(network, "crs", None) not in (None, ""):
            gdf = gdf.set_crs(str(network.crs), allow_override=True)
        store.write_geographic_feature(ctx.sim_id, feature_name, gdf)
        return True
    except Exception:
        logger.debug("Failed to persist hydrographic network feature %s", feature_name)
        return False


__all__ = (
    "step_persist_forcings",
    "step_persist_geographic",
    "step_persist_mesh",
    "step_persist_params",
    "step_write_provenance",
)
