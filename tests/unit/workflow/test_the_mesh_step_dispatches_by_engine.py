"""The mesh step plans one request, builds it with the engine of [mesh], and caches what needs it."""

from __future__ import annotations

import dataclasses
import logging
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.core.exceptions import MeshError
from hydromodpy.core.state.run_state import WorkflowContext
from hydromodpy.spatial.mesh import cache as cache_module
from hydromodpy.spatial.mesh.cache import cache_dir, library_versions
from hydromodpy.spatial.mesh.config.mesh import MeshConfig
from hydromodpy.spatial.mesh.engines.regular.engine import RegularMeshEngine
from hydromodpy.workflow.internals.state import PipelineState
from hydromodpy.workflow.steps import mesh as mesh_module
from hydromodpy.workflow.steps.mesh import BuildMeshStep, step_mesh
from tests._helpers.fake_engines import FakeMeshEngine, registered
from tests._helpers.mesh_cases import L93_ORIGIN, LAMBERT93_WKT, grid_spec, planning_inputs

X0, Y0 = L93_ORIGIN
SIDE, N = 1000.0, 10


@pytest.fixture(autouse=True)
def planned_inputs(use_planning_inputs):
    grid = grid_spec(N, N, SIDE / N, xmin=X0, ymin=Y0, crs_wkt=LAMBERT93_WKT)
    use_planning_inputs(planning_inputs(grid))


def _context(tmp_path, mesh: MeshConfig | None, *, workspace: bool = True) -> WorkflowContext:
    ctx = WorkflowContext(cfg=SimpleNamespace(mesh=mesh), config_path="config.toml", raw_toml={})
    if workspace:
        ctx.setup.workspace = SimpleNamespace(project_root=tmp_path)
    return ctx


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


def test_the_summary_names_the_library_builds_the_mesh_depends_on(tmp_path) -> None:
    ctx = _context(tmp_path, None)

    step_mesh(ctx)

    versions = ctx.setup.mesh_summary["library_versions"]
    assert set(versions) == {"gmsh", "scipy", "shapely", "geos"}
    assert versions == library_versions()
    assert all(isinstance(value, str) and value for value in versions.values())


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


def test_the_regular_shape_of_the_section_reaches_the_grid(tmp_path) -> None:
    ctx = _context(tmp_path, MeshConfig.model_validate({"regular": {"shape": [4, 5]}}))

    step_mesh(ctx)

    assert ctx.setup.cell_mesh.structured_shape == (4, 5)


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


def test_a_changed_request_is_meshed_again_under_its_own_key(tmp_path, cached_engine) -> None:
    coarse = _context(tmp_path, MeshConfig(engine=cached_engine.engine_id, cell_size=100.0))
    fine = _context(tmp_path, MeshConfig(engine=cached_engine.engine_id, cell_size=125.0))

    step_mesh(coarse)
    step_mesh(fine)

    assert cached_engine.builds == 2
    assert coarse.setup.mesh_summary["cache_key"] != fine.setup.mesh_summary["cache_key"]
    assert len(list((tmp_path / ".hmp" / "mesh_cache").iterdir())) == 2


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


def test_a_resume_that_finds_no_cache_says_the_mesh_will_differ(
    tmp_path, cached_engine, caplog
) -> None:
    ctx = _context(tmp_path, MeshConfig(engine=cached_engine.engine_id))
    caplog.set_level(logging.WARNING, logger=mesh_module.logger.name)

    step_mesh(ctx, resume=True)

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "cached mesh of this request is gone" in warnings[0]


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


def test_a_resume_keeps_the_mesh_the_process_already_holds(tmp_path) -> None:
    ctx = _context(tmp_path, None)
    step_mesh(ctx)
    held = ctx.setup.cell_mesh
    state = PipelineState(run_id="run-1", step_index=2, step_name="build_mesh", data={"ctx": ctx})

    BuildMeshStep().rebuild_state(prior_state=state, workspace=tmp_path, run_id="run-1")

    assert ctx.setup.cell_mesh is held
    assert BuildMeshStep().is_prebuilt(state)


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


def test_a_cached_engine_needs_a_workspace_to_cache_in(tmp_path, cached_engine) -> None:
    ctx = _context(tmp_path, MeshConfig(engine=cached_engine.engine_id), workspace=False)

    with pytest.raises(MeshError, match="no workspace"):
        step_mesh(ctx)


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


def test_a_mesh_past_a_quality_threshold_is_warned_and_used(tmp_path, caplog) -> None:
    with registered(_ConcaveEngine):
        ctx = _context(tmp_path, MeshConfig(engine=_ConcaveEngine.engine_id))
        with caplog.at_level(logging.WARNING, logger=mesh_module.logger.name):
            step_mesh(ctx)

    assert ctx.setup.cell_mesh.qa.n_concave_cells == 3
    assert "Mesh quality: 3 of 100 cells are concave" in caplog.text


def test_a_mesh_within_the_thresholds_is_not_warned(tmp_path, caplog) -> None:
    with caplog.at_level(logging.WARNING, logger=mesh_module.logger.name):
        step_mesh(_context(tmp_path, None))

    assert "Mesh quality" not in caplog.text
