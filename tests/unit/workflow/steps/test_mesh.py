"""The mesh step."""

from __future__ import annotations

import dataclasses
import logging
import shutil
import tomllib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from rasterio.features import shapes
from rasterio.transform import Affine
from shapely.geometry import Polygon, box, shape

from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.exceptions import ConfigError, MeshError
from hydromodpy.core.state.run_state import WorkflowContext
from hydromodpy.results.catalog.registration import config_identity_hash
from hydromodpy.results.run.field_envelope import read_run_fields
from hydromodpy.results.storage.attempt import _config_changed
from hydromodpy.results.storage.contract import RUN_CONFIG_FILENAME
from hydromodpy.results.storage.sealing import seal_completed
from hydromodpy.spatial.mesh import cache as cache_module
from hydromodpy.spatial.mesh.cache import cache_dir, library_versions
from hydromodpy.spatial.mesh.engines.regular.engine import RegularMeshEngine
from hydromodpy.spatial.mesh.mesh_config import MeshConfig
from hydromodpy.spatial.mesh.planning.inputs import PlanningInputs
from hydromodpy.spatial.mesh.planning.plan import smoothed_catchment
from hydromodpy.spatial.mesh.planning.refinement_zones import (
    CriterionInputs,
    RefinementZone,
    load_refinement_zones,
)
from hydromodpy.spatial.mesh.refinement_config import RefinementZoneConfig
from hydromodpy.workflow.state import PipelineState
from hydromodpy.workflow.steps import mesh as mesh_module
from hydromodpy.workflow.steps.mesh import BuildMeshStep, step_mesh, zone_runs
from hydromodpy.workflow.steps.prepare_solver.freeze import (
    freeze_run_config,
    frozen_config_document,
)
from tests._helpers.fake_engines import FakeMeshEngine, registered
from tests._helpers.mesh_cases import L93_ORIGIN, LAMBERT93_WKT, grid_spec, planning_inputs
from tests._helpers.run_stores import open_run_store

# --- test_the_mesh_step_dispatches_by_engine ---
# The mesh step plans one request, builds it with the engine of [mesh], and caches what needs it.

X0, Y0 = L93_ORIGIN


SIDE, N = 1000.0, 10


@pytest.fixture
def planned_inputs(use_planning_inputs):
    grid = grid_spec(N, N, SIDE / N, xmin=X0, ymin=Y0, crs_wkt=LAMBERT93_WKT)
    use_planning_inputs(planning_inputs(grid))


def _context(tmp_path, mesh: MeshConfig | None, *, workspace: bool = True) -> WorkflowContext:
    ctx = WorkflowContext(cfg=SimpleNamespace(mesh=mesh), config_path="config.toml", raw_toml={})
    if workspace:
        ctx.setup.workspace = SimpleNamespace(project_root=tmp_path)
    return ctx


@pytest.mark.usefixtures("planned_inputs")
def test_a_run_without_mesh_section_gets_the_regular_grid_and_no_cache(tmp_path) -> None:
    ctx = _context(tmp_path, None)

    step_mesh(ctx)

    assert ctx.setup.cell_mesh.structured_shape == (N, N)
    summary = ctx.setup.mesh_summary
    assert summary["engine"] == "regular"
    assert summary["cache_key"] is None
    assert summary["request_hash"] == ctx.setup.cell_mesh.identity.request_hash
    assert summary["qa"]["n_cells"] == N * N
    assert not (tmp_path / ".hmp").exists()


@pytest.mark.usefixtures("planned_inputs")
def test_the_summary_names_the_library_builds_the_mesh_depends_on(tmp_path) -> None:
    ctx = _context(tmp_path, None)

    step_mesh(ctx)

    versions = ctx.setup.mesh_summary["library_versions"]
    assert set(versions) == {"gmsh", "scipy", "shapely", "geos"}
    assert versions == library_versions()
    assert all(isinstance(value, str) and value for value in versions.values())


@pytest.mark.usefixtures("planned_inputs")
def test_the_planner_notes_reach_the_qa_of_the_summary(tmp_path, use_planning_inputs) -> None:
    use_planning_inputs(
        dataclasses.replace(
            mesh_module.planning_inputs(None, None), notes=("the geology map is a raster",)
        )
    )
    ctx = _context(tmp_path, MeshConfig(river_cell_size=20.0, cell_size=200.0))

    step_mesh(ctx)

    notes = ctx.setup.mesh_summary["qa"]["notes"]
    assert "the geology map is a raster" in notes
    assert any("regular ignores river_cell_size" in note for note in notes)


