"""A case started by the launcher owns its scratch: ``HMP_RUN_SCRATCH`` never reaches it.

``HMP_RUN_SCRATCH`` names the scratch folder of the run the current process is
inside; a child that inherited it would work in the folder of its parent. The
launcher removes it, and the ``HMP_SET_*`` the plan already rendered, from the
environment of every case, and gives each case its thread budget. A case has no
data cache of its own: it writes the shared ``data/`` folder.

A launched case also inherits the machine scratch root ``HMP_SCRATCH_ROOT``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from hydromodpy.core.state.scratch import RUN_SCRATCH_ENV, SCRATCH_ROOT_ENV, run_scratch
from hydromodpy.project.launch import plan_project, run_plan
from hydromodpy.project.launch.env import (
    THREAD_LIMIT_VARIABLES,
    THREADS_ENV,
    apply_thread_budget,
    child_environment,
    threads_of,
)
from tests.unit.project.launch._launch_fakes import CASES, seen, write_project


def test_the_environment_of_a_case_drops_the_scratch_of_the_parent() -> None:
    parent = {
        RUN_SCRATCH_ENV: "parent.p123",
        "HMP_SET_flow__param__K__field__value": "1e-6",
        "PATH": "/usr/bin",
    }

    env = child_environment(parent, threads_per_case=2)

    assert RUN_SCRATCH_ENV not in env
    assert "HMP_SET_flow__param__K__field__value" not in env
    assert env["PATH"] == "/usr/bin"
    assert env[THREADS_ENV] == "2"
    assert set(env) == {"PATH", THREADS_ENV}


@pytest.mark.allow_subprocess
def test_a_case_launched_from_inside_a_run_does_not_inherit_its_scratch(
    tmp_path: Path, fake_worker: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = write_project(tmp_path, sites_extra="[sites.run]\nthreads_per_case = 1\n")
    plan_project(project)
    monkeypatch.setenv("HMP_SET_flow__param__K__field__value", "1e-6")

    with run_scratch(project, "parent"):
        assert RUN_SCRATCH_ENV in __import__("os").environ
        run_plan(project)

    for case_id in CASES:
        for phase in ("prepare", "run"):
            env = seen(project, case_id, phase)["env"]
            assert env["HMP_RUN_SCRATCH"] is None
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
    env = child_environment(
        {SCRATCH_ROOT_ENV: str(tmp_path), "HMP_RUN_SCRATCH": "parent.p1"},
        threads_per_case=1,
    )

    assert env[SCRATCH_ROOT_ENV] == str(tmp_path)
    assert "HMP_RUN_SCRATCH" not in env
