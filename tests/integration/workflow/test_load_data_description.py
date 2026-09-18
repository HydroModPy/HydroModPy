"""``load_data`` declares the document that names what it bound to the runtime.

The step reads files it does not own and writes none of its own, so its journal
row carried the digest of the empty string: the run's own record of which
variable came from which source lived only in the provenance rows
``prepare_solver`` writes five steps later, and only in SQL.

The run below crashes in ``build_mesh``, right after the load. Its ``load_data``
row must name a document, and that document must name the records that were
loaded. A run that can no longer show the document is a run whose load is
undescribed, and the resume planner replans from the load instead of trusting
it.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
DEM = REPO_ROOT / "examples" / "data" / "dem" / "regional_dem_naizin.tif"

RUN_NAME = "loaded_then_stopped"
LOAD_DATA_ORDER = 3

PROJECT_TOML = """
[workflow]
mode = "simulation"

[simulation]
name = "naizin_load_description"

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


def _isolated_copy(root: Path, destination: Path) -> Path:
    """Return a copy of a finished project tree, journal included.

    The resume planner rewrites the journal of every run it invalidates, so a
    test that asks it a question has to own its workspace: two such tests
    sharing one tree would answer each other instead of the code.
    """
    shutil.copytree(root, destination, dirs_exist_ok=True)
    return destination


def _journal_rows(root: Path, run_id: str):
    from hydromodpy.results.catalog import Catalog
    from hydromodpy.workflow.tracking.journal import WorkflowJournal

    catalog = Catalog(root)
    try:
        return WorkflowJournal(catalog).list_steps(run_id)
    finally:
        catalog.close()


@pytest.fixture(scope="module")
def loaded_run(tmp_path_factory: pytest.TempPathFactory):
    """Load a real catchment, then crash in ``build_mesh``.

    Two constraints pick this shape. A window stopping before ``setup_process``
    registers no simulation and keeps no journal at all, so the window has to
    reach it; and a run that ends cleanly has its preprocessing tree removed on
    close, which would make the resume planner replan from ``build_geographic``
    for reasons that have nothing to do with the load. A crash leaves both.
    """
    if not DEM.is_file():
        pytest.skip(f"missing DEM fixture {DEM}")
    from hydromodpy.core.exceptions import StepError
    from hydromodpy.project.facade import Project
    from hydromodpy.workflow.internals.data_description import iter_loaded_records
    from hydromodpy.workflow.steps.mesh import BuildMeshStep

    root = tmp_path_factory.mktemp("load_data_description")
    config_path = root / "project.toml"
    config_path.write_text(
        PROJECT_TOML.format(root=root.as_posix(), dem=DEM.as_posix()),
        encoding="utf-8",
    )

    walked: set[str] = set()

    def _bomb(_self, state):
        walked.update(
            f"{item.scope}:{item.variable}"
            for item in iter_loaded_records(state.get("ctx").loaded_data)
        )
        raise RuntimeError("injected crash in build_mesh")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(BuildMeshStep, "run", _bomb)
        project = Project(config_path, no_display=True)
        try:
            with pytest.raises(StepError):
                project.simulate(name=RUN_NAME, until_step="setup_process")
        finally:
            project.close()

    rows = _journal_rows(root, RUN_NAME)
    row = next(r for r in rows if r.step_order == LOAD_DATA_ORDER)
    return root, row, walked


def test_the_step_declares_the_document_that_names_its_load(loaded_run) -> None:
    """The journal carries a real digest over a document, not the empty one."""
    from hydromodpy.workflow.internals.data_description import DESCRIPTION_FILENAME

    root, row, _walked = loaded_run

    assert row.step_name == "load_data"
    assert row.status == "completed"
    assert row.artifact_uris, "load_data declares nothing after loading its forcings"
    assert {Path(uri).name for uri in row.artifact_uris} == {DESCRIPTION_FILENAME}
    assert all((root / uri).exists() for uri in row.artifact_uris)
    assert row.outputs_hash != hashlib.sha256(b"").hexdigest()


