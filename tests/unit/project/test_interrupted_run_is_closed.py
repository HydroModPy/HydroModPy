"""A run cut by Ctrl+C or SIGTERM closes its outcome as aborted, a crash as failed.

The attempt protocol brackets the pipeline: the directory of the case is
claimed before the first step and its ``outcome.json`` is rewritten on the
way out, whatever the exception, with the signal that cut it and the end of
the run log. No index is opened.
"""

from __future__ import annotations

import signal
from pathlib import Path

import pytest

from hydromodpy.core.interrupts import TerminationRequested
from hydromodpy.core.logging import get_logger
from hydromodpy.results.outcome import read_outcome
from hydromodpy.results.storage.run_log import run_log_path
from tests.unit.project.test_run_pipeline_state import DEM, PROJECT_TOML

LAST_WORDS = "stress period 51: the solver is about to give up"


@pytest.mark.parametrize(
    ("signal_error", "status", "number"),
    [
        (KeyboardInterrupt, "aborted", int(signal.SIGINT)),
        (TerminationRequested, "aborted", int(signal.SIGTERM)),
        (RuntimeError, "failed", None),
    ],
)
def test_an_interrupted_run_closes_its_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    signal_error: type[BaseException],
    status: str,
    number: int | None,
) -> None:
    from hydromodpy.project.facade import Project

    config_path = tmp_path / "project.toml"
    config_path.write_text(
        PROJECT_TOML.format(root=tmp_path.as_posix(), dem=DEM.as_posix()), encoding="utf-8"
    )

    class _Pipeline:
        def __init__(self, steps, *, workspace, run_dir) -> None:
            self.steps = steps
            self.run_dir = run_dir

        def run(self, state, **kwargs):
            heartbeat = kwargs.get("heartbeat")
            if heartbeat is not None:
                heartbeat.set_step("run_solver")
            get_logger("hydromodpy.solver.test").warning(LAST_WORDS)
            raise signal_error("cut")

    monkeypatch.setattr("hydromodpy.workflow.runner.Pipeline", _Pipeline)
    project = Project(config_path, no_display=True)

    with pytest.raises(signal_error):
        project._execute(name="asked_name")

    run_dir = tmp_path / "runs" / "asked_name"
    outcome = read_outcome(run_dir)
    assert outcome is not None
    assert outcome.status == status
    assert outcome.step == "run_solver"
    assert outcome.ended_at is not None
    assert outcome.signal == number
    if status == "failed":
        assert outcome.error is not None and outcome.error.type == "RuntimeError"
    assert outcome.log_tail, "the end of the run log travels with the outcome"
    assert any(LAST_WORDS in line for line in outcome.log_tail)
    assert run_log_path(run_dir).is_file()
    assert LAST_WORDS in run_log_path(run_dir).read_text(encoding="utf-8")
    readme = (run_dir / "README.md").read_text(encoding="utf-8")
    assert LAST_WORDS in readme
    assert not (tmp_path / ".hmp" / "index.duckdb").exists()
