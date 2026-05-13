"""RO-Crate v1.1 metadata generator (https://www.researchobject.org/ro-crate/1.1/).

Emits a JSON-LD ``ro-crate-metadata.json`` describing one simulation,
including its inputs, outputs, lockfile, solver binary fingerprint and
license. The embedded PROV-O ``CreateAction`` is produced by
:mod:`hydromodpy.results.export.prov`, so the same payload can be re-used
when serialised on its own.

The generated graph stays self-contained: every ``hasPart`` / ``object`` /
``result`` reference resolves to a sibling entity in the same ``@graph``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hydromodpy.results.export.context import (
    AssetEntry,
    FairExportContext,
    _is_missing,
    build_context,
    to_json,
)
from hydromodpy.results.export.prov import build_prov_document

RO_CRATE_CONFORMS = "https://w3id.org/ro/crate/1.1"
RO_CRATE_CONTEXT = "https://w3id.org/ro/crate/1.1/context"
RO_CRATE_METADATA_FILENAME = "ro-crate-metadata.json"


def _person_id(name: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in name)
    return f"#person/{safe}"


def _asset_node(asset: AssetEntry, sim_id: str) -> dict[str, Any]:
    node: dict[str, Any] = {
        "@id": asset.relative_path,
        "@type": "File",
        "name": asset.relative_path.rsplit("/", 1)[-1],
        "encodingFormat": asset.media_type,
        "hydromodpy:assetKey": asset.key,
        "hydromodpy:simId": sim_id,
    }
    if asset.sha256:
        node["sha256"] = asset.sha256
    if asset.size_bytes is not None:
        node["contentSize"] = int(asset.size_bytes)
    if asset.description:
        node["description"] = asset.description
    if asset.roles:
        node["hydromodpy:roles"] = list(asset.roles)
    return node


def _input_node(idx: int, entry: Any) -> dict[str, Any]:
    base_id = f"inputs/{entry.role}/{idx}/{Path(entry.original_path).name or 'file'}"
    node: dict[str, Any] = {
        "@id": base_id,
        "@type": "File",
        "name": Path(entry.original_path).name or entry.role,
        "encodingFormat": "application/octet-stream",
        "hydromodpy:role": entry.role,
        "hydromodpy:category": entry.category,
    }
    if entry.sha256:
        node["sha256"] = entry.sha256
    if entry.size_bytes:
        node["contentSize"] = int(entry.size_bytes)
    if entry.source_ref:
        node["url"] = entry.source_ref
    if entry.source_type:
        node["hydromodpy:sourceType"] = entry.source_type
    if entry.loader_name:
        node["hydromodpy:loader"] = entry.loader_name
    if entry.license:
        node["license"] = entry.license
    if entry.data_provider:
        node["publisher"] = {"@type": "Organization", "name": entry.data_provider}
    if entry.fetched_at:
        node["dateCreated"] = entry.fetched_at
    return node


def _software_nodes(context: FairExportContext) -> list[dict[str, Any]]:
    hmp_node: dict[str, Any] = {
        "@id": "#software/hydromodpy",
        "@type": "SoftwareApplication",
        "name": "HydroModPy",
        "softwareVersion": context.hydromodpy_version,
        "url": "https://hydromodpy-docs.readthedocs.io/",
        "codeRepository": "https://github.com/HydroModPy/HydroModPy",
    }
    git_commit = context.runs_env.get("git_commit")
    if git_commit:
        hmp_node["softwareSourceCode"] = str(git_commit)
    nodes = [hmp_node]
    if context.solver_name:
        solver_node: dict[str, Any] = {
            "@id": f"#software/{context.solver_name}",
            "@type": "SoftwareApplication",
            "name": context.solver_name,
        }
        if context.solver_version:
            solver_node["softwareVersion"] = context.solver_version
        if context.solver_binary_sha256:
            solver_node["sha256"] = context.solver_binary_sha256
        nodes.append(solver_node)
    return nodes


def build_ro_crate(context: FairExportContext) -> dict[str, Any]:
    """Return the RO-Crate JSON-LD payload as a plain ``dict``."""
    metadata_descriptor: dict[str, Any] = {
        "@id": RO_CRATE_METADATA_FILENAME,
        "@type": "CreativeWork",
        "conformsTo": {"@id": RO_CRATE_CONFORMS},
        "about": {"@id": "./"},
    }

    sim_row = context.sim_row

    def _safe(key: str) -> Any:
        val = sim_row.get(key)
        if _is_missing(val):
            return None
        return val

    name = _safe("name") or context.sim_id
    description = _safe("description") or _safe("notes") or ""

    dataset_node: dict[str, Any] = {
        "@id": "./",
        "@type": "Dataset",
        "name": str(name),
        "description": str(description),
        "identifier": context.sim_id,
        "datePublished": context.generated_at,
        "license": {"@id": context.license_url},
        "hydromodpy:project": _safe("project"),
        "hydromodpy:solverId": (
            int(_safe("solver_id")) if _safe("solver_id") is not None else None
        ),
        "hydromodpy:simId": context.sim_id,
        "hasPart": [{"@id": asset.relative_path} for asset in context.assets],
        "wasGeneratedBy": {"@id": "#action/simulation"},
    }
    doi = _safe("doi")
    if doi:
        dataset_node["sameAs"] = str(doi)
    if context.period_start:
        dataset_node["temporalCoverage"] = (
            f"{context.period_start}/{context.period_end}"
            if context.period_end
            else context.period_start
        )
    place_nodes: list[dict[str, Any]] = []
    if context.bbox is not None:
        xmin, ymin, xmax, ymax = context.bbox
        geo_id = "#geo/bbox"
        place_id = "#place/bbox"
        place_nodes = [
            {
                "@id": geo_id,
                "@type": "GeoShape",
                "box": f"{ymin} {xmin} {ymax} {xmax}",
            },
            {
                "@id": place_id,
                "@type": "Place",
                "geo": {"@id": geo_id},
            },
        ]
        dataset_node["spatialCoverage"] = {"@id": place_id}

    inputs_nodes = [_input_node(idx, entry) for idx, entry in enumerate(context.inputs)]
    asset_nodes = [_asset_node(asset, context.sim_id) for asset in context.assets]
    software_nodes = _software_nodes(context)

    creator_nodes: list[dict[str, Any]] = []
    creator_ref: dict[str, Any] | None = None
    if context.creator_name:
        cid = _person_id(context.creator_name)
        creator_node: dict[str, Any] = {
            "@id": cid,
            "@type": "Person",
            "name": context.creator_name,
        }
        if context.creator_email:
            creator_node["email"] = context.creator_email
        creator_nodes.append(creator_node)
        creator_ref = {"@id": cid}
        dataset_node["creator"] = [{"@id": cid}]

    prov_doc = build_prov_document(context)
    action_node = prov_doc["createAction"]
    activities = prov_doc["activities"]

    graph: list[dict[str, Any]] = [metadata_descriptor, dataset_node]
    graph.extend(asset_nodes)
    graph.extend(inputs_nodes)
    graph.extend(software_nodes)
    graph.extend(creator_nodes)
    graph.extend(place_nodes)
    if creator_ref is not None:
        action_node = {**action_node, "agent": creator_ref}
    graph.append(action_node)
    graph.extend(activities)

    return {
        "@context": [
            RO_CRATE_CONTEXT,
            {
                "hydromodpy": "https://hydromodpy-docs.readthedocs.io/schema#",
                "prov": "http://www.w3.org/ns/prov#",
                "sha256": "https://www.iana.org/assignments/hashes/sha-256",
            },
        ],
        "@graph": graph,
    }


def write_ro_crate(
    catalog: Any,
    sim_id: str,
    output_path: Path | str,
    *,
    context: FairExportContext | None = None,
) -> Path:
    """Render the RO-Crate for *sim_id* and write it to *output_path*.

    *output_path* may point at a directory (the file is then named
    ``ro-crate-metadata.json``) or at an explicit ``.json`` file.
    """
    ctx = context or build_context(catalog, sim_id)
    crate = build_ro_crate(ctx)
    out = Path(output_path)
    if out.is_dir() or out.suffix == "":
        out = out / RO_CRATE_METADATA_FILENAME
    return to_json(crate, out)


def write_ro_crate_to_staging(context: FairExportContext, staging: Path) -> Path:
    """Write the RO-Crate alongside an ``.hmp`` staging directory."""
    crate = build_ro_crate(context)
    return to_json(crate, staging / RO_CRATE_METADATA_FILENAME)


def loads(payload: str) -> dict[str, Any]:
    """Parse a serialised RO-Crate string back to a dict (test helper)."""
    return json.loads(payload)


__all__ = [
    "RO_CRATE_CONFORMS",
    "RO_CRATE_CONTEXT",
    "RO_CRATE_METADATA_FILENAME",
    "build_ro_crate",
    "loads",
    "write_ro_crate",
    "write_ro_crate_to_staging",
]
