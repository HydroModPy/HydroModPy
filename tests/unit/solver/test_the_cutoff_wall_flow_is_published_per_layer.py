"""The flow through a lake cutoff wall is published, layer by layer (D21).

``seepage_under_dam`` was the VERTICAL exchange of the whole lake bed, not a
flow under or through the dam, and the flow across the wall was published
nowhere. The wall faces are known at build time (the faces the HFB bars, of the
``barriers`` family on an engine that follows it). They go in the LAK sidecar,
lake side first, and the extractor sums ``FLOW-JA-FACE`` of the GWF budget over
them, per layer: ``cutoff_wall_flow``, m3/s, positive from the lake side to the
downstream side. Station ``lake:<id>:layer<k>`` per layer, ``lake:<id>`` for
the sum.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import LineString

from hydromodpy.solver.modflow6.builders import build_lake_obs_spec
from hydromodpy.solver.modflow6.builders.lake import cutoff_wall_flow_faces
from hydromodpy.solver.modflow6.extractors.cbc_reader import Mf6CellBudgetReader
from hydromodpy.solver.modflow6.extractors.lake import (
    LakeObsSpec,
    build_lake_records,
    read_cutoff_wall_flow,
)
from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays


def _mesh(nrow: int, ncol: int, nlay: int = 2):
    top = np.full((nrow, ncol), 100.0)
    botm = np.stack([np.full((nrow, ncol), 100.0 - 10.0 * (k + 1)) for k in range(nlay)])
    return solver_mesh_from_structured_arrays(
        nrow=nrow, ncol=ncol, top=top, botm=botm, dx=10.0, dy=10.0
    )


def test_the_wall_faces_are_listed_lake_side_first() -> None:
    nrow, ncol = 5, 11
    mesh = _mesh(nrow, ncol)
    centres = np.asarray(mesh.cell_centers(), dtype=float)
    lake = [r * ncol + c for r in (1, 2, 3) for c in (1, 2, 3)]
    # The wall runs between columns 3 and 4, with the lake (west) on its left.
    x = 0.5 * (centres[3, 0] + centres[4, 0])
    ys = centres[:, 1]
    south, north = float(ys.min()) - 5.0, float(ys.max()) + 5.0
    wall = LineString([(x, south), (x, north)])
    faces = cutoff_wall_flow_faces({"cutoff_wall_line": wall}, lake, mesh)
    assert sorted(faces) == [(r * ncol + 3, r * ncol + 4) for r in range(nrow)]
    # Rows 0 and 4 are wing faces, with no lake cell: their order is the side of
    # the wall. Run the wall the other way and the lake side of a wing is east.
    reverse = LineString([(x, north), (x, south)])
    swapped = set(cutoff_wall_flow_faces({"cutoff_wall_line": reverse}, lake, mesh))
    assert {(4, 3), (4 * ncol + 4, 4 * ncol + 3)} <= swapped
    # A face with a lake cell keeps it first whatever the direction of the line.
    assert all(a in lake for a, b in swapped if a in lake or b in lake)
    assert cutoff_wall_flow_faces({}, lake, mesh) == []


def test_the_sidecar_carries_the_wall_faces_and_the_gwf_budget() -> None:
    info = [
        {
            "lake_index": 0,
            "lake_id": "res",
            "n_conn": 1,
            "vertical_iconns": [0],
            "wall_faces": [(1, 2)],
        },
        {"lake_index": 1, "lake_id": "fore", "n_conn": 1, "vertical_iconns": [0]},
    ]
    _, meta = build_lake_obs_spec(stem="m", lake_conn_info=info, outlets=[])
    assert meta["cutoff_walls"] == {"res": [[1, 2]]}
    assert meta["gwf_budget_bin"] == "m.cbc"
    spec = LakeObsSpec.from_mapping(meta)
    assert spec.cutoff_walls == {"res": [(1, 2)]}
    assert spec.gwf_budget_bin == "m.cbc"


def _run_wall_model(ws: Path) -> tuple[float, float]:
    """1 x 4 cells, 2 layers, heads 10 -> 0 across the row, an HFB in layer 1.

    Returns the end time and the CHD inflow of the model, which must all cross
    the wall face between cells 1 and 2.
    """
    import flopy

    mesh = _mesh(1, 4)
    sim = flopy.mf6.MFSimulation(
        sim_name="m", sim_ws=str(ws), exe_name=str(ensure_solver_binary("mf6"))
    )
    flopy.mf6.ModflowTdis(sim, time_units="seconds", nper=1, perioddata=[(86400.0, 1, 1.0)])
    flopy.mf6.ModflowIms(sim, complexity="SIMPLE")
    gwf = flopy.mf6.ModflowGwf(sim, modelname="m", save_flows=True)
    flopy.mf6.ModflowGwfdisv(gwf, nlay=mesh.nlay, idomain=mesh.idomain, **mesh.to_disv_kwargs())
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=0, k=1e-4, k33=1e-5)
    flopy.mf6.ModflowGwfic(gwf, strt=50.0)
    chd = [[(k, 0), 60.0] for k in range(2)] + [[(k, 3), 50.0] for k in range(2)]
    flopy.mf6.ModflowGwfchd(gwf, stress_period_data={0: chd}, save_flows=True)
    flopy.mf6.ModflowGwfhfb(gwf, maxhfb=1, stress_period_data={0: [[(0, 1), (0, 2), 1e-9]]})
    flopy.mf6.ModflowGwfoc(gwf, budget_filerecord="m.cbc", saverecord=[("BUDGET", "ALL")])
    sim.write_simulation(silent=True)
    success, _ = sim.run_simulation(silent=True)
    assert success
    with Mf6CellBudgetReader(ws / "m.cbc") as budget:
        index = next(i for i, r in enumerate(budget.records) if r.text == "CHD")
        record = budget.records[index]
        q = np.asarray(budget.read_record(index)["q"], dtype=float)
    return record.totim, float(q[q > 0].sum())


@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.allow_subprocess
@pytest.mark.fast
def test_the_wall_flow_is_the_face_flow_per_layer(tmp_path: Path) -> None:
    totim, inflow = _run_wall_model(tmp_path)
    spec = LakeObsSpec(
        obs_csv="m.lak.obs.csv", cutoff_walls={"res": [(1, 2)]}, gwf_budget_bin="m.cbc"
    )
    flow = read_cutoff_wall_flow(spec, tmp_path, times=[totim])
    layers = flow["res"]
    assert sorted(layers) == [1, 2]
    # Everything that enters at the left CHD crosses the wall, mostly under the HFB.
    assert layers[1][0] + layers[2][0] == pytest.approx(inflow, rel=1e-6)
    assert 0.0 < layers[1][0] < 1e-3 * layers[2][0]


@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.allow_subprocess
@pytest.mark.fast
def test_the_lake_records_carry_the_wall_flow(tmp_path: Path) -> None:
    totim, inflow = _run_wall_model(tmp_path)
    spec = LakeObsSpec.from_mapping(
        {
            "obs_csv": "m.lak.obs.csv",
            "entries": [{"obsname": "res_stage", "lake_id": "res", "quantity": "stage"}],
            "cutoff_walls": {"res": [[1, 2]]},
            "gwf_budget_bin": "m.cbc",
        }
    )
    obs = tmp_path / "m.lak.obs.csv"
    obs.write_text(f"time,RES_STAGE\n{totim},55.0\n")
    timeseries, _ = build_lake_records(spec, obs, times=[totim], seconds_per_time_unit=1.0)
    wall = {r["station_id"]: r["value"] for r in timeseries if r["variable"] == "cutoff_wall_flow"}
    assert set(wall) == {"lake:res", "lake:res:layer1", "lake:res:layer2"}
    assert wall["lake:res"] == pytest.approx(inflow, rel=1e-6)
    assert wall["lake:res:layer1"] + wall["lake:res:layer2"] == pytest.approx(wall["lake:res"])
    assert all(r["unit"] == "m3 s-1" for r in timeseries if r["variable"] == "cutoff_wall_flow")
