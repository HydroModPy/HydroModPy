"""A failed attempt leaves a directory that explains itself and never a manifest.

The attempt protocol closes a failed run with ``outcome.json`` (``failed``,
the error, the step, the end of the log) and a ``README.md`` rendered from
that outcome. The tables written before the failure stay. ``manifest.json`` is
never written: its presence would mean ``completed``. The attempt state under
``<run>/.hmp/`` is left as it was, for the retry. The indexer indexes the
directory from its outcome alone.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from hydromodpy.core.state.layout import INTERNAL_DIRNAME, RUNS_DIRNAME
from hydromodpy.results.catalog.indexer import index_new_runs
from hydromodpy.results.outcome import effective_status, read_outcome
from hydromodpy.results.storage.attempt import claim_run_directory, finish_attempt
from hydromodpy.results.storage.contract import (
    PARQUET_FILE_SUFFIX,
    README_FILENAME,
    RUN_MANIFEST_FILENAME,
    RUN_OUTCOME_FILENAME,
    TABLES_DIRNAME,
)
from hydromodpy.results.storage.run_facts import RunFacts, read_facts
from hydromodpy.results.storage.run_store import RunStore
from tests._helpers.sealed_runs import make_project

CASE = "nancon_daily"


def _facts(claim) -> RunFacts:
    return RunFacts(
        sim_id=claim.sim_id,
        name=claim.name,
        case_id=CASE,
        project="demo",
        attempt=claim.attempt,
        attempt_id=claim.attempt_id,
        created_at=claim.started_at,
        started_at=claim.started_at,
        solver="modflow6",
    )


def _fail_a_run(project: Path) -> Path:
    claim = claim_run_directory(project, CASE, case_id=CASE, project="demo", site="nancon")
    with RunStore.open(claim.run_dir, facts=_facts(claim)) as store:
        index = pd.date_range("2020-01-01", periods=3, freq="D")
        store.write_timeseries(claim.sim_id, "P01", "head", pd.Series(np.ones(3), index=index))
        store.write_budget(claim.sim_id, 0, "z1", "recharge", 10.0, 0.0)
    finish_attempt(
        claim.run_dir,
        status="failed",
        step="run_solver",
        error=RuntimeError("mf6 did not converge at stress period 51"),
        exit_code=15,
        log_tail=["stress period 51 failed"],
    )
    return claim.run_dir


def test_a_failed_attempt_writes_its_outcome_and_readme_and_keeps_its_tables(tmp_path):
    project = make_project(tmp_path / "demo")

    run_dir = _fail_a_run(project)

    outcome = read_outcome(run_dir)
    assert outcome is not None
    assert outcome.status == "failed"
    assert outcome.step == "run_solver"
    assert outcome.exit_code == 15
    assert outcome.error is not None and outcome.error.type == "RuntimeError"
    assert outcome.log_tail == ["stress period 51 failed"]
    assert outcome.ended_at is not None
    readme = (run_dir / README_FILENAME).read_text(encoding="utf-8")
    assert "did not complete" in readme
    assert "stress period 51" in readme
    tables = sorted(path.name for path in (run_dir / TABLES_DIRNAME).iterdir())
    assert tables == [f"budgets{PARQUET_FILE_SUFFIX}", f"timeseries{PARQUET_FILE_SUFFIX}"]


def test_a_failed_attempt_has_no_manifest_and_reads_as_failed(tmp_path):
    project = make_project(tmp_path / "demo")

    run_dir = _fail_a_run(project)

    assert not (run_dir / RUN_MANIFEST_FILENAME).exists()
    assert effective_status(run_dir) == "failed"


def test_a_failed_attempt_keeps_its_attempt_state_for_the_retry(tmp_path):
    project = make_project(tmp_path / "demo")

    run_dir = _fail_a_run(project)

    assert (run_dir / INTERNAL_DIRNAME).is_dir()
    facts = read_facts(run_dir)
    assert facts is not None and facts.solver == "modflow6"


def test_a_failed_attempt_is_indexed_from_its_outcome(tmp_path):
    project = make_project(tmp_path / "demo")
    run_dir = _fail_a_run(project)

    report = index_new_runs(project)

    assert f"{RUNS_DIRNAME}/{CASE}" in set(report.indexed), report
    assert (run_dir / RUN_OUTCOME_FILENAME).is_file()
