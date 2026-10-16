"""End-to-end: the worker of ``hmp run`` never opens the index.

``Catalog.__init__`` is patched to raise for the whole worker (the dispatch of
the simulation workflow, which claims the directory, runs the thirteen steps
and seals the run). Step 1 of example 04 solves on a real MODFLOW 6 model in a
disposable workspace. Afterwards ``runs/<case>/`` carries its seal and its
outcome, and ``.hmp/index.duckdb`` does not exist: the index is derived by
the launcher once the worker has returned, never by the run.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from hydromodpy.core.state.paths import INTERNAL_DIRNAME, catalog_path_for
from hydromodpy.results.manifest import read_manifest
from hydromodpy.results.outcome import effective_status, read_outcome
from hydromodpy.results.storage.contract import (
    README_FILENAME,
    RUN_CONFIG_FILENAME,
    RUN_INPUTS_FILENAME,
    RUN_LOGS_DIRNAME,
    RUN_MANIFEST_FILENAME,
    RUN_OUTCOME_FILENAME,
)
from tests.e2e._step1_minimal import RUN_NAME, disposable_env, make_workspace

pytestmark = pytest.mark.e2e


def _refuse_the_index(monkeypatch: pytest.MonkeyPatch) -> None:
    from hydromodpy.results.catalog import facade

    def _refuse(self, *args, **kwargs):
        raise AssertionError("the run opened the index")

    monkeypatch.setattr(facade.Catalog, "__init__", _refuse)


def test_the_worker_of_hmp_run_never_opens_the_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hydromodpy
    from hydromodpy.project.dispatch.workflow import dispatch_workflow

    hydromodpy.bootstrap()
    project = make_workspace(tmp_path / "workspace")
    for key, value in disposable_env(tmp_path / "home").items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("HMP_WORKSPACE", raising=False)
    monkeypatch.chdir(project)
    _refuse_the_index(monkeypatch)

    summary = dispatch_workflow("simulation", project / "step1_minimal.toml", no_display=True)

    run_dir = project / "runs" / RUN_NAME
    assert summary["name"] == RUN_NAME
    assert summary["run_dir"] == str(run_dir)
    assert not catalog_path_for(project).exists(), "the run wrote the index"
    assert (run_dir / RUN_MANIFEST_FILENAME).is_file()
    assert (run_dir / RUN_OUTCOME_FILENAME).is_file()
    assert (run_dir / RUN_INPUTS_FILENAME).is_file()
    assert (run_dir / README_FILENAME).is_file()
    assert (run_dir / RUN_CONFIG_FILENAME).is_file()
    assert (run_dir / RUN_LOGS_DIRNAME).is_dir()
    assert not (run_dir / INTERNAL_DIRNAME).exists(), "the seal consumes the attempt state"
    assert effective_status(run_dir) == "completed"
    outcome = read_outcome(run_dir)
    assert outcome is not None and outcome.status == "completed" and outcome.attempt == 1
    manifest = read_manifest(run_dir)
    assert manifest["run"]["sim_id"] == summary["sim_id"]
    assert manifest["identity"]["config_hash"]
    assert manifest["site"]["name"] == "nancon"
    assert os.environ.get("HMP_RUN_SCRATCH") is None
