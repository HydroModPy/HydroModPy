"""A synthetic domain gives neither a catchment polygon nor an outlet.

A synthetic geographic writes its box as ``watershed_shp`` for the data masks
and the figures. That box is the domain. Read as a catchment, it made the build
take the most drained cell inside it and its basin of D, 12 cells of 960 on the
flat Brutsaert case, and every synthetic run carried a ``catchment`` budget row
on those few cells. Now the basin of a synthetic domain is only its largest
basin, which closes no catchment: its runs carry the domain row alone, its
discharge observable sums the whole domain and the network criterion has no
delineated catchment to close on.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np

from hydromodpy.catchment.synthetic.catchment import build_synthetic_geographic
from hydromodpy.catchment.synthetic.synthetic_config import (
    LinearTopography,
    SyntheticGeographicConfig,
    SyntheticGridConfig,
)
from hydromodpy.model.domain.geometry import CatchmentGeometry
from hydromodpy.model.model import Geometry
from hydromodpy.solver.modflow_common.catchment_basin import catchment_cell_mask, run_basin
from hydromodpy.solver.modflow_common.descent_store import write_descent_sidecar
from hydromodpy.solver.modflow_common.flow_directions import build_solver_mesh_descent
from hydromodpy.solver.modflow_nwt.extractors.flow import catchment_basin_the_build_left
from tests._helpers.model_factory import make_model
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

N = 10
DX = 10.0


def _geographic(tmp_path: Path):
    config = SyntheticGeographicConfig(
        case_id="tilted",
        grid=SyntheticGridConfig(
            length_x=f"{N * DX} m", length_y=f"{N * DX} m", nx=N, ny=N, xmin=0.0, ymin=0.0
        ),
        topography=LinearTopography(base_elevation=20.0, right_to_left_amplitude=5.0),
    )
    return build_synthetic_geographic(config=config, output_dir=tmp_path / "synthetic")


def _catchment(geographic) -> CatchmentGeometry:
    """Where the catchment closes, as the ``Model`` of the run carries it."""
    return CatchmentGeometry.from_geographic(geographic, crs=None)


def _mesh(geographic):
    top = np.asarray(geographic.surface_topo.as_array(), dtype=float)
    return solver_mesh_from_structured_arrays(
        nrow=N, ncol=N, top=top, botm=np.full((1, N, N), 0.0), dx=DX, dy=DX
    )


def test_a_synthetic_run_carries_the_domain_row_alone(tmp_path) -> None:
    geographic = _geographic(tmp_path)
    mesh = _mesh(geographic)
    descent = build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=None)
    basin = run_basin(_catchment(geographic), mesh, descent)
    write_descent_sidecar(descent, tmp_path, "flow", basin=basin)

    assert catchment_basin_the_build_left(tmp_path, n_cells=N * N) is None


def test_the_discharge_of_a_synthetic_domain_sums_the_whole_domain(tmp_path) -> None:
    geographic = _geographic(tmp_path)
    mesh = _mesh(geographic)
    descent = build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=None)
    model = SimpleNamespace(
        model_name="flow",
        inputs=make_model(
            geometry=Geometry(cells=None, domain=None, catchment=_catchment(geographic))
        ),
        solver_mesh=mesh,
        descent_basin=run_basin(_catchment(geographic), mesh, descent),
    )

    mask = catchment_cell_mask(model)

    np.testing.assert_array_equal(mask, np.ones(N * N, dtype=bool))
