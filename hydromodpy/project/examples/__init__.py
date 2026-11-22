"""Shipped examples: the catalog, the blob cache and the workspace install.

``hmp example`` drops documented examples into a scaffolded workspace. Five
modules carry it, and nothing is re-exported here so each name keeps one home:

- ``manifest.py`` -- ``catalog.toml``, read from the wheel, no network;
- ``blobs.py`` -- the content-addressed download cache;
- ``install.py`` -- writing the files of one or more examples into a workspace;
- ``rows.py`` -- the plain rows ``hmp example list`` and ``show`` print;
- ``generate.py`` -- the discovery of ``examples/projects/`` and the generator behind
  ``python -m tools.dev examples manifest``, which writes ``catalog.toml``.
"""
