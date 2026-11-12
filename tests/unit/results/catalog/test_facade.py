"""The catalog lists the mesh engine that the seal of each run states."""

from __future__ import annotations

from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from tests._helpers.sealed_runs import make_project, seal_run


# A configuration without a [mesh] section ran on the default engine of its release, so the
# frozen config.toml has no mesh key. The index reads the seal (geometry.mesh_engine) instead.
def test_a_config_without_a_mesh_section_lists_the_engine_of_its_seal(tmp_path):
    root = make_project(tmp_path / "demo")
    seal_run(root, "plain", mesh_engine="regular", config_text="[flow]\nK = 1e-5\n")
    seal_run(root, "cells", mesh_engine="voronoi", config_text='[mesh]\nengine = "voronoi"\n')

    rebuild_index(root)

    with Catalog(root) as catalog:
        listed = catalog.list_simulations()
        filtered = catalog.list_simulations(mesh_engine="regular")
    engines = dict(zip(listed["name"], listed["mesh_engine"], strict=True))
    assert engines == {"plain": "regular", "cells": "voronoi"}
    assert list(filtered["name"]) == ["plain"]
