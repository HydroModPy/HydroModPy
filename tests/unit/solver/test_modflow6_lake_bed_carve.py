"""Bathymetry bed carving on a real SolverMesh, reconciled to the abacus.

``carve_lake_bed`` resamples a bathymetry raster onto the lake cells, reconciles
it to the abacus by area-weighted quantile mapping, and re-grades each lake
column so the bottom of the occupied layer sits at the carved bed. The simulated
abacus of the carved bed must reproduce the input abacus, and every carved column
must stay a valid prism (strictly decreasing bottoms, fixed aquifer base).
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.physics.flow.sinks_sources.lake import BathymetryReconstructionConfig
from hydromodpy.solver.modflow6.builders import build_lake_connectiondata, carve_lake_bed
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.lake_bed import simulate_abacus

_EXTENT = 100.0
_NCELL = 10  # 10 x 10 structured grid, dx = dy = 10 -> cell area 100, footprint 10000


def _write_raster(path, bed: np.ndarray) -> None:
    """Write a single-band GeoTIFF bed over [0, 100]^2."""
    import rasterio
    from rasterio.transform import from_bounds

    n = bed.shape[0]
    transform = from_bounds(0.0, 0.0, _EXTENT, _EXTENT, n, n)
    with rasterio.open(
        str(path),
        "w",
        driver="GTiff",
        height=n,
        width=n,
        count=1,
        dtype="float32",
        crs="EPSG:2154",
        transform=transform,
        nodata=-9999.0,
    ) as dst:
        dst.write(bed.astype("float32"), 1)


def _write_bowl_raster(path, *, n=100):
    """Write a fine GeoTIFF bowl bed over [0, 100]^2 (deep centre ~20, rim ~60)."""
    dx = _EXTENT / n
    x = (np.arange(n) + 0.5) * dx
    y = _EXTENT - (np.arange(n) + 0.5) * dx
    gx, gy = np.meshgrid(x, y)
    r2 = (gx - 50.0) ** 2 + (gy - 50.0) ** 2
    _write_raster(path, 60.0 - 40.0 * np.exp(-r2 / (2.0 * 30.0**2)))


def _write_flat_raster(path, value: float, *, n=100):
    """Write a flat GeoTIFF bed at ``value`` over [0, 100]^2."""
    _write_raster(path, np.full((n, n), float(value)))


def _mesh() -> SolverMesh:
    top = np.full((_NCELL, _NCELL), 100.0)
    botm = np.stack(
        [
            np.full((_NCELL, _NCELL), 70.0),
            np.full((_NCELL, _NCELL), 40.0),
            np.full((_NCELL, _NCELL), 10.0),
        ]
    )
    return SolverMesh.from_structured_arrays(
        nrow=_NCELL, ncol=_NCELL, top=top, botm=botm, dx=10.0, dy=10.0
    )


class _Flow:
    def __init__(self, lakes):
        self.active_bc = ["lake"]
        self.sinks_sources = {"lakes": lakes}


class _Model:
    def __init__(self, lakes):
        self.flow = _Flow(lakes)


def _abacus():
    stage = [20.0, 30.0, 40.0, 50.0, 60.0]
    sarea = [0.0, 2500.0, 5000.0, 7500.0, 10000.0]
    volume = [0.0, 12500.0, 50000.0, 112500.0, 200000.0]
    return {"stage": stage, "sarea": sarea, "volume": volume}


def test_carve_reconciles_to_abacus_and_keeps_valid_columns(tmp_path):
    raster = tmp_path / "lake_bathymetry_lac0.tif"
    _write_bowl_raster(raster)
    abacus = _abacus()
    payload = {
        "bedleak": 1.0e-6,
        "bathymetry": str(raster),
        "abacus": abacus,
        "bed_reconstruction": BathymetryReconstructionConfig(),
        "occupied_layers": 1,
    }
    model = _Model({"lac0": payload})
    mesh = _mesh()
    cell_ids = list(range(_NCELL * _NCELL))

    carved = carve_lake_bed(
        model,
        mesh,
        lake_cell_ids_by_lake={"lac0": cell_ids},
        occupied_layers_by_lake={"lac0": 1},
    )

    # Top is untouched; the frozen source mesh survives.
    assert np.allclose(carved.top, 100.0)
    assert np.allclose(mesh.botm, _mesh().botm)

    # Every carved column is a valid prism: strictly decreasing, base preserved.
    for cid in cell_ids:
        col = carved.botm[:, cid]
        assert np.all(np.diff(col) < 0.0)
        assert col[-1] == 10.0  # aquifer base unchanged
        assert carved.top[cid] > col[0]

    # The reconstruction is stashed for the figure.
    recon = model._lake_bed_reconstruction["lac0"]
    bed = recon["bed_by_cell"]
    area = recon["area_by_cell"]
    assert recon["diagnostics"]["area_scale"] == 1.0  # footprint == abacus top area

    # The carved bed is a real basin, not a flat reservoir: the centre cell
    # (row 5, col 5 -> id 55) sits deeper than a rim cell (id 0).
    assert bed[55] < bed[0]
    # occupied_layers is per cell: each column pins its bed at botm[occ_c - 1] and
    # a deeper cell cuts at least as many layers as a shallower one.
    occ_by_cell = model._lake_occupied_layers_by_cell["lac0"]
    for cid in (0, 55):
        occ_c = occ_by_cell[cid]
        assert carved.botm[occ_c - 1, cid] == pytest.approx(bed[cid], abs=1e-6)
    assert occ_by_cell[55] >= occ_by_cell[0]

    # The simulated abacus reproduces the input abacus.
    sim = simulate_abacus(bed_by_cell=bed, area_by_cell=area, stages=abacus["stage"])
    target_sarea = np.array(abacus["sarea"])
    assert np.max(np.abs(sim["sarea"] - target_sarea)) <= 3.0 * 100.0  # within ~3 cells
    target_vol = np.array(abacus["volume"])
    denom = np.sum((target_vol - target_vol.mean()) ** 2)
    nse = 1.0 - np.sum((sim["volume"] - target_vol) ** 2) / denom
    assert nse > 0.99


def test_carved_mesh_builds_a_valid_disv(tmp_path):
    """flopy accepts the carved + masked geometry as a DISV package."""
    import flopy

    from hydromodpy.solver.modflow6.builders import apply_lake_idomain_mask

    raster = tmp_path / "lake_bathymetry_lac0.tif"
    _write_bowl_raster(raster)
    payload = {
        "bedleak": 1.0e-6,
        "bathymetry": str(raster),
        "abacus": _abacus(),
        "bed_reconstruction": BathymetryReconstructionConfig(),
        "occupied_layers": 1,
    }
    model = _Model({"lac0": payload})
    cell_ids = list(range(_NCELL * _NCELL))
    carved = carve_lake_bed(
        model,
        _mesh(),
        lake_cell_ids_by_lake={"lac0": cell_ids},
        occupied_layers_by_lake={"lac0": 1},
    )
    masked = apply_lake_idomain_mask(carved, lake_cell_ids_by_lake={"lac0": cell_ids})

    sim = flopy.mf6.MFSimulation(sim_name="carve", sim_ws=str(tmp_path))
    flopy.mf6.ModflowTdis(sim, nper=1, perioddata=[(1.0, 1, 1.0)])
    gwf = flopy.mf6.ModflowGwf(sim, modelname="carve")
    disv = flopy.mf6.ModflowGwfdisv(
        gwf,
        nlay=masked.nlay,
        **masked.to_disv_kwargs(),
        idomain=masked.idomain(),
        xorigin=0.0,
        yorigin=0.0,
        length_units="METERS",
    )
    # flopy ingested the carved geometry; the package botm equals the carved botm
    # and every layer stays strictly below the one above (DISV requirement).
    botm = np.asarray(disv.botm.array)
    assert botm.shape == (masked.nlay, masked.n_cells)
    assert np.allclose(botm, masked.botm)
    tops = np.vstack([np.asarray(disv.top.array).reshape(1, -1), botm[:-1]])
    assert np.all(botm < tops)


def test_carve_marnage_keeps_cells_active_with_bed_as_top(tmp_path):
    """Active-littoral mode sets cell top = bed, keeps the column active, flags marnage."""
    raster = tmp_path / "lake_bathymetry_lac0.tif"
    _write_bowl_raster(raster)
    payload = {
        "bedleak": 1.0e-6,
        "bathymetry": str(raster),
        "bed_reconstruction": BathymetryReconstructionConfig(
            dynamic_area=True, reconcile_to_abacus=False
        ),
        "occupied_layers": 1,
    }
    model = _Model({"lac0": payload})
    mesh = _mesh()
    cell_ids = list(range(_NCELL * _NCELL))
    carved = carve_lake_bed(
        model,
        mesh,
        lake_cell_ids_by_lake={"lac0": cell_ids},
        occupied_layers_by_lake={"lac0": 1},
    )

    assert model._marnage_lake_ids == {"lac0"}
    # The cell TOP became the bathymetric bed (a real basin: centre deeper than rim).
    assert carved.top[55] < carved.top[0]
    assert carved.top[55] < 100.0
    # Columns stay valid prisms with the aquifer base preserved; nothing deactivated.
    for cid in cell_ids:
        col = carved.botm[:, cid]
        assert np.all(np.diff(col) < 0.0)
        assert col[0] < carved.top[cid]
        assert col[-1] == 10.0


def test_marnage_connectiondata_is_one_vertical_per_active_cell(tmp_path):
    """The marnage LAK connectiondata is exactly one VERTICAL connection per cell."""
    raster = tmp_path / "lake_bathymetry_lac0.tif"
    _write_bowl_raster(raster)
    payload = {
        "bedleak": 1.0e-6,
        "bathymetry": str(raster),
        "bed_reconstruction": BathymetryReconstructionConfig(
            dynamic_area=True, reconcile_to_abacus=False
        ),
        "occupied_layers": 1,
    }
    model = _Model({"lac0": payload})
    cell_ids = list(range(_NCELL * _NCELL))
    carved = carve_lake_bed(
        model,
        _mesh(),
        lake_cell_ids_by_lake={"lac0": cell_ids},
        occupied_layers_by_lake={"lac0": 1},
    )
    rows = build_lake_connectiondata(
        model,
        lake_index=0,
        lake_cell_ids=cell_ids,
        bedleak=1.0e-6,
        solver_mesh=carved,
        dynamic_area=True,
    )
    assert len(rows) == len(cell_ids)
    assert all(row[3] == "VERTICAL" for row in rows)
    # Each connection is on the cell itself at layer 0 (the active littoral cell).
    assert {row[2] for row in rows} == {(0, cid) for cid in cell_ids}


def test_record_holds_the_carved_bed_when_the_clamp_bites(tmp_path, caplog):
    """The stashed bed is the one the grid carries, not the bathymetric request.

    A ``min_thickness`` wide enough to bite forces the re-grade to clamp the bed
    into the band the column can hold. Everything downstream of the record (the
    simulated abacus, the exposed-band runoff) reasons about the grid, so the
    record must follow the grid and the shift must be reported.
    """
    raster = tmp_path / "lake_bathymetry_lac0.tif"
    _write_bowl_raster(raster)
    payload = {
        "bedleak": 1.0e-6,
        "bathymetry": str(raster),
        "bed_reconstruction": BathymetryReconstructionConfig(
            min_thickness=25.0, reconcile_to_abacus=False
        ),
        "occupied_layers": 1,
    }
    model = _Model({"lac0": payload})
    cell_ids = list(range(_NCELL * _NCELL))
    with caplog.at_level("WARNING"):
        carved = carve_lake_bed(
            model,
            _mesh(),
            lake_cell_ids_by_lake={"lac0": cell_ids},
            occupied_layers_by_lake={"lac0": 1},
        )

    recon = model._lake_bed_reconstruction["lac0"]
    bed = recon["bed_by_cell"]
    occ_by_cell = model._lake_occupied_layers_by_cell["lac0"]

    # The clamp bit: the deep centre cannot hold a 25 m cap plus a 25 m aquifer.
    assert recon["diagnostics"]["bed_clamp_shift_max"] > 1.0
    assert "min_thickness clamp moved the carved bed" in caplog.text

    # Every recorded bed is exactly the bottom of its deepest occupied layer.
    for cid in cell_ids:
        assert bed[cid] == pytest.approx(carved.botm[occ_by_cell[cid] - 1, cid], abs=1e-9)


def test_marnage_record_holds_the_clamped_top(tmp_path):
    """In active-littoral mode the recorded bed is the cell top MF6 wets and dries."""
    raster = tmp_path / "lake_bathymetry_lac0.tif"
    _write_bowl_raster(raster)
    payload = {
        "bedleak": 1.0e-6,
        "bathymetry": str(raster),
        "bed_reconstruction": BathymetryReconstructionConfig(
            dynamic_area=True, reconcile_to_abacus=False, min_thickness=25.0
        ),
        "occupied_layers": 1,
    }
    model = _Model({"lac0": payload})
    cell_ids = list(range(_NCELL * _NCELL))
    carved = carve_lake_bed(
        model,
        _mesh(),
        lake_cell_ids_by_lake={"lac0": cell_ids},
        occupied_layers_by_lake={"lac0": 1},
    )

    bed = model._lake_bed_reconstruction["lac0"]["bed_by_cell"]
    for cid in cell_ids:
        assert bed[cid] == pytest.approx(carved.top[cid], abs=1e-9)


def test_marnage_top_follows_a_bed_that_reaches_the_terrain(tmp_path):
    """A bed at the DEM keeps the cell top at the DEM: nothing sits above it.

    In active-littoral mode the cell top IS the bed and all layers live below it,
    so the terrain ceiling must reserve no thickness. Reserving one would drop
    every cell whose bathymetry reaches the terrain by ``min_thickness`` and
    deepen the cuvette for free.
    """
    raster = tmp_path / "lake_bathymetry_lac0.tif"
    _write_flat_raster(raster, 100.0)
    min_thickness = 5.0
    payload = {
        "bedleak": 1.0e-6,
        "bathymetry": str(raster),
        "bed_reconstruction": BathymetryReconstructionConfig(
            dynamic_area=True, reconcile_to_abacus=False, min_thickness=min_thickness
        ),
        "occupied_layers": 1,
    }
    model = _Model({"lac0": payload})
    cell_ids = list(range(_NCELL * _NCELL))
    carved = carve_lake_bed(
        model,
        _mesh(),
        lake_cell_ids_by_lake={"lac0": cell_ids},
        occupied_layers_by_lake={"lac0": 1},
    )

    assert np.allclose(carved.top, 100.0)
    assert model._lake_bed_reconstruction["lac0"]["diagnostics"]["bed_clamp_shift_max"] == 0.0
    for cid in cell_ids:
        col = carved.botm[:, cid]
        thickness = np.concatenate(([carved.top[cid]], col[:-1])) - col
        assert np.all(thickness >= min_thickness - 1e-9)
        assert col[-1] == 10.0


def test_carve_is_noop_without_bed_reconstruction(tmp_path):
    payload = {"bedleak": 1.0e-6, "occupied_layers": 1}
    model = _Model({"lac0": payload})
    mesh = _mesh()
    carved = carve_lake_bed(
        model,
        mesh,
        lake_cell_ids_by_lake={"lac0": [0, 1, 2]},
        occupied_layers_by_lake={"lac0": 1},
    )
    assert carved is mesh
    assert not hasattr(model, "_lake_bed_reconstruction")
