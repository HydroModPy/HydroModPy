"""The seal is a step of the pipeline; the attempt protocol closes the run after it.

A real ``Pipeline`` ends on ``SealStep``. Once the step returns, the pipeline
still writes the journal row of the seal and its checkpoint under
``<run>/.hmp/``: nothing may have removed that directory. The bracket of the
attempt (:func:`run_attempt`) then finds the seal, flips the outcome to
``completed`` and drops ``<run>/.hmp/``. No index is opened anywhere.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.config_kit.persistence import PersistenceConfig
from hydromodpy.core.state.layout import INTERNAL_DIRNAME, PROJECT_MARKER_FILENAME
from hydromodpy.results.manifest import is_sealed
from hydromodpy.results.outcome import effective_status, read_outcome
from hydromodpy.results.storage.contract import RUN_CONFIG_FILENAME, RUN_MANIFEST_FILENAME
from hydromodpy.results.storage.run_store import RunStore
from hydromodpy.workflow.record.attempt import run_attempt
from hydromodpy.workflow.record.journal import WorkflowJournal
from hydromodpy.workflow.runner import Pipeline
from hydromodpy.workflow.state import PipelineState
from hydromodpy.workflow.steps.export import SealStep
from tests._helpers.run_stores import facts_of

CASE = "cheze_baseline"


class _Solved:
    """A step standing for everything before the seal; it leaves the context as it is."""

    name = "solved"

    def run(self, state: PipelineState) -> PipelineState:
        return state.advance(step_index=state.step_index + 1, step_name=self.name)


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "demo"
    project.mkdir()
    (project / PROJECT_MARKER_FILENAME).write_text("[workspace]\n", encoding="utf-8")
    return project


def _refuse_the_index(monkeypatch: pytest.MonkeyPatch) -> None:
    from hydromodpy.results.catalog import facade

    def _refuse(self, *args, **kwargs):
        raise AssertionError("the run opened the index")

    monkeypatch.setattr(facade.Catalog, "__init__", _refuse)


def _ctx(project: Path, run_dir: Path, sim_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        sim_id=sim_id,
        run_dir=run_dir,
        cfg=SimpleNamespace(
            simulation=SimpleNamespace(results=SimpleNamespace(persistence=PersistenceConfig())),
            export=[],
        ),
        execution=SimpleNamespace(lightweight=False),
        setup=SimpleNamespace(workspace=SimpleNamespace(project_root=project)),
    )


def _fill(project: Path, claim) -> None:
    """Write what a solved run leaves in its store, the way the pipeline does."""
    with RunStore.open(
        claim.run_dir,
        facts=facts_of(claim, project=project.name, n_cells=4, n_layers=1),
        workspace=project,
    ) as store:
        store.create_zarr(n_cells=4, n_layers=1)
        (store.run_dir / RUN_CONFIG_FILENAME).write_text("[flow]\nk = 1e-5\n", encoding="utf-8")
        index = pd.date_range("2020-01-01", periods=3, freq="D")
        store.write_timeseries(claim.sim_id, "P01", "head", pd.Series(np.ones(3), index=index))


def test_the_seal_step_ends_a_real_pipeline_and_the_bracket_closes_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _refuse_the_index(monkeypatch)
    project = _project(tmp_path)

    with run_attempt(project, CASE, case_id=CASE, project="demo", site=None) as handle:
        _fill(project, handle.claim)
        ctx = _ctx(project, handle.run_dir, handle.claim.sim_id)
        pipeline = Pipeline([_Solved(), SealStep()], workspace=project, run_dir=handle.run_dir)

        final = pipeline.run(
            PipelineState(run_id=CASE, data={"ctx": ctx, "wall_seconds": 1.0}),
            heartbeat=handle.heartbeat,
        )

        # Inside the bracket: sealed, journalled, the attempt state still there.
        assert final.step_name == "seal"
        assert is_sealed(handle.run_dir)
        rows = WorkflowJournal(handle.run_dir).list_steps(CASE)
        assert [(row.step_name, row.status) for row in rows] == [
            ("solved", "completed"),
            ("seal", "completed"),
        ]
        assert read_outcome(handle.run_dir).status == "running"
        assert (handle.run_dir / INTERNAL_DIRNAME).is_dir()

    run_dir = handle.run_dir
    assert (run_dir / RUN_MANIFEST_FILENAME).is_file()
    assert not (run_dir / INTERNAL_DIRNAME).exists(), "the seal consumes the attempt state"
    outcome = read_outcome(run_dir)
    assert outcome is not None and outcome.status == "completed" and outcome.attempt == 1
    assert effective_status(run_dir) == "completed"
    assert not (project / INTERNAL_DIRNAME / "index.duckdb").exists()


# A handle marked by withdraw() closes nothing: the pulse stops, the run log is
# detached, and the claim is undone. That is how an identical run gives the
# completed run back without leaving a directory.


@pytest.mark.parametrize("raised", [False, True], ids=["returns", "raises"])
def test_a_withdrawn_attempt_leaves_no_directory(tmp_path: Path, raised: bool) -> None:
    project = _project(tmp_path)

    with pytest.raises(RuntimeError) if raised else _no_error():
        with run_attempt(project, CASE, case_id=CASE, project="demo", site=None) as handle:
            assert (handle.run_dir / "logs").is_dir()
            handle.withdraw()
            if raised:
                raise RuntimeError("after the withdrawal")

    assert not handle.heartbeat.is_alive()
    assert not (project / "runs" / CASE).exists()


def test_a_withdrawn_retry_gives_back_the_failed_attempt(tmp_path: Path) -> None:
    project = _project(tmp_path)
    with pytest.raises(RuntimeError):
        with run_attempt(project, CASE, case_id=CASE, project="demo", site=None) as first:
            raise RuntimeError("the first attempt fails")
    failed = read_outcome(first.run_dir)

    with run_attempt(project, CASE, case_id=CASE, project="demo", site=None) as retry:
        assert retry.claim.attempt == 2
        retry.start_over_if_changed("a" * 64)
        retry.withdraw()

    assert read_outcome(first.run_dir) == failed
    assert not (first.run_dir / "attempts").exists()
    assert effective_status(first.run_dir) == "failed"


def _no_error():
    from contextlib import nullcontext

    return nullcontext()
