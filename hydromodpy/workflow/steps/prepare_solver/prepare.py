"""Concern 1 of PrepareSolverStep: persistence helpers.

Hosts the helpers that write inputs to disk before the solver runs:

- parameter writes via :func:`step_persist_params`
- mesh persistence via :func:`step_persist_mesh`
- geographic raster persistence via :func:`step_persist_geographic`
- provenance fingerprints and the loaded inputs of ``inputs.json`` via
  :func:`step_write_provenance`

The forcings are persisted by :mod:`~hydromodpy.workflow.steps.prepare_solver.forcings`.
The functions stay free-standing so notebook helpers and the orchestrator
prepared-run path keep importing them by name.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.core.exceptions import MeshError, PipelineError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.portable import encode_workspace_path
from hydromodpy.data.contracts.spatial_field import INPUT_FILES_KEY
from hydromodpy.results.manifest import InputEntry
from hydromodpy.results.storage.attempt import is_run_product
from hydromodpy.results.storage.digests import path_size_bytes
from hydromodpy.schema.sources import input_licence, licence_for_source
from hydromodpy.workflow.steps.data_description import (
    LoadedRecord,
    iter_loaded_records,
    read_data_description,
    record_source_path,
    sha256_file_or_none,
    source_digests,
)

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import WorkflowContext
    from hydromodpy.model.domain.domain import Domain
    from hydromodpy.results.catalog.protocol import SimulationStore

logger = get_logger(__name__)


def step_persist_params(
    store: SimulationStore,
    sim_id: str,
    profiles: Mapping[str, Any],
    *,
    domain: Domain | None = None,
) -> None:
    """Write the hydraulic parameter profiles of a ``Model`` into the catalog."""
    params: list[dict] = []

    if profiles:
        for pid, fp in profiles.items():
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
    from hydromodpy.catchment.preprocess.store_ingestion import persist_geographic_to_store

    if ctx.setup.geographic is None:
        return
    persist_geographic_to_store(ctx.setup.geographic, store, sim_id=sim_id)


# ---------------------------------------------------------------------------
# Provenance + forcings
# ---------------------------------------------------------------------------


def field_data_array(record: object) -> np.ndarray | None:
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
                arr = field_data_array(rec)
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
                    _loaded_input_entry(
                        item,
                        source_path=input_path,
                        sha256=input_digest,
                        anchor=anchor,
                        provider=provider,
                    ),
                )
            written += 1
        except Exception as exc:
            # Whatever a record raised, the run stops and names the record.
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
    the mapped network is rasterized in the scratch, its inputs are the files
    of its sources. Any other record was read from its own source path.
    """
    metadata = getattr(item.record, "metadata", None)
    listed = metadata.get(INPUT_FILES_KEY) if isinstance(metadata, dict) else None
    if listed:
        return [(Path(str(entry["path"])), str(entry["provider"])) for entry in listed]
    return [] if source_path is None else [(source_path, None)]


def _loaded_input_entry(
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
    if source in ("file", "custom") and source_path is not None:
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


__all__ = (
    "field_data_array",
    "step_persist_geographic",
    "step_persist_mesh",
    "step_persist_params",
    "step_write_provenance",
)
