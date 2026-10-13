"""The mesh step ends with the planar cell mesh the solvers read, in the run's CRS."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.core.exceptions import MeshError
from hydromodpy.core.state.run_state import WorkflowContext
from hydromodpy.spatial.mesh.gmsh_grid.gmsh_planar_mesh import GmshPlanarMesh2D
from hydromodpy.workflow.internals.state import PipelineState
from hydromodpy.workflow.steps import mesh as mesh_module
from hydromodpy.workflow.steps.mesh import BuildMeshStep, load_mesh_artifacts_from_summary

_X0, _Y0 = 351_250.0, 6_789_500.0


def _two_triangles() -> GmshPlanarMesh2D:
    return GmshPlanarMesh2D(
        points_xy=np.array([[0.0, 0.0], [90.0, 0.0], [90.0, 60.0], [0.0, 60.0]]) + [_X0, _Y0],
        connectivity=np.array([[0, 1, 2], [0, 2, 3]]),
        cell_type="triangle",
    )


def _context(**setup: object) -> WorkflowContext:
    ctx = WorkflowContext(cfg=SimpleNamespace(), config_path="config.toml", raw_toml={})
    ctx.setup.mesh_summary = {}
    for name, value in setup.items():
        setattr(ctx.setup, name, value)
    return ctx


def test_the_cell_mesh_carries_the_geographic_crs_and_the_vertex_mean_centres() -> None:
    ctx = _context(geographic=SimpleNamespace(crs_project="EPSG:2154"))

    load_mesh_artifacts_from_summary(ctx, strict=False, planar=_two_triangles())

    cell_mesh = ctx.setup.cell_mesh
    assert "Lambert" in cell_mesh.crs_wkt
    assert cell_mesh.n_cells == 2
    assert cell_mesh.center_kind == "vertex_mean"
    np.testing.assert_allclose(
        cell_mesh.centers,
        [[_X0 + 60.0, _Y0 + 20.0], [_X0 + 30.0, _Y0 + 40.0]],
    )


def test_the_dem_support_gives_the_crs_when_the_geographic_setup_has_none() -> None:
    surface = SimpleNamespace(support=SimpleNamespace(crs="EPSG:2154"))
    ctx = _context(geographic=SimpleNamespace(), domain=SimpleNamespace(surface_topo=surface))

    load_mesh_artifacts_from_summary(ctx, strict=False, planar=_two_triangles())

    assert "Lambert" in ctx.setup.cell_mesh.crs_wkt


def test_a_run_without_a_crs_cannot_build_a_cell_mesh() -> None:
    ctx = _context(geographic=SimpleNamespace(), domain=None)

    with pytest.raises(MeshError, match="needs the run's CRS"):
        load_mesh_artifacts_from_summary(ctx, strict=False, planar=_two_triangles())


def test_a_reload_that_keeps_what_is_loaded_keeps_the_cell_mesh() -> None:
    ctx = _context(geographic=SimpleNamespace(crs_project="EPSG:2154"))
    load_mesh_artifacts_from_summary(ctx, strict=False, planar=_two_triangles())
    built = ctx.setup.cell_mesh

    load_mesh_artifacts_from_summary(ctx, strict=False, keep_loaded=True)

    assert ctx.setup.cell_mesh is built


def test_a_fresh_load_drops_the_mesh_of_the_previous_build() -> None:
    ctx = _context(geographic=SimpleNamespace(crs_project="EPSG:2154"))
    load_mesh_artifacts_from_summary(ctx, strict=False, planar=_two_triangles())
    ctx.setup.mesh_support = object()

    load_mesh_artifacts_from_summary(ctx, strict=False)

    assert ctx.setup.cell_mesh is None
    assert ctx.setup.mesh_support is None


def test_a_failed_reload_says_why_before_it_meshes_again(monkeypatch, caplog) -> None:
    ctx = _context(geographic=SimpleNamespace(crs_project="EPSG:2154"))
    ctx.setup.mesh_summary = {"output_mesh": "mesh.msh"}
    state = PipelineState(run_id="run-1", step_index=2, step_name="build_mesh", data={"ctx": ctx})
    remeshed = state.advance(step_index=3, step_name="build_mesh", ctx=ctx)

    def stale(*args: object, **kwargs: object) -> None:
        raise ValueError("the support describes 9 cells, the mesh has 2")

    monkeypatch.setattr(mesh_module, "load_mesh_artifacts_from_summary", stale)
    monkeypatch.setattr(BuildMeshStep, "run", lambda self, prior: remeshed)
    caplog.set_level(logging.WARNING, logger=mesh_module.logger.name)

    result = BuildMeshStep().rebuild_state(prior_state=state, workspace=".", run_id="run-1")

    assert result is remeshed
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "ValueError" in warnings[0]
    assert "the support describes 9 cells" in warnings[0]
