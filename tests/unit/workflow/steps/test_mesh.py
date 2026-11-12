"""The mesh step."""

from __future__ import annotations

import dataclasses
import logging
import shutil
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from rasterio.features import shapes
from rasterio.transform import Affine
from shapely.geometry import Polygon, box, shape

from hydromodpy.core.state.run_state import WorkflowContext
from hydromodpy.mesh.engines.regular.engine import RegularMeshEngine
from hydromodpy.mesh.mesh_config import MeshConfig
from hydromodpy.mesh.planning.inputs import PlanningInputs
from hydromodpy.mesh.planning.plan import smoothed_catchment
from hydromodpy.mesh.planning.refinement_zones import RefinementZone
from hydromodpy.mesh.refinement_config import RefinementZoneConfig
from hydromodpy.mesh.stored import ARRAYS_FILENAME, DESCRIPTION_FILENAME
from hydromodpy.results.products.store import ProductStore, products_root
from hydromodpy.results.storage.contract import MESH_DIRNAME
from hydromodpy.results.storage.run_profile import read_profile
from hydromodpy.workflow.state import PipelineState
from hydromodpy.workflow.steps import mesh as mesh_module
from hydromodpy.workflow.steps.mesh import BuildMeshStep, step_mesh, zone_runs
from tests._helpers.fake_engines import FakeMeshEngine, registered
from tests._helpers.mesh_cases import L93_ORIGIN, LAMBERT93_WKT, grid_spec, planning_inputs

# --- test_the_mesh_step_dispatches_by_engine ---
# The mesh step plans one request, builds it with the engine of [mesh], and
# stores what it built in the product store.

X0, Y0 = L93_ORIGIN


SIDE, N = 1000.0, 10


@pytest.fixture
def planned_inputs(use_planning_inputs):
    grid = grid_spec(N, N, SIDE / N, xmin=X0, ymin=Y0, crs_wkt=LAMBERT93_WKT)
    use_planning_inputs(planning_inputs(grid))


def _context(tmp_path, mesh: MeshConfig | None, *, workspace: bool = True) -> WorkflowContext:
    ctx = WorkflowContext(
        cfg=SimpleNamespace(
            mesh=mesh,
            workspace=SimpleNamespace(products_cap_mb=5000, project_root=tmp_path),
        ),
        config_path="config.toml",
        raw_toml={},
    )
    if workspace:
        ctx.setup.workspace = SimpleNamespace(project_root=tmp_path)
    return ctx


def _store_dir(tmp_path: Path, key: str) -> Path:
    return ProductStore(products_root(tmp_path)).path(key)


@pytest.mark.usefixtures("planned_inputs")
def test_the_regular_shape_of_the_section_reaches_the_grid(tmp_path) -> None:
    ctx = _context(tmp_path, MeshConfig.model_validate({"regular": {"shape": [4, 5]}}))

    step_mesh(ctx)

    assert ctx.setup.cell_mesh.structured_shape == (4, 5)


@pytest.mark.usefixtures("planned_inputs")
def test_a_resume_that_finds_no_stored_mesh_says_it_will_differ(
    tmp_path, cached_engine, caplog
) -> None:
    ctx = _context(tmp_path, MeshConfig(engine=cached_engine.engine_id))
    ctx.execution.resumed = True
    caplog.set_level(logging.WARNING, logger="hydromodpy.workflow.products")

    step_mesh(ctx)

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "differs" in warnings[0]


@pytest.mark.usefixtures("planned_inputs")
def test_a_resume_reads_the_stored_mesh_a_crashed_process_left(
    tmp_path, cached_engine, caplog
) -> None:
    mesh_cfg = MeshConfig(engine=cached_engine.engine_id)
    step_mesh(_context(tmp_path, mesh_cfg))
    fresh = _context(tmp_path, mesh_cfg)
    state = PipelineState(run_id="run-1", step_index=2, step_name="build_mesh", data={"ctx": fresh})
    caplog.set_level(logging.WARNING, logger="hydromodpy.workflow.products")

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


# --- test_the_mesh_step_keeps_the_smoothed_outline ---
# The mesh step hands the catchment outline the planner smoothed to the cell mesh.
#
# The solver reads its cells against the catchment, and the faces of the mesh
# follow the smooth outline, not the pixel staircase of ``watershed.shp``. The
# product store holds the mesh as the engine built it, so the step puts the
# outline on the mesh after the build and after a store hit alike.

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


def test_a_mesh_read_from_the_store_carries_it_too(tmp_path, graded_engine, inputs) -> None:
    mesh_cfg = MeshConfig(engine=graded_engine.engine_id, cell_size=50.0, families=_FACE)
    first, second = _context(tmp_path, mesh_cfg), _context(tmp_path, mesh_cfg)

    step_mesh(first)
    step_mesh(second)

    assert graded_engine.builds == 1
    assert second.setup.cell_mesh.smoothed_catchment.equals(
        first.setup.cell_mesh.smoothed_catchment
    )
    assert second.setup.cell_mesh.smoothed_catchment is not None


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
    ctx = _context(tmp_path, mesh)

    step_mesh(ctx)

    assert ctx.setup.mesh_summary["zone_runs"] == {"coarse": "3" * 32}


