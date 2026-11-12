"""Edge sets of a Boussinesq mesh by support label, on a committed triangle bundle.

A label is a side id, ``stream``, ``river`` or ``boundary:<name>``. An unknown label has no edge.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.mesh.io.bundle import load_catchment_mesh_bundle
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh
from tests._helpers.mesh_cases import MESH_BUNDLES

pytestmark = pytest.mark.fast

BUNDLE = "hantush_recharge_mound_tri_conforming"


def bundle_mesh() -> BoussinesqMesh:
    return BoussinesqMesh.from_bundle(load_catchment_mesh_bundle(MESH_BUNDLES / BUNDLE))


def test_boundary_label_is_the_side_family() -> None:
    mesh = bundle_mesh()

    edges = mesh.edge_indices_for_label("boundary:west")

    assert edges.size > 0
    np.testing.assert_array_equal(edges, mesh.boundary_edge_indices_for_side("west_side"))


def test_unknown_label_has_no_edge() -> None:
    edges = bundle_mesh().edge_indices_for_label("not_a_support")

    assert edges.size == 0
    assert edges.dtype == np.int64


def test_refuses_an_unknown_side() -> None:
    with pytest.raises(ValueError, match="Unsupported side boundary id: up_side"):
        bundle_mesh().boundary_edge_indices_for_side("up_side")
