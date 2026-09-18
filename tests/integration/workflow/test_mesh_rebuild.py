"""A resume reloads the mesh it generated instead of generating another one.

Gmsh is not reproducible run to run - the measured evidence is in
:mod:`hydromodpy.spatial.mesh.mesh_cache`. A resume that re-meshes therefore
does not repeat the step's work, it changes the mesh every number downstream is
computed on, and the run that comes back from the crash is not the run that
went into it.

The runtime summary the meshing produces is exactly what
``load_mesh_artifacts_from_summary`` consumes, and it only ever lived in memory:
a fresh process had nothing to read. The run below crashes after the mesh is
complete, then resumes in a context that knows nothing, with the mesher itself
replaced by a bomb.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
DEM = REPO_ROOT / "examples" / "data" / "dem" / "regional_dem_naizin.tif"

RUN_NAME = "meshed_then_crashed"

PROJECT_TOML = """
[workflow]
mode = "simulation"

[simulation]
name = "naizin_mesh_rebuild"

[[simulation.process]]
id = "flow"
type = "flow"
solvers = ["modflow_nwt"]

[workspace]
project_root = "{root}"

[geographic]
crs_project = "EPSG:2154"
dem_correc_type = "breach"

[geographic.catchment]
catch_def = "from_outlet_coord"
dem_init_path = "{dem}"
x_outlet = 265611.933
y_outlet = 6784182.776
snap_dist = "50 m"
buff_area = "20%"

[geographic.river_network]
enabled = true
threshold_mode = "area_km2"
threshold_area_km2 = 1.0
prune_short_streams = false
compute_strahler_order = true
compute_stream_links = true
all_vertices = true

[mesh_catchment]
constraints_mode = "rivers_only"
output_layout = "flat"
figures_enabled = false

[mesh_catchment.zone_meshing]
global_size = 350.0
min_size = 150.0
max_size = 800.0

[domain]

[domain.depth_model]
kind = "constant_thickness"
thickness = "50.0 m"

[data]
types = ["recharge"]
inference_mode = "warn"

[[data.recharge.sources]]
source = "synthetic"
values = [3.0]
runoff_ratio = 0.0

[flow]
flow_regime = "steady"
active_sinks_sources = ["recharge"]
active_bc = ["drainage"]
param_list = ["K"]

[flow.param.K.field]
id = "K"
kind = "homogeneous"
value = "1e-5 m/s"

[flow.ic]
type = "custom"
value = "5.0 m"

[modflownwt.sgrid.planar]
mode = "keep_native"

[modflownwt.sgrid.vertical]
nlay = 1

[display]
enabled = false
"""


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _journal_row(root: Path, run_id: str, step_order: int):
    from hydromodpy.results.catalog import Catalog
    from hydromodpy.workflow.tracking.journal import WorkflowJournal

    catalog = Catalog(root)
    try:
        rows = WorkflowJournal(catalog).list_steps(run_id)
    finally:
        catalog.close()
    return next(row for row in rows if row.step_order == step_order)


@pytest.fixture(scope="module")
def meshed_then_crashed(tmp_path_factory: pytest.TempPathFactory):
    """Mesh a real catchment, then crash in ``setup_process``.

    The crash lands after ``build_mesh`` completed, which is the case a resume
    must not re-mesh. The window stops at ``setup_process`` so no solver binary
    is needed.
    """
    if not DEM.is_file():
        pytest.skip(f"missing DEM fixture {DEM}")
    from hydromodpy.core.exceptions import StepError
    from hydromodpy.project.facade import Project
    from hydromodpy.workflow.steps.setup import SetupProcessStep

    root = tmp_path_factory.mktemp("mesh_rebuild")
    config_path = root / "project.toml"
    config_path.write_text(
        PROJECT_TOML.format(root=root.as_posix(), dem=DEM.as_posix()),
        encoding="utf-8",
    )

    def _bomb(_self, _state):
        raise RuntimeError("injected crash in setup_process")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(SetupProcessStep, "run", _bomb)
        project = Project(config_path, no_display=True)
        try:
            with pytest.raises(StepError):
                project.simulate(name=RUN_NAME, until_step="setup_process")
        finally:
            project.close()

    row = _journal_row(root, RUN_NAME, 4)
    return root, row, _digest(root / "mesh" / "mesh_catchment.msh")


def test_the_step_declares_the_mesh_it_left(meshed_then_crashed) -> None:
    """The journal carries a real digest over the mesh, not the empty one."""
    from hydromodpy.spatial.mesh.runtime_description import DESCRIPTION_FILENAME

    root, row, _msh_digest = meshed_then_crashed

    assert row.step_name == "build_mesh"
    assert row.status == "completed"
    assert row.artifact_uris, "build_mesh declares nothing after meshing a catchment"
    names = {Path(uri).name for uri in row.artifact_uris}
    assert DESCRIPTION_FILENAME in names
    assert "mesh_catchment.msh" in names
    assert {"nodes.csv", "cells.csv", "metadata.json"} <= names
    assert all((root / uri).exists() for uri in row.artifact_uris)
    assert row.outputs_hash != hashlib.sha256(b"").hexdigest()


def test_a_resume_reloads_the_mesh_instead_of_generating_another(
    meshed_then_crashed,
) -> None:
    """The mesher is a bomb: reaching it at all is the failure."""
    import hydromodpy.spatial.mesh.launcher.runtime as mesh_runtime
    from hydromodpy.project.facade import Project

    root, _row, msh_digest = meshed_then_crashed

    def _bomb(*_args, **_kwargs):
        raise AssertionError("the resume regenerated the mesh")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            mesh_runtime,
            "run_single_mesh_catchment_workflow_with_runtime_artifacts",
            _bomb,
        )
        project = Project(root / "project.toml", no_display=True)
        try:
            project.simulate(resume=RUN_NAME, until_step="setup_process")
            setup = project._ctx.setup
            assert setup.mesh_planar is not None, "the resume loaded no mesh"
            assert setup.mesh_bundle is not None, "the resume loaded no exchange bundle"
            # The three-key summary a cache hit used to leave is enough to load
            # the files and tells nothing about the meshing that produced them.
            assert len(setup.mesh_summary) > 10
        finally:
            project.close()

    assert _digest(root / "mesh" / "mesh_catchment.msh") == msh_digest
