"""The file names a generated view takes inside a run or a job directory.

A generated view restates, in a public vocabulary, facts a sealed directory
already holds: RO-Crate for a research-object reader, STAC for a geospatial
catalogue, PROV-O for a lineage graph. It is rendered from the seal and the
documents the seal hashes, so it can be rendered again at any time and must
say the same thing.

The names live here because both directory profiles use them and neither may
import the other: the run profile is declared in ``results`` and the job
profile in ``schema``. A view is written beside the seal, after it, and the
seal never inventories it, exactly like the annotations of a run.
"""

from __future__ import annotations

RO_CRATE_VIEW_FILENAME = "ro-crate-metadata.json"
"""RO-Crate 1.1 metadata. The name is fixed by the RO-Crate specification."""

STAC_ITEM_VIEW_FILENAME = "stac-item.json"
"""STAC 1.0 Item describing the directory as one catalogue entry."""

PROV_VIEW_FILENAME = "prov.jsonld"
"""W3C PROV-O lineage as a standalone JSON-LD document."""

VIEW_FILENAMES: dict[str, str] = {
    "rocrate": RO_CRATE_VIEW_FILENAME,
    "stac": STAC_ITEM_VIEW_FILENAME,
    "prov": PROV_VIEW_FILENAME,
}
"""Each view format, by the name ``hmp export <run> --format`` already uses."""

GENERATED_VIEWS: frozenset[str] = frozenset(VIEW_FILENAMES.values())
"""Every name a generated view may take at the top level of a directory."""


__all__ = [
    "GENERATED_VIEWS",
    "PROV_VIEW_FILENAME",
    "RO_CRATE_VIEW_FILENAME",
    "STAC_ITEM_VIEW_FILENAME",
    "VIEW_FILENAMES",
]
