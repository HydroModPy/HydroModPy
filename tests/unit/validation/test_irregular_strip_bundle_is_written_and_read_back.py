"""The validation generator writes an irregular strip bundle that the bundle reader loads.

Gmsh draws from the system clock, so the mesh is not the same twice. The test checks that
Gmsh runs through the session helpers of ``validation_cases/shared/gmsh_session.py`` and that
the bundle it writes reads back.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.spatial.mesh.io.bundle import (
    load_catchment_mesh_bundle,
)
from validation_cases.shared.gmsh_irregular_strip import write_irregular_strip_bundle


def test_an_irregular_strip_bundle_reads_back(tmp_path: Path) -> None:
    pytest.importorskip("gmsh")

    bundle_dir = write_irregular_strip_bundle(
        tmp_path / "bundle",
        nx_seed=8,
        ny_seed=3,
        length_x_m=100.0,
        width_y_m=20.0,
        z_top_m=10.0,
        z_bottom_m=0.0,
        hydraulic_conductivity_m_s=1.0e-4,
        storage_coefficient=0.1,
    )
    bundle = load_catchment_mesh_bundle(bundle_dir)

    assert (bundle_dir / "mesh_2d.msh").is_file()
    assert len(bundle.cells) > 0
    assert len(bundle.nodes) > 0
    assert len(bundle.edges) > 0
