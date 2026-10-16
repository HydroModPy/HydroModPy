"""A run of a planned case seals its recipe, read from the plan.

``hmp report compare k_mid k_low k_high`` and ``--by site`` read the recipe of
each run from ``manifest.run.recipe`` and the index: a worker of the plan
must write it. The case id names the recipe for the life of the project, so
the current plan answers; a run outside any plan has none.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.project.launch import plan_project
from hydromodpy.workflow.steps.prepare_solver.dispatch import planned_recipe
from tests.unit.project._launch_fakes import write_project


def test_a_planned_case_reads_its_recipe_from_the_plan(tmp_path: Path) -> None:
    project = write_project(tmp_path)
    plan_project(project)

    assert planned_recipe(project, "alpha-k2e_5") == "k2e_5"
    assert planned_recipe(project, "beta-base") == "base"
    assert planned_recipe(project, "a_free_run") is None


def test_a_project_without_a_plan_gives_no_recipe(tmp_path: Path) -> None:
    assert planned_recipe(tmp_path, "alpha-base") is None
