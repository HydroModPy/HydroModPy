"""WP2 - the GWT DISV must share the GWF active domain (IDOMAIN).

MODFLOW 6 requires the GWF and GWT models in a GWF6-GWT6 exchange to have
identical active domains. ``SolverMesh.idomain`` is the single derivation used
by the GWF, PRT and GWT DISV packages.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import flopy
import numpy as np

from hydromodpy.physics.transport.transport import Transport
from hydromodpy.solver.modflow6.transport import Modflow6Transport
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh


def _mesh(top, botm, inactive_mask) -> SolverMesh:
    n_cells = np.asarray(top, dtype=float).reshape(-1).size
    vertices = np.zeros((2 * (n_cells + 1), 2), dtype=float)
    xs = np.arange(n_cells + 1, dtype=float)
    vertices[: n_cells + 1, 0] = xs
    vertices[n_cells + 1 :, 0] = xs
    vertices[n_cells + 1 :, 1] = 1.0
    connectivity = np.array(
        [[i, i + 1, n_cells + 2 + i, n_cells + 1 + i] for i in range(n_cells)], dtype=int
    )
    planar_mesh = HydroMesh(
        vertices=vertices,
        cell_blocks=(CellBlock(CellType.QUADRILATERAL, connectivity),),
    )
    return SolverMesh(
        planar_mesh=planar_mesh,
        top=np.asarray(top, dtype=float),
        botm=np.asarray(botm, dtype=float),
        inactive_mask=np.asarray(inactive_mask, dtype=bool),
    )


def test_solver_mesh_idomain_matches_active_mask_multilayer() -> None:
    mask = np.array([[False, False, True], [True, False, False]])
    mesh = _mesh(
        top=np.array([2.0, 2.0, 2.0]),
        botm=np.array([[1.0, 1.0, 1.0], [0.0, 0.0, 0.0]]),
        inactive_mask=mask,
    )
    idomain = mesh.idomain()
    assert idomain.tolist() == [[1, 1, 0], [0, 1, 1]]
    assert idomain.dtype == np.dtype(int)
    assert np.array_equal(idomain, np.where(mask, 0, 1).astype(int))


def test_solver_mesh_idomain_all_active_is_all_ones() -> None:
    mesh = _mesh(top=np.array([1.0]), botm=np.array([[0.0]]), inactive_mask=np.array([[False]]))
    assert mesh.idomain().tolist() == [[1]]


def test_gwt_and_gwf_idomain_identical_via_shared_helper() -> None:
    mask = np.array([[False, True, False, True]])
    mesh = _mesh(
        top=np.array([1.0, 1.0, 1.0, 1.0]),
        botm=np.array([[0.0, 0.0, 0.0, 0.0]]),
        inactive_mask=mask,
    )
    idomain = mesh.idomain()
    assert idomain.tolist() == [[1, 0, 1, 0]]
    assert idomain.shape == (1, 4)
    assert idomain.dtype == np.dtype(int)


def test_gwt_disv_receives_idomain_with_inactive_cell(tmp_path: Path) -> None:
    mesh = _mesh(
        top=np.array([10.0, 10.0, 10.0]),
        botm=np.array([[0.0, 0.0, 0.0]]),
        inactive_mask=np.array([[False, False, True]]),
    )
    ncpl = 3

    sim = flopy.mf6.MFSimulation(sim_name="sim", sim_ws=str(tmp_path), exe_name="mf6")
    flopy.mf6.ModflowTdis(sim, nper=1, perioddata=[(1.0, 1, 1.0)], time_units="SECONDS")
    gwf = flopy.mf6.ModflowGwf(sim, modelname="flow", save_flows=True)
    ims = flopy.mf6.ModflowIms(sim, filename="flow.ims")
    sim.register_ims_package(ims, [gwf.name])
    gwf_disv = flopy.mf6.ModflowGwfdisv(
        gwf,
        nlay=mesh.nlay,
        **mesh.to_disv_kwargs(),
        idomain=mesh.idomain(),
        xorigin=0.0,
        yorigin=0.0,
        length_units="METERS",
    )
    flopy.mf6.ModflowGwfic(gwf, strt=5.0)
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=1, k=1.0)
    rch = flopy.mf6.ModflowGwfrcha(
        gwf,
        recharge={0: 1.0e-8},
        auxiliary=["CONCENTRATION"],
        aux={0: [np.zeros(ncpl)]},
        pname="RCHA",
    )

    flow_model = SimpleNamespace(
        sim=sim,
        gwf=gwf,
        ims=ims,
        rch=rch,
        solver_mesh=mesh,
        nlay=1,
        ncpl=ncpl,
        nper=1,
        sy=np.array([[0.25, 0.25, 0.25]]),
        model_name="flow",
        exe="mf6",
    )
    transport = Transport({"modflow6gwt": {"parameters": {"sconc_input": 0.0}}})

    gwt_solver = Modflow6Transport(SimpleNamespace(), transport, flow_model, str(tmp_path), "flow")
    gwt_solver.pre_processing()

    gwt_idomain = np.asarray(gwt_solver.gwtdis.idomain.array)
    gwf_idomain = np.asarray(gwf_disv.idomain.array)
    assert gwt_idomain.tolist() == [[1, 1, 0]]
    assert np.array_equal(gwt_idomain, gwf_idomain)
    # The GWF6-GWT6 exchange is created.
    assert gwt_solver.gwfgwt is not None
