"""FAIR views of a sealed run or job directory, read from the directory alone.

:mod:`hydromodpy.results.export.rocrate` builds the one view the wheel ships,
the RO-Crate v1.1 JSON-LD bundle; :mod:`hydromodpy.results.export.prov` keeps
the PROV-O lineage it embeds. :mod:`hydromodpy.results.export.directory`
builds the export context from the seal and the documents beside it, never
from a workspace, the index or a ``sim_id``, and it is the only way a view
gets that context.

A view format outside the wheel registers itself as an export format, and
``hmp export <run> all --as <format>`` writes it. Import each name from the
module that defines it.

All modules are import-light: external validators (``pystac``,
``stac-validator``) are optional and only loaded when explicitly requested.
The serialized payloads are always plain Python ``dict`` objects so callers
can write them as JSON without third-party dependencies.
"""
