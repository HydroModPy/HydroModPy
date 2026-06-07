"""WP14 - MODFLOW 6 uses DISV for every grid; native DIS belongs to NWT only.

Option B of the DISV-only decision: MF6 builds ``ModflowGwfdisv`` even for a
regular structured mesh, so there is a single discretization code path. The
``to_dis_kwargs`` export stays alive because the NWT backend consumes it. The
dead ``describe_grid`` / ``DisDescriptor`` scaffolding was removed in WP12.
"""

from __future__ import annotations

import flopy
import numpy as np
import pytest

from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh


def _structured_mesh() -> SolverMesh:
    return SolverMesh.from_structured_arrays(
        nrow=2,
        ncol=3,
        top=np.full((2, 3), 10.0),
        botm=np.zeros((1, 2, 3)),
        dx=25.0,
        dy=25.0,
        xoff=300000.0,
        yoff=6800000.0,
    )


def _unstructured_mesh() -> SolverMesh:
    vertices = np.array(
        [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [2.0, 0.0], [2.0, 1.0]],
        dtype=float,
    )
    connectivity = np.array([[0, 1, 2], [0, 2, 3], [1, 4, 2], [4, 5, 2]], dtype=int)
    planar = HydroMesh(
        vertices=vertices,
        cell_blocks=(CellBlock(CellType.TRIANGLE, connectivity),),
    )
    return SolverMesh(
        planar_mesh=planar,
        top=np.full(4, 10.0),
        botm=np.zeros((1, 4)),
        inactive_mask=np.zeros((1, 4), dtype=bool),
    )


def _build_gwf_disv(tmp_path, mesh: SolverMesh):
    sim = flopy.mf6.MFSimulation(sim_name="sim", sim_ws=str(tmp_path), exe_name="mf6")
    flopy.mf6.ModflowTdis(sim, nper=1, perioddata=[(1.0, 1, 1.0)], time_units="SECONDS")
    gwf = flopy.mf6.ModflowGwf(sim, modelname="flow")
    ims = flopy.mf6.ModflowIms(sim, filename="flow.ims")
    sim.register_ims_package(ims, [gwf.name])
    # Mirror build.py: DISV with absolute vertices and origin 0.
    return flopy.mf6.ModflowGwfdisv(
        gwf,
        nlay=mesh.nlay,
        **mesh.to_disv_kwargs(),
        idomain=mesh.idomain(),
        xorigin=0.0,
        yorigin=0.0,
        length_units="METERS",
    )


def test_mf6_structured_mesh_uses_disv_discretization(tmp_path) -> None:
    mesh = _structured_mesh()
    assert mesh.is_structured is True

    disv = _build_gwf_disv(tmp_path, mesh)
    assert type(disv).__name__ == "ModflowGwfdisv"
    assert int(disv.ncpl.get_data()) == 6
    assert int(disv.nlay.get_data()) == 1
    assert int(disv.nvert.get_data()) == 12
    # Origin is 0 (vertices already absolute); centroids stay at absolute coords.
    assert float(disv.xorigin.get_data()) == pytest.approx(0.0)
    centers = np.asarray(disv.parent.modelgrid.xcellcenters).ravel()
    assert centers.min() > 300000.0


def test_to_dis_kwargs_geometry_exact_for_structured_mesh() -> None:
    mesh = _structured_mesh()
    kwargs = mesh.to_dis_kwargs()
    assert kwargs["nlay"] == 1
    assert kwargs["nrow"] == 2
    assert kwargs["ncol"] == 3
    assert np.asarray(kwargs["delr"]).tolist() == pytest.approx([25.0, 25.0, 25.0])
    assert np.asarray(kwargs["delc"]).tolist() == pytest.approx([25.0, 25.0])
    assert np.asarray(kwargs["top"]).shape == (2, 3)
    assert np.all(np.asarray(kwargs["top"]) == 10.0)
    assert np.asarray(kwargs["botm"]).shape == (1, 2, 3)
    assert np.all(np.asarray(kwargs["botm"]) == 0.0)

    with pytest.raises(ValueError, match="structured"):
        _unstructured_mesh().to_dis_kwargs()


def test_mf6_unstructured_mesh_still_uses_disv(tmp_path) -> None:
    mesh = _unstructured_mesh()
    assert mesh.is_structured is False
    disv = _build_gwf_disv(tmp_path, mesh)
    assert type(disv).__name__ == "ModflowGwfdisv"
    assert int(disv.ncpl.get_data()) == 4
    with pytest.raises(ValueError, match="structured"):
        mesh.to_dis_kwargs()


def test_grid_mapping_descriptors_are_removed() -> None:
    with pytest.raises(ModuleNotFoundError):
        import hydromodpy.solver.modflow_grid.grid_mapping  # noqa: F401
    with pytest.raises(ImportError):
        from hydromodpy.solver.modflow_grid import describe_grid  # noqa: F401
