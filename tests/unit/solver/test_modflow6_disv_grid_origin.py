"""WP1 - the MODFLOW 6 DISV grid must not double-apply the catchment origin.

DISV vertices built by ``to_disv_kwargs`` already carry absolute model
coordinates (UTM/Lambert meters). The package origin must therefore be 0.
Passing ``solver_mesh.xoffset`` as ``xorigin`` would shift the whole grid by
one full origin, so a corner at x=1000 m would read back at x=2000 m.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import flopy
import numpy as np
import pytest

from hydromodpy.physics.transport.transport import Transport
from hydromodpy.solver.modflow6.prt import Modflow6Prt
from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh


def _offset_two_cell_mesh() -> SolverMesh:
    """Two 5 m x 10 m cells in a row, absolute x in [1000, 1010] (xoffset=1000)."""
    vertices = np.array(
        [
            [1000.0, 0.0],
            [1005.0, 0.0],
            [1010.0, 0.0],
            [1000.0, 10.0],
            [1005.0, 10.0],
            [1010.0, 10.0],
        ],
        dtype=float,
    )
    connectivity = np.array([[0, 1, 4, 3], [1, 2, 5, 4]], dtype=int)
    planar_mesh = HydroMesh(
        vertices=vertices,
        cell_blocks=(CellBlock(CellType.QUADRILATERAL, connectivity),),
    )
    return SolverMesh(
        planar_mesh=planar_mesh,
        top=np.array([10.0, 10.0]),
        botm=np.array([[0.0, 0.0]]),
        inactive_mask=np.array([[False, False]]),
    )


def _build_gwf_disv(sim_ws: str, mesh: SolverMesh, *, xorigin: float, yorigin: float):
    """Build a minimal GWF model with a DISV at the given origin."""
    sim = flopy.mf6.MFSimulation(sim_name="sim", sim_ws=sim_ws, exe_name="mf6")
    flopy.mf6.ModflowTdis(sim, nper=1, perioddata=[(1.0, 1, 1.0)], time_units="SECONDS")
    gwf = flopy.mf6.ModflowGwf(sim, modelname="flow", save_flows=True)
    ims = flopy.mf6.ModflowIms(sim, filename="flow.ims")
    sim.register_ims_package(ims, [gwf.name])
    idomain = np.where(mesh.inactive_mask, 0, 1).astype(int)
    flopy.mf6.ModflowGwfdisv(
        gwf,
        nlay=mesh.nlay,
        **mesh.to_disv_kwargs(),
        idomain=idomain,
        xorigin=xorigin,
        yorigin=yorigin,
        length_units="METERS",
    )
    return sim, gwf, ims


def test_mf6_disv_does_not_double_apply_grid_origin(tmp_path: Path) -> None:
    mesh = _offset_two_cell_mesh()
    _, gwf, _ = _build_gwf_disv(str(tmp_path), mesh, xorigin=0.0, yorigin=0.0)

    mg = gwf.modelgrid
    # Production origin (0): vertices stay absolute, no doubling.
    assert np.nanmin(mg.xvertices) == pytest.approx(1000.0)
    assert np.nanmax(mg.xvertices) == pytest.approx(1010.0)
    assert np.asarray(mg.xcellcenters).ravel().tolist() == pytest.approx([1002.5, 1007.5])
    # Guard: the wrong origin (xoffset) would double the coordinates.
    assert np.asarray(mg.xcellcenters).ravel().tolist() != pytest.approx([2002.5, 2007.5])

    # The double-offset bug, demonstrated explicitly for documentation.
    _, gwf_wrong, _ = _build_gwf_disv(
        str(tmp_path / "wrong"), mesh, xorigin=mesh.xoffset, yorigin=mesh.yoffset
    )
    assert np.asarray(gwf_wrong.modelgrid.xcellcenters).ravel().tolist() == pytest.approx(
        [2002.5, 2007.5]
    )
    assert np.nanmax(gwf_wrong.modelgrid.xvertices) == pytest.approx(2010.0)


@pytest.mark.integration
@pytest.mark.mf6
@pytest.mark.slow
@pytest.mark.allow_subprocess
def test_modflow6_prt_end_to_end_produces_tracks(tmp_path: Path) -> None:
    """Run the real Modflow6Prt class against the binary end-to-end.

    Guards the coordinate_check_method=None fix at the class level: re-introducing
    the dev-only 'eager' tag makes the release binary reject the run, so SUCCESS
    flips to False and no track CSV is produced.
    """
    import pandas as pd

    exe = str(ensure_solver_binary("mf6"))
    mesh = _offset_two_cell_mesh()

    sim = flopy.mf6.MFSimulation(sim_name="sim", sim_ws=str(tmp_path), exe_name=exe)
    tdis = flopy.mf6.ModflowTdis(sim, nper=1, perioddata=[(86400.0, 1, 1.0)], time_units="SECONDS")
    gwf = flopy.mf6.ModflowGwf(sim, modelname="flow", save_flows=True)
    ims = flopy.mf6.ModflowIms(sim, complexity="SIMPLE", filename="flow.ims")
    sim.register_ims_package(ims, [gwf.name])
    idomain = np.where(mesh.inactive_mask, 0, 1).astype(int)
    flopy.mf6.ModflowGwfdisv(
        gwf,
        nlay=mesh.nlay,
        **mesh.to_disv_kwargs(),
        idomain=idomain,
        xorigin=0.0,
        yorigin=0.0,
        length_units="METERS",
    )
    flopy.mf6.ModflowGwfic(gwf, strt=9.0)
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=0, k=1.0, save_specific_discharge=True)
    # A head gradient across the two cells drives the flow PRT tracks.
    flopy.mf6.ModflowGwfchd(gwf, stress_period_data={0: [[(0, 0), 9.5], [(0, 1), 8.5]]})
    flopy.mf6.ModflowGwfoc(
        gwf,
        head_filerecord="flow.hds",
        budget_filerecord="flow.cbc",
        saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
    )

    flow_model = SimpleNamespace(
        sim=sim,
        gwf=gwf,
        ims=ims,
        tdis=tdis,
        solver_mesh=mesh,
        nlay=1,
        ncpl=2,
        sy=np.array([[0.25, 0.25]]),
        model_name="flow",
        exe=exe,
    )
    transport = Transport(
        {"modflow6prt": {"parameters": {"release_zone": "domain", "porosity": 0.25}}}
    )
    prt = Modflow6Prt(SimpleNamespace(), transport, flow_model, str(tmp_path), "flow")
    prt.pre_processing()
    success = prt.processing(write_model=True, run_model=True, verbose=False)

    assert success, "Modflow6Prt run did not terminate normally (binary may reject PRP tags)"
    track_csv = tmp_path / "flow_prt.trk.csv"
    assert track_csv.exists(), "no PRT track CSV was produced"
    track = pd.read_csv(track_csv)
    assert len(track) > 0
    assert "x" in track.columns


def test_solver_mesh_xoffset_matches_disv_vertices_no_offset() -> None:
    mesh = _offset_two_cell_mesh()
    disv_kwargs = mesh.to_disv_kwargs()
    vertex_x = [float(v[1]) for v in disv_kwargs["vertices"]]
    # xoffset is a georef accessor equal to the minimum absolute vertex x.
    assert mesh.xoffset == pytest.approx(1000.0)
    assert mesh.xoffset == pytest.approx(min(vertex_x))


@pytest.mark.integration
def test_mf6_prt_release_point_uses_absolute_centroid(tmp_path: Path) -> None:
    mesh = _offset_two_cell_mesh()
    sim, gwf, ims = _build_gwf_disv(str(tmp_path), mesh, xorigin=0.0, yorigin=0.0)

    flow_model = SimpleNamespace(
        sim=sim,
        gwf=gwf,
        ims=ims,
        solver_mesh=mesh,
        nlay=1,
        ncpl=2,
        sy=np.array([[0.25, 0.25]]),
        model_name="flow",
        exe="mf6",
    )
    transport = Transport(
        {
            "modflow6prt": {
                "parameters": {
                    "release_zone": "domain",
                    "release_times_days": [0.0],
                    "track_times_days": [0.5],
                }
            }
        }
    )

    prt = Modflow6Prt(SimpleNamespace(), transport, flow_model, str(tmp_path), "flow")
    prt.pre_processing()
    prt.processing(write_model=True, run_model=False, verbose=False)

    # Release points are the absolute cell centroids, matching the un-offset grid.
    release_x = [float(entry[2]) for entry in prt._build_packagedata()]
    assert release_x == pytest.approx([1002.5, 1007.5])
    # PRT DISV origin is 0, so the PRT modelgrid stays absolute.
    assert np.asarray(prt.prt.modelgrid.xcellcenters).ravel().tolist() == pytest.approx(
        [1002.5, 1007.5]
    )

    prp_text = (tmp_path / "flow_prt.prp").read_text(encoding="utf-8")
    assert "1002.5" in prp_text
    # Neither the doubled (2002.5) nor the relative (2.5) coordinate may appear.
    assert "2002.5" not in prp_text
    # The dev-only COORDINATE_CHECK_METHOD tag must stay suppressed (None), or
    # the release MF6 binary rejects every PRT run.
    assert prt.prp.coordinate_check_method.get_data() is None
    assert "coordinate_check_method" not in prp_text.lower()


@pytest.mark.integration
def test_mf6_gwf_prt_gwt_grids_agree_on_absolute_coords(tmp_path: Path) -> None:
    mesh = _offset_two_cell_mesh()
    sim, gwf, ims = _build_gwf_disv(str(tmp_path), mesh, xorigin=0.0, yorigin=0.0)
    disv_kwargs = mesh.to_disv_kwargs()
    idomain = np.where(mesh.inactive_mask, 0, 1).astype(int)

    # GWT DISV: no origin keyword, identical absolute vertices (transport.py style).
    gwt = flopy.mf6.ModflowGwt(sim, modelname="trans", save_flows=True)
    flopy.mf6.ModflowGwtdisv(gwt, nlay=mesh.nlay, **disv_kwargs, idomain=idomain)

    flow_model = SimpleNamespace(
        sim=sim,
        gwf=gwf,
        ims=ims,
        solver_mesh=mesh,
        nlay=1,
        ncpl=2,
        sy=np.array([[0.25, 0.25]]),
        model_name="flow",
        exe="mf6",
    )
    transport = Transport({"modflow6prt": {"parameters": {"release_zone": "domain"}}})
    prt = Modflow6Prt(SimpleNamespace(), transport, flow_model, str(tmp_path), "flow")
    prt.pre_processing()

    gwf_centers = np.asarray(gwf.modelgrid.xcellcenters).ravel()
    gwt_centers = np.asarray(gwt.modelgrid.xcellcenters).ravel()
    prt_centers = np.asarray(prt.prt.modelgrid.xcellcenters).ravel()
    assert gwf_centers.tolist() == pytest.approx([1002.5, 1007.5])
    assert gwt_centers.tolist() == pytest.approx(gwf_centers.tolist())
    assert prt_centers.tolist() == pytest.approx(gwf_centers.tolist())
    assert np.nanmax(gwf.modelgrid.xvertices) == pytest.approx(1010.0)
    assert np.nanmax(gwt.modelgrid.xvertices) == pytest.approx(1010.0)


@pytest.mark.regression
@pytest.mark.slow
@pytest.mark.mf6
@pytest.mark.allow_subprocess
def test_mf6_grb_vertices_round_trip_absolute_after_run(tmp_path: Path) -> None:
    exe = str(ensure_solver_binary("mf6"))
    mesh = _offset_two_cell_mesh()
    sim, gwf, _ = _build_gwf_disv(str(tmp_path), mesh, xorigin=0.0, yorigin=0.0)
    sim.exe_name = exe
    flopy.mf6.ModflowGwfic(gwf, strt=5.0)
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=1, k=1.0, save_specific_discharge=True)
    flopy.mf6.ModflowGwfchd(gwf, stress_period_data={0: [[(0, 0), 5.0]]})
    flopy.mf6.ModflowGwfoc(
        gwf,
        head_filerecord="flow.hds",
        budget_filerecord="flow.cbc",
        saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
    )
    sim.write_simulation(silent=True)
    success, _ = sim.run_simulation(silent=True)
    assert success

    grb = flopy.mf6.utils.MfGrdFile(str(tmp_path / "flow.disv.grb"))
    verts = np.asarray(grb.verts)
    assert verts[:, 0].min() == pytest.approx(1000.0)
    assert verts[:, 0].max() == pytest.approx(1010.0)
    assert np.nanmin(grb.modelgrid.xvertices) == pytest.approx(1000.0)
    assert np.nanmax(grb.modelgrid.xvertices) == pytest.approx(1010.0)
