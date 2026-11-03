"""The plan of a [sites] project: sites x recipes, precedence, origins, replay."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hydromodpy.config.sites.budget import dry_run_lines, plan_budget
from hydromodpy.config.sites.expansion import SitesProjectError, expand_plan
from hydromodpy.config.sites.issues import PlanError, group_issues
from hydromodpy.config.sites.plan import (
    RunningCaseError,
    is_plan_case,
    refuse_env_overrides,
    write_plan_draft,
)
from hydromodpy.core.config_kit.base import ConfigKeyRenamedWarning, forget_old_forms_told
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.toml_io.paths import lookup
from hydromodpy.results.plan_store import current_plan_hash, read_plan
from hydromodpy.results.storage.contract import RUN_MANIFEST_FILENAME
from tests._helpers.sealed_runs import manifest_document

_PROJECT = """\
[workspace]
data_dir = "data"

[workflow]
mode = "simulation"

[geographic]
crs_project = "EPSG:2154"

[geographic.catchment]
catch_def = "from_outlet_coord"
dem_init_path = "dem.tif"
snap_dist = "150 m"
buff_area = "10%"

[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2000-03-31"
step_value = "1 month"

[[simulation.process]]
id = "flow_main"
type = "flow"
solvers = ["modflow6"]

[flow]
flow_regime = "steady"
param_list = ["K"]
active_bc = ["drainage"]

[flow.param.K.field]
kind = "homogeneous"
unit = "m/s"
value = 5e-5
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


@pytest.mark.allow_subprocess
def test_plan_case_replays_from_another_cwd(tmp_path: Path) -> None:
    from hydromodpy.config import HydroModPyConfig

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
    for argv in (["run", str(case_toml), "--dry-run"], ["config", "check", str(case_toml)]):
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


def test_a_column_present_in_both_tables_is_refused(tmp_path: Path) -> None:
    project = write_sites_project(tmp_path, sites_extra='recipes_table = "recipes.csv"\n')
    (project / "recipes.csv").write_text("recipe,k\nlow,1e-6\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="column\\(s\\) k present in both"):
        expand_plan(project, project / "project.toml")


def test_a_recipe_table_without_the_recipe_column_is_refused(tmp_path: Path) -> None:
    project = write_sites_project(tmp_path, sites_extra='recipes_table = "recipes.csv"\n')
    (project / "recipes.csv").write_text("name,kk\nlow,1e-6\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="'recipe' column"):
        expand_plan(project, project / "project.toml")


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


def test_an_unknown_bind_key_is_refused_with_its_neighbours(tmp_path: Path) -> None:
    project = write_sites_project(
        tmp_path, bind_extra='"geographic.catchment.x_outlt" = "x_outlet"\n'
    )

    with pytest.raises(ConfigError, match="x_outlt.*nearest.*x_outlet"):
        expand_plan(project, project / "project.toml")


def test_a_bind_column_no_table_has_is_refused(tmp_path: Path) -> None:
    project = write_sites_project(
        tmp_path, bind_extra='"geographic.catchment.snap_dist" = "snap"\n'
    )

    with pytest.raises(ConfigError, match="names column\\(s\\) snap, found in sites.csv"):
        expand_plan(project, project / "project.toml")


def test_simulation_name_is_refused_in_a_sites_project(tmp_path: Path) -> None:
    project = write_sites_project(tmp_path, extra='[simulation]\nname = "nancon_monthly"\n')

    draft = expand_plan(project, project / "project.toml")

    [line] = group_issues(draft.errors)
    assert line.startswith("4 cases: project.toml -> simulation.name: [simulation] name is refused")


def test_a_site_declared_beside_sites_is_refused(tmp_path: Path) -> None:
    project = write_sites_project(tmp_path, extra='[site]\nname = "nancon"\n')

    with pytest.raises(SitesProjectError, match=r"\[site\] is declared beside \[sites\]"):
        expand_plan(project, project / "project.toml")


def test_a_recipe_declaring_sites_is_refused(tmp_path: Path) -> None:
    project = write_sites_project(tmp_path)
    (project / "other.toml").write_text(
        'base_config = "project.toml"\n[sites]\ninclude = ["nancon"]\n', encoding="utf-8"
    )
    (project / "project.toml").write_text(
        (project / "project.toml")
        .read_text(encoding="utf-8")
        .replace("[sites.recipes]\n", '[sites.recipes]\nother = "other.toml"\n'),
        encoding="utf-8",
    )

    with pytest.raises(SitesProjectError, match="is declared in two files"):
        expand_plan(project, project / "project.toml")


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
    assert stored.sites.column("site").to_pylist() == ["nancon", "couesnon"]
    assert "project.toml" in stored.plan.fingerprints and "sites.csv" in stored.plan.fingerprints
    assert stored.case_toml("nancon-base") == _case(draft, "nancon-base").toml()
    # The same draft written again is the same plan.
    assert write_plan_draft(project, expand_plan(project, project / "project.toml")) == plan_dir
    assert {p.name for p in (project / "plan").iterdir()} == {"current", plan_dir.name}


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
    from hydromodpy.results.session.descriptor import SessionDescriptor, write_session

    session_dir = project / "sessions" / case_id
    session_dir.mkdir(parents=True)
    now = datetime.now(UTC)
    write_session(
        session_dir,
        SessionDescriptor(
            session_id="s1",
            case_id=case_id,
            config_hash="h1",
            hydromodpy_version="0",
            method="grid",
            objective_name="nse",
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
    from hydromodpy.config.sites.plan import running_cases

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


def test_the_config_hash_of_a_case_is_the_hash_of_the_worker(tmp_path: Path) -> None:
    from hydromodpy.config import HydroModPyConfig
    from hydromodpy.results.catalog.registration import config_identity_hash

    project = write_sites_project(tmp_path)
    draft = expand_plan(project, project / "project.toml")
    plan_dir = write_plan_draft(project, draft)

    for case in draft.cases:
        cfg = HydroModPyConfig.from_toml(plan_dir / f"{case.case_id}.toml")
        assert config_identity_hash(cfg) == case.config_hash, case.case_id


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
    from hydromodpy.results.session.descriptor import SessionDescriptor, write_session

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
            SessionDescriptor(
                session_id=f"s-{site}",
                case_id=case_id,
                config_hash=_case(draft, case_id).config_hash,
                hydromodpy_version="0",
                method="tpe",
                objective_name="nse",
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


def test_a_recipe_that_cannot_be_read_is_a_finding_named_after_it(tmp_path: Path) -> None:
    from hydromodpy.config.sites.check import check_project

    project = write_sites_project(tmp_path)
    _add_recipe(project, "bad", "bad.toml", "[flow\n")

    report = check_project(project / "project.toml")

    assert not report.ok and report.kind == "sites"
    [error] = report.errors
    assert error.startswith("[sites.recipes] bad: ") and "invalid TOML" in error

    (project / "bad.toml").write_text('base_config = "missing.toml"\n', encoding="utf-8")
    [error] = check_project(project / "project.toml").errors
    assert error.startswith("[sites.recipes] bad: ") and "missing.toml" in error


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


def test_one_row_of_the_migration_reaches_every_layer_of_a_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bind line, a recipe, a site file and --set all write the key under its old name."""
    from hydromodpy.config import config_migration as migration
    from hydromodpy.config.config_migration import KeyRename

    rows = (
        KeyRename("flow.param.{*}.field", "value_before", "value", since="2.3.0"),
        KeyRename("mesh", "size_before", "cell_size", since="2.3.0"),
    )
    monkeypatch.setattr(migration, "RENAMED_KEYS", (*migration.RENAMED_KEYS, *rows))
    project = write_sites_project(
        tmp_path,
        recipes_extra='small = { file = "project.toml", set = { "mesh.size_before" = 50.0 } }\n',
    )
    marker = project / "project.toml"
    marker.write_text(
        marker.read_text(encoding="utf-8").replace(
            f'"{_K_PATH}" = "k"', f'"{_K_PATH}_before" = "k"'
        ),
        encoding="utf-8",
    )
    (project / "site_overrides" / "couesnon.toml").write_text(
        "[mesh]\nsize_before = 60.0\n", encoding="utf-8"
    )

    forget_old_forms_told()
    with pytest.warns(ConfigKeyRenamedWarning):
        draft = expand_plan(project, marker)
    with pytest.warns(ConfigKeyRenamedWarning, match="--set"):
        forced = expand_plan(project, marker, set_overrides={"mesh": {"size_before": 70.0}})

    assert not draft.errors
    assert _k(_case(draft, "nancon-base")) == pytest.approx(1e-5)
    assert lookup(_case(draft, "nancon-small").document, "mesh.cell_size") == 50.0
    assert lookup(_case(draft, "couesnon-base").document, "mesh.cell_size") == 60.0
    assert all(lookup(case.document, "mesh.cell_size") == 70.0 for case in forced.cases)
