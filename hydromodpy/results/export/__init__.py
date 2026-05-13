"""FAIR export formats for HydroModPy simulations.

Modules
-------
- :mod:`hydromodpy.results.export.rocrate`: RO-Crate v1.1 JSON-LD bundle.
- :mod:`hydromodpy.results.export.stac`: STAC Item 1.0 geospatial catalog entry.
- :mod:`hydromodpy.results.export.prov`: W3C PROV-O lineage embedded as JSON-LD.

All modules are import-light: external validators (``pystac``,
``stac-validator``) are optional and only loaded when explicitly
requested. The serialized payloads are always plain Python ``dict``
objects so callers can write them as JSON without third-party
dependencies.
"""

from __future__ import annotations

from hydromodpy.results.export.context import FairExportContext, build_context
from hydromodpy.results.export.prov import build_prov_document
from hydromodpy.results.export.rocrate import build_ro_crate, write_ro_crate
from hydromodpy.results.export.stac import build_stac_item, write_stac_item

__all__ = [
    "FairExportContext",
    "build_context",
    "build_prov_document",
    "build_ro_crate",
    "build_stac_item",
    "write_ro_crate",
    "write_stac_item",
]