def test_the_document_names_the_records_that_were_loaded(loaded_run) -> None:
    """A synthetic series is named as one, with no digest it cannot compute."""
    from hydromodpy.workflow.internals.data_description import (
        SCHEMA_VERSION,
        read_data_description,
    )

    root, _row, _walked = loaded_run

    payload = read_data_description(root, RUN_NAME)
    assert payload is not None
    assert payload["schema"] == SCHEMA_VERSION
    assert payload["plan_types"] == ["recharge"]

    records = {f"{r['scope']}:{r['variable']}": r for r in payload["records"]}
    assert "recharge:recharge" in records
    record = records["recharge:recharge"]
    assert record["kind"] == "point"
    assert record["source"] == "synthetic"
    assert record["source_path"] is None
    assert record["source_sha256"] is None


def test_the_document_names_every_record_the_shared_walk_yields(loaded_run) -> None:
    """The load and the fingerprints three steps later read the same walk."""
    from hydromodpy.workflow.internals.data_description import read_data_description

    root, _row, walked = loaded_run

    payload = read_data_description(root, RUN_NAME)
    assert payload is not None
    described = {f"{r['scope']}:{r['variable']}" for r in payload["records"]}
    assert described == walked
    assert walked, "the probe loaded nothing, so it proves nothing"


def test_a_run_that_lost_its_document_replans_from_the_load(loaded_run, tmp_path: Path) -> None:
    """Without the document the load is undescribed, so it is not trusted."""
    from hydromodpy.results.catalog import Catalog
    from hydromodpy.workflow.internals.data_description import description_path
    from hydromodpy.workflow.tracking.journal import WorkflowJournal
    from hydromodpy.workflow.tracking.resume import ResumePlanner

    source, row, _walked = loaded_run
    root = _isolated_copy(source, tmp_path / "lost_document")
    blueprint = [r.step_name for r in _journal_rows(root, RUN_NAME)]

    catalog = Catalog(root)
    try:
        planner = ResumePlanner(WorkflowJournal(catalog), root)
        before = planner.compute(
            run_id=RUN_NAME,
            current_config_sha256=None,
            steps_blueprint=blueprint,
        )
        assert before.restart_index == LOAD_DATA_ORDER + 1

        description_path(root, RUN_NAME).unlink()
        after = planner.compute(
            run_id=RUN_NAME,
            current_config_sha256=None,
            steps_blueprint=blueprint,
        )
    finally:
        catalog.close()

    assert after.restart_index == LOAD_DATA_ORDER
    assert [item.step_name for item in after.invalidated] == ["load_data"]
    assert row.outputs_hash is not None


def test_a_document_that_no_longer_matches_replans_from_the_load(
    loaded_run, tmp_path: Path
) -> None:
    """A load whose document moved is a load the run no longer rests on.

    This is the second move of the two a changed forcing takes. The resume that
    reloads it verifies the document written before the crash - which matches
    itself - then overwrites it with what it just read. The resume after that
    finds the recorded digest and the document disagreeing, and replans from
    the load rather than keeping a run built on bytes that are gone.
    """
    from hydromodpy.results.catalog import Catalog
    from hydromodpy.workflow.internals.data_description import (
        description_path,
        read_data_description,
        write_data_description,
    )
    from hydromodpy.workflow.tracking.journal import WorkflowJournal
    from hydromodpy.workflow.tracking.resume import ResumePlanner

    source, _row, _walked = loaded_run
    root = _isolated_copy(source, tmp_path / "moved_document")
    blueprint = [r.step_name for r in _journal_rows(root, RUN_NAME)]

    payload = read_data_description(root, RUN_NAME)
    assert payload is not None
    payload["records"][0]["source"] = "a different source"
    write_data_description(root, RUN_NAME, payload)

    catalog = Catalog(root)
    try:
        plan = ResumePlanner(WorkflowJournal(catalog), root).compute(
            run_id=RUN_NAME,
            current_config_sha256=None,
            steps_blueprint=blueprint,
        )
    finally:
        catalog.close()

    assert plan.restart_index == LOAD_DATA_ORDER
    assert [item.step_name for item in plan.invalidated] == ["load_data"]
    assert plan.reason is not None and "load_data" in plan.reason
