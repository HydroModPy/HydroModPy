"""Concern 1 of PrepareSolverStep: persistence helpers.

Hosts the helpers that write inputs to disk before the solver runs:

- parameter writes via :func:`step_persist_params`
- mesh persistence via :func:`step_persist_mesh`
- geographic raster persistence via :func:`step_persist_geographic`
- provenance fingerprints and the loaded inputs of ``inputs.json`` via
  :func:`step_write_provenance`
- forcings persistence via :func:`step_persist_forcings`

The functions stay free-standing so notebook helpers and the orchestrator
prepared-run path keep importing them by name.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.core.exceptions import MeshError, PipelineError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.scope import CATCHMENT
from hydromodpy.core.state.paths import encode_workspace_path
from hydromodpy.data.contracts.spatial_field import INPUT_FILES_KEY
from hydromodpy.results.manifest import InputEntry
from hydromodpy.results.storage.attempt import is_run_product
from hydromodpy.results.storage.digests import path_size_bytes
from hydromodpy.schema.sources import input_licence, licence_for_source
from hydromodpy.spatial.field.zone_fractions import zone_fractions
from hydromodpy.workflow.internals.data_description import (
    LoadedRecord,
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
    from hydromodpy.spatial.domain.domain import Domain

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
    """Write the cell mesh into the simulation's Zarr and its two family tables.

    This is the only write of the mesh geometry: the solver extractors check
    their grid against it and add the vertical part, never the vertices.
    """
    from hydromodpy.results.zarr_store.mesh_layout import (
        cell_family_rows,
        face_family_rows,
        mesh_layout_from_cell_mesh,
    )

    domain = ctx.setup.domain
    if domain is None:
        return

    cell_mesh = ctx.setup.cell_mesh
    if cell_mesh is None:
        raise MeshError("step_persist_mesh: the mesh step built no cell mesh")
    # The domain mean column under every cell, until the solver extractor
    # replaces it with the interfaces of the solved model.
    z_intf = np.tile(
        np.asarray(domain.z_interfaces, dtype=float).reshape(-1, 1), (1, cell_mesh.n_cells)
    )
    summary = ctx.setup.mesh_summary or {}
    # Three columns with z = 0: ``vertices`` is declared as "x y z".
    xy = np.asarray(cell_mesh.mesh.vertices, dtype=float)[:, :2]
    vertices = np.column_stack([xy, np.zeros(len(xy))])

    store.write_mesh(
        sim_id,
        vertices=vertices,
        face_node_connectivity=cell_mesh.connectivity_rows,
        z_interfaces=z_intf,
        structured_shape=cell_mesh.structured_shape,
        layout=mesh_layout_from_cell_mesh(
            cell_mesh,
            request_hash=summary.get("request_hash", ""),
            qa=summary.get("qa"),
            library_versions=summary.get("library_versions"),
        ),
    )
    store.write_view(sim_id, "mesh_cell_families", cell_family_rows(cell_mesh))
    store.write_view(sim_id, "mesh_face_families", face_family_rows(cell_mesh))


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
    run_dir = getattr(ctx, "run_dir", None)
    if run_dir is None:
        return {}
    return source_digests(read_data_description(Path(run_dir)))


def step_write_provenance(ctx: WorkflowContext, *, store: SimulationStore) -> None:
    """Record provenance fingerprints and the ``inputs.json`` entry of each loaded variable.

    The walk over the loaded scopes is the one ``load_data`` used to describe
    itself, and the source digests are the ones it computed, so the rows
    written here and the document it left cannot name a different set of inputs
    nor disagree on their bytes. The same walk fills the inputs of the seal:
    provider, request, path, digest, size and licence of every loaded record.
    A record read from a product of the run (:func:`is_run_product`) keeps its
    provenance row but is no input of the seal.
    """
    if ctx.sim_id is None:
        return

    import numpy as np

    known_digests = _digests_the_load_already_computed(ctx)
    workspace_root = getattr(getattr(ctx, "setup", None), "workspace", None)
    anchor = getattr(workspace_root, "root", None)
    project_root = getattr(workspace_root, "project_root", None)
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
            digest = digest or sha256_file_or_none(source_path)
            store.write_provenance(
                ctx.sim_id,
                variable=label,
                source_ref=str(getattr(rec, "source", "")),
                data=arr,
                source_type="data_manager",
                source_sha256=digest,
                loader_name=item.loader_name,
                loader_version="v1",
                period_start=getattr(rec, "date_start", None),
                period_end=getattr(rec, "date_end", None),
            )
            for input_path, provider in _input_files(item, source_path):
                if is_run_product(input_path, project_root):
                    continue
                input_digest = (
                    digest
                    if input_path == source_path
                    else known_digests.get(str(input_path)) or sha256_file_or_none(input_path)
                )
                store.record_input(
                    ctx.sim_id,
                    loaded_input_entry(
                        item,
                        source_path=input_path,
                        sha256=input_digest,
                        anchor=anchor,
                        provider=provider,
                    ),
                )
            written += 1
        except Exception as exc:
            prefix = (
                "Provenance failed for" if item.kind == "point" else "Provenance failed for field"
            )
            raise PipelineError(f"{prefix} {label}") from exc

    if written:
        logger.debug("Wrote %d provenance records for sim %s", written, ctx.sim_id)


def _input_files(item: LoadedRecord, source_path: Path | None) -> list[tuple[Path, str | None]]:
    """Return the files one record was read from, each with its provider when it says one.

    A record built from files it does not point at lists them in its
    metadata (:data:`~hydromodpy.data.contracts.spatial_field.INPUT_FILES_KEY`):
    the mapped network is rasterised in the scratch, its inputs are the files
    of its sources. Any other record was read from its own source path.
    """
    metadata = getattr(item.record, "metadata", None)
    listed = metadata.get(INPUT_FILES_KEY) if isinstance(metadata, dict) else None
    if listed:
        return [(Path(str(entry["path"])), str(entry["provider"])) for entry in listed]
    return [] if source_path is None else [(source_path, None)]


def loaded_input_entry(
    item: LoadedRecord,
    *,
    source_path: Path | None,
    sha256: str | None,
    anchor: Path | str | None,
    provider: str | None = None,
) -> InputEntry:
    """Return the ``inputs.json`` entry of one file a loaded record was read from.

    The provider is *provider*, else the source slug of the record; its
    licence comes from the registry of sources, or from the sidecar of the
    file for a user file. The request is what the record covers: its station,
    its period, its box. The path is written relative to the workspace when
    the file sits under it.
    """
    rec = item.record
    source = provider or str(getattr(rec, "source", "") or "")
    request: dict[str, Any] = {}
    station = getattr(rec, "station_id", None)
    if station not in (None, ""):
        request["station"] = str(station)
    start, end = getattr(rec, "date_start", None), getattr(rec, "date_end", None)
    if start is not None or end is not None:
        request["period"] = [_iso_or_none(start), _iso_or_none(end)]
    bbox = getattr(rec, "bbox", None)
    if bbox is not None:
        request["bbox"] = [float(value) for value in bbox]
    if source == "custom" and source_path is not None:
        licence = input_licence(source_path).spdx
    else:
        licence = licence_for_source(source).spdx
    exists = source_path is not None and source_path.exists()
    return InputEntry(
        variable=f"{item.scope}:{item.variable}",
        provider=source or "unknown",
        request=request,
        fetched_at=(
            datetime.fromtimestamp(source_path.stat().st_mtime, tz=UTC) if exists else None
        ),
        path=_portable_path(source_path, anchor),
        sha256=sha256,
        bytes=path_size_bytes(source_path) if exists else None,
        license=licence,
    )


def _iso_or_none(value: Any) -> str | None:
    isoformat = getattr(value, "isoformat", None)
    return None if value is None else (isoformat() if callable(isoformat) else str(value))


def _portable_path(source_path: Path | None, anchor: Path | str | None) -> str:
    """The location of the bytes, relative to the workspace when it holds them."""
    if source_path is None:
        return ""
    if anchor is None:
        return str(source_path)
    try:
        return encode_workspace_path(Path(anchor), source_path)
    except ValueError:
        return str(source_path)


# Gridded forcing families reduced to a watershed-mean station series at
# persist time. The catchment discharge derivation reads runoff back from
# Zarr forcing/ when no stream network routes it.
_WATERSHED_MEAN_FORCINGS = frozenset({"runoff", "recharge"})


def _watershed_mean_series(load_result: object):
    """Reduce a gridded forcing family to one tz-naive watershed-mean series.

    None when the reduction has nothing to reduce. Its refusals, such as a day
    without any valid pixel, propagate and stop the run.
    """
    import pandas as pd

    from hydromodpy.spatial.forcing.cells import spatial_mean_from_fields

    series = spatial_mean_from_fields(load_result)
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
                    written += 1
                except Exception:
                    logger.debug("Failed to persist geology forcing")

                # The fractions the solvers map K, Sy and Ss with, not a second
                # sampling: an error here is the solver's error, never swallowed.
                cell_mesh = getattr(getattr(ctx, "setup", None), "cell_mesh", None)
                if cell_mesh is not None:
                    fractions = zone_fractions(cell_mesh, obj)
                    for zone_key, frac_array in fractions.by_zone().items():
                        safe_key = zone_key.replace("/", "_").replace(" ", "_")
                        sz.write_forcing_field(
                            f"geology_frac_{safe_key}",
                            np.asarray(frac_array, dtype="float64"),
                            unit="fraction",
                            source=f"geology:{zone_key}",
                        )
                    written += 1
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
                            CATCHMENT,
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
                    "available_water_capacity": float(ru_mm[j]),
                    "basin_weight": float(columns.basin_weight[j]),
                    "year": int(budget.years[i]),
                    "days": int(budget.days[i]),
                    "precipitation": float(budget.precipitation[i, j]),
                    "etp": float(budget.etp[i, j]),
                    "etr": float(budget.etr[i, j]),
                    "residual_etp": float(budget.residual_etp[i, j]),
                    "recharge": float(budget.recharge[i, j]),
                    "runoff": float(budget.runoff[i, j]),
                    "runoff_cn": float(budget.runoff_cn[i, j]),
                    "soil_storage_change": float(budget.soil_storage_change[i, j]),
                    "transit_storage_change": float(budget.transit_storage_change[i, j]),
                    "cn_storage_change": float(budget.cn_storage_change[i, j]),
                    "lag_storage_change": float(budget.lag_storage_change[i, j]),
                    "balance_residual": float(budget.residual[i, j]),
                    "unit": "mm",
                }
            )

    basin_ru_mm = float(np.sum(ru_mm * columns.basin_weight))
    for i in range(n_years):
        rows.append(
            {
                "column_id": CATCHMENT,
                "cell_index": None,
                "class_index": None,
                "x": None,
                "y": None,
                "available_water_capacity": basin_ru_mm,
                "basin_weight": 1.0,
                "year": int(budget.years[i]),
                "days": int(budget.days[i]),
                "precipitation": float(budget.basin("precipitation")[i]),
                "etp": float(budget.basin("etp")[i]),
                "etr": float(budget.basin("etr")[i]),
                "residual_etp": float(budget.basin("residual_etp")[i]),
                "recharge": float(budget.basin("recharge")[i]),
                "runoff": float(budget.basin("runoff")[i]),
                "runoff_cn": float(budget.basin("runoff_cn")[i]),
                "soil_storage_change": float(budget.basin("soil_storage_change")[i]),
                "transit_storage_change": float(budget.basin("transit_storage_change")[i]),
                "cn_storage_change": float(budget.basin("cn_storage_change")[i]),
                "lag_storage_change": float(budget.basin("lag_storage_change")[i]),
                "balance_residual": float(budget.basin("residual")[i]),
                "unit": "mm",
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
    "loaded_input_entry",
)
