"""The ``.zenodo.json`` of a published copy, rendered from the seal.

Why
---
Zenodo reads one JSON file at the root of an upload to fill the deposit form:
title, creators, licence, keywords, version and the identifiers the record is
related to. A published copy of a run already carries every one of those facts
in its seal or in the ``[publication]`` table of the project, so the file is a
view of the seal, written beside the RO-Crate and never inventoried by the
seal itself.

Format
------
The file follows the Zenodo deposit metadata: ``upload_type`` is ``dataset``,
``creators`` is a list of names, and ``related_identifiers`` names the run the
copy derives from, its parent and the run a replay read. A fact the seal does
not carry is left out rather than invented.
"""

from __future__ import annotations

from typing import Any, Final

from hydromodpy.results.publication import PublicationConfig
from hydromodpy.results.record.manifest import RunSeal

ZENODO_UPLOAD_TYPE: Final[str] = "dataset"
"""What a published run is to Zenodo."""

_KEYWORD: Final[str] = "HydroModPy"


def zenodo_metadata(seal: RunSeal, record: PublicationConfig | None = None) -> dict[str, Any]:
    """Return the Zenodo deposit metadata of one sealed run.

    *record* is the ``[publication]`` table of the project. Its creators and its
    licence are written when it declares them; the licence of the run, read
    from the inputs it consumed, is the fallback.
    """
    run = seal.run
    metadata: dict[str, Any] = {
        "upload_type": ZENODO_UPLOAD_TYPE,
        "title": run.name,
        "description": _description(seal),
        "version": str(run.version),
        "keywords": _keywords(seal),
    }
    creators = [] if record is None else [{"name": name} for name in record.creators]
    if creators:
        metadata["creators"] = creators
    licence = (record.license if record is not None else None) or run.license
    if licence:
        metadata["license"] = licence
    identifiers = _related_identifiers(seal)
    if identifiers:
        metadata["related_identifiers"] = identifiers
    return metadata


def _description(seal: RunSeal) -> str:
    """Return what the run says of itself, or one sentence naming it."""
    run = seal.run
    for candidate in (run.description, run.scientific_objective):
        if candidate:
            return candidate
    return f"Run {run.name} of project {run.project}."


def _keywords(seal: RunSeal) -> list[str]:
    """Return the words that name the run, in a stable order, each once."""
    run = seal.run
    words = [_KEYWORD, run.project, run.case_id, run.solver, seal.identity.site]
    seen: list[str] = []
    for word in words:
        if word and word not in seen:
            seen.append(word)
    return seen


def _related_identifiers(seal: RunSeal) -> list[dict[str, str]]:
    """Return the records this run is related to: its DOI, its parent, its source."""
    run = seal.run
    lineage = seal.lineage
    pairs: list[tuple[str, str, str]] = []
    if run.doi:
        pairs.append((run.doi, "isIdenticalTo", "doi"))
    if lineage.parent_sim_id:
        pairs.append((lineage.parent_sim_id, "isDerivedFrom", "other"))
    if lineage.replay is not None:
        pairs.append((lineage.replay.of, "isDerivedFrom", "other"))
    identifiers: list[dict[str, str]] = []
    seen: set[str] = set()
    for identifier, relation, scheme in pairs:
        if identifier in seen:
            continue
        seen.add(identifier)
        identifiers.append({"identifier": identifier, "relation": relation, "scheme": scheme})
    return identifiers


__all__ = ["ZENODO_UPLOAD_TYPE", "zenodo_metadata"]
