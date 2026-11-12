"""The plan of a [sites] project: tables, binding, precedence, origins, refusals, writing, replay."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import pytest

from hydromodpy.core.config_kit.base import ConfigKeyRenamedWarning
from hydromodpy.core.diagnostic import Diagnostic
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.site.row import SiteRow
from hydromodpy.core.toml_io.paths import lookup
from hydromodpy.data.sites.catalog import write_catalog
from hydromodpy.project.launch.plan import (
    PlanError,
    PlanIssue,
    RunningCaseError,
    SitesProjectError,
    case_is_done,
    dry_run_lines,
    expand_plan,
    group_diagnostics,
    group_issues,
    is_empty_cell,
    is_plan_case,
    plan_budget,
    plan_hash,
    read_table,
    refuse_env_overrides,
    write_plan_draft,
)
from hydromodpy.results.plan_store import PLAN_SCHEMA, current_plan_hash, read_plan
from hydromodpy.results.session.descriptor import write_session
from hydromodpy.results.storage.contract import PUBLICATION_FILENAME, RUN_MANIFEST_FILENAME
from tests._helpers.sealed_runs import manifest_document
from tests._helpers.session_documents import session_descriptor

_PROJECT = """\
[workspace]
data_dir = "data"

[workflow]
mode = "simulation"

[geographic]
crs_project = "EPSG:2154"

[geographic.catchment]
kind = "from_outlet_coord"
snap_dist = "150 m"
buff_area = "10%"

