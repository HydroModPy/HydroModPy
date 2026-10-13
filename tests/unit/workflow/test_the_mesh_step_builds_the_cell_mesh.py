"""The cell mesh is built in the run's CRS: the geographic one, else the DEM support one."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.core.exceptions import MeshError
from hydromodpy.workflow.steps.mesh_inputs import mesh_crs_wkt


def test_the_cell_mesh_carries_the_geographic_crs() -> None:
    setup = SimpleNamespace(geographic=SimpleNamespace(crs_project="EPSG:2154"))

    assert "Lambert" in mesh_crs_wkt(setup)


def test_the_dem_support_gives_the_crs_when_the_geographic_setup_has_none() -> None:
    surface = SimpleNamespace(support=SimpleNamespace(crs="EPSG:2154"))
    setup = SimpleNamespace(
        geographic=SimpleNamespace(), domain=SimpleNamespace(surface_topo=surface)
    )

    assert "Lambert" in mesh_crs_wkt(setup)


def test_a_run_without_a_crs_cannot_build_a_cell_mesh() -> None:
    setup = SimpleNamespace(geographic=SimpleNamespace(), domain=None)

    with pytest.raises(MeshError, match="needs the run's CRS"):
        mesh_crs_wkt(setup)
