"""A case started by the launcher gets a clean environment and claims its own scratch.

The scratch folder of a run lives in a context variable, so a child process never
inherits it and a run writes nothing into the environment. The launcher removes
the ``HMP_SET_*`` the plan already rendered from the environment of every case,
and gives each case its thread budget. A case has no data cache of its own: it
writes the shared ``data/`` folder.

A launched case also inherits the machine scratch root ``HMP_SCRATCH_ROOT``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from hydromodpy.core.state.scratch import SCRATCH_ROOT_ENV, run_scratch
from hydromodpy.project.launch.env import (
    THREAD_LIMIT_VARIABLES,
    THREADS_ENV,
    apply_thread_budget,
    child_environment,
    threads_of,
)
from hydromodpy.project.launch.local import plan_project, run_plan
from tests.unit.project.launch._launch_fakes import CASES, seen, write_project


def test_the_environment_of_a_case_drops_the_overrides_of_the_plan() -> None:
    parent = {"HMP_SET_flow__param__K__field__value": "1e-6", "PATH": "/usr/bin"}

    env = child_environment(parent, threads_per_case=2)

    assert "HMP_SET_flow__param__K__field__value" not in env
    assert env["PATH"] == "/usr/bin"
    assert env[THREADS_ENV] == "2"
    assert set(env) == {"PATH", THREADS_ENV}


@pytest.mark.allow_subprocess
def test_a_case_launched_from_inside_a_run_gets_a_clean_environment(
    tmp_path: Path, fake_worker: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = write_project(tmp_path, sites_extra="[sites.run]\nthreads_per_case = 1\n")
    plan_project(project)
    monkeypatch.setenv("HMP_SET_flow__param__K__field__value", "1e-6")

    with run_scratch(project, "parent"):
        assert "HMP_RUN_SCRATCH" not in os.environ
        run_plan(project)

    for case_id in CASES:
        for phase in ("prepare", "run"):
            env = seen(project, case_id, phase)["env"]
            assert env["HMP_SET_flow__param__K__field__value"] is None
            assert env["HMP_THREADS_PER_CASE"] == "1"


def test_the_worker_applies_the_thread_budget_of_its_case(monkeypatch: pytest.MonkeyPatch) -> None:
    applied: list[int] = []
    monkeypatch.setattr("threadpoolctl.threadpool_limits", lambda limits: applied.append(limits))
    for name in THREAD_LIMIT_VARIABLES:
        monkeypatch.delenv(name, raising=False)

    assert apply_thread_budget({}) is None
    assert applied == []
    assert apply_thread_budget({THREADS_ENV: "3"}) == 3

    assert applied == [3]
    assert {os.environ[name] for name in THREAD_LIMIT_VARIABLES} == {"3"}
    with pytest.raises(ValueError, match="positive integer"):
        threads_of({THREADS_ENV: "0"})


def test_a_launched_case_inherits_the_machine_scratch_root(tmp_path: Path) -> None:
    env = child_environment({SCRATCH_ROOT_ENV: str(tmp_path)}, threads_per_case=1)

    assert env[SCRATCH_ROOT_ENV] == str(tmp_path)