@pytest.mark.usefixtures("planned_inputs")
def test_the_regular_shape_of_the_section_reaches_the_grid(tmp_path) -> None:
    ctx = _context(tmp_path, MeshConfig.model_validate({"regular": {"shape": [4, 5]}}))

    step_mesh(ctx)

    assert ctx.setup.cell_mesh.structured_shape == (4, 5)


@pytest.mark.usefixtures("planned_inputs")
def test_an_engine_that_needs_a_cache_builds_once_per_request(tmp_path, cached_engine) -> None:
    mesh_cfg = MeshConfig(engine=cached_engine.engine_id)
    first, second = _context(tmp_path, mesh_cfg), _context(tmp_path, mesh_cfg)

    step_mesh(first)
    step_mesh(second)

    assert cached_engine.builds == 1
    np.testing.assert_array_equal(
        second.setup.cell_mesh.mesh.vertices, first.setup.cell_mesh.mesh.vertices
    )
    assert second.setup.cell_mesh.identity == first.setup.cell_mesh.identity
    key = first.setup.mesh_summary["cache_key"]
    assert second.setup.mesh_summary == first.setup.mesh_summary
    assert cache_dir(tmp_path, key).is_dir()
    assert first.setup.mesh_summary["engine"] == cached_engine.engine_id


@pytest.mark.usefixtures("planned_inputs")
def test_a_changed_request_is_meshed_again_under_its_own_key(tmp_path, cached_engine) -> None:
    coarse = _context(tmp_path, MeshConfig(engine=cached_engine.engine_id, cell_size=100.0))
    fine = _context(tmp_path, MeshConfig(engine=cached_engine.engine_id, cell_size=125.0))

    step_mesh(coarse)
    step_mesh(fine)

    assert cached_engine.builds == 2
    assert coarse.setup.mesh_summary["cache_key"] != fine.setup.mesh_summary["cache_key"]
    assert len(list((tmp_path / ".hmp" / "mesh_cache").iterdir())) == 2


@pytest.mark.usefixtures("planned_inputs")
@pytest.mark.parametrize("library", ["gmsh", "scipy", "shapely", "geos"])
def test_a_new_build_of_a_library_is_meshed_again_under_its_own_key(
    tmp_path, cached_engine, monkeypatch, library
) -> None:
    mesh_cfg = MeshConfig(engine=cached_engine.engine_id)
    before = _context(tmp_path, mesh_cfg)
    step_mesh(before)
    bumped = {**library_versions(), library: "99.9.9"}
    monkeypatch.setattr(cache_module, "library_versions", lambda: bumped)
    after = _context(tmp_path, mesh_cfg)

    step_mesh(after)

    assert cached_engine.builds == 2
    assert before.setup.mesh_summary["cache_key"] != after.setup.mesh_summary["cache_key"]
    assert len(list((tmp_path / ".hmp" / "mesh_cache").iterdir())) == 2


@pytest.mark.usefixtures("planned_inputs")
def test_a_resume_that_finds_no_cache_says_the_mesh_will_differ(
    tmp_path, cached_engine, caplog
) -> None:
    ctx = _context(tmp_path, MeshConfig(engine=cached_engine.engine_id))
    caplog.set_level(logging.WARNING, logger=mesh_module.logger.name)

    step_mesh(ctx, resume=True)

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "cached mesh of this request is gone" in warnings[0]


@pytest.mark.usefixtures("planned_inputs")
def test_a_resume_reads_the_cache_a_crashed_process_left(tmp_path, cached_engine, caplog) -> None:
    mesh_cfg = MeshConfig(engine=cached_engine.engine_id)
    step_mesh(_context(tmp_path, mesh_cfg))
    fresh = _context(tmp_path, mesh_cfg)
    state = PipelineState(run_id="run-1", step_index=2, step_name="build_mesh", data={"ctx": fresh})
    caplog.set_level(logging.WARNING, logger=mesh_module.logger.name)

    advanced = BuildMeshStep().rebuild_state(prior_state=state, workspace=tmp_path, run_id="run-1")

    assert cached_engine.builds == 1
    assert fresh.setup.cell_mesh is not None
    assert advanced.step_index == 3
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]


