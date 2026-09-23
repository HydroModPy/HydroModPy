"""FAIR export formats for HydroModPy simulations.

Modules
-------
- :mod:`hydromodpy.results.export.rocrate`: RO-Crate v1.1 JSON-LD bundle.
- :mod:`hydromodpy.results.export.stac`: STAC Item 1.0 geospatial catalog entry.
- :mod:`hydromodpy.results.export.prov`: W3C PROV-O lineage embedded as JSON-LD.
- :mod:`hydromodpy.results.export.directory`: the same views built from a
  sealed run or job directory alone, and written inside it.

All modules are import-light: external validators (``pystac``,
``stac-validator``) are optional and only loaded when explicitly
requested. The serialized payloads are always plain Python ``dict``
objects so callers can write them as JSON without third-party
dependencies.
"""

from __future__ import annotations

from hydromodpy.results.export.context import FairExportContext, build_context
from hydromodpy.results.export.directory import context_from_directory, write_views
from hydromodpy.results.export.prov import build_prov_document, write_prov_view
from hydromodpy.results.export.rocrate import (
    build_ro_crate,
    write_ro_crate,
    write_ro_crate_view,
)
from hydromodpy.results.export.stac import (
    build_stac_catalog,
    build_stac_collection,
    build_stac_item,
    write_stac_catalog,
    write_stac_collection,
    write_stac_item,
    write_stac_item_view,
)

__all__ = [
    "FairExportContext",
    "build_context",
    "context_from_directory",
    "build_prov_document",
    "build_ro_crate",
    "build_stac_catalog",
    "build_stac_collection",
    "build_stac_item",
    "write_prov_view",
    "write_ro_crate",
    "write_ro_crate_view",
    "write_stac_catalog",
    "write_stac_collection",
    "write_stac_item",
    "write_stac_item_view",
    "write_views",
]
