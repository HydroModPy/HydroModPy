"""Unit tests for the MODFLOW 6 PRT integration contracts."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import flopy
import numpy as np
import zarr

from hydromodpy.display.figures.particle_tracks import _read_pathlines
from hydromodpy.physics.transport.transport import Transport
from hydromodpy.physics.transport.transport_config import TransportConfig
from hydromodpy.solver.modflow6.extractors.flow import Modflow6OutputAdapter
from hydromodpy.solver.modflow6.extractors.prt import Modflow6PrtOutputAdapter
from hydromodpy.solver.modflow6.prt import Modflow6Prt
from hydromodpy.solver.modflow6.prt_tracks import read_prt_track_csv
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh


class _ZarrHandle:
    def __init__(self, path: Path):
        self.root = zarr.open_group(str(path), mode="a")

    def close(self) -> None:
        pass


class _Store:
    def __init__(self, root: Path):
        self.root = root

    def open_zarr(self, sim_id: str) -> _ZarrHandle:
        return _ZarrHandle(self.root / f"{sim_id}.zarr")


def test_transport_config_accepts_modflow6prt_parameters() -> None:
    cfg = TransportConfig.model_validate(
        {
            "modflow6prt": {
                "parameters": {
                    "release_zone": "upstream_nonriver",
                    "upstream_top_quantile": 0.85,
                    "max_particles": 12,
                    "release_times_days": [0.0, 10.0],
                    "track_times_days": [1.0, 2.0, 3.0],
                    "track_time_step_days": 10.0,
                }
            }
        }
    )
    transport = Transport(cfg)

    assert transport.modflow6prt.parameters["release_zone"] == "upstream_nonriver"
    assert transport.modflow6prt.parameters["upstream_top_quantile"] == 0.85
    assert transport.modflow6prt.parameters["max_particles"] == 12
    assert transport.parameters["modflow6prt"]["release_times_days"] == [0.0, 10.0]
    assert transport.modflow6prt.parameters["track_time_step_days"] == 10.0


def test_modflow6_prt_upstream_nonriver_release_excludes_stream_cells() -> None:
    transport = Transport(
        {
            "modflow6prt": {
                "parameters": {
                    "release_zone": "upstream_nonriver",
                    "upstream_top_quantile": 0.5,
                }
            }
        }
    )
    flow_model = SimpleNamespace(
        solver_mesh=SimpleNamespace(
            top=np.array([1.0, 5.0, 10.0, 9.0, 8.0, 7.0]),
            inactive_mask=np.array([[False, False, False, False, False, False]]),
        ),
        ncpl=6,
        _stream_support_mask=np.array([False, False, True, False, True, False]),
    )

    prt = Modflow6Prt(SimpleNamespace(), transport, flow_model)

    assert prt._select_release_cells().tolist() == [3]


def test_modflow6_prt_extractor_writes_vectorized_pathlines(tmp_path: Path) -> None:
    output_dir = tmp_path / "solver"
    output_dir.mkdir()
    (output_dir / "case_prt.trk.csv").write_text(
        "\n".join(
            [
                "iprp,irpt,trelease,time,x,y,z,istatus",
                "0,0,0,0,0,0,1,1",
                "0,0,0,1,1,0,1,2",
                "0,1,0,0,0,1,2,1",
                "0,1,0,2,2,1,2,2",
                "0,1,0,3,3,1,2,2",
            ]
        ),
        encoding="utf-8",
    )
    store = _Store(tmp_path / "catalog")

    Modflow6PrtOutputAdapter().extract("sim_a", output_dir, store)

    handle = store.open_zarr("sim_a")
    try:
        grp = handle.root["pathlines"]
        x = np.asarray(grp["x"])
        time = np.asarray(grp["time"])
        status = np.asarray(grp["status"])
    finally:
        handle.close()

    assert x.shape == (2, 3)
    assert np.allclose(x[0, :2], [0.0, 1.0])
    assert np.isnan(x[0, 2])
    assert np.allclose(time[1], [0.0, 2.0, 3.0])
    assert np.allclose(status[1], [1.0, 2.0, 2.0])


def test_modflow6_prt_track_csv_reader_can_feed_reports_directly(tmp_path: Path) -> None:
    csv_path = tmp_path / "case_prt.trk.csv"
    csv_path.write_text(
        "\n".join(
            [
                "iprp,irpt,trelease,time,x,y,z,istatus",
                "0,0,0,0,0,0,1,1",
                "0,0,0,86400,1,0,1,2",
                "0,1,0,0,0,1,2,1",
                "0,1,0,172800,2,1,2,2",
                "0,1,0,259200,3,1,2,2",
            ]
        ),
        encoding="utf-8",
    )

    arrays = read_prt_track_csv(csv_path, time_units="SECONDS")

    assert arrays is not None
    assert arrays.x.shape == (2, 3)
    assert np.allclose(arrays.time[0, :2], [0.0, 1.0])
    assert np.isnan(arrays.time[0, 2])
    assert np.allclose(arrays.time[1], [0.0, 2.0, 3.0])
    assert arrays.source_file == csv_path


def test_modflow6_prt_can_write_minimal_disv_package(tmp_path: Path) -> None:
    sim = flopy.mf6.MFSimulation(sim_name="sim", sim_ws=str(tmp_path), exe_name="mf6")
    flopy.mf6.ModflowTdis(
        sim,
        nper=1,
        perioddata=[(1.0, 1, 1.0)],
        time_units="DAYS",
    )
    gwf = flopy.mf6.ModflowGwf(sim, modelname="flow", save_flows=True)
    ims = flopy.mf6.ModflowIms(sim, filename="flow.ims")
    sim.register_ims_package(ims, [gwf.name])

    hydro_mesh = HydroMesh(
        vertices=np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]]),
        cell_blocks=(CellBlock(CellType.QUADRILATERAL, np.array([[0, 1, 2, 3]], dtype=int)),),
    )
    solver_mesh = SolverMesh(
        hydro_mesh,
        top=np.array([1.0]),
        botm=np.array([[0.0]]),
        inactive_mask=np.array([[False]]),
    )
    flopy.mf6.ModflowGwfdisv(
        gwf,
        nlay=1,
        **solver_mesh.to_disv_kwargs(),
        idomain=np.array([[1]]),
        xorigin=0.0,
        yorigin=0.0,
    )
    flopy.mf6.ModflowGwfic(gwf, strt=1.0)
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=1, k=1.0, save_specific_discharge=True)
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
        solver_mesh=solver_mesh,
        nlay=1,
        ncpl=1,
        sy=np.array([[0.25]]),
        model_name="flow",
        exe="mf6",
    )
    transport = Transport(
        {
            "modflow6prt": {
                "parameters": {
                    "release_zone": "domain",
                    "max_particles": 1,
                    "release_times_days": [0.0],
                    "track_times_days": [0.5],
                }
            }
        }
    )

    prt = Modflow6Prt(SimpleNamespace(), transport, flow_model, str(tmp_path), "flow")
    prt.pre_processing()
    assert prt.processing(write_model=True, run_model=False, verbose=False) is False

    assert (tmp_path / "flow_prt.prp").exists()
    assert (tmp_path / "flow_prt.oc").exists()
    assert (tmp_path / "flow_prt.ems").exists()
    assert (tmp_path / "sim.gwfprt").exists()
    prp_text = (tmp_path / "flow_prt.prp").read_text(encoding="utf-8").lower()
    oc_text = (tmp_path / "flow_prt.oc").read_text(encoding="utf-8").lower()
    assert "track  fileout" not in prp_text
    assert "track  fileout" in oc_text
    namefile = (tmp_path / "mfsim.nam").read_text(encoding="utf-8").lower()
    assert namefile.index("ims6") < namefile.index("ems6")


def test_modflow6_prt_converts_day_controls_to_model_seconds(tmp_path: Path) -> None:
    sim = flopy.mf6.MFSimulation(sim_name="sim", sim_ws=str(tmp_path), exe_name="mf6")
    flopy.mf6.ModflowTdis(
        sim,
        nper=1,
        perioddata=[(86400.0, 1, 1.0)],
        time_units="SECONDS",
    )
    gwf = flopy.mf6.ModflowGwf(sim, modelname="flow", save_flows=True)
    ims = flopy.mf6.ModflowIms(sim, filename="flow.ims")
    sim.register_ims_package(ims, [gwf.name])
    hydro_mesh = HydroMesh(
        vertices=np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]]),
        cell_blocks=(CellBlock(CellType.QUADRILATERAL, np.array([[0, 1, 2, 3]], dtype=int)),),
    )
    solver_mesh = SolverMesh(
        hydro_mesh,
        top=np.array([1.0]),
        botm=np.array([[0.0]]),
        inactive_mask=np.array([[False]]),
    )
    flopy.mf6.ModflowGwfdisv(
        gwf,
        nlay=1,
        **solver_mesh.to_disv_kwargs(),
        idomain=np.array([[1]]),
        xorigin=0.0,
        yorigin=0.0,
    )
    flow_model = SimpleNamespace(
        sim=sim,
        gwf=gwf,
        ims=ims,
        tdis=sim.tdis,
        solver_mesh=solver_mesh,
        nlay=1,
        ncpl=1,
        sy=np.array([[0.25]]),
        model_name="flow",
        exe="mf6",
    )
    transport = Transport(
        {
            "modflow6prt": {
                "parameters": {
                    "release_zone": "domain",
                    "max_particles": 1,
                    "release_times_days": [1.0],
                    "track_times_days": [2.0],
                    "stop_time_days": 3.0,
                    "stop_travel_time_days": 4.0,
                }
            }
        }
    )

    prt = Modflow6Prt(SimpleNamespace(), transport, flow_model, str(tmp_path), "flow")
    prt.pre_processing()
    prt.processing(write_model=True, run_model=False, verbose=False)

    prp_text = (tmp_path / "flow_prt.prp").read_text(encoding="utf-8")
    oc_text = (tmp_path / "flow_prt.oc").read_text(encoding="utf-8")
    assert "STOPTIME  2.59200000E+05" in prp_text
    assert "STOPTRAVELTIME  3.45600000E+05" in prp_text
    assert "86400.00000000" in prp_text
    assert "1.72800000E+05" in oc_text


def test_modflow6_prt_generates_regular_track_times(tmp_path: Path) -> None:
    sim = flopy.mf6.MFSimulation(sim_name="sim", sim_ws=str(tmp_path), exe_name="mf6")
    flopy.mf6.ModflowTdis(
        sim,
        nper=1,
        perioddata=[(30.0, 1, 1.0)],
        time_units="DAYS",
    )
    gwf = flopy.mf6.ModflowGwf(sim, modelname="flow", save_flows=True)
    ims = flopy.mf6.ModflowIms(sim, filename="flow.ims")
    sim.register_ims_package(ims, [gwf.name])
    hydro_mesh = HydroMesh(
        vertices=np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]]),
        cell_blocks=(CellBlock(CellType.QUADRILATERAL, np.array([[0, 1, 2, 3]], dtype=int)),),
    )
    solver_mesh = SolverMesh(
        hydro_mesh,
        top=np.array([1.0]),
        botm=np.array([[0.0]]),
        inactive_mask=np.array([[False]]),
    )
    flopy.mf6.ModflowGwfdisv(
        gwf,
        nlay=1,
        **solver_mesh.to_disv_kwargs(),
        idomain=np.array([[1]]),
        xorigin=0.0,
        yorigin=0.0,
    )
    flow_model = SimpleNamespace(
        sim=sim,
        gwf=gwf,
        ims=ims,
        tdis=sim.tdis,
        solver_mesh=solver_mesh,
        nlay=1,
        ncpl=1,
        sy=np.array([[0.25]]),
        model_name="flow",
        exe="mf6",
    )
    transport = Transport(
        {
            "modflow6prt": {
                "parameters": {
                    "release_zone": "domain",
                    "max_particles": 1,
                    "release_times_days": [0.0],
                    "track_time_step_days": 10.0,
                    "stop_time_days": 30.0,
                }
            }
        }
    )

    prt = Modflow6Prt(SimpleNamespace(), transport, flow_model, str(tmp_path), "flow")
    prt.pre_processing()
    prt.processing(write_model=True, run_model=False, verbose=False)

    oc_text = (tmp_path / "flow_prt.oc").read_text(encoding="utf-8")
    assert "0.00000000" in oc_text
    assert "10.00000000" in oc_text
    assert "20.00000000" in oc_text
    assert "30.00000000" in oc_text


def test_modflow6_prt_extractor_converts_model_seconds_to_days(tmp_path: Path) -> None:
    output_dir = tmp_path / "solver"
    output_dir.mkdir()
    (output_dir / "case.tdis").write_text(
        "BEGIN options\n  TIME_UNITS  seconds\nEND options\n",
        encoding="utf-8",
    )
    (output_dir / "case_prt.trk.csv").write_text(
        "\n".join(
            [
                "iprp,irpt,trelease,t,x,y,z,istatus",
                "1,1,86400,0,0,0,1,1",
                "1,1,86400,172800,2,0,1,2",
            ]
        ),
        encoding="utf-8",
    )
    store = _Store(tmp_path / "catalog")

    Modflow6PrtOutputAdapter().extract("sim_time", output_dir, store)

    handle = store.open_zarr("sim_time")
    try:
        time = np.asarray(handle.root["pathlines/time"])
        attrs = dict(handle.root["pathlines"].attrs)
    finally:
        handle.close()

    assert np.allclose(time[0], [0.0, 2.0])
    assert attrs["source_time_units"] == "SECONDS"
    assert attrs["time_units"] == "days"


def test_modflow6_flow_extractor_writes_spdis_magnitude_from_vector_recarray() -> None:
    rec = np.array(
        [(1, 1, 0.0, 3.0, 4.0, 0.0), (2, 2, 0.0, 0.0, 12.0, 5.0)],
        dtype=[
            ("node", "<i4"),
            ("node2", "<i4"),
            ("q", "<f8"),
            ("qx", "<f8"),
            ("qy", "<f8"),
            ("qz", "<f8"),
        ],
    )

    field = Modflow6OutputAdapter._recarray_to_grid(rec, nlay=1, n_cells=2)

    assert np.allclose(field, [[5.0, 13.0]])


def test_particle_tracks_reader_supports_vectorized_layout(tmp_path: Path) -> None:
    store = _Store(tmp_path / "catalog")
    handle = store.open_zarr("sim_b")
    try:
        grp = handle.root.require_group("pathlines")
        grp.create_array("x", data=np.array([[0.0, 1.0, np.nan], [2.0, 3.0, 4.0]]))
        grp.create_array("y", data=np.array([[0.0, 0.0, np.nan], [1.0, 1.0, 1.0]]))
        grp.create_array("z", data=np.array([[5.0, 5.0, np.nan], [6.0, 6.0, 6.0]]))
    finally:
        handle.close()

    sim = SimpleNamespace(_catalog=store, sim_id="sim_b")
    tracks = _read_pathlines(sim)

    assert len(tracks) == 2
    assert tracks[0].shape == (2, 3)
    assert np.allclose(tracks[0][:, :2], [[0.0, 0.0], [1.0, 0.0]])
    assert tracks[1].shape == (3, 3)
