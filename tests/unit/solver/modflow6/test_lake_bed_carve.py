"""Bathymetry bed carving on a real SolverMesh, reconciled to the abacus.

The carved bed must flood back into the input abacus, and every carved column must
stay a valid prism on the fixed base. On a stack with pass-through cells
(``idomain = -1``) the first active cell under the lake has its top on the carved
bed; those stacks get a flat bed, not reconciled.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.vertical_column import check_layer_interfaces
from hydromodpy.solver.modflow6.builders import (
    apply_lake_idomain_mask,
    build_lake_connectiondata,
    carve_lake_bed,
)
from hydromodpy.spatial.lake_bed.abacus import simulate_abacus
from tests._helpers.lake_bed_cases import (
    BASE,
    CELLS,
    TOP,
    abacus,
    bowl_bed,
    carve,
    lake_model,
    nse,
    stack_mesh,
)

MARNAGE = {"dynamic_area": True, "reconcile_to_abacus": False}


def _assert_valid_columns(carved, *, min_thickness: float = 0.0) -> None:
    """Every column is a prism on the fixed base, each layer at least the floor."""
    for cid in CELLS:
        col = carved.botm[:, cid]
        thickness = np.concatenate(([carved.top[cid]], col[:-1])) - col
        assert np.all(thickness > 0.0) and np.all(thickness >= min_thickness - 1e-9)
        assert col[-1] == BASE


def test_carve_reconciles_to_abacus_keeps_valid_columns_and_builds_a_valid_disv(tmp_path) -> None:
    import flopy

    mesh = stack_mesh()
    model, carved = carve(tmp_path, bowl_bed(), mesh=mesh, with_abacus=True)

    assert np.allclose(carved.top, TOP)  # top untouched, frozen source mesh intact
    assert np.allclose(mesh.botm, stack_mesh().botm)
    _assert_valid_columns(carved)

    recon = model._lake_bed_reconstruction["lac0"]
    bed, area = recon["bed_by_cell"], recon["area_by_cell"]
    assert recon["diagnostics"]["area_scale"] == 1.0  # footprint == abacus top area
    assert bed[55] < bed[0]  # a basin: the centre cell sits deeper than the rim cell 0
    # Each column pins its bed at botm[occ_c - 1]; a deeper cell cuts at least as many layers.
    occ_by_cell = model._lake_occupied_layers_by_cell["lac0"]
    for cid in (0, 55):
        assert carved.botm[occ_by_cell[cid] - 1, cid] == pytest.approx(bed[cid], abs=1e-6)
    assert occ_by_cell[55] >= occ_by_cell[0]

    sim = simulate_abacus(bed_by_cell=bed, area_by_cell=area, stages=abacus()["stage"])
    assert np.max(np.abs(sim["sarea"] - np.array(abacus()["sarea"]))) <= 3.0 * 100.0
    assert nse(sim["volume"], abacus()["volume"]) > 0.99

    # flopy accepts the carved and masked geometry as a DISV package.
    masked = apply_lake_idomain_mask(carved, lake_cell_ids_by_lake={"lac0": CELLS})
    sim = flopy.mf6.MFSimulation(sim_name="carve", sim_ws=str(tmp_path))
    flopy.mf6.ModflowTdis(sim, nper=1, perioddata=[(1.0, 1, 1.0)])
    gwf = flopy.mf6.ModflowGwf(sim, modelname="carve")
    disv = flopy.mf6.ModflowGwfdisv(
        gwf, nlay=masked.nlay, **masked.to_disv_kwargs(), idomain=masked.idomain,
        xorigin=0.0, yorigin=0.0, length_units="METERS",
    )  # fmt: skip
    botm = np.asarray(disv.botm.array)
    assert botm.shape == (masked.nlay, masked.n_cells)
    assert np.allclose(botm, masked.botm)
    tops = np.vstack([np.asarray(disv.top.array).reshape(1, -1), botm[:-1]])
    assert np.all(botm < tops)


def test_carve_marnage_keeps_cells_active_with_bed_as_top(tmp_path) -> None:
    """Active-littoral mode: top = bed, column active, one VERTICAL connection per cell at layer 0."""
    model, carved = carve(tmp_path, bowl_bed(), **MARNAGE)

    assert model._marnage_lake_ids == {"lac0"}
    assert carved.top[55] < carved.top[0]
    assert carved.top[55] < TOP
    _assert_valid_columns(carved)
    rows = build_lake_connectiondata(
        model, lake_index=0, lake_cell_ids=CELLS, bedleak=1.0e-6, solver_mesh=carved,
        dynamic_area=True,
    )  # fmt: skip
    assert len(rows) == len(CELLS)
    assert all(row[3] == "VERTICAL" for row in rows)
    assert {row[2] for row in rows} == {(0, cid) for cid in CELLS}


def test_record_holds_the_carved_bed_when_the_clamp_bites(tmp_path, caplog) -> None:
    """A ``min_thickness`` that bites clamps the bed; the record follows the grid and says so."""
    with caplog.at_level("WARNING"):
        model, carved = carve(tmp_path, bowl_bed(), min_thickness=25.0, reconcile_to_abacus=False)
    recon = model._lake_bed_reconstruction["lac0"]
    occ_by_cell = model._lake_occupied_layers_by_cell["lac0"]
    # The deep centre cannot hold a 25 m cap plus a 25 m aquifer.
    assert recon["diagnostics"]["bed_clamp_shift_max"] > 1.0
    assert "min_thickness clamp moved the carved bed" in caplog.text
    for cid in CELLS:
        expected = carved.botm[occ_by_cell[cid] - 1, cid]
        assert recon["bed_by_cell"][cid] == pytest.approx(expected, abs=1e-9)


def test_marnage_record_holds_the_clamped_top(tmp_path) -> None:
    """In active-littoral mode the recorded bed is the cell top MF6 wets and dries."""
    model, carved = carve(tmp_path, bowl_bed(), min_thickness=25.0, **MARNAGE)
    bed = model._lake_bed_reconstruction["lac0"]["bed_by_cell"]
    for cid in CELLS:
        assert bed[cid] == pytest.approx(carved.top[cid], abs=1e-9)


def test_marnage_top_follows_a_bed_that_reaches_the_terrain(tmp_path) -> None:
    """In active-littoral mode the top is the bed, so the terrain ceiling reserves no thickness."""
    model, carved = carve(tmp_path, TOP, min_thickness=5.0, **MARNAGE)
    assert np.allclose(carved.top, TOP)
    assert model._lake_bed_reconstruction["lac0"]["diagnostics"]["bed_clamp_shift_max"] == 0.0
    _assert_valid_columns(carved, min_thickness=5.0)


def test_carve_is_noop_without_bed_reconstruction() -> None:
    model = lake_model({"bedleak": 1.0e-6, "occupied_layers": 1})
    mesh = stack_mesh()
    carved = carve_lake_bed(
        model, mesh, lake_cell_ids_by_lake={"lac0": [0, 1, 2]}, occupied_layers_by_lake={"lac0": 1}
    )
    assert carved is mesh
    assert not hasattr(model, "_lake_bed_reconstruction")


# A layer stack with pass-through cells


def _vertical_tops(model, carved) -> set[float]:
    """Top of the cell each VERTICAL connection leaks into, the floor MODFLOW 6 gives it."""
    occupied = model._lake_occupied_layers_by_cell["lac0"]
    masked = apply_lake_idomain_mask(
        carved, lake_cell_ids_by_lake={"lac0": CELLS}, occupied_layers_by_cell={"lac0": occupied}
    )
    rows = build_lake_connectiondata(
        None, lake_index=0, lake_cell_ids=CELLS, bedleak=1e-6, solver_mesh=masked,
        occupied_layers_by_cell=occupied,
    )  # fmt: skip
    vertical = [row[2] for row in rows if row[3] == "VERTICAL"]
    return {round(float(masked.botm[layer - 1, cell]), 9) for layer, cell in vertical}


@pytest.mark.parametrize(
    ("botm", "idomain", "bed", "occupied", "cap_bottom"),
    [
        # A pass-through cell under the bed stays flat on the bed.
        ([92.0, 92.0, BASE], [1, -1, 1], 95.0, 1, [95.0, 95.0, BASE]),
        # A bed under the pinched layer takes it into the cap.
        ([92.0, 92.0, BASE], [1, -1, 1], 80.0, 2, [None, 80.0, None]),
        # A pinched top layer becomes the lake cap.
        ([TOP, 80.0, BASE], [-1, 1, 1], 95.0, 1, [95.0, None, None]),
    ],
    ids=["pass_through_under_the_bed", "bed_under_the_pinch", "pinched_top_is_the_cap"],
)
def test_a_pinched_stack_puts_the_first_active_top_on_the_bed(
    tmp_path, botm, idomain, bed, occupied, cap_bottom
) -> None:
    mesh = stack_mesh(botm, idomain)
    model, carved = carve(tmp_path, bed, mesh=mesh, reconcile_to_abacus=False)
    for layer, expected in enumerate(cap_bottom):
        if expected is not None:
            assert carved.botm[layer, 0] == pytest.approx(expected)
    assert carved.botm[occupied, 0] < bed or idomain[occupied] == -1
    assert set(model._lake_occupied_layers_by_cell["lac0"].values()) == {occupied}
    assert model._lake_bed_reconstruction["lac0"]["bed_by_cell"][0] == pytest.approx(bed)
    assert _vertical_tops(model, carved) == {bed}
    check_layer_interfaces(carved.top, carved.botm, carved.idomain)


def test_a_column_pinched_out_under_its_top_layer_is_refused(tmp_path) -> None:
    mesh = stack_mesh([BASE, BASE, BASE], [1, -1, -1])
    with pytest.raises(ValueError, match=r"lakes\.lac0 bed_reconstruction: column 0 has no layer"):
        carve(tmp_path, 95.0, mesh=mesh, reconcile_to_abacus=False)


def test_a_marnage_bed_keeps_a_pinched_top_layer_flat(tmp_path) -> None:
    _model, carved = carve(
        tmp_path, 95.0, mesh=stack_mesh([TOP, 80.0, BASE], [-1, 1, 1]), **MARNAGE
    )
    assert carved.top[0] == pytest.approx(95.0)
    assert carved.botm[0, 0] == pytest.approx(95.0)
    assert carved.botm[2, 0] == pytest.approx(BASE)
    check_layer_interfaces(carved.top, carved.botm, carved.idomain)
    rows = build_lake_connectiondata(
        None, lake_index=0, lake_cell_ids=CELLS, bedleak=1e-6, solver_mesh=carved,
        dynamic_area=True, bank_seepage=False,
    )  # fmt: skip
    assert {tuple(r[2])[0] for r in rows} == {1}
