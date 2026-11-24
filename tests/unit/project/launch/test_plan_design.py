"""A [sites.design] plan: points drawn at each expansion become the recipes of the base recipe."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from hydromodpy.core.toml_io.paths import lookup
from hydromodpy.project.launch.plan import (
    SitesProjectError,
    expand_plan,
    group_issues,
    write_plan_draft,
)
from hydromodpy.results.plan_store import read_plan
from tests.unit.project.launch.test_plan import _K_PATH, _seal, write_sites_project

_PARAMETER = f"""
[sites.design.parameters.K]
path = "{_K_PATH}"
bounds = [1e-7, 1e-3]
sampling = "log_uniform"
"""


def _design(
    method: str = "sobol", n: str = "n = 4", seed: str = "seed = 3", extra: str = ""
) -> str:
    return (
        f'\n[sites.design]\nmethod = "{method}"\n{n}\n{seed}\nrecipe = "base"\n{extra}{_PARAMETER}'
    )


def _project(tmp_path: Path, design: str | None = None, **kwargs) -> Path:
    return write_sites_project(
        tmp_path, k_column=False, sites_extra=design if design is not None else _design(), **kwargs
    )


def _rewrite(project: Path, old: str, new: str) -> None:
    file = project / "project.toml"
    file.write_text(file.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")


def _expand(project: Path):
    return expand_plan(project, project / "project.toml")


def _ids(draft) -> list[str]:
    return [case.case_id for case in draft.cases]


def _hashes(draft) -> dict[str, str | None]:
    return {case.case_id: case.config_hash for case in draft.cases}


def test_points_are_cases_named_by_site_and_point(tmp_path: Path) -> None:
    draft = _expand(_project(tmp_path))

    assert draft.ok, group_issues(draft.errors)
    sobol = [f"{site}-p{i:04d}" for site in ("nancon", "couesnon") for i in range(1, 5)]
    assert sorted(case.case_id for case in draft.cases if "-p" in case.case_id) == sorted(sobol)
    # The recipe that is not the base still runs once per site.
    assert {"nancon-k2e_5", "couesnon-k2e_5"} <= set(_ids(draft))
    drawn = [float(lookup(c.document, _K_PATH)) for c in draft.cases if c.recipe.startswith("p")]
    assert all(1e-7 <= k <= 1e-3 for k in drawn)
    assert len(set(drawn)) == 4


def test_two_expansions_give_the_same_cases_and_hashes(tmp_path: Path) -> None:
    project = _project(tmp_path)
    assert _hashes(_expand(project)) == _hashes(_expand(project))
    assert _ids(_expand(project)) == _ids(_expand(project))


def test_doubling_a_sobol_n_keeps_the_first_cases(tmp_path: Path) -> None:
    project = _project(tmp_path)
    four = _hashes(_expand(project))
    _rewrite(project, "n = 4", "n = 8")
    eight = _hashes(_expand(project))

    assert len(eight) == len(four) + 8
    assert {case: key for case, key in eight.items() if case in four} == four


def test_lhs_lots_keep_the_earlier_lots(tmp_path: Path) -> None:
    project = _project(tmp_path, _design("lhs", "n = [3]"))
    first = _expand(project)
    assert sorted(c.recipe for c in first.cases if c.site == "nancon" and c.recipe[0] == "b") == [
        "b1p0001",
        "b1p0002",
        "b1p0003",
    ]
    _rewrite(project, "n = [3]", "n = [3, 2]")
    second = _expand(project)

    kept = _hashes(first)
    assert {case: key for case, key in _hashes(second).items() if case in kept} == kept
    assert "nancon-b2p0002" in _ids(second)


def test_sobol_not_a_power_of_two_warns_and_does_not_refuse(tmp_path: Path) -> None:
    draft = _expand(_project(tmp_path, _design(n="n = 6")))

    assert draft.ok
    assert any("power of two" in line for line in group_issues(draft.warnings))


def test_the_drawn_values_reach_cases_csv_without_a_new_schema(tmp_path: Path) -> None:
    project = _project(tmp_path)
    draft = _expand(project)
    plan_dir = write_plan_draft(project, draft)

    header = (plan_dir / "cases.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header.endswith(",K")
    frame = pd.read_csv(plan_dir / "cases.csv", dtype=str, keep_default_na=False)
    by_id = frame.set_index("case_id")["K"]
    point = next(c for c in draft.cases if c.case_id == "nancon-p0002")
    assert float(by_id["nancon-p0002"]) == float(lookup(point.document, _K_PATH))
    assert by_id["nancon-k2e_5"] == ""
    stored = read_plan(project)
    assert stored.plan.schema_ == "hydromodpy.plan.v2"
    assert stored.plan.design_columns == ["K"]
    assert "K" not in stored.sites.columns
    assert stored.design is not None and len(stored.design) == len(draft.cases)


def test_a_plan_without_a_design_writes_the_same_plan_json(tmp_path: Path) -> None:
    project = write_sites_project(tmp_path)
    plan_dir = write_plan_draft(project, _expand(project))

    assert "design_columns" not in (plan_dir / "plan.json").read_text(encoding="utf-8")


def test_an_unsealed_plan_can_change_its_size(tmp_path: Path) -> None:
    project = _project(tmp_path, _design("lhs", "n = [4]"))
    write_plan_draft(project, _expand(project))
    _rewrite(project, "n = [4]", "n = [6]")

    assert _expand(project).ok