@pytest.mark.usefixtures("planned_inputs")
def test_a_resume_keeps_the_mesh_the_process_already_holds(tmp_path) -> None:
    ctx = _context(tmp_path, None)
    step_mesh(ctx)
    held = ctx.setup.cell_mesh
    state = PipelineState(run_id="run-1", step_index=2, step_name="build_mesh", data={"ctx": ctx})

    BuildMeshStep().rebuild_state(prior_state=state, workspace=tmp_path, run_id="run-1")

    assert ctx.setup.cell_mesh is held
    assert BuildMeshStep().is_prebuilt(state)


@pytest.mark.usefixtures("planned_inputs")
def test_the_step_declares_the_cache_files_it_left(tmp_path, cached_engine) -> None:
    cached = _context(tmp_path, MeshConfig(engine=cached_engine.engine_id))
    plain = _context(tmp_path, None)
    step_mesh(cached)
    step_mesh(plain)

    declared = BuildMeshStep().artifacts(PipelineState(run_id="r", data={"ctx": cached}))

    assert len(declared) == 2
    assert all(
        cache_dir(tmp_path, cached.setup.mesh_summary["cache_key"]) in p.parents
        for p in map(Path, declared)
    )
    assert BuildMeshStep().artifacts(PipelineState(run_id="r", data={"ctx": plain})) == ()


@pytest.mark.usefixtures("planned_inputs")
def test_a_cached_engine_needs_a_workspace_to_cache_in(tmp_path, cached_engine) -> None:
    ctx = _context(tmp_path, MeshConfig(engine=cached_engine.engine_id), workspace=False)

    with pytest.raises(MeshError, match="no workspace"):
        step_mesh(ctx)


@pytest.mark.usefixtures("planned_inputs")
def test_the_step_reads_its_sections_from_the_config_names() -> None:
    step = BuildMeshStep()

    assert step.config_sections == ("domain.supports", "mesh")
    assert "mesh_section_data" not in step.reads
    assert "external_mesh_input" not in step.reads


class _ConcaveEngine(FakeMeshEngine):
    """A fake engine whose regular grid reports three concave cells."""

    engine_id = "concave_probe"
    capabilities = RegularMeshEngine.capabilities

    def build(self, request):
        built = super().build(request)
        return dataclasses.replace(built, qa=dataclasses.replace(built.qa, n_concave_cells=3))


@pytest.mark.usefixtures("planned_inputs")
def test_a_mesh_past_a_quality_threshold_is_warned_and_used(tmp_path, caplog) -> None:
    with registered(_ConcaveEngine):
        ctx = _context(tmp_path, MeshConfig(engine=_ConcaveEngine.engine_id))
        with caplog.at_level(logging.WARNING, logger=mesh_module.logger.name):
            step_mesh(ctx)

    assert ctx.setup.cell_mesh.qa.n_concave_cells == 3
    assert "Mesh quality: 3 of 100 cells are concave" in caplog.text


@pytest.mark.usefixtures("planned_inputs")
def test_a_mesh_within_the_thresholds_is_not_warned(tmp_path, caplog) -> None:
    with caplog.at_level(logging.WARNING, logger=mesh_module.logger.name):
        step_mesh(_context(tmp_path, None))

    assert "Mesh quality" not in caplog.text


# --- test_the_mesh_step_keeps_the_smoothed_outline ---
# The mesh step hands the catchment outline the planner smoothed to the cell mesh.
#
# The solver reads its cells against the catchment, and the faces of the mesh
# follow the smooth outline, not the pixel staircase of ``watershed.shp``. The
# cache stores the mesh as the engine built it, so the step puts the outline on
# the mesh after the build and after a cache hit alike.

PIXEL, OUTLINE_N = 50.0, 20


_FACE = {"watershed_boundary": "face"}


def _staircase() -> Polygon:
    rows, cols = np.mgrid[0:OUTLINE_N, 0:OUTLINE_N]
    x = (cols + 0.5) * PIXEL - 0.5 * OUTLINE_N * PIXEL
    y = (OUTLINE_N - rows - 0.5) * PIXEL - 0.5 * OUTLINE_N * PIXEL
    mask = np.hypot(x, 0.8 * y) < 0.35 * OUTLINE_N * PIXEL
    transform = Affine(PIXEL, 0.0, X0, 0.0, -PIXEL, Y0 + OUTLINE_N * PIXEL)
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
    grid = grid_spec(OUTLINE_N, OUTLINE_N, PIXEL, xmin=X0, ymin=Y0, crs_wkt=LAMBERT93_WKT)
    return use_planning_inputs(planning_inputs(grid, watershed=_staircase(), synthetic=False))


