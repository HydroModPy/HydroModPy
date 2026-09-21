"""Shipped examples: the catalog, the blob cache and the workspace install.

``hmp example`` drops one documented example into a scaffolded workspace. Three
modules carry it, and nothing is re-exported here so each name keeps one home:

- ``manifest.py`` -- ``catalog.toml``, read from the wheel, no network;
- ``blobs.py`` -- the content-addressed download cache;
- ``install.py`` -- writing an example's files into a workspace;
- ``generate.py`` -- the whitelist and the generator behind
  ``hmp dev examples manifest``, which writes ``catalog.toml``.
"""

from __future__ import annotations