[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2000-03-31"
step_value = "1 month"

[[simulation.process]]
id = "flow_main"
kind = "flow"
solvers = ["modflow6"]

[flow]
flow_regime = "steady"
param_list = ["K"]

[flow.param.K.field]
kind = "homogeneous"
unit = "m/s"
value = 5e-5

[flow.bc.drainage]
{extra}
[sites]
table = "sites.csv"
overrides = "site_overrides"
{sites_extra}
[sites.recipes]
base = "project.toml"
k2e_5 = {{ file = "project.toml", set = {{ "flow.param.K.field.value" = 2e-5 }} }}
{recipes_extra}
[sites.bind]
"site.name" = "site"
"site.gauge" = "gauge"
"geographic.catchment.x_outlet" = "x_outlet"
"geographic.catchment.y_outlet" = "y_outlet"
{bind_extra}
"""

_K_PATH = "flow.param.K.field.value"


def write_sites_project(
    tmp_path: Path,
    *,
    k_cells: tuple[str, str] | None = None,
    extra: str = "",
    sites_extra: str = "",
    recipes_extra: str = "",
    bind_extra: str = "",
    k_column: bool = True,
) -> Path:
    """Write a two-site, two-recipe project under *tmp_path* and return its root."""
    project = tmp_path / "campaign"
    project.mkdir(parents=True)
    (project / "data").mkdir()
    (project / "dem.tif").write_bytes(b"not a raster, never read by the plan")
    if k_column:
        bind_extra = f'"{_K_PATH}" = "k"\n' + bind_extra
    (project / "project.toml").write_text(
        _PROJECT.format(
            extra=extra, sites_extra=sites_extra, recipes_extra=recipes_extra, bind_extra=bind_extra
        ),
        encoding="utf-8",
    )
    k1, k2 = k_cells or ("1e-5", "")
    header = "site,gauge,x_outlet,y_outlet" + (",k" if k_column else "")
    row1 = "nancon,J0014010,389285.910,6816518.749" + (f",{k1}" if k_column else "")
    row2 = "couesnon,,377120.0,6831410.0" + (f",{k2}" if k_column else "")
    (project / "sites.csv").write_text(f"{header}\n{row1}\n{row2}\n", encoding="utf-8")
    (project / "site_overrides").mkdir()
    return project


def _k(case) -> float:
    return float(lookup(case.document, _K_PATH))


def _case(draft, case_id: str):
    return next(case for case in draft.cases if case.case_id == case_id)


def test_recipes_are_exactly_the_listed_files(tmp_path: Path) -> None:
    project = write_sites_project(tmp_path)
    (project / "run_daily.toml").write_text(
        'base_config = "project.toml"\n[simulation.time]\nstep_value = "1 day"\n', encoding="utf-8"
    )
    (project / "k7.toml").write_text(
        'base_config = "project.toml"\n[flow.param.K.field]\nvalue = 7e-5\n', encoding="utf-8"
    )
    (project / "project.toml").write_text(
        (project / "project.toml")
        .read_text(encoding="utf-8")
        .replace("[sites.recipes]\n", '[sites.recipes]\nk7 = "k7.toml"\n'),
        encoding="utf-8",
    )

    draft = expand_plan(project, project / "project.toml")

    assert [recipe.name for recipe in draft.recipes] == ["k7", "base", "k2e_5"]
    assert sorted(case.case_id for case in draft.cases) == sorted(
        f"{site}-{recipe}" for site in ("nancon", "couesnon") for recipe in ("base", "k2e_5", "k7")
    )
    # A file of the folder that is not listed is not a recipe.
    with pytest.raises(SitesProjectError, match="run_daily.toml is not a recipe"):
        expand_plan(project, project / "run_daily.toml")
    # Running one listed file runs that recipe alone, on every site.
    alone = expand_plan(project, project / "k7.toml")
    assert [case.case_id for case in alone.cases] == ["nancon-k7", "couesnon-k7"]


def test_a_bad_cell_names_its_row_and_column(tmp_path: Path) -> None:
    project = write_sites_project(tmp_path, k_cells=("5e-5", "not_a_number"))

    draft = expand_plan(project, project / "project.toml")

    lines = group_issues(draft.errors)
    assert len(lines) == 1
    # The recipe k2e_5 writes K itself, so the bad cell fails the base case alone.
    assert lines[0].startswith("couesnon-base: sites.csv:3 column k -> flow.param.K.field.value: ")
    assert sorted(case.case_id for case in draft.cases) == [
        "couesnon-k2e_5",
        "nancon-base",
        "nancon-k2e_5",
    ]
    with pytest.raises(PlanError, match="sites.csv:3 column k"):
        write_plan_draft(project, draft)


def _other_recipe_declaring_sites(project: Path) -> None:
    (project / "other.toml").write_text(
        'base_config = "project.toml"\n[sites]\ninclude = ["nancon"]\n', encoding="utf-8"
    )
    text = (project / "project.toml").read_text(encoding="utf-8")
    text = text.replace("[sites.recipes]\n", '[sites.recipes]\nother = "other.toml"\n')
    (project / "project.toml").write_text(text, encoding="utf-8")


def _recipes_table(text: str):
    def write(project: Path) -> None:
        (project / "recipes.csv").write_text(text, encoding="utf-8")

    return write


def _write_sites(text: str):
    def write(project: Path) -> None:
        (project / "sites.csv").write_text(text, encoding="utf-8")

    return write


_HEADER = "site,gauge,x_outlet,y_outlet,k\n"
_RECIPES_TABLE = {"sites_extra": 'recipes_table = "recipes.csv"\n'}

# (project arguments, what to do to the project, the sentence of the refusal)
REFUSALS = {
    "a column in both tables": (
        _RECIPES_TABLE,
        _recipes_table("recipe,k\nlow,1e-6\n"),
        r"column\(s\) k present in both",
    ),
    "a recipe table without the recipe column": (
        _RECIPES_TABLE,
        _recipes_table("name,kk\nlow,1e-6\n"),
        "'recipe' column",
    ),
    "a recipe name with a hyphen": (
        _RECIPES_TABLE,
        _recipes_table("recipe,kk\nlow-k,1e-6\n"),
        "is not a recipe name",
    ),
    "a recipe with no name": (
        _RECIPES_TABLE,
        _recipes_table("recipe,kk\n,1e-6\n"),
        "no recipe name",
    ),
    "a recipe named twice": (
        {"sites_extra": 'recipes_table = "recipes.csv"\n'},
        _recipes_table("recipe,kk\nbase,1e-6\n"),
        "recipe 'base' is also declared in",
    ),
    "an unknown bind key": (
        {"bind_extra": '"geographic.catchment.x_outlt" = "x_outlet"\n'},
        None,
        "x_outlt.*nearest.*x_outlet",
    ),
    "a bind key that is a table": (
        {"bind_extra": '"geographic.catchment" = "gauge"\n'},
        None,
        "is a table, and a cell holds",
    ),
    "a bind column no table has": (
        {"bind_extra": '"geographic.catchment.snap_dist" = "snap"\n'},
        None,
        r"names column\(s\) snap, found in sites.csv",
    ),
    "a key unknown to the schema in set": (
        {"recipes_extra": 'bad = { file = "project.toml", set = { "flow.nope" = 1 } }\n'},
        None,
        r"\[sites.recipes\] bad: set",
    ),
    "a site declared beside sites": (
        {"extra": '[site]\nname = "nancon"\n'},
        None,
        r"\[site\] is declared beside",
    ),
    "a recipe declaring sites": ({}, _other_recipe_declaring_sites, "is declared in two files"),
    "a column the plan writes for each case": (
        {},
        _write_sites("site,gauge,x_outlet,y_outlet,k,recipe\nnancon,J1,1.0,2.0,1e-5,x\n"),
        r"sites.csv: column recipe is a column the plan writes for each case \(case_id, site, "
        r"recipe, config_hash, config_path\). Rename it.",
    ),
    "a boolean column that is not a boolean": (
        {"sites_extra": 'enabled = "k"\n'},
        None,
        "enabled column: '1e-5' is not a boolean",
    ),
    "an enabled column no table has": (
        {"sites_extra": 'enabled = "go"\n'},
        None,
        "no column 'go' for",
    ),
}


@pytest.mark.parametrize("name", REFUSALS)
def test_a_project_that_cannot_be_planned_is_refused_with_its_sentence(
    tmp_path: Path, name: str
) -> None:
    arguments, change, sentence = REFUSALS[name]
    project = write_sites_project(tmp_path, **arguments)
    if change is not None:
        change(project)

    with pytest.raises(ConfigError, match=sentence):
        expand_plan(project, project / "project.toml")


def _two_columns_one_blank(project: Path) -> None:
    text = (project / "project.toml").read_text(encoding="utf-8")
    text = text.replace("[sites.bind]\n", '[sites.bind]\n"site.label" = ["gauge", "k"]\n')
    (project / "project.toml").write_text(text, encoding="utf-8")


def _name_twice(project: Path) -> None:
    (project / "sites.csv").write_text(
        _HEADER + "nancon,J1,1.0,2.0,1e-5\nnancon,J2,3.0,4.0,1e-5\n", encoding="utf-8"
    )


def _bad_site_name(project: Path) -> None:
    (project / "sites.csv").write_text(_HEADER + "bad name,J1,1.0,2.0,1e-5\n", encoding="utf-8")


def _no_site_name(project: Path) -> None:
    (project / "sites.csv").write_text(_HEADER + ",J1,1.0,2.0,1e-5\n", encoding="utf-8")


def _unreadable_override(project: Path) -> None:
    (project / "site_overrides" / "nancon.toml").write_text("[flow\n", encoding="utf-8")


# (project arguments, what to do to the project, the line of the plan that names it)
ISSUES = {
    "a half filled list": (
        {"k_cells": ("1e-5", "2e-5")},
        _two_columns_one_blank,
        "sites.csv:3 column gauge -> site.label: column(s) gauge empty; fill every cell or none",
    ),
    "a site declared twice": ({}, _name_twice, "site 'nancon' is declared twice (rows 1 and 2)"),
    "a wrong site name": ({}, _bad_site_name, "String should match pattern"),
    "a row with no site": ({}, _no_site_name, "the row names no site"),
    "an override that does not read": ({}, _unreadable_override, "site_overrides/nancon.toml:"),
}


@pytest.mark.parametrize("name", ISSUES)
def test_a_fault_of_one_row_is_an_issue_of_the_plan_with_its_cell(
    tmp_path: Path, name: str
) -> None:
    arguments, change, sentence = ISSUES[name]
    project = write_sites_project(tmp_path, **arguments)
    change(project)

    draft = expand_plan(project, project / "project.toml")

    assert not draft.ok
    assert any(sentence in line for line in group_issues(draft.errors)), group_issues(draft.errors)


@pytest.mark.allow_subprocess
def test_plan_case_replays_from_another_cwd(tmp_path: Path) -> None:
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig

    project = write_sites_project(tmp_path)
    draft = expand_plan(project, project / "project.toml")
    plan_dir = write_plan_draft(project, draft)
    copy = tmp_path / "elsewhere" / "campaign_copy"
    shutil.copytree(project, copy)
    case_toml = copy / "plan" / plan_dir.name / "nancon-k2e_5.toml"
    assert case_toml.is_file()

    # Loaded alone, the case reads its relative paths from the project root of
    # the copy, two folders up, not from the plan folder and not from the source.
    cfg = HydroModPyConfig.from_toml(case_toml)
    assert Path(cfg.workspace.data_dir) == copy / "data"
    assert Path(cfg.workspace.project_root) == copy
    assert cfg.simulation.name == "nancon-k2e_5"
    assert cfg.site is not None and cfg.site.name == "nancon"
    assert cfg.flow.param["K"].field.value == pytest.approx(2e-5)

    env = {**os.environ, "HMP_WORKSPACE": str(copy)}
    for argv in (["run", str(case_toml), "--dry-run"], ["check", str(case_toml)]):
        result = subprocess.run(
            [sys.executable, "-m", "hydromodpy", *argv],
            cwd="/",
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stderr


def test_the_precedence_of_a_case_is_written_in_full(tmp_path: Path) -> None:
    project = write_sites_project(tmp_path, k_cells=("1e-5", "1e-5"))
    (project / "site_overrides" / "couesnon.toml").write_text(
        "[flow.param.K.field]\nvalue = 3e-5\n", encoding="utf-8"
    )
    (project / "kfile.toml").write_text(
        'base_config = "project.toml"\n[flow.param.K.field]\nvalue = 7e-5\n', encoding="utf-8"
    )
    (project / "project.toml").write_text(
        (project / "project.toml")
        .read_text(encoding="utf-8")
        .replace("[sites.recipes]\n", '[sites.recipes]\nkfile = "kfile.toml"\n'),
        encoding="utf-8",
    )

    draft = expand_plan(project, project / "project.toml")
    assert not draft.errors, group_issues(draft.errors)

    # defaults < project.toml (5e-5) < bind (1e-5) < site override (3e-5)
    assert _k(_case(draft, "nancon-base")) == pytest.approx(1e-5)
    assert _k(_case(draft, "couesnon-base")) == pytest.approx(3e-5)
    # < the recipe's own keys: an inline set and a file both beat the override
    assert _k(_case(draft, "couesnon-k2e_5")) == pytest.approx(2e-5)
    assert _k(_case(draft, "couesnon-kfile")) == pytest.approx(7e-5)
    # < --set, on top of everything
    forced = expand_plan(
        project,
        project / "project.toml",
        set_overrides={"flow": {"param": {"K": {"field": {"value": 4e-5}}}}},
    )
    assert [_k(case) for case in forced.cases] == pytest.approx([4e-5] * len(forced.cases))


def test_a_literal_site_scoped_key_is_refused_with_the_list(tmp_path: Path) -> None:
    project = write_sites_project(
        tmp_path, extra='[display.overrides.cross_section]\norientation = "sn"\n'
    )

    draft = expand_plan(project, project / "project.toml")

    lines = group_issues(draft.errors)
    assert len(lines) == 1
    assert lines[0].startswith("4 cases: site scoped key(s) hold a literal value")
    assert "display.overrides.cross_section" in lines[0]
    assert draft.cases == ()

    # Written per site, the same key is accepted.
    project_toml = project / "project.toml"
    project_toml.write_text(
        project_toml.read_text(encoding="utf-8").replace(
            '[display.overrides.cross_section]\norientation = "sn"\n', ""
        ),
        encoding="utf-8",
    )
    (project / "site_overrides" / "nancon.toml").write_text(
        '[display.overrides.cross_section]\norientation = "sn"\n', encoding="utf-8"
    )
    accepted = expand_plan(project, project_toml)
    assert not accepted.errors, group_issues(accepted.errors)
    assert lookup(_case(accepted, "nancon-base").document, "display.overrides.cross_section") == {
        "orientation": "sn"
    }


def test_an_outlet_written_in_the_base_is_a_literal_site_scoped_key(tmp_path: Path) -> None:
    project = write_sites_project(tmp_path)
    project_toml = project / "project.toml"
    # The outlet is written in the base and its bind is removed: it stays literal.
    project_toml.write_text(
        project_toml.read_text(encoding="utf-8")
        .replace('snap_dist = "150 m"\n', 'snap_dist = "150 m"\nx_outlet = 1.0\ny_outlet = 2.0\n')
        .replace('"geographic.catchment.x_outlet" = "x_outlet"\n', "")
        .replace('"geographic.catchment.y_outlet" = "y_outlet"\n', ""),
        encoding="utf-8",
    )

    draft = expand_plan(project, project_toml)

    [line] = group_issues(draft.errors)
    assert "geographic.catchment.x_outlet, geographic.catchment.y_outlet" in line


def test_a_recipes_table_adds_recipes_bound_by_column(tmp_path: Path) -> None:
    project = write_sites_project(
        tmp_path,
        k_column=False,
        sites_extra='recipes_table = "recipes.csv"\n',
        bind_extra=f'"{_K_PATH}" = "k"\n',
    )
    (project / "recipes.csv").write_text("recipe,k\nlow,1e-6\nhigh,1e-4\n", encoding="utf-8")

    draft = expand_plan(project, project / "project.toml")

    assert not draft.errors, group_issues(draft.errors)
    assert [recipe.name for recipe in draft.recipes] == ["base", "k2e_5", "low", "high"]
    assert _k(_case(draft, "nancon-low")) == pytest.approx(1e-6)
    assert _k(_case(draft, "couesnon-high")) == pytest.approx(1e-4)
    assert _k(_case(draft, "nancon-base")) == pytest.approx(5e-5)


def test_env_overrides_are_rendered_by_the_plan_and_refused_by_a_worker(tmp_path: Path) -> None:
    project = write_sites_project(tmp_path)
    env = {"HMP_SET_geographic__catchment__snap_dist": '"300 m"'}

    draft = expand_plan(project, project / "project.toml", env=env)

    assert not draft.errors, group_issues(draft.errors)
    assert {lookup(case.document, "geographic.catchment.snap_dist") for case in draft.cases} == {
        "300 m"
    }
    plan_dir = write_plan_draft(project, draft)
    case_toml = plan_dir / "nancon-base.toml"
    assert is_plan_case(case_toml)
    assert not is_plan_case(project / "project.toml")
    with pytest.raises(ConfigError, match="HMP_SET_geographic__catchment__snap_dist set while"):
        refuse_env_overrides(env, case_toml)
    refuse_env_overrides(env, project / "project.toml")
    refuse_env_overrides({}, case_toml)


def test_simulation_name_is_refused_in_a_sites_project(tmp_path: Path) -> None:
    project = write_sites_project(tmp_path, extra='[simulation]\nname = "nancon_monthly"\n')

    draft = expand_plan(project, project / "project.toml")

    [line] = group_issues(draft.errors)
    assert line.startswith("4 cases: project.toml -> simulation.name: [simulation] name is refused")


def test_deliver_to_is_refused_in_a_sites_project(tmp_path: Path) -> None:
    """Every case would send its files to the same destination, one over the other."""
    project = write_sites_project(tmp_path)
    (project / "project.toml").write_text(
        (project / "project.toml").read_text(encoding="utf-8") + '\n[[export]]\nvariables = "all"\n'
        'deliver_to = "ftp://example.org/incoming/"\n',
        encoding="utf-8",
    )

    draft = expand_plan(project, project / "project.toml")

    [line] = group_issues(draft.errors)
    assert line.startswith(
        "4 cases: project.toml -> export.deliver_to: deliver_to is refused in a [sites] project"
    )
    assert draft.cases == ()


def test_an_export_block_without_deliver_to_is_planned(tmp_path: Path) -> None:
    project = write_sites_project(tmp_path)
    (project / "project.toml").write_text(
        (project / "project.toml").read_text(encoding="utf-8")
        + '\n[[export]]\nvariables = "all"\n',
        encoding="utf-8",
    )

    draft = expand_plan(project, project / "project.toml")

    assert not draft.errors, group_issues(draft.errors)
    assert {case.case_id for case in draft.cases} == {
        "nancon-base",
        "nancon-k2e_5",
        "couesnon-base",
        "couesnon-k2e_5",
    }


def test_a_recipe_adds_its_own_bind_lines(tmp_path: Path) -> None:
    project = write_sites_project(tmp_path, k_column=False)
    (project / "sites.csv").write_text(
        "site,gauge,x_outlet,y_outlet,snap\nnancon,J0014010,389285.910,6816518.749,300 m\n"
        "couesnon,,377120.0,6831410.0,\n",
        encoding="utf-8",
    )
    (project / "snap.toml").write_text(
        'base_config = "project.toml"\n[sites.bind]\n"geographic.catchment.snap_dist" = "snap"\n',
        encoding="utf-8",
    )
    (project / "project.toml").write_text(
        (project / "project.toml")
        .read_text(encoding="utf-8")
        .replace("[sites.recipes]\n", '[sites.recipes]\nsnap = "snap.toml"\n'),
        encoding="utf-8",
    )

    draft = expand_plan(project, project / "project.toml")

    assert not draft.errors, group_issues(draft.errors)
    assert lookup(_case(draft, "nancon-snap").document, "geographic.catchment.snap_dist") == "300 m"
    # An empty cell leaves the key to the base.
    assert (
        lookup(_case(draft, "couesnon-snap").document, "geographic.catchment.snap_dist") == "150 m"
    )
    assert lookup(_case(draft, "nancon-base").document, "geographic.catchment.snap_dist") == "150 m"


def test_the_enabled_column_selects_the_sites(tmp_path: Path) -> None:
    project = write_sites_project(tmp_path, sites_extra='enabled = "on"\n')
    (project / "sites.csv").write_text(
        "site,gauge,x_outlet,y_outlet,k,on\nnancon,J0014010,389285.910,6816518.749,1e-5,true\n"
        "couesnon,,377120.0,6831410.0,,false\n",
        encoding="utf-8",
    )

    draft = expand_plan(project, project / "project.toml")

    assert [site.name for site in draft.sites] == ["nancon"]
    assert sorted(case.case_id for case in draft.cases) == ["nancon-base", "nancon-k2e_5"]


def test_include_and_exclude_select_the_sites(tmp_path: Path) -> None:
    included = write_sites_project(tmp_path / "in", sites_extra='include = ["nancon"]\n')
    excluded = write_sites_project(tmp_path / "out", sites_extra='exclude = ["nancon"]\n')

    kept = expand_plan(included, included / "project.toml")
    left = expand_plan(excluded, excluded / "project.toml")

    assert [site.name for site in kept.sites] == ["nancon"]
    assert sorted(case.case_id for case in kept.cases) == ["nancon-base", "nancon-k2e_5"]
    assert [site.name for site in left.sites] == ["couesnon"]
    assert sorted(case.case_id for case in left.cases) == ["couesnon-base", "couesnon-k2e_5"]
    # A name in both lists is refused by the section itself.
    both = write_sites_project(
        tmp_path / "both", sites_extra='include = ["nancon"]\nexclude = ["nancon"]\n'
    )
    with pytest.raises(SitesProjectError, match="include and exclude both name nancon"):
        expand_plan(both, both / "project.toml")


def test_a_plan_is_written_once_and_current_points_at_it(tmp_path: Path) -> None:
    project = write_sites_project(tmp_path)
    draft = expand_plan(project, project / "project.toml")

    plan_dir = write_plan_draft(project, draft)

    assert current_plan_hash(project) == plan_dir.name
    stored = read_plan(project)
    assert sorted(case.case_id for case in stored.cases) == sorted(c.case_id for c in draft.cases)
    assert stored.plan.n_cases == 4
    assert stored.sites["site"].tolist() == ["nancon", "couesnon"]
    assert stored.sites.loc[0, "gauge"] == "J0014010"
    header = (plan_dir / "cases.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header == "case_id,site,recipe,config_hash,config_path,gauge,x_outlet,y_outlet,k"
    assert sorted(p.name for p in plan_dir.glob("*.toml")) == sorted(
        f"{c.case_id}.toml" for c in draft.cases
    )
    assert not list(plan_dir.glob("*.parquet"))
    assert "project.toml" in stored.plan.fingerprints and "sites.csv" in stored.plan.fingerprints
    assert stored.case_toml("nancon-base") == _case(draft, "nancon-base").toml()
    # The same draft written again is the same plan.
    assert write_plan_draft(project, expand_plan(project, project / "project.toml")) == plan_dir
    assert {p.name for p in (project / "plan").iterdir()} == {"current", plan_dir.name}


def test_the_hash_of_a_plan_starts_from_its_schema(tmp_path: Path) -> None:
    project = write_sites_project(tmp_path)
    draft = expand_plan(project, project / "project.toml")
    inputs = {"project.toml": "ab" * 32}
    lines = sorted(
        f"{c.case_id}\t{c.config_hash}\t{sha256(c.toml().encode()).hexdigest()}"
        for c in draft.cases
    )
    lines.append(f"project.toml\t{'ab' * 32}")
    body = "\n".join(lines)

    assert (
        plan_hash(draft.cases, inputs) == sha256(f"{PLAN_SCHEMA}\n{body}".encode()).hexdigest()[:16]
    )
    assert plan_hash(draft.cases, inputs) != sha256(body.encode()).hexdigest()[:16]


def test_a_running_case_refuses_a_new_plan_without_force(tmp_path: Path) -> None:
    from hydromodpy.results.outcome import Outcome, write_outcome

    project = write_sites_project(tmp_path)
    draft = expand_plan(project, project / "project.toml")
    run_dir = project / "runs" / "nancon-base"
    run_dir.mkdir(parents=True)
    write_outcome(
        run_dir,
        Outcome(
            case_id="nancon-base",
            attempt=1,
            attempt_id="a1",
            status="running",
            written_by="worker",
            started_at=datetime.now(UTC),
            host="here",
            pid=os.getpid(),
        ),
    )

    with pytest.raises(RunningCaseError, match="nancon-base"):
        write_plan_draft(project, draft)
    assert write_plan_draft(project, draft, force=True).is_dir()


def _session(project: Path, case_id: str, status: str, *, host: str, pid: int) -> Path:
    """Write a calibration session of *case_id* with a running outcome."""
    from hydromodpy.results.outcome import Outcome, write_outcome
    from hydromodpy.results.session.descriptor import write_session
    from tests._helpers.session_documents import session_descriptor

    session_dir = project / "sessions" / case_id
    session_dir.mkdir(parents=True)
    now = datetime.now(UTC)
    write_session(
        session_dir,
        session_descriptor(
            case_id,
            session_id="s1",
            config_hash="h1",
            status=status,
            started_at=now,
            ended_at=None if status == "running" else now,
        ),
    )
    write_outcome(
        session_dir,
        Outcome(
            case_id=case_id,
            attempt=1,
            attempt_id="a1",
            status="running",
            written_by="worker",
            started_at=now,
            host=host,
            pid=pid,
        ),
    )
    return session_dir


def test_a_running_calibration_session_refuses_a_new_plan_without_force(tmp_path: Path) -> None:
    from hydromodpy.project.launch.plan import running_cases

    project = write_sites_project(tmp_path)
    draft = expand_plan(project, project / "project.toml")
    first = write_plan_draft(project, draft)
    session = _session(project, "nancon-base", "running", host="here", pid=os.getpid())
    assert running_cases(project, ["nancon-base"]) == ["sessions/nancon-base"]

    project_toml = project / "project.toml"
    project_toml.write_text(
        project_toml.read_text(encoding="utf-8").replace("2000-03-31", "2000-04-30"),
        encoding="utf-8",
    )
    changed = expand_plan(project, project_toml)
    with pytest.raises(RunningCaseError, match="sessions/nancon-base"):
        write_plan_draft(project, changed)
    assert current_plan_hash(project) == first.name

    # A session closed, or whose worker is dead, holds nothing.
    shutil.rmtree(session)
    _session(project, "nancon-base", "failed", host="here", pid=os.getpid())
    assert running_cases(project, ["nancon-base"]) == []
    shutil.rmtree(project / "sessions" / "nancon-base")
    _session(project, "nancon-base", "running", host=socket.gethostname(), pid=2**22 + 7)
    assert running_cases(project, ["nancon-base"]) == []
    assert write_plan_draft(project, changed).name != first.name


def test_the_plan_counts_a_calibration_at_its_widest_phase(tmp_path: Path) -> None:
    project = write_sites_project(tmp_path)
    _add_recipe(
        project,
        "calib",
        "calib.toml",
        "[calibration]\nparallel = 2\n\n[calibration.parameters.K]\nbounds = [1e-6, 1e-4]\n\n"
        '[[calibration.phases]]\nname = "narrow"\nparameters = ["K"]\n'
        'variable = "discharge"\nobjective = "nse"\n\n'
        '[[calibration.phases]]\nname = "wide"\nparameters = ["K"]\nparallel = 6\n'
        'variable = "discharge"\nobjective = "nse"\n',
    )
    draft = expand_plan(project, project / "project.toml")
    assert not draft.errors, group_issues(draft.errors)

    assert _case(draft, "nancon-calib").solves == 6


def test_a_calibration_that_keeps_no_best_run_still_counts_one_kept_solve(tmp_path: Path) -> None:
    project = write_sites_project(tmp_path)
    _add_recipe(
        project,
        "calib",
        "calib.toml",
        "[calibration]\nsave_best_n = 0\n\n[calibration.parameters.K]\nbounds = [1e-6, 1e-4]\n\n"
        '[[calibration.phases]]\nname = "one"\nparameters = ["K"]\n'
        'variable = "discharge"\nobjective = "nse"\n',
    )
    draft = expand_plan(project, project / "project.toml")
    assert not draft.errors, group_issues(draft.errors)

    case = _case(draft, "nancon-calib")
    assert (case.solves >= 1, case.kept_solves) == (True, 1)


def test_dry_run_counts_cases_solves_and_scratch(tmp_path: Path) -> None:
    project = write_sites_project(tmp_path, sites_extra="[sites.run]\nparallel = 3\n")
    draft = expand_plan(project, project / "project.toml")

    budget = plan_budget(draft, cores=8)
    lines = dry_run_lines(draft, budget)

    assert (budget.n_cases, budget.n_sites, budget.n_recipes) == (4, 2, 2)
    assert (budget.parallel, budget.peak_solves, budget.kept_solves) == (3, 3, 4)
    assert budget.scratch_gib == pytest.approx((4 * 0.6, 4 * 4.8))
    assert lines[1].endswith("4 cases (2 sites x 2 recipes), 0 already sealed, 4 to run")
    assert any("nancon-k2e_5: simulation, 1 solve(s)" in line for line in lines)
    assert not (project / "plan").exists()


def test_two_outlets_closer_than_near_site_m_are_reported(tmp_path: Path) -> None:
    project = write_sites_project(tmp_path)
    (project / "sites.csv").write_text(
        "site,gauge,x_outlet,y_outlet,k\nnancon,J0014010,389285.910,6816518.749,\n"
        "nancon_bis,,389300.0,6816520.0,\n",
        encoding="utf-8",
    )

    draft = expand_plan(project, project / "project.toml", near_site_m=500.0)

    assert not draft.errors
    [line] = group_issues(draft.warnings)
    assert line.startswith("sites nancon and nancon_bis have outlets 14 m apart")


def _add_recipe(project: Path, name: str, file: str, body: str) -> None:
    """Write a recipe file inheriting project.toml and list it under [sites.recipes]."""
    (project / file).write_text(f'base_config = "project.toml"\n{body}', encoding="utf-8")
    project_toml = project / "project.toml"
    project_toml.write_text(
        project_toml.read_text(encoding="utf-8").replace(
            "[sites.recipes]\n", f'[sites.recipes]\n{name} = "{file}"\n'
        ),
        encoding="utf-8",
    )


def _seal(project: Path, dirname: str, config_hash: str) -> None:
    """Write the manifest of a sealed run, with the identity the plan reads."""
    run_dir = project / "runs" / dirname
    run_dir.mkdir(parents=True)
    (run_dir / RUN_MANIFEST_FILENAME).write_text(
        json.dumps(manifest_document(name=dirname, config_hash=config_hash)), encoding="utf-8"
    )


def test_a_case_sealed_after_the_plan_leaves_the_plan_unchanged(tmp_path: Path) -> None:
    project = write_sites_project(tmp_path)
    draft = expand_plan(project, project / "project.toml")
    plan_dir = write_plan_draft(project, draft)
    _seal(project, "nancon-base", _case(draft, "nancon-base").config_hash)

    again = expand_plan(project, project / "project.toml")

    assert _case(again, "nancon-base").done and not _case(again, "couesnon-base").done
    # The sealed case is a fact of the disk, counted at --dry-run, not a fact of the plan.
    assert write_plan_draft(project, again) == plan_dir
    assert plan_budget(again, cores=8).n_done == 1
    assert "done" not in read_plan(project).plan.budget
    assert {p.name for p in (project / "plan").iterdir()} == {"current", plan_dir.name}


def test_the_config_hash_of_a_case_is_the_solution_key_of_the_worker(tmp_path: Path) -> None:
    """The case file read back gives the key the plan holds: a plan and a run compare one key."""
    from hydromodpy.config.loading import load
    from hydromodpy.workflow.solution_key import planned_solution_key

    project = write_sites_project(tmp_path)
    draft = expand_plan(project, project / "project.toml")
    plan_dir = write_plan_draft(project, draft)

    for case in draft.cases:
        cfg = load(plan_dir / f"{case.case_id}.toml")
        key = planned_solution_key(cfg, search=case.kind == "calibration")
        assert key is not None, case.case_id
        assert key == case.config_hash, case.case_id


@pytest.mark.parametrize(
    ("site", "recipe", "case_id"),
    [
        ("nancon", "base", "nancon-base"),
        ("Nancon", "Base", "nancon-base"),
        ("J0014010", "calage", "j0014010-calage"),
        ("a_site", "b_recipe", "a_site-b_recipe"),
    ],
    ids=["already a name", "capitals folded", "a gauge code folded", "underscores kept"],
)
def test_the_case_id_is_the_folded_name_of_the_site_and_the_recipe(
    site: str, recipe: str, case_id: str
) -> None:
    from hydromodpy.project.launch.plan import _case_id

    taken: dict[str, str] = {}
    errors: list = []

    found = _case_id(
        SimpleNamespace(name=site), SimpleNamespace(name=recipe), taken=taken, errors=errors
    )

    assert (found, errors) == (case_id, [])
    assert taken == {case_id: f"{site}-{recipe}"}


def test_two_cases_that_fold_to_one_name_are_a_refusal_of_the_plan() -> None:
    from hydromodpy.project.launch.plan import _case_id

    taken: dict[str, str] = {}
    errors: list = []
    first = _case_id(
        SimpleNamespace(name="Nancon"), SimpleNamespace(name="base"), taken=taken, errors=errors
    )
    second = _case_id(
        SimpleNamespace(name="nancon"), SimpleNamespace(name="base"), taken=taken, errors=errors
    )

    assert (first, second) == ("nancon-base", None)
    [issue] = errors
    assert "fold to the same run name 'nancon-base'" in issue.message


def test_a_case_id_longer_than_a_run_name_is_a_refusal_of_the_plan() -> None:
    from hydromodpy.project.launch.plan import _case_id

    errors: list = []

    found = _case_id(
        SimpleNamespace(name="s" * 41), SimpleNamespace(name="base"), taken={}, errors=errors
    )

    assert found is None
    [issue] = errors
    assert "has 46 characters" in issue.message and "keeps to 40" in issue.message


def test_a_plan_moves_with_the_code_that_computes_and_with_nothing_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A case is computed again after an edit of a solver, and not after an edit of a figure."""
    from hydromodpy.core import code_fingerprint as fingerprint_module
    from hydromodpy.core.code_fingerprint import RUN_LAYERS, code_fingerprint

    project = write_sites_project(tmp_path)
    table = code_fingerprint(RUN_LAYERS)

    def hashes() -> dict[str, str | None]:
        draft = expand_plan(project, project / "project.toml")
        return {case.case_id: case.config_hash for case in draft.cases}

    base = hashes()
    monkeypatch.setattr(fingerprint_module, "code_fingerprint", lambda _layers: dict(table))
    assert hashes() == base
    monkeypatch.setattr(
        fingerprint_module, "code_fingerprint", lambda _layers: {**table, "solver": "edited"}
    )
    moved = hashes()
    assert set(moved) == set(base) and all(moved[case] != base[case] for case in base)


def test_a_sealed_run_or_a_completed_session_marks_the_case_done(tmp_path: Path) -> None:
    from hydromodpy.results.session.descriptor import write_session
    from tests._helpers.session_documents import session_descriptor

    project = write_sites_project(tmp_path)
    _add_recipe(
        project, "calib", "calib.toml", "[calibration.parameters.K]\nbounds = [1e-6, 1e-4]\n"
    )
    draft = expand_plan(project, project / "project.toml")
    assert not draft.errors, group_issues(draft.errors)
    assert _case(draft, "nancon-calib").kind == "calibration"
    assert not any(case.done for case in draft.cases)
    _seal(project, "nancon-base.v2", "another computation")
    _seal(project, "nancon-base.v3", _case(draft, "nancon-base").config_hash)
    _seal(project, "couesnon-base", "another computation")
    now = datetime.now(UTC)
    for site, status in (("nancon", "completed"), ("couesnon", "partial")):
        case_id = f"{site}-calib"
        session_dir = project / "sessions" / case_id
        session_dir.mkdir(parents=True)
        write_session(
            session_dir,
            session_descriptor(
                case_id,
                session_id=f"s-{site}",
                config_hash=_case(draft, case_id).config_hash,
                method="tpe",
                status=status,
                started_at=now,
                ended_at=now,
            ),
        )

    again = expand_plan(project, project / "project.toml")

    done = sorted(case.case_id for case in again.cases if case.done)
    assert done == ["nancon-base", "nancon-calib"]
    lines = dry_run_lines(again, plan_budget(again, cores=8))
    assert lines[1].endswith("6 cases (2 sites x 3 recipes), 2 already sealed, 4 to run")


def test_a_recipe_writing_site_is_refused(tmp_path: Path) -> None:
    project = write_sites_project(tmp_path)
    _add_recipe(project, "other", "other.toml", '[site]\nname = "other"\n')

    with pytest.raises(SitesProjectError, match=r"other: other.toml writes \[site\]"):
        expand_plan(project, project / "project.toml")

    # An inline set reaching [site] is refused the same way.
    inline = write_sites_project(
        tmp_path / "inline",
        recipes_extra='named = { file = "project.toml", set = { "site.label" = "Other" } }\n',
    )
    with pytest.raises(SitesProjectError, match=r"named: project.toml writes \[site\]"):
        expand_plan(inline, inline / "project.toml")


@pytest.mark.parametrize(
    ("issues", "detail"),
    [
        (
            [PlanIssue("bad", origin="sites.csv:3 column k", target="flow.k", case_id="a")],
            "a: sites.csv:3 column k -> flow.k: bad",
        ),
        (
            [
                PlanIssue("bad", origin="sites.csv:3 column k", target="flow.k", case_id=case)
                for case in ("a", "b", "c")
            ],
            "3 cases: sites.csv:3 column k -> flow.k: bad",
        ),
        ([PlanIssue("the plan is empty")], "the plan is empty"),
    ],
    ids=["one case", "three cases", "the plan"],
)
def test_an_issue_is_a_sites_case_diagnostic_at_its_key(
    issues: list[PlanIssue], detail: str
) -> None:
    [found] = group_diagnostics(issues, "warning")

    assert found == Diagnostic(
        path=issues[0].target or "", code="sites_case", severity="warning", detail=detail
    )


def test_the_same_issue_on_many_cases_is_one_diagnostic_and_one_line() -> None:
    issues = [
        PlanIssue("bad", origin="sites.csv:3 column k", target="flow.k", case_id="a-low"),
        PlanIssue("bad", origin="sites.csv:3 column k", target="flow.k", case_id="a-high"),
        PlanIssue("other", case_id="b-low"),
    ]

    found = group_diagnostics(issues)

    assert [item.detail for item in found] == [
        "2 cases: sites.csv:3 column k -> flow.k: bad",
        "b-low: other",
    ]
    assert group_issues(issues) == [item.detail for item in found]
    assert {item.severity for item in found} == {"error"}


def test_a_recipe_that_cannot_be_read_is_a_finding_named_after_it(tmp_path: Path) -> None:
    from hydromodpy.project.api import check

    project = write_sites_project(tmp_path)
    _add_recipe(project, "bad", "bad.toml", "[flow\n")

    [error] = check(project / "project.toml")

    assert error.severity == "error" and error.code == "sites_case"
    assert error.detail.startswith("[sites.recipes] bad: ") and "invalid TOML" in error.detail

    (project / "bad.toml").write_text('base_config = "missing.toml"\n', encoding="utf-8")
    [error] = check(project / "project.toml")
    assert error.detail.startswith("[sites.recipes] bad: ") and "missing.toml" in error.detail


def test_an_error_no_check_expected_is_a_finding(tmp_path: Path, monkeypatch) -> None:
    import hydromodpy.project.api as api

    def fail(target: Path, **_: object) -> None:
        raise RuntimeError("the disk went away")

    monkeypatch.setattr(api, "check_file", fail)

    [error] = api.check(tmp_path / "run.toml")

    assert error.severity == "error"
    assert error.detail == "Config check failed: the disk went away"


def test_a_recipes_table_names_the_file_of_a_recipe(tmp_path: Path) -> None:
    project = write_sites_project(
        tmp_path,
        k_column=False,
        sites_extra='recipes_table = "recipes.csv"\n',
        bind_extra=f'"{_K_PATH}" = "k"\n',
    )
    (project / "daily.toml").write_text(
        'base_config = "project.toml"\n[simulation.time]\nstep_value = "1 day"\n', encoding="utf-8"
    )
    (project / "recipes.csv").write_text(
        "recipe,file,k\nlow,,1e-6\ndaily_low,daily.toml,1e-6\n", encoding="utf-8"
    )

    draft = expand_plan(project, project / "project.toml")

    assert not draft.errors, group_issues(draft.errors)
    by_name = {recipe.name: recipe for recipe in draft.recipes}
    assert by_name["low"].file == project / "project.toml"
    assert by_name["daily_low"].file == project / "daily.toml"
    assert (
        lookup(_case(draft, "nancon-daily_low").document, "simulation.time.step_value") == "1 day"
    )
    assert lookup(_case(draft, "nancon-low").document, "simulation.time.step_value") == "1 month"
    assert _k(_case(draft, "couesnon-daily_low")) == pytest.approx(1e-6)
    # Running the file of a table recipe runs the recipes that name it.
    alone = expand_plan(project, project / "daily.toml")
    assert sorted(case.case_id for case in alone.cases) == [
        "couesnon-daily_low",
        "nancon-daily_low",
    ]


def test_one_row_of_the_migration_reaches_every_layer_of_a_case(tmp_path: Path) -> None:
    """A bind line, a recipe, a site file and --set all write a key under its old name.

    ``[modflow6]`` moved to ``[solver.modflow6]`` in 2.0.0, so each layer loads with a
    warning and every case holds the key at its new place.
    """
    complexity = "solver.modflow6.runtime.mf6_ims_complexity"
    project = write_sites_project(
        tmp_path,
        recipes_extra=(
            'small = { file = "project.toml", '
            'set = { "modflow6.runtime.mf6_ims_complexity" = "SIMPLE" } }\n'
        ),
        bind_extra='"modflow6.runtime.mf6_inner_dvclose" = "k"\n',
    )
    marker = project / "project.toml"
    (project / "site_overrides" / "couesnon.toml").write_text(
        '[modflow6.runtime]\nmf6_ims_complexity = "MODERATE"\n', encoding="utf-8"
    )

    with pytest.warns(ConfigKeyRenamedWarning):
        draft = expand_plan(project, marker)
    with pytest.warns(ConfigKeyRenamedWarning, match="--set"):
        forced = expand_plan(
            project,
            marker,
            set_overrides={"modflow6": {"runtime": {"mf6_ims_complexity": "COMPLEX"}}},
        )

    assert not draft.errors
    nancon = _case(draft, "nancon-base").document
    assert _k(_case(draft, "nancon-base")) == pytest.approx(1e-5)
    assert lookup(nancon, "solver.modflow6.runtime.mf6_inner_dvclose") == pytest.approx(1e-5)
    assert lookup(_case(draft, "nancon-small").document, complexity) == "SIMPLE"
    assert lookup(_case(draft, "couesnon-base").document, complexity) == "MODERATE"
    assert all(lookup(case.document, complexity) == "COMPLEX" for case in forced.cases)
    assert all("modflow6" not in case.document for case in [*draft.cases, *forced.cases])


# -- tables: CSV, Parquet and GeoPackage, each cell keeps its origin ----------


def test_the_catalog_columns_reach_the_case_without_bind(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    (workspace / "data").mkdir(parents=True)
    write_catalog(
        workspace,
        [
            SiteRow(
                site="nancon",
                label="Le Nancon",
                gauge="J0014010",
                x_outlet=389285.91,
                y_outlet=6816518.749,
                crs="EPSG:2154",
            ),
            SiteRow(site="couesnon", x_outlet=377120.0, y_outlet=6831410.0),
        ],
    )
    project = write_sites_project(tmp_path, k_column=False)
    project_toml = project / "project.toml"
    text = project_toml.read_text(encoding="utf-8")
    text = text.replace('data_dir = "data"', f'root = "{workspace.as_posix()}"')
    text = text.replace('table = "sites.csv"\n', "")
    for line in (
        '"site.name" = "site"\n',
        '"site.gauge" = "gauge"\n',
        '"geographic.catchment.x_outlet" = "x_outlet"\n',
        '"geographic.catchment.y_outlet" = "y_outlet"\n',
    ):
        text = text.replace(line, "")
    project_toml.write_text(text, encoding="utf-8")

    draft = expand_plan(project, project_toml)

    assert not draft.errors, group_issues(draft.errors)
    assert [site.name for site in draft.sites] == ["nancon", "couesnon"]
    nancon = next(case for case in draft.cases if case.case_id == "nancon-base")
    assert lookup(nancon.document, "site.label") == "Le Nancon"
    assert lookup(nancon.document, "site.gauge") == "J0014010"
    assert lookup(nancon.document, "geographic.catchment.x_outlet") == 389285.91
    couesnon = next(case for case in draft.cases if case.case_id == "couesnon-k2e_5")
    assert "gauge" not in couesnon.document["site"]


# Site and recipe tables are read as rows, each cell keeping its origin.


def _write_points(path: Path) -> None:
    frame = gpd.GeoDataFrame(
        {"site": ["nancon", "couesnon"], "gauge": ["J0014010", None]},
        geometry=gpd.points_from_xy([389285.91, 377120.0], [6816518.749, 6831410.0]),
        crs="EPSG:2154",
    )
    frame.to_file(path, driver="GPKG")


def test_a_parquet_table_keeps_its_types_and_names_its_rows(tmp_path: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    path = tmp_path / "sites.parquet"
    pq.write_table(pa.table({"site": ["nancon", "couesnon"], "area_km2": [4.5, None]}), path)

    table = read_table(path, label="sites.parquet")

    assert table.columns == ("site", "area_km2")
    assert table.rows[0].cells == {"site": "nancon", "area_km2": 4.5}
    assert is_empty_cell(table.rows[1].cells["area_km2"])
    assert str(table.rows[1].origin(table, "site")) == "sites.parquet row 2 column site"


@pytest.mark.parametrize(
    ("name", "text", "message"),
    [
        ("sites.csv", "", "the file is empty"),
        ("sites.csv", "site,site\na,b\n", "column(s) named twice: site"),
        ("sites.csv", "site,\na,b\n", "a column has no name"),
        ("sites.csv", "site,gauge\na\n", "sites.csv:2: 1 cells for 2 columns"),
        ("sites.json", "{}", "a table is one of"),
    ],
)
def test_a_table_that_cannot_be_read_names_its_file(
    tmp_path: Path, name: str, text: str, message: str
) -> None:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ConfigError) as info:
        read_table(path, label=name)

    assert message in str(info.value)
    assert str(info.value).startswith(name)


def test_a_missing_table_is_refused_by_name(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"^sites\.csv: no such file"):
        read_table(tmp_path / "sites.csv", label="sites.csv")


def test_a_geopackage_of_points_gains_the_geometry_columns(tmp_path: Path) -> None:
    path = tmp_path / "sites.gpkg"
    _write_points(path)

    table = read_table(path, label="sites.gpkg")

    assert table.columns == ("site", "gauge", "geometry_x", "geometry_y")
    assert [row.cells["site"] for row in table.rows] == ["nancon", "couesnon"]
    assert table.rows[0].cells["geometry_x"] == pytest.approx(389285.91)
    assert table.rows[1].cells["geometry_y"] == pytest.approx(6831410.0)
    assert is_empty_cell(table.rows[1].cells["gauge"])
    # A binary table has no physical line: the origin names the row.
    assert table.rows[1].line is None
    assert str(table.rows[1].origin(table, "gauge")) == "sites.gpkg row 2 column gauge"


@pytest.mark.parametrize("suffix", [".csv", ".parquet", ".gpkg"])
def test_the_three_table_formats_give_the_same_cases(tmp_path: Path, suffix: str) -> None:
    import pandas as pd

    project = write_sites_project(tmp_path, k_column=False)
    rows = pd.DataFrame(
        {"site": ["nancon", "couesnon"], "gauge": ["J0014010", None], "x": [389285.91, 377120.0]}
    ).assign(y=[6816518.749, 6831410.0])
    table = project / f"sites{suffix}"
    if suffix == ".csv":
        rows.to_csv(table, index=False)
    elif suffix == ".parquet":
        rows.to_parquet(table)
    else:
        points = gpd.points_from_xy(rows["x"], rows["y"])
        gpd.GeoDataFrame(rows[["site", "gauge"]], geometry=points, crs="EPSG:2154").to_file(table)
    text = (project / "project.toml").read_text(encoding="utf-8").replace("sites.csv", table.name)
    x, y = ("geometry_x", "geometry_y") if suffix == ".gpkg" else ("x", "y")
    text = text.replace('"x_outlet"', f'"{x}"').replace('"y_outlet"', f'"{y}"')
    (project / "project.toml").write_text(text, encoding="utf-8")

    draft = expand_plan(project, project / "project.toml")

    assert not draft.errors, group_issues(draft.errors)
    nancon = _case(draft, "nancon-base")
    assert lookup(nancon.document, "geographic.catchment.x_outlet") == pytest.approx(389285.91)
    assert lookup(nancon.document, "site.gauge") == "J0014010"
    assert "gauge" not in _case(draft, "couesnon-base").document["site"]
    assert table.name in {p.name for p in draft.inputs}


def test_a_geopackage_site_table_binds_the_outlet_to_the_geometry(tmp_path: Path) -> None:
    project = write_sites_project(tmp_path, k_column=False)
    _write_points(project / "sites.gpkg")
    project_toml = project / "project.toml"
    project_toml.write_text(
        project_toml.read_text(encoding="utf-8")
        .replace('table = "sites.csv"', 'table = "sites.gpkg"')
        .replace(
            '"geographic.catchment.x_outlet" = "x_outlet"',
            '"geographic.catchment.x_outlet" = "geometry_x"',
        )
        .replace(
            '"geographic.catchment.y_outlet" = "y_outlet"',
            '"geographic.catchment.y_outlet" = "geometry_y"',
        ),
        encoding="utf-8",
    )

    draft = expand_plan(project, project_toml)

    assert not draft.errors, group_issues(draft.errors)
    nancon = next(case for case in draft.cases if case.case_id == "nancon-base")
    assert lookup(nancon.document, "geographic.catchment.x_outlet") == pytest.approx(389285.91)
    assert lookup(nancon.document, "site.gauge") == "J0014010"
    couesnon = next(case for case in draft.cases if case.case_id == "couesnon-base")
    assert "gauge" not in couesnon.document["site"]
    assert "sites.gpkg" in {p.name for p in draft.inputs}


# -- a case is done when a run or a session of its key says so -----------------


KEY = "H" * 64


def _sealed_run(
    root: Path,
    name: str,
    *,
    key: str = KEY,
    kind: str | None = None,
    published: bool = False,
) -> Path:
    """Write a sealed run directory of *name* with the solution key *key*."""
    lineage = {} if kind is None else {"kind": kind, "trial": 1, "session_id": "s" * 32}
    document = manifest_document(name=name, lineage=lineage)
    document["identity"]["solution_key"] = key
    directory = root / "runs" / name
    directory.mkdir(parents=True)
    (directory / RUN_MANIFEST_FILENAME).write_text(json.dumps(document), encoding="utf-8")
    if published:
        (directory / PUBLICATION_FILENAME).write_text("{}", encoding="utf-8")
    return directory


def test_a_research_run_of_the_key_does_not_close_the_case(tmp_path: Path) -> None:
    _sealed_run(tmp_path, "case", kind="trial")

    assert case_is_done(tmp_path, "case", KEY, "simulation") is False


def test_a_result_run_of_the_key_closes_the_case(tmp_path: Path) -> None:
    _sealed_run(tmp_path, "case")

    assert case_is_done(tmp_path, "case", KEY, "simulation") is True


def test_a_published_copy_of_the_key_closes_the_case(tmp_path: Path) -> None:
    _sealed_run(tmp_path, "case", published=True)

    assert case_is_done(tmp_path, "case", KEY, "simulation") is True


def test_a_version_of_the_case_name_is_read_at_its_level(tmp_path: Path) -> None:
    _sealed_run(tmp_path, "case.v2", kind="trial")
    assert case_is_done(tmp_path, "case", KEY, "simulation") is False

    _sealed_run(tmp_path, "case.v3")
    assert case_is_done(tmp_path, "case", KEY, "simulation") is True


@pytest.mark.parametrize(
    ("key", "hash_"),
    [("other", KEY), (KEY, None)],
    ids=["another-key", "no-key"],
)
def test_a_different_key_or_no_key_never_closes_the_case(
    tmp_path: Path, key: str, hash_: str | None
) -> None:
    _sealed_run(tmp_path, "case", key=key)

    assert case_is_done(tmp_path, "case", hash_, "simulation") is False


def test_a_project_without_runs_closes_nothing(tmp_path: Path) -> None:
    assert case_is_done(tmp_path / "absent", "case", KEY, "simulation") is False


def test_an_unreadable_manifest_never_closes_the_case(tmp_path: Path) -> None:
    directory = tmp_path / "runs" / "case"
    directory.mkdir(parents=True)
    (directory / RUN_MANIFEST_FILENAME).write_text("{", encoding="utf-8")

    assert case_is_done(tmp_path, "case", KEY, "simulation") is False


def test_a_completed_session_of_the_hash_closes_the_calibration_case(tmp_path: Path) -> None:
    write_session(
        tmp_path / "sessions" / "case",
        session_descriptor("case", config_hash=KEY, status="completed"),
    )

    assert case_is_done(tmp_path, "case", KEY, "calibration") is True


def test_a_running_session_never_closes_the_calibration_case(tmp_path: Path) -> None:
    write_session(
        tmp_path / "sessions" / "case",
        session_descriptor("case", config_hash=KEY, status="running"),
    )

    assert case_is_done(tmp_path, "case", KEY, "calibration") is False
