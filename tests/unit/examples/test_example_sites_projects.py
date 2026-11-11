"""Examples 09 and 19 are ``[sites]`` projects: they plan, check and dry-run clean.

Example 09 is one catchment and three recipes, read by ``hmp diff``.
Example 19 is two Breton catchments and two recipes, a plain run and a short
calibration, summed up by ``hmp campaign collect``. Neither runs here: the
plan, the check and the dry run need no solver and no network.
"""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

import pytest

from hydromodpy.project.api import check
from hydromodpy.project.launch.plan import expand_plan
from tests._helpers.cli_runner import CliRunner

pytestmark = pytest.mark.fast

PROJECTS = Path(__file__).resolve().parents[3] / "examples" / "projects"
EXAMPLE_09 = PROJECTS / "09_comparison_workflow"
EXAMPLE_19 = PROJECTS / "19_many_catchments"


def _cases(project: Path, config: str = "project.toml") -> dict:
    draft = expand_plan(project, project / config)
    assert draft.ok, draft.errors
    return {case.case_id: case for case in draft.cases}


def _rows() -> dict[str, dict[str, str]]:
    with (EXAMPLE_19 / "sites.csv").open(newline="", encoding="utf-8") as handle:
        return {row["site"]: row for row in csv.DictReader(handle)}


@pytest.mark.parametrize("project", [EXAMPLE_09, EXAMPLE_19], ids=["09", "19"])
def test_the_check_finds_no_error(project: Path) -> None:
    assert _cases(project)
    errors = [item.line() for item in check(project / "project.toml") if item.severity == "error"]
    assert not errors, errors


def test_example_09_is_one_site_crossed_with_three_values_of_k() -> None:
    cases = _cases(EXAMPLE_09)
    assert sorted(cases) == ["nancon-k_high", "nancon-k_low", "nancon-k_mid"]
    k = {
        case.recipe: case.document["flow"]["param"]["K"]["field"]["value"]
        for case in cases.values()
    }
    assert k == {"k_low": 1e-5, "k_mid": 5e-5, "k_high": 2e-4}


def test_example_19_crosses_two_sites_with_a_run_and_a_calibration() -> None:
    cases = _cases(EXAMPLE_19)
    assert sorted(cases) == [
        "canut-base",
        "canut-calibration",
        "nancon-base",
        "nancon-calibration",
    ]
    assert {case.case_id: case.kind for case in cases.values()} == {
        "canut-base": "simulation",
        "canut-calibration": "calibration",
        "nancon-base": "simulation",
        "nancon-calibration": "calibration",
    }


def test_every_key_of_a_catchment_comes_from_its_row() -> None:
    rows = _rows()
    for case in _cases(EXAMPLE_19).values():
        row = rows[case.site]
        document = case.document
        assert document["site"] == {
            "name": row["site"],
            "label": row["label"],
            "gauge": row["gauge"],
        }
        catchment = document["geographic"]["catchment"]
        assert catchment["x_outlet"] == float(row["x_outlet"])
        assert catchment["y_outlet"] == float(row["y_outlet"])
        # No station is written: the Hub'Eau source reads the gauge of the site.
        assert "station_ids" not in document["data"]["hydrometry"]["sources"][0]


def test_the_calibration_recipe_binds_its_bounds_and_its_station() -> None:
    rows = _rows()
    calibrations = [case for case in _cases(EXAMPLE_19).values() if case.kind == "calibration"]
    assert len(calibrations) == 2
    for case in calibrations:
        row = rows[case.site]
        calibration = case.document["calibration"]
        assert calibration["parameters"]["K"]["bounds"] == [
            float(row["k_low"]),
            float(row["k_high"]),
        ]
        assert calibration["outputs"]["hydrograph"]["observes"] == row["gauge"]


def test_the_calibration_recipe_alone_runs_on_every_site() -> None:
    cases = _cases(EXAMPLE_19, "calibration.toml")
    assert sorted(cases) == ["canut-calibration", "nancon-calibration"]


def test_a_site_override_reaches_the_cases_of_its_site_only() -> None:
    for case in _cases(EXAMPLE_19).values():
        overrides = case.document.get("display", {}).get("overrides", {})
        if case.site == "nancon":
            assert overrides["cross_section"] == {"orientation": "sn"}
        else:
            assert "cross_section" not in overrides


def test_the_summary_and_its_exports_are_declared() -> None:
    sites = expand_plan(EXAMPLE_19, EXAMPLE_19 / "project.toml").sites_config
    assert sites.summary.best == "calibrated"
    assert {"nse", "kge"} <= set(sites.summary.metrics)
    assert sites.summary.parameters == ["K"]
    assert [(item.table, item.runs) for item in sites.export] == [
        ("by_site", None),
        (None, "best"),
    ]


@pytest.mark.parametrize(
    ("project", "planned"),
    [(EXAMPLE_09, "3 cases (1 sites x 3 recipes)"), (EXAMPLE_19, "4 cases (2 sites x 2 recipes)")],
    ids=["09", "19"],
)
def test_a_dry_run_prints_the_plan_and_writes_nothing(
    project: Path, planned: str, tmp_path: Path
) -> None:
    copy = tmp_path / project.name
    outputs = ("runs", "sessions", "plan", "jobs", "summary", "trash", ".hmp", "hydromodpy.lock")
    shutil.copytree(project, copy, ignore=shutil.ignore_patterns(*outputs))
    before = sorted(path.relative_to(copy) for path in copy.rglob("*"))

    result = CliRunner().invoke(["run", str(copy / "project.toml"), "--dry-run", "-q"])

    assert result.exit_code == 0, result.stderr
    assert planned in result.stdout
    assert sorted(path.relative_to(copy) for path in copy.rglob("*")) == before
