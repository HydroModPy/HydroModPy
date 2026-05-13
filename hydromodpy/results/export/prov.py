"""W3C PROV-O JSON-LD lineage for HydroModPy simulations.

The exporter walks the catalog graph ``simulation -> tracked_files -> provenance``
and emits a PROV-O document (https://www.w3.org/TR/prov-o/) that maps:

- the simulation itself onto a ``prov:Activity`` (a ``CreateAction`` for
  schema.org compatibility),
- every input file onto a ``prov:Entity`` ``used`` by the activity,
- every fetch / loader as an upstream ``prov:Activity`` (``wasGeneratedBy``)
  that produced the input,
- every output asset onto a ``prov:Entity`` ``wasGeneratedBy`` the
  simulation activity.

The same payload is embedded by the RO-Crate exporter under ``@graph``
without modification, so consumers can run a single ``json.load`` and
walk either tree.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.results.export.context import (
    FairExportContext,
    _is_missing,
    build_context,
    to_json,
)

PROV_CONTEXT = {
    "prov": "http://www.w3.org/ns/prov#",
    "schema": "http://schema.org/",
    "hydromodpy": "https://hydromodpy-docs.readthedocs.io/schema#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
}


def _activity_id(sim_id: str) -> str:
    return f"#action/simulation"  # noqa: F541 - intentional anchor for RO-Crate cross-refs


def _entity_id(role: str, idx: int, name: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in name)
    return f"#entity/input/{role}/{idx}/{safe}" if safe else f"#entity/input/{role}/{idx}"


def _output_id(asset_key: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in asset_key)
    return f"#entity/output/{safe}"


def _fetch_activity_id(role: str, idx: int) -> str:
    return f"#action/fetch/{role}/{idx}"


def build_prov_document(context: FairExportContext) -> dict[str, Any]:
    """Return both the create-action node and the supporting activities.

    The output dict has two keys:

    - ``createAction``: schema.org ``CreateAction`` node for the run.
    - ``activities``: list of upstream nodes (input entities, fetch
      activities, output entities, hydromodpy/prov annotations).
    """
    sim_id = context.sim_id
    sim_row = context.sim_row
    runs_env = context.runs_env

    action: dict[str, Any] = {
        "@id": _activity_id(sim_id),
        "@type": ["CreateAction", "prov:Activity"],
        "name": f"HydroModPy simulation {sim_id}",
        "instrument": [{"@id": "#software/hydromodpy"}],
        "object": [],
        "result": [],
    }
    if context.solver_name:
        action["instrument"].append({"@id": f"#software/{context.solver_name}"})

    started = sim_row.get("started_at")
    ended = sim_row.get("ended_at")
    if not _is_missing(started):
        action["startTime"] = str(started)
        action["prov:startedAtTime"] = str(started)
    if not _is_missing(ended):
        action["endTime"] = str(ended)
        action["prov:endedAtTime"] = str(ended)
    if runs_env.get("hostname") and not _is_missing(runs_env.get("hostname")):
        action["hydromodpy:hostname"] = str(runs_env["hostname"])
    if runs_env.get("git_commit") and not _is_missing(runs_env.get("git_commit")):
        action["hydromodpy:gitCommit"] = str(runs_env["git_commit"])
    if not _is_missing(runs_env.get("rng_seed")):
        action["hydromodpy:rngSeed"] = int(runs_env["rng_seed"])

    activities: list[dict[str, Any]] = []
    for idx, entry in enumerate(context.inputs):
        eid = _entity_id(entry.role, idx, Path(entry.original_path).name or entry.role)
        entity: dict[str, Any] = {
            "@id": eid,
            "@type": ["prov:Entity", "File"],
            "name": Path(entry.original_path).name or entry.role,
            "hydromodpy:role": entry.role,
            "hydromodpy:category": entry.category,
        }
        if entry.sha256:
            entity["sha256"] = entry.sha256
        if entry.size_bytes:
            entity["contentSize"] = int(entry.size_bytes)
        if entry.source_ref:
            entity["url"] = entry.source_ref
        if entry.license:
            entity["license"] = entry.license

        if entry.loader_name or entry.source_type or entry.fetched_at:
            fetch_id = _fetch_activity_id(entry.role, idx)
            fetch_node: dict[str, Any] = {
                "@id": fetch_id,
                "@type": ["prov:Activity", "Action"],
                "name": f"Fetch {entry.role}",
                "hydromodpy:loaderName": entry.loader_name,
                "hydromodpy:sourceType": entry.source_type,
            }
            if entry.fetched_at:
                fetch_node["endTime"] = entry.fetched_at
                fetch_node["prov:endedAtTime"] = entry.fetched_at
            if entry.data_provider:
                fetch_node["agent"] = {
                    "@type": "Organization",
                    "name": entry.data_provider,
                }
            activities.append(fetch_node)
            entity["prov:wasGeneratedBy"] = {"@id": fetch_id}

        activities.append(entity)
        action["object"].append({"@id": eid})
        action.setdefault("prov:used", []).append({"@id": eid})

    for asset in context.assets:
        oid = _output_id(asset.key)
        output_entity: dict[str, Any] = {
            "@id": oid,
            "@type": ["prov:Entity", "File"],
            "name": asset.relative_path,
            "encodingFormat": asset.media_type,
            "hydromodpy:assetKey": asset.key,
            "prov:wasGeneratedBy": {"@id": _activity_id(sim_id)},
        }
        if asset.sha256:
            output_entity["sha256"] = asset.sha256
        if asset.size_bytes is not None:
            output_entity["contentSize"] = int(asset.size_bytes)
        activities.append(output_entity)
        action["result"].append({"@id": oid})

    return {"createAction": action, "activities": activities}


def serialise_prov(context: FairExportContext) -> dict[str, Any]:
    """Return a standalone JSON-LD PROV-O document for *context*."""
    parts = build_prov_document(context)
    return {
        "@context": PROV_CONTEXT,
        "@graph": [parts["createAction"], *parts["activities"]],
    }


def write_prov(
    catalog: Any,
    sim_id: str,
    output_path: Path | str,
    *,
    context: FairExportContext | None = None,
) -> Path:
    """Materialise a JSON-LD PROV-O document for *sim_id*."""
    ctx = context or build_context(catalog, sim_id)
    payload = serialise_prov(ctx)
    out = Path(output_path)
    if out.is_dir() or out.suffix == "":
        out = out / "prov.jsonld"
    return to_json(payload, out)


__all__ = [
    "PROV_CONTEXT",
    "build_prov_document",
    "serialise_prov",
    "write_prov",
]