def _outline_context(tmp_path, mesh: MeshConfig) -> WorkflowContext:
    ctx = WorkflowContext(cfg=SimpleNamespace(mesh=mesh), config_path="config.toml", raw_toml={})
    ctx.setup.workspace = SimpleNamespace(project_root=tmp_path)
    return ctx


def test_the_cell_mesh_carries_the_outline_the_planner_smoothed(
    tmp_path, graded_engine, inputs
) -> None:
    mesh_cfg = MeshConfig(engine=graded_engine.engine_id, cell_size=50.0, families=_FACE)
    ctx = _outline_context(tmp_path, mesh_cfg)

    step_mesh(ctx)

    outline = ctx.setup.cell_mesh.smoothed_catchment
    assert outline is not None
    assert outline.equals(smoothed_catchment(mesh_cfg, inputs))
    assert outline.area != inputs.watershed.area
    assert len(outline.exterior.coords) < len(inputs.watershed.exterior.coords)


def test_a_mesh_read_from_the_cache_carries_it_too(tmp_path, graded_engine, inputs) -> None:
    mesh_cfg = MeshConfig(engine=graded_engine.engine_id, cell_size=50.0, families=_FACE)
    first, second = _outline_context(tmp_path, mesh_cfg), _outline_context(tmp_path, mesh_cfg)

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
    ctx = _outline_context(tmp_path, MeshConfig(engine=graded_engine.engine_id, cell_size=50.0))

    step_mesh(ctx)

    assert ctx.setup.cell_mesh.smoothed_catchment is None


def test_a_regular_mesh_carries_none(tmp_path, inputs) -> None:
    ctx = _outline_context(tmp_path, MeshConfig(families=_FACE))

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


# --- test_a_frozen_config_pins_the_run_a_refinement_zone_reads ---
# The frozen config names the run a refinement zone read by its sim_id, not by its name.
#
# A zone that reads an earlier run writes ``run = "<name>"``, and a bare name is
# the latest version of that run. After a ``.v2`` of the first run, a replay
# (``hmp catalog rerun`` reads the frozen snapshot, ``hmp run --resume`` the
# frozen file) would read the ``.v2`` and draw another mesh. The mesh step keeps
# the sim_id each zone read, and the freeze writes it in place of the name.

ZONE = {"where": "watertable_depth", "below": 0.5, "run": "coarse", "cell_size": 25.0}


def _planned(source_run: str | None) -> RefinementZone:
    return RefinementZone(
        region=box(0.0, 0.0, 1.0, 1.0), cell_size_m=25.0, ramp_m=50.0, source_run=source_run
    )


def test_the_mesh_step_keeps_one_sim_id_per_reference() -> None:
    cfgs = [
        RefinementZoneConfig.model_validate(ZONE),
        RefinementZoneConfig.model_validate(
            {"where": "seepage", "above": 1.0, "run": "coarse", "cell_size": 25.0}
        ),
        RefinementZoneConfig.model_validate({**ZONE, "run": "other"}),
        RefinementZoneConfig.model_validate({"path": "layer.gpkg", "cell_size": 30.0}),
    ]
    zones = [_planned("1" * 32), _planned("1" * 32), _planned("2" * 32), _planned(None)]

    assert zone_runs(cfgs, zones) == {"coarse": "1" * 32, "other": "2" * 32}


def test_the_mesh_step_keeps_nothing_when_the_planner_dropped_a_zone() -> None:
    cfgs = [
        RefinementZoneConfig.model_validate(ZONE),
        RefinementZoneConfig.model_validate({"path": "layer.gpkg", "cell_size": 30.0}),
    ]

    assert zone_runs(cfgs, [_planned(None)]) == {}


def test_the_summary_of_the_mesh_step_carries_the_zone_runs(tmp_path: Path, monkeypatch) -> None:
    inputs = planning_inputs(grid_spec(10, 10, 100.0), refinement_zones=(_planned("3" * 32),))
    monkeypatch.setattr(mesh_module, "planning_inputs", lambda ctx, mesh_cfg: inputs)
    mesh = MeshConfig(engine="regular", refinement_zone=[ZONE])
    ctx = SimpleNamespace(
        cfg=SimpleNamespace(mesh=mesh),
        setup=SimpleNamespace(workspace=SimpleNamespace(project_root=tmp_path)),
    )

    step_mesh(ctx)

    assert ctx.setup.mesh_summary["zone_runs"] == {"coarse": "3" * 32}