# --- test_a_replay_reads_the_mesh_sealed_beside_its_source ---
# An engine that cannot rebuild its mesh bit for bit reads the one the source sealed.
#
# The source of a replay holds ``mesh/`` beside its seal. A replay of such an
# engine reads it, its identity compared to the request as the store's is; a
# miss builds again through the store. An engine that rebuilds the same cells in
# every process never reads the sealed copy.

SEALED_RUN = "probe.v2"


def _seal(tmp_path: Path, mesh_cfg: MeshConfig) -> tuple[Path, str]:
    """Build *mesh_cfg* in a project and copy its stored mesh beside a sealed run.

    Returns the sealed run directory, as ``hmp replay`` would see it, and the
    product key of the mesh that was built.
    """
    step_mesh(_context(tmp_path, mesh_cfg))
    store = ProductStore(products_root(tmp_path))
    (only,) = store.entries()
    stored = store.path(only.key)
    sealed = tmp_path / "runs" / SEALED_RUN
    sealed.mkdir(parents=True)
    (sealed / MESH_DIRNAME).mkdir()
    shutil.copy(stored / ARRAYS_FILENAME, sealed / MESH_DIRNAME / ARRAYS_FILENAME)
    shutil.copy(stored / DESCRIPTION_FILENAME, sealed / MESH_DIRNAME / DESCRIPTION_FILENAME)
    _write_mesh_row(sealed)
    return sealed, only.key


def _write_mesh_row(sealed: Path) -> None:
    """Write the ``mesh`` row of ``inputs.json`` the seal writes, with the digest of ``mesh/``."""
    import json

    from hydromodpy.results.record.manifest import InputEntry
    from hydromodpy.results.record.record import InputsDocument
    from hydromodpy.results.storage.digests import sha256_directory

    row = InputEntry(
        variable=MESH_DIRNAME,
        provider="store",
        product=MESH_DIRNAME,
        path=MESH_DIRNAME,
        sha256=sha256_directory(sealed / MESH_DIRNAME),
    )
    document = InputsDocument(sim_id="s" * 32, inputs=[row])
    (sealed / "inputs.json").write_text(
        json.dumps(document.model_dump(mode="json", by_alias=True)), encoding="utf-8"
    )


@pytest.mark.usefixtures("planned_inputs")
def test_a_replay_reads_the_mesh_sealed_beside_the_source_run(tmp_path, cached_engine) -> None:
    mesh_cfg = MeshConfig(engine=cached_engine.engine_id)
    sealed, key = _seal(tmp_path, mesh_cfg)
    replay = _context(tmp_path / "replay_project", mesh_cfg)
    replay.run_dir = tmp_path / "replay" / "runs" / "probe.v3"
    replay.run_dir.mkdir(parents=True)

    step_mesh(replay, sealed)

    assert cached_engine.builds == 1
    assert replay.setup.mesh_summary["product_key"] == key
    assert replay.setup.cell_mesh is not None
    line = read_profile(replay.run_dir).lines[-1]
    assert (line.name, line.reused, line.key) == ("mesh", "sealed", None)


@pytest.mark.usefixtures("planned_inputs")
def test_a_sealed_mesh_of_another_request_is_a_miss_and_the_step_builds_again(
    tmp_path, cached_engine, caplog
) -> None:
    sealed, key = _seal(tmp_path, MeshConfig(engine=cached_engine.engine_id, cell_size=100.0))
    replay = _context(
        tmp_path / "replay_project", MeshConfig(engine=cached_engine.engine_id, cell_size=125.0)
    )

    with caplog.at_level(logging.WARNING, logger=mesh_module.logger.name):
        step_mesh(replay, sealed)

    assert cached_engine.builds == 2
    assert "does not read for this request" in caplog.text
    assert replay.setup.mesh_summary["product_key"] != key


@pytest.mark.usefixtures("planned_inputs")
def test_a_sealed_mesh_changed_after_its_seal_is_a_miss(tmp_path, cached_engine, caplog) -> None:
    mesh_cfg = MeshConfig(engine=cached_engine.engine_id)
    sealed, _key = _seal(tmp_path, mesh_cfg)
    arrays = sealed / MESH_DIRNAME / ARRAYS_FILENAME
    arrays.write_bytes(arrays.read_bytes() + b"\0")
    replay = _context(tmp_path / "replay_project", mesh_cfg)

    with caplog.at_level(logging.WARNING, logger=mesh_module.logger.name):
        step_mesh(replay, sealed)

    assert cached_engine.builds == 2
    assert "is not the one its seal certifies" in caplog.text


@pytest.mark.usefixtures("planned_inputs")
def test_a_source_run_with_no_mesh_directory_is_a_miss(tmp_path, cached_engine) -> None:
    sealed = tmp_path / "runs" / SEALED_RUN
    sealed.mkdir(parents=True)
    replay = _context(tmp_path, MeshConfig(engine=cached_engine.engine_id))

    step_mesh(replay, sealed)

    assert cached_engine.builds == 1
    assert replay.setup.cell_mesh is not None
