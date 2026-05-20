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
import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.core.exceptions import MeshError, PipelineError
from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    from hydromodpy.physics.flow import Flow
    from hydromodpy.results.catalog.protocol import SimulationStore
    from hydromodpy.spatial.domain import Domain
    from hydromodpy.workflow.context import WorkflowContext

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
        depth_model = getattr(domain, "depth_model", None)
        thickness = getattr(depth_model, "thickness", None) if depth_model else None
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


def step_persist_mesh(ctx: WorkflowContext, sim_id: str) -> None:
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
        from hydromodpy.spatial.mesh.grid_wrappers import RegularGrid

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

    ctx.store.write_mesh(
        sim_id,
        vertices=vertices,
        face_node_connectivity=connectivity,
        z_interfaces=z_intf,
    )


def step_persist_geographic(ctx: WorkflowContext, sim_id: str) -> None:
    """Persist the geographic rasters (DEM, watershed masks) into the Zarr."""
    from hydromodpy.spatial.geographic.store_ingestion import (
        persist_geographic_to_store,
    )

    if ctx.setup.geographic is None:
        return
    persist_geographic_to_store(ctx.setup.geographic, ctx.store, sim_id=sim_id)


# ---------------------------------------------------------------------------
# Provenance + forcings
# ---------------------------------------------------------------------------


def _record_source_path(record: object) -> Path | None:
    metadata = getattr(record, "metadata", None)
    if isinstance(metadata, dict):
        for key in ("source_path", "raster_path", "vector_path"):
            value = metadata.get(key)
            if value not in (None, ""):
                return Path(str(value))
    file_path = getattr(record, "file_path", None)
    if file_path is not None:
        return Path(file_path)
    data = getattr(record, "data", None)
    if isinstance(data, (str, Path)):
        return Path(data)
    return None


def _sha256_file_or_none(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _loader_name(scope_name: str, record: object) -> str:
    return f"{scope_name}:{type(record).__name__}"


def step_write_provenance(ctx: WorkflowContext) -> None:
    """Record provenance fingerprints for each loaded data variable."""
    if ctx.store is None or ctx.sim_id is None:
        return

    import numpy as np

    loaded = ctx.loaded_data
    written = 0
    for f in dataclasses.fields(loaded):
        load_result = getattr(loaded, f.name, None)
        if load_result is None:
            continue

        points = getattr(load_result, "points", None)
        if points:
            for rec in points:
                try:
                    arr = np.asarray(rec.data["value"].values, dtype="float64")
                    source_path = _record_source_path(rec)
                    ctx.store.write_provenance(
                        ctx.sim_id,
                        variable=f"{f.name}:{rec.variable}",
                        source_ref=str(getattr(rec, "source", "")),
                        data=arr,
                        source_type="data_manager",
                        source_sha256=_sha256_file_or_none(source_path),
                        loader_name=_loader_name(f.name, rec),
                        loader_version="v1",
                        period_start=getattr(rec, "date_start", None),
                        period_end=getattr(rec, "date_end", None),
                    )
                    written += 1
                except Exception as exc:
                    raise PipelineError(f"Provenance failed for {f.name}:{rec.variable}") from exc

        fields = getattr(load_result, "fields", None)
        if fields:
            for rec in fields:
                try:
                    source_path = _record_source_path(rec)
                    arr = _field_data_array(rec)
                    if arr is None and source_path is not None and source_path.is_file():
                        arr = np.frombuffer(source_path.read_bytes(), dtype="uint8")
                    if arr is None:
                        continue
                    ctx.store.write_provenance(
                        ctx.sim_id,
                        variable=f"{f.name}:{rec.variable}",
                        source_ref=str(getattr(rec, "source", "")),
                        data=arr,
                        source_type="data_manager",
                        source_sha256=_sha256_file_or_none(source_path),
                        loader_name=_loader_name(f.name, rec),
                        loader_version="v1",
                        period_start=getattr(rec, "date_start", None),
                        period_end=getattr(rec, "date_end", None),
                    )
                    written += 1
                except Exception as exc:
                    raise PipelineError(
                        f"Provenance failed for field {f.name}:{rec.variable}"
                    ) from exc

    if written:
        logger.info("Wrote %d provenance records for sim %s", written, ctx.sim_id)


def step_persist_forcings(ctx: WorkflowContext) -> None:
    """Persist input forcings into the Zarr ``forcing/`` group."""
    if ctx.store is None or ctx.sim_id is None:
        return

    import numpy as np
    import pandas as pd

    sz = ctx.store.open_zarr(ctx.sim_id)
    loaded = ctx.loaded_data
    written = 0

    for f in dataclasses.fields(loaded):
        obj = getattr(loaded, f.name, None)
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

        if f.name == "hydrography":
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
                    _persist_reference_hydrographic_feature(ctx, obj)
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
                    station = getattr(rec, "station_id", None) or f.name
                    sz.write_forcing_timeseries(
                        f.name,
                        station,
                        timestamps,
                        values,
                        unit=getattr(rec, "unit", ""),
                        source=getattr(rec, "source", ""),
                    )
                    written += 1
                except Exception:
                    logger.debug(
                        "Failed to persist forcing %s:%s", f.name, getattr(rec, "station_id", "?")
                    )

        fields_list = getattr(obj, "fields", None)
        if fields_list:
            for rec in fields_list:
                try:
                    arr = _field_data_array(rec)
                    if arr is None:
                        continue
                    sz.write_forcing_field(
                        f"{f.name}_{rec.variable}",
                        arr,
                        unit=getattr(rec, "unit", ""),
                        source=getattr(rec, "source", ""),
                    )
                    written += 1
                except Exception:
                    logger.debug(
                        "Failed to persist forcing field %s:%s",
                        f.name,
                        getattr(rec, "variable", "?"),
                    )

    if written:
        logger.info("Persisted %d forcing datasets for sim %s", written, ctx.sim_id)


def _persist_reference_hydrographic_feature(
    ctx: WorkflowContext,
    hydrography_load_result: object,
) -> bool:
    """Persist the imported hydrography vector as one canonical feature."""
    if ctx.store is None or ctx.sim_id is None:
        return False

    from hydromodpy.spatial.geographic.core.hydrographic_network import (
        HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME,
        HydrographicNetwork,
    )

    features = getattr(getattr(ctx, "setup", None), "geographic_features", None)
    network = (
        getattr(features, "reference_hydrographic_network", None) if features is not None else None
    )
    if network is None:
        network = HydrographicNetwork.from_hydrography_load_result(hydrography_load_result)

    vector_path = getattr(network, "vector_path", None)
    if vector_path in (None, "") or not Path(str(vector_path)).exists():
        return False

    try:
        gdf = network.read_vector()
        if gdf is None or gdf.empty:
            return False
        if gdf.crs is None and getattr(network, "crs", None) not in (None, ""):
            gdf = gdf.set_crs(str(network.crs), allow_override=True)
        ctx.store.write_geographic_feature(
            ctx.sim_id,
            HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME,
            gdf,
        )
        return True
    except Exception:
        logger.debug("Failed to persist hydrographic network reference feature")
        return False


__all__ = (
    "step_persist_forcings",
    "step_persist_geographic",
    "step_persist_mesh",
    "step_persist_params",
    "step_write_provenance",
)
