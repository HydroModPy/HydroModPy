"""The mesh step hands the catchment outline the planner smoothed to the cell mesh.

The solver reads its cells against the catchment, and the faces of the mesh
follow the smooth outline, not the pixel staircase of ``watershed.shp``. The
cache stores the mesh as the engine built it, so the step puts the outline on
the mesh after the build and after a cache hit alike.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from rasterio.features import shapes
from rasterio.transform import Affine
from shapely.geometry import Polygon, box, shape

from hydromodpy.core.state.run_state import WorkflowContext
from hydromodpy.spatial.mesh.config.mesh import MeshConfig
from hydromodpy.spatial.mesh.planning import PlanningInputs, smoothed_catchment
from hydromodpy.workflow.steps.mesh import step_mesh
from tests._helpers.mesh_cases import L93_ORIGIN, LAMBERT93_WKT, grid_spec, planning_inputs

X0, Y0 = L93_ORIGIN
PIXEL, N = 50.0, 20
_FACE = {"watershed_boundary": "face"}


def _staircase() -> Polygon:
    rows, cols = np.mgrid[0:N, 0:N]
    x = (cols + 0.5) * PIXEL - 0.5 * N * PIXEL
    y = (N - rows - 0.5) * PIXEL - 0.5 * N * PIXEL
    mask = np.hypot(x, 0.8 * y) < 0.35 * N * PIXEL
    transform = Affine(PIXEL, 0.0, X0, 0.0, -PIXEL, Y0 + N * PIXEL)
    parts = [
        shape(geometry)
        for geometry, value in shapes(
            mask.astype("uint8"), mask=mask, transform=transform, connectivity=4
        )
        if value == 1
    ]
    return max(parts, key=lambda part: part.area)


@pytest.fixture
def inputs(use_planning_inputs) -> PlanningInputs:
    grid = grid_spec(N, N, PIXEL, xmin=X0, ymin=Y0, crs_wkt=LAMBERT93_WKT)
    return use_planning_inputs(planning_inputs(grid, watershed=_staircase(), synthetic=False))


def _context(tmp_path, mesh: MeshConfig) -> WorkflowContext:
    ctx = WorkflowContext(cfg=SimpleNamespace(mesh=mesh), config_path="config.toml", raw_toml={})
    ctx.setup.workspace = SimpleNamespace(project_root=tmp_path)
    return ctx


def test_the_cell_mesh_carries_the_outline_the_planner_smoothed(
    tmp_path, graded_engine, inputs
) -> None:
    mesh_cfg = MeshConfig(engine=graded_engine.engine_id, cell_size=50.0, families=_FACE)
    ctx = _context(tmp_path, mesh_cfg)

    step_mesh(ctx)

    outline = ctx.setup.cell_mesh.smoothed_catchment
    assert outline is not None
    assert outline.equals(smoothed_catchment(mesh_cfg, inputs))
    assert outline.area != inputs.watershed.area
    assert len(outline.exterior.coords) < len(inputs.watershed.exterior.coords)


def test_a_mesh_read_from_the_cache_carries_it_too(tmp_path, graded_engine, inputs) -> None:
    mesh_cfg = MeshConfig(engine=graded_engine.engine_id, cell_size=50.0, families=_FACE)
    first, second = _context(tmp_path, mesh_cfg), _context(tmp_path, mesh_cfg)

    step_mesh(first)
    step_mesh(second)

    assert graded_engine.builds == 1
    assert second.setup.cell_mesh.smoothed_catchment.equals(
        first.setup.cell_mesh.smoothed_catchment
    )
    assert second.setup.cell_mesh.smoothed_catchment is not None


def test_a_mesh_that_does_not_follow_the_catchment_carries_none(
    tmp_path, graded_engine, inputs
) -> None:
    ctx = _context(tmp_path, MeshConfig(engine=graded_engine.engine_id, cell_size=50.0))

    step_mesh(ctx)

    assert ctx.setup.cell_mesh.smoothed_catchment is None


def test_a_regular_mesh_carries_none(tmp_path, inputs) -> None:
    ctx = _context(tmp_path, MeshConfig(families=_FACE))

    step_mesh(ctx)

    assert ctx.setup.cell_mesh.smoothed_catchment is None


def test_the_outline_is_put_on_the_mesh_without_losing_its_geometry() -> None:
    from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

    cell_mesh = solver_mesh_from_structured_arrays(
        nrow=3, ncol=3, top=np.zeros((3, 3)), botm=np.zeros((1, 3, 3))
    ).cell_mesh
    geometry = cell_mesh.geometry
    outline = box(0.0, 0.0, 2.0, 2.0)

    carried = cell_mesh.with_smoothed_catchment(outline)

    assert carried.smoothed_catchment is outline
    assert carried.geometry is geometry
    assert cell_mesh.smoothed_catchment is None
