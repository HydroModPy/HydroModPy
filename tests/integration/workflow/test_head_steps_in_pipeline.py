"""The model phase of a fresh run is executed by the Pipeline, and journalled.

Finding A1: ``Project.simulate`` built geographic, data and mesh through the
facade verbs before the Pipeline was constructed. A process that died inside
``build_mesh`` therefore died before the Pipeline had started, and left no
journal row at all - not even for the delineation it had just paid for. There
was nothing to resume from.

The run below crashes inside ``build_mesh`` on purpose and reads the journal it
left behind.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
DEM = REPO_ROOT / "examples" / "data" / "dem" / "regional_dem_naizin.tif"

RUN_NAME = "crashed_head"

PROJECT_TOML = """
[workflow]
mode = "simulation"

[simulation]
name = "naizin_head_steps"

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


def _journal_rows(root: Path, run_id: str) -> tuple[tuple[int, str, str], ...]:
    """Return ``(step_order, step_name, status)`` for every row of ``run_id``."""
    from hydromodpy.results.catalog import Catalog
    from hydromodpy.workflow.tracking.journal import WorkflowJournal

    catalog = Catalog(root)
    try:
        rows = WorkflowJournal(catalog).list_steps(run_id)
    finally:
        catalog.close()
    return tuple((row.step_order, row.step_name, row.status) for row in rows)


@pytest.fixture(scope="module")
def crashed_at_build_mesh(tmp_path_factory: pytest.TempPathFactory):
    """Run a fresh project until ``build_mesh`` raises, and read its journal.

    The window stops at ``setup_process``: it is the first step consuming the
    model phase, so the run still owns a workspace and a journal, and it needs
    no solver binary.
    """
    if not DEM.is_file():
        pytest.skip(f"missing DEM fixture {DEM}")
    from hydromodpy.core.exceptions import StepError
    from hydromodpy.project.facade import Project

    root = tmp_path_factory.mktemp("head_steps")
    config_path = root / "project.toml"
    config_path.write_text(
        PROJECT_TOML.format(root=root.as_posix(), dem=DEM.as_posix()),
        encoding="utf-8",
    )

    def _bomb(*_args, **_kwargs):
        raise RuntimeError("injected crash in build_mesh")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("hydromodpy.workflow.steps.mesh.step_mesh", _bomb)
        project = Project(config_path, no_display=True)
        try:
            with pytest.raises(StepError):
                project.simulate(name=RUN_NAME, until_step="setup_process")
        finally:
            project.close()

    return root, _journal_rows(root, RUN_NAME)


def test_the_head_steps_are_journalled_up_to_the_crash(crashed_at_build_mesh) -> None:
    """Steps 0 to 3 completed, step 4 failed. Nothing beyond."""
    _root, rows = crashed_at_build_mesh

    assert rows == (
        (0, "validate", "completed"),
        (1, "resolve", "completed"),
        (2, "build_geographic", "completed"),
        (3, "load_data", "completed"),
        (4, "build_mesh", "failed"),
    )


def test_the_delineation_survives_the_crash(crashed_at_build_mesh) -> None:
    """A resume needs the tree, so a crashed run must not drop it.

    The cleanup only runs for a Project whose phase marker names a step. A run
    that died inside the Pipeline never adopts one, so its preprocessing tree
    is still there for the resume.
    """
    root, _rows = crashed_at_build_mesh

    assert (root / ".hmp" / "scratch" / "_preprocessing").is_dir()


def test_the_resume_restarts_at_the_step_that_failed(crashed_at_build_mesh) -> None:
    """``--resume`` picks step 4 and finishes the window without redoing 0 to 3."""
    from hydromodpy.project.facade import Project
    from hydromodpy.project.runner import _resolve_resume_step_index
    from hydromodpy.workflow.orchestrator import standard_steps

    root, _rows = crashed_at_build_mesh
    blueprint = tuple(step.name for step in standard_steps())

    assert _resolve_resume_step_index(root, RUN_NAME, steps_blueprint=blueprint) == 4

    project = Project(root / "project.toml", no_display=True)
    try:
        project.simulate(resume=RUN_NAME, until_step="setup_process")
    finally:
        project.close()

    assert _journal_rows(root, RUN_NAME) == (
        (0, "validate", "completed"),
        (1, "resolve", "completed"),
        (2, "build_geographic", "completed"),
        (3, "load_data", "completed"),
        (4, "build_mesh", "completed"),
        (5, "setup_process", "completed"),
    )
