"""Irregular strip of triangles (m) drawn by Gmsh, and its history projected on a grid.

The bundle writer meshes a strip with Gmsh. The projection averages cell values
onto a structured grid, weighted by cell area (m2).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.mesh.io.bundle import load_catchment_mesh_bundle
from validation_cases.shared.gmsh_irregular_strip import (
    interpolate_bundle_history_to_structured_grids,
    write_irregular_strip_bundle,
)


def minimal_bundle(bundle_dir: Path) -> Path:
    # A 2 m x 1 m strip cut in four cells of 1, 3, 2 and 2 m2.
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "nodes.csv").write_text(
        "node_id,x,y\n0,0.0,0.0\n1,2.0,0.0\n2,2.0,1.0\n3,0.0,1.0\n", encoding="utf-8"
    )
    (bundle_dir / "cells.csv").write_text(
        "cell_id,centroid_x,centroid_y,area_m2\n"
        "0,0.25,0.25,1.0\n1,0.75,0.75,3.0\n2,1.25,0.25,2.0\n3,1.75,0.75,2.0\n",
        encoding="utf-8",
    )
    return bundle_dir


def test_bundle_reads_back(tmp_path):
    # Gmsh draws from the system clock, so the mesh differs from one run to the next.
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


def test_history_collapses_to_an_x_profile(tmp_path):
    history = np.array([[10.0, 18.0, 30.0, 34.0], [20.0, 28.0, 40.0, 44.0]])

    projected = interpolate_bundle_history_to_structured_grids(
        history,
        bundle_dir=minimal_bundle(tmp_path / "bundle"),
        nx=2,
        ny=3,
        collapse_y_to_x_profile=True,
    )

    # West column: (10 x 1 + 18 x 3) / 4 = 16 m. East column: (30 + 34) / 2 = 32 m.
    profiles = np.array([[16.0, 32.0], [26.0, 42.0]])
    assert projected.shape == (2, 3, 2)
    for row in range(3):
        np.testing.assert_allclose(projected[:, row, :], profiles)
    np.testing.assert_allclose(np.std(projected, axis=1), 0.0)
