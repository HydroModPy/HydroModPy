"""The ``mesh_engine`` column of the index is the engine the seal names.

A configuration without a ``[mesh]`` section ran on the default engine of its
release; the frozen ``config.toml`` then has no ``mesh`` key, but the seal
(``geometry.mesh_engine``) says which engine built the mesh. The index reads
the seal, so ``hmp catalog ls`` and every listing show it.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.results.catalog import Catalog, rebuild_index
from tests._helpers.sealed_runs import make_project, seal_run


def test_a_config_without_a_mesh_section_lists_the_engine_of_its_seal(tmp_path: Path) -> None:
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
