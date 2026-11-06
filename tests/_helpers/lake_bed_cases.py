"""Lake-bed cases: a quad mesh, bathymetry rasters, a column stack and a carve."""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import numpy as np

from hydromodpy.spatial.raster_support import RasterSupport
from hydromodpy.spatial.surface import Surface
from tests._helpers.geotiffs import write_geotiff

EXTENT = 100.0
NCELL = 10
"""The solver mesh is NCELL x NCELL cells of 10 m over [0, EXTENT]^2."""
CELLS = list(range(NCELL * NCELL))
TOP = 100.0
BASE = 10.0


def quad_mesh(*, dx: float, dy: float, ncol: int, nrow: int, xmin=0.0, ymin=0.0):
    """A planar mesh double: vertices and one quad per cell, row by row from the south."""
    xs, ys = np.meshgrid(xmin + dx * np.arange(ncol + 1), ymin + dy * np.arange(nrow + 1))
    vid = np.arange((nrow + 1) * (ncol + 1)).reshape(nrow + 1, ncol + 1)
    quads = np.stack([vid[:-1, :-1], vid[:-1, 1:], vid[1:, 1:], vid[1:, :-1]], axis=-1)
    return SimpleNamespace(
        vertices=np.column_stack([xs.ravel(), ys.ravel()]).astype(float),
        flat_connectivity=quads.reshape(-1, 4),
    )


def ramp_surface(*, extent: float = EXTENT, n: int = 100, crs: str | None = None) -> Surface:
    """A fine raster of the plane z = x, north-up, over [0, extent]^2."""
    dx = extent / n
    values = np.tile((np.arange(n) + 0.5) * dx, (n, 1))
    support = RasterSupport(
        crs=crs, dx=dx, dy=dx, xmin=0.0, xmax=extent, ymin=0.0, ymax=extent, nrows=n, ncols=n
    )
    return Surface(name="bathy", values=values, support=support)


def bowl_bed(n: int = 100) -> np.ndarray:
    """A bowl over [0, 100]^2, about 20 m at the center and 60 m at the rim."""
    centres = (np.arange(n) + 0.5) * EXTENT / n
    gx, gy = np.meshgrid(centres, centres[::-1])
    return 60.0 - 40.0 * np.exp(-((gx - 50.0) ** 2 + (gy - 50.0) ** 2) / (2.0 * 30.0**2))


def write_bed(path, bed) -> str:
    """Write a bed raster over [0, 100]^2; a scalar *bed* is a flat 20 x 20 raster."""
    values = np.full((20, 20), float(bed)) if np.isscalar(bed) else np.asarray(bed)
    cell = EXTENT / values.shape[0]
    return str(write_geotiff(path, values, cell=cell, nodata=-9999.0, dtype="float32"))


def stack_mesh(botm=(70.0, 40.0, BASE), idomain=None):
    """The solver mesh, every column holding the same layers under a 100 m top."""
    from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

    shape = (NCELL, NCELL)
    mesh = solver_mesh_from_structured_arrays(
        nrow=NCELL, ncol=NCELL, top=np.full(shape, TOP),
        botm=np.stack([np.full(shape, b) for b in botm]), dx=10.0, dy=10.0,
    )  # fmt: skip
    if idomain is None:
        return mesh
    column = np.asarray(idomain, dtype=int).reshape(-1, 1)
    return dataclasses.replace(mesh, idomain=np.repeat(column, len(CELLS), axis=1))


def lake_model(payload: dict) -> SimpleNamespace:
    """The model double ``carve_lake_bed`` reads: one active lake ``lac0``."""
    flow = SimpleNamespace(active_bc=["lake"], sinks_sources={"lakes": {"lac0": payload}})
    return SimpleNamespace(flow=flow)


def abacus() -> dict[str, list[float]]:
    """A cone abacus whose top area is the 10 000 m2 footprint of the mesh."""
    stage = np.arange(20.0, 61.0, 10.0)
    sarea = 250.0 * (stage - 20.0)
    return {"stage": stage.tolist(), "sarea": sarea.tolist(), "volume": (sarea * (stage - 20.0) / 2).tolist()}  # fmt: skip


def carve(tmp_path, bed, *, mesh=None, with_abacus=False, **config):
    """Carve lake ``lac0`` over every cell of *mesh*; *config* is the bed reconstruction's."""
    from hydromodpy.physics.flow.sinks_sources.lake import BathymetryReconstructionConfig
    from hydromodpy.solver.modflow6.builders.lake_cells import carve_lake_bed

    payload = {
        "bedleak": 1.0e-6,
        "bathymetry": write_bed(tmp_path / "lake_bathymetry_lac0.tif", bed),
        "bed_reconstruction": BathymetryReconstructionConfig(**config),
        "occupied_layers": 1,
    }
    if with_abacus:
        payload["abacus"] = abacus()
    model = lake_model(payload)
    carved = carve_lake_bed(
        model,
        stack_mesh() if mesh is None else mesh,
        lake_cell_ids_by_lake={"lac0": CELLS},
        occupied_layers_by_lake={"lac0": 1},
    )
    return model, carved


def nse(simulated, target) -> float:
    """Nash-Sutcliffe efficiency of *simulated* against *target*."""
    target = np.asarray(target, dtype=float)
    return 1.0 - np.sum((simulated - target) ** 2) / np.sum((target - target.mean()) ** 2)
