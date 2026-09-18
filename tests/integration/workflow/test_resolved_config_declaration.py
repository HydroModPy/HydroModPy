"""``validate`` leaves the configuration the run was resolved on, and it is read.

A run that dies while building its model used to leave no resolved
configuration anywhere: the only frozen copy is written into the run directory
by ``prepare_solver``, step six. The resume checkpoint still carried its sha256,
so a resume after an edit refused with "the configuration changed" and could
name nothing.

The run below crashes in ``build_mesh``, then is resumed against an edited
configuration. The refusal must name the section that moved.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
DEM = REPO_ROOT / "examples" / "data" / "dem" / "regional_dem_naizin.tif"

RUN_NAME = "config_drifted"
VALIDATE_ORDER = 0

PROJECT_TOML = """
[workflow]
mode = "simulation"

[simulation]
name = "naizin_resolved_config"

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
value = "{conductivity}"

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


def _write_config(root: Path, conductivity: str) -> Path:
    config_path = root / "project.toml"
    config_path.write_text(
        PROJECT_TOML.format(
            root=root.as_posix(),
            dem=DEM.as_posix(),
            conductivity=conductivity,
        ),
        encoding="utf-8",
    )
    return config_path


@pytest.fixture(scope="module")
def crashed_run(tmp_path_factory: pytest.TempPathFactory):
    """Validate a real project, then crash in ``build_mesh``."""
    if not DEM.is_file():
        pytest.skip(f"missing DEM fixture {DEM}")
    from hydromodpy.core.exceptions import StepError
    from hydromodpy.project.facade import Project
    from hydromodpy.workflow.steps.mesh import BuildMeshStep

    root = tmp_path_factory.mktemp("resolved_config")
    config_path = _write_config(root, "1e-5 m/s")

    def _bomb(_self, _state):
        raise RuntimeError("injected crash in build_mesh")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(BuildMeshStep, "run", _bomb)
        project = Project(config_path, no_display=True)
        try:
            with pytest.raises(StepError):
                project.simulate(name=RUN_NAME, until_step="setup_process")
        finally:
            project.close()

    from hydromodpy.results.catalog import Catalog
    from hydromodpy.workflow.tracking.journal import WorkflowJournal

    catalog = Catalog(root)
    try:
        rows = WorkflowJournal(catalog).list_steps(RUN_NAME)
    finally:
        catalog.close()
    return root, next(r for r in rows if r.step_order == VALIDATE_ORDER)


def test_the_step_declares_the_configuration_it_resolved(crashed_run) -> None:
    """A run stopped in its model phase still holds the config it ran on."""
    from hydromodpy.workflow.internals.manifest import RESOLVED_CONFIG_FILENAME

    root, row = crashed_run

    assert row.step_name == "validate"
    assert row.status == "completed"
    assert {Path(uri).name for uri in row.artifact_uris} == {RESOLVED_CONFIG_FILENAME}
    assert all((root / uri).exists() for uri in row.artifact_uris)
    assert row.outputs_hash != hashlib.sha256(b"").hexdigest()


def test_the_document_is_what_the_resume_checkpoint_signs(crashed_run) -> None:
    """The digest the checkpoint carries is taken over this exact payload."""
    from hydromodpy.core.io.canonical_json import dumps as canonical_dumps
    from hydromodpy.workflow.internals.manifest import (
        ResolvedRunManifest,
        read_resolved_config,
    )

    root, _row = crashed_run

    payload = read_resolved_config(root, RUN_NAME)
    assert payload is not None
    manifest = ResolvedRunManifest.read(root, RUN_NAME)
    assert manifest is not None
    digest = hashlib.sha256(canonical_dumps(payload).encode("utf-8")).hexdigest()
    assert digest == manifest.config_sha256


def test_a_resume_against_an_edited_config_names_the_section_that_moved(crashed_run) -> None:
    """The refusal sends the reader to ``[flow]`` instead of to the whole file.

    Edited in place rather than in a copy: ``project_root`` is part of the
    payload the checkpoint signs, so a project resumed from another directory
    reports ``workspace`` as moved too and the test would stop proving that the
    edit itself was located.
    """
    from hydromodpy.core.exceptions import ResumeError
    from hydromodpy.project.facade import Project

    root, _row = crashed_run
    kept = (root / "project.toml").read_text(encoding="utf-8")
    _write_config(root, "2e-5 m/s")

    try:
        project = Project(root / "project.toml", no_display=True)
        try:
            with pytest.raises(ResumeError) as raised:
                project.simulate(resume=RUN_NAME, until_step="setup_process")
        finally:
            project.close()
        message = str(raised.value)
    finally:
        (root / "project.toml").write_text(kept, encoding="utf-8")

    assert "Resolved configuration changed" in message
    assert "(flow)" in message


def test_a_head_only_window_does_not_rewrite_the_document_of_a_real_run(
    crashed_run, tmp_path: Path
) -> None:
    """A window that registers no simulation owns no run record, so it writes none.

    ``hmp run --until validate`` on the name of an existing run is handed no
    workspace, precisely so it cannot overwrite that run's manifest. The
    document has to obey the same rule: a rewritten one would no longer be what
    the frozen ``config_sha256`` beside it signs, and the next resume would
    name the wrong sections.
    """
    import shutil

    from hydromodpy.project.facade import Project
    from hydromodpy.workflow.internals.manifest import resolved_config_path

    source, _row = crashed_run
    root = tmp_path / "head_only"
    shutil.copytree(source, root, dirs_exist_ok=True)
    document = resolved_config_path(root, RUN_NAME)
    kept = document.read_bytes()

    _write_config(root, "9e-5 m/s")
    project = Project(root / "project.toml", no_display=True)
    try:
        project.simulate(name=RUN_NAME, until_step="validate")
    finally:
        project.close()

    assert document.read_bytes() == kept
