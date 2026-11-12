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
from hydromodpy.core.exceptions import DisplayError, ExportError, StepError
from hydromodpy.core.runtime.interrupts import StopRequested
from hydromodpy.core.state.layout import (
    INTERNAL_DIRNAME,
    PROJECT_MARKER_FILENAME,
    stop_flag_for,
)
from hydromodpy.results.outcome import effective_status, read_outcome
from hydromodpy.results.record.manifest import is_sealed
from hydromodpy.results.storage.attempt import request_stop
from hydromodpy.results.storage.contract import RUN_CONFIG_FILENAME
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
        attempt=1,
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


class _FailsAfterTheSeal:
    """A render after the seal that raises, as a figure or an export may."""

    name = "display"

    def __init__(self, error: BaseException, seen: dict) -> None:
        self.error = error
        self.seen = seen

    def run(self, state: PipelineState) -> PipelineState:
        run_dir = state.get("ctx").run_dir
        self.seen["readme"] = (run_dir / "README.md").read_text(encoding="utf-8")
        raise self.error


@pytest.mark.parametrize(
    ("error", "raised_type"),
    [
        pytest.param(
            DisplayError("run x is sealed; draw the figure again"), StepError, id="a figure"
        ),
        pytest.param(
            ExportError("run x is sealed; write the exports again"), StepError, id="an export"
        ),
        pytest.param(KeyboardInterrupt(), KeyboardInterrupt, id="a stop while the figures draw"),
    ],
)
def test_render_failure_after_the_seal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: BaseException, raised_type: type
) -> None:
    _refuse_the_index(monkeypatch)
    project = _project(tmp_path)
    seen: dict = {}

    # The pipeline wraps a failure in a StepError that names the step. The CLI exits by
    # the category of its cause. A stop passes through unwrapped.
    with pytest.raises(raised_type) as raised:
        with run_attempt(project, CASE, case_id=CASE, project="demo", site=None) as handle:
            _fill(project, handle.claim)
            ctx = _ctx(project, handle.run_dir, handle.claim.sim_id)
            pipeline = Pipeline(
                [_Solved(), SealStep(), _FailsAfterTheSeal(error, seen)],
                workspace=project,
                run_dir=handle.run_dir,
            )
            pipeline.run(
                PipelineState(run_id=CASE, data={"ctx": ctx}),
                heartbeat=handle.heartbeat,
            )

    assert getattr(raised.value, "cause", error) is error
    run_dir = handle.run_dir
    assert is_sealed(run_dir)
    outcome = read_outcome(run_dir)
    assert outcome is not None and outcome.status == "completed"
    assert outcome.error is None
    assert effective_status(run_dir) == "completed"
    assert not (run_dir / INTERNAL_DIRNAME).exists(), "the seal consumes the attempt state"
    assert (run_dir / "README.md").read_text(encoding="utf-8") == seen["readme"]


class _AsksToStop:
    """A step that asks its own run to stop, as a server would from another process."""

    name = "asks_to_stop"

    def run(self, state: PipelineState) -> PipelineState:
        request_stop(state.get("run_dir"))
        return state.advance(step_index=state.step_index + 1, step_name=self.name)


def test_stop_between_two_steps_aborts(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)

    with pytest.raises(StopRequested, match="stop requested at"):
        with run_attempt(project, CASE, case_id=CASE, project="demo", site=None) as handle:
            pipeline = Pipeline(
                [_AsksToStop(), _Solved()], workspace=project, run_dir=handle.run_dir
            )
            pipeline.run(
                PipelineState(run_id=CASE, data={"run_dir": handle.run_dir}),
                heartbeat=handle.heartbeat,
            )

    run_dir = handle.run_dir
    outcome = read_outcome(run_dir)
    assert outcome.status == "aborted"
    assert outcome.signal is None
    assert outcome.error is not None and outcome.error.type == "StopRequested"
    assert outcome.step == "solved"
    assert not is_sealed(run_dir)
    assert stop_flag_for(run_dir).is_file(), "the flag stays for the attempt that resumes"
    rows = WorkflowJournal(run_dir).list_steps(CASE)
    assert [(row.step_name, row.status) for row in rows] == [("asks_to_stop", "completed")]
