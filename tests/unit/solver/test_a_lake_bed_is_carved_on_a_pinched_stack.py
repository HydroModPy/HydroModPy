"""``carve_lake_bed`` on a layer stack with pass-through cells.

The stacks are those of a layering by surfaces after the pinch-out: a pass-through
cell (``idomain = -1``) has no thickness and the active cell next to it holds it.
The cap above the carved bed takes its pass-through cells, which the lake mask
closes. Below the bed a pass-through cell stays flat, so the first active cell
under the lake has its top on the carved bed, the elevation the reconstruction
records and the floor MODFLOW 6 gives the lake. A column with no cell under its
top one but pass-through cells is refused.

The bathymetry is flat and not reconciled to an abacus, so every lake cell gets
the same bed.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from hydromodpy.core.vertical_column import check_layer_interfaces
from hydromodpy.physics.flow.sinks_sources.lake import BathymetryReconstructionConfig
from hydromodpy.solver.modflow6.builders import (
    apply_lake_idomain_mask,
    build_lake_connectiondata,
    carve_lake_bed,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

_EXTENT = 100.0
_NCELL = 10
CELLS = list(range(_NCELL * _NCELL))
TOP = 100.0
BASE = 10.0


def _write_flat_raster(path, value: float, n: int = 20) -> None:
    import rasterio
    from rasterio.transform import from_bounds

    with rasterio.open(
        str(path),
        "w",
        driver="GTiff",
        height=n,
        width=n,
        count=1,
        dtype="float32",
        crs="EPSG:2154",
        transform=from_bounds(0.0, 0.0, _EXTENT, _EXTENT, n, n),
        nodata=-9999.0,
    ) as dst:
        dst.write(np.full((n, n), value, dtype="float32"), 1)


def _stack(botm: list[float], idomain: list[int]) -> SolverMesh:
    """A 10 x 10 grid whose every column holds the same three layers."""
    shape = (_NCELL, _NCELL)
    mesh = solver_mesh_from_structured_arrays(
        nrow=_NCELL,
        ncol=_NCELL,
        top=np.full(shape, TOP),
        botm=np.stack([np.full(shape, b) for b in botm]),
        dx=10.0,
        dy=10.0,
    )
    column = np.asarray(idomain, dtype=int).reshape(-1, 1)
    return dataclasses.replace(mesh, idomain=np.repeat(column, len(CELLS), axis=1))


class _Model:
    def __init__(self, payload: dict) -> None:
        self.flow = type(
            "Flow", (), {"active_bc": ["lake"], "sinks_sources": {"lakes": {"lac0": payload}}}
        )()


def _carve(tmp_path, mesh: SolverMesh, bed: float, *, dynamic_area: bool = False):
    raster = tmp_path / "lake_bathymetry_lac0.tif"
    _write_flat_raster(raster, bed)
    model = _Model(
        {
            "bedleak": 1.0e-6,
            "bathymetry": str(raster),
            "bed_reconstruction": BathymetryReconstructionConfig(
                reconcile_to_abacus=False, dynamic_area=dynamic_area
            ),
            "occupied_layers": 1,
        }
    )
    carved = carve_lake_bed(
        model, mesh, lake_cell_ids_by_lake={"lac0": CELLS}, occupied_layers_by_lake={"lac0": 1}
    )
    return model, carved


def _vertical_top(model, carved: SolverMesh) -> set[float]:
    """Top of the cell each VERTICAL connection leaks into, the floor MODFLOW 6 gives it."""
    occupied = model._lake_occupied_layers_by_cell["lac0"]
    masked = apply_lake_idomain_mask(
        carved, lake_cell_ids_by_lake={"lac0": CELLS}, occupied_layers_by_cell={"lac0": occupied}
    )
    rows = build_lake_connectiondata(
        None,
        lake_index=0,
        lake_cell_ids=CELLS,
        bedleak=1e-6,
        solver_mesh=masked,
        occupied_layers_by_cell=occupied,
    )
    tops = set()
    for row in rows:
        if row[3] == "VERTICAL":
            lay, cid = row[2]
            tops.add(round(float(masked.botm[lay - 1, cid]), 9))
    return tops


def test_a_pass_through_cell_under_the_bed_stays_flat_on_the_bed(tmp_path) -> None:
    mesh = _stack([92.0, 92.0, BASE], [1, -1, 1])
    model, carved = _carve(tmp_path, mesh, 95.0)

    np.testing.assert_allclose(carved.botm[:, 0], [95.0, 95.0, BASE])
    assert set(model._lake_occupied_layers_by_cell["lac0"].values()) == {1}
    assert model._lake_bed_reconstruction["lac0"]["bed_by_cell"][0] == pytest.approx(95.0)
    assert _vertical_top(model, carved) == {95.0}
    check_layer_interfaces(carved.top, carved.botm, carved.idomain)


def test_a_bed_under_the_pinched_layer_takes_it_into_the_cap(tmp_path) -> None:
    mesh = _stack([92.0, 92.0, BASE], [1, -1, 1])
    model, carved = _carve(tmp_path, mesh, 80.0)

    assert set(model._lake_occupied_layers_by_cell["lac0"].values()) == {2}
    assert carved.botm[1, 0] == pytest.approx(80.0)
    assert _vertical_top(model, carved) == {80.0}


def test_a_pinched_top_layer_becomes_the_lake_cap(tmp_path) -> None:
    mesh = _stack([TOP, 80.0, BASE], [-1, 1, 1])
    model, carved = _carve(tmp_path, mesh, 95.0)

    assert set(model._lake_occupied_layers_by_cell["lac0"].values()) == {1}
    assert carved.botm[0, 0] == pytest.approx(95.0)
    assert carved.botm[1, 0] < 95.0
    assert _vertical_top(model, carved) == {95.0}


def test_a_column_pinched_out_under_its_top_layer_is_refused(tmp_path) -> None:
    mesh = _stack([BASE, BASE, BASE], [1, -1, -1])
    with pytest.raises(ValueError, match=r"lakes\.lac0 bed_reconstruction: column 0 has no layer"):
        _carve(tmp_path, mesh, 95.0)


def test_a_marnage_bed_keeps_a_pinched_top_layer_flat(tmp_path) -> None:
    mesh = _stack([TOP, 80.0, BASE], [-1, 1, 1])
    _, carved = _carve(tmp_path, mesh, 95.0, dynamic_area=True)

    assert carved.top[0] == pytest.approx(95.0)
    assert carved.botm[0, 0] == pytest.approx(95.0)
    assert carved.botm[2, 0] == pytest.approx(BASE)
    check_layer_interfaces(carved.top, carved.botm, carved.idomain)
    rows = build_lake_connectiondata(
        None,
        lake_index=0,
        lake_cell_ids=CELLS,
        bedleak=1e-6,
        solver_mesh=carved,
        dynamic_area=True,
        bank_seepage=False,
    )
    assert {tuple(r[2])[0] for r in rows} == {1}
