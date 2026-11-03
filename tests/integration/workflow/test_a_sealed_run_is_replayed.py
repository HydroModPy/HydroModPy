"""What a sealed run promises: its overrides, its whole configuration, its replay.

A run of the scaffolded demo, solved by MODFLOW-NWT in about a second, is sealed,
replayed and rerun for real. The default that moves is a real Pydantic default of
``[solver]``, changed in the class and put back after the test.
"""

from __future__ import annotations

import json
import shutil
import tomllib
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest
import zarr

import hydromodpy as hmp
from hydromodpy.core.code_fingerprint import RUN_LAYERS
from hydromodpy.core.exceptions import ConfigError, StepError
from hydromodpy.data.workspace.scaffold import scaffold
from hydromodpy.results.storage.contract import RUN_RESOLVED_CONFIG_FILENAME, RUN_SEARCH_TABLE
from hydromodpy.spatial.terrain import registry as terrain_registry
from hydromodpy.workflow.steps.extract import ExtractStep
from tests._helpers.cli_runner import CliRunner
from tests.characterization.comparator import compare_run_dirs

pytestmark = [pytest.mark.integration, pytest.mark.binary, pytest.mark.slow]

K = 3.3e-3
K_PATH = "flow.param.K.field.value"


@pytest.fixture
def demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The scaffolded demo project, with the current directory inside it."""
    project = scaffold(tmp_path / "workspace") / "projects" / "example"
    monkeypatch.chdir(project)
    return project


def _config(run_dir: Path) -> dict:
    return tomllib.loads((run_dir / "config.toml").read_text(encoding="utf-8"))


def _resolved(run_dir: Path) -> dict:
    return tomllib.loads((run_dir / RUN_RESOLVED_CONFIG_FILENAME).read_text(encoding="utf-8"))


def _manifest(run_dir: Path) -> dict:
    return json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))


def _parameter(run_dir: Path, name: str) -> float:
    rows = [row for row in _manifest(run_dir)["parameters"] if row["name"] == name]
    assert len(rows) == 1, rows
    return float(rows[0]["value"])


def _drift(run_a: Path, run_b: Path) -> list[tuple[str, str]]:
    """Return what differs between two runs, beyond the version in their names."""
    return [
        (verdict.target, verdict.detail)
        for verdict in compare_run_dirs(run_a, run_b).drifted
        if not verdict.target.endswith(":version_int")
    ]


def _hmp(project: Path, *args: str):
    return CliRunner().invoke(["run", *args, "-w", str(project), "-q"])


def _simulate(project: Path, **keywords) -> Path:
    with hmp.Project(project / "run_demo.toml", no_display=True) as opened:
        return opened.simulate(**keywords).dir


def test_an_override_is_sealed_and_a_rerun_repeats_it(demo: Path) -> None:
    source = _simulate(demo, name="probe", set={"K": K})

    assert _config(source)["flow"]["param"]["K"]["field"]["value"] == K
    assert _parameter(source, "K") == pytest.approx(K)
    assert _manifest(source)["lineage"]["overrides"] == {K_PATH: K}

    by_project = hmp.Project.rerun(hmp.open(source), name="by_project", no_display=True).dir
    assert _parameter(by_project, "K") == pytest.approx(K)
    lineage = _manifest(by_project)["lineage"]
    assert (lineage["kind"], lineage["overrides"]) == ("rerun", {})

    done = CliRunner().invoke(["catalog", "rerun", "probe", "--name", "by_cli", "-w", str(demo)])
    assert done.exit_code == 0, done.stderr
    assert _parameter(demo / "runs" / "by_cli", "K") == pytest.approx(K)


def test_a_rerun_writes_in_the_project_of_its_source_whatever_the_cwd(
    demo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sealed file holds no ``[workspace]``, so the current directory was the project."""
    source = _simulate(demo, name="probe")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    by_project = hmp.Project.rerun(hmp.open(source), name="by_project", no_display=True).dir
    done = CliRunner().invoke(["catalog", "rerun", "probe", "--name", "by_cli", "-w", str(demo)])

    assert done.exit_code == 0, done.stderr
    assert by_project == demo / "runs" / "by_project"
    assert (demo / "runs" / "by_cli").is_dir()
    assert list(elsewhere.iterdir()) == []


def test_a_rerun_takes_dotted_paths_and_the_lineage_says_them(demo: Path) -> None:
    source = _simulate(demo, name="probe")

    changed = hmp.Project.rerun(
        hmp.open(source), name="changed", no_display=True, set={K_PATH: 2e-4, "Sy": 0.2}
    ).dir

    assert _parameter(changed, "K") == pytest.approx(2e-4)
    assert _parameter(changed, "Sy") == pytest.approx(0.2)
    assert _manifest(changed)["lineage"]["overrides"] == {
        K_PATH: 2e-4,
        "flow.param.Sy.field.value": 0.2,
    }


def test_each_run_of_a_sweep_gets_its_own_flow_and_lineage(demo: Path) -> None:
    with hmp.Project(demo / "run_demo.toml", no_display=True) as opened:
        first = opened.simulate(name="first", set={"K": K}).dir
        second = opened.simulate(name="second", set={"K": 2 * K}).dir
        plain = opened.simulate(name="plain").dir

    assert _parameter(first, "K") == pytest.approx(K)
    assert _parameter(second, "K") == pytest.approx(2 * K)
    assert _manifest(second)["lineage"]["overrides"] == {K_PATH: 2 * K}
    assert _parameter(plain, "K") == pytest.approx(1e-4)
    assert _manifest(plain)["lineage"]["overrides"] == {}


@pytest.mark.parametrize(
    ("keywords", "section", "value"),
    [
        (
            {"set": {"first_clim": "first"}},
            ("flow", "sinks_sources", "recharge", "first_clim"),
            "first",
        ),
        ({"set": {"thickness": 70.0}}, ("domain", "depth_model", "thickness"), 70.0),
    ],
)
def test_a_keyword_lands_at_its_path_in_the_sealed_config(
    demo: Path, keywords: dict, section: tuple[str, ...], value: object
) -> None:
    held: object = _config(_simulate(demo, name="probe", **keywords))
    for key in section:
        held = held[key]
    assert held == value


def test_an_unknown_keyword_is_refused_with_what_this_project_offers(demo: Path) -> None:
    with hmp.Project(demo / "run_demo.toml", no_display=True) as opened:
        with pytest.raises(ConfigError, match=r"Unknown parameter 'porosity'.*K, Sy"):
            opened.simulate(name="probe", set={"porosity": 0.3})


def test_the_properties_keyword_is_gone(demo: Path) -> None:
    with hmp.Project(demo / "run_demo.toml", no_display=True) as opened:
        with pytest.raises(TypeError, match="properties"):
            opened.simulate(name="probe", properties={"K": 1e-5})


def test_the_run_seals_its_whole_configuration_portable(demo: Path) -> None:
    run_dir = _simulate(demo, name="probe")

    written, resolved = _config(run_dir), _resolved(run_dir)
    assert "terrain_engine" not in written["geographic"]
    assert resolved["geographic"]["terrain_engine"] == terrain_registry.DEFAULT_ENGINE_ID
    assert resolved["solver"]["drain_bed_thickness_m"] == pytest.approx(1.0)
    assert "drain_bed_thickness_m" not in written.get("solver", {})
    assert resolved["resolved_at_build"]["mesh"]["pixel"] == pytest.approx(50.0)
    # The machine keys are gone, as from config.toml.
    assert str(demo.parent) not in (run_dir / RUN_RESOLVED_CONFIG_FILENAME).read_text()

    roles = {entry["path"]: entry["role"] for entry in _manifest(run_dir)["artifacts"]}
    assert roles[RUN_RESOLVED_CONFIG_FILENAME] == "config_resolved"
    assert RUN_RESOLVED_CONFIG_FILENAME in _copy_entries(run_dir, demo)


def _copy_entries(run_dir: Path, project: Path) -> set[str]:
    from hydromodpy.results.export.publish import publish

    copy = publish(run_dir, project.parent / "copy", project_root=project)
    return {entry.name for entry in Path(copy).iterdir()}


def test_a_frozen_replay_of_an_unchanged_run_has_nothing_to_do(demo: Path) -> None:
    source = _simulate(demo, name="probe", set={"K": K})

    done = _hmp(demo, str(source / "config.toml"), "--frozen")

    assert done.exit_code == 0, done.stderr
    assert "identical" in done.stderr
    assert not (demo / "runs" / "probe.v2").exists()


def test_a_forced_frozen_replay_gives_the_same_numbers(demo: Path) -> None:
    source = _simulate(demo, name="probe", set={"K": K})

    done = _hmp(demo, str(source / "config.toml"), "--frozen", "--force", "--no-display")

    assert done.exit_code == 0, done.stderr
    replay = demo / "runs" / "probe.v2"
    assert _manifest(replay)["config"]["hash"] == _manifest(source)["config"]["hash"]
    assert _drift(source, replay) == []


@pytest.fixture
def sealed_then_moved(demo: Path) -> Iterator[tuple[Path, Path]]:
    """A run sealed under today's default, then the default moves."""
    from hydromodpy.config import HydroModPyConfig
    from hydromodpy.solver.base.solver_config import SolverConfig

    source = _simulate(demo, name="probe")
    field = SolverConfig.model_fields["drain_bed_thickness_m"]
    declared = field.default

    def rebuild(value: float) -> None:
        field.default = value
        SolverConfig.model_rebuild(force=True)
        HydroModPyConfig.model_rebuild(force=True)

    rebuild(2.0)
    try:
        yield demo, source
    finally:
        rebuild(declared)


def test_a_copied_run_replays_into_a_project_and_never_into_itself(
    demo: Path, tmp_path: Path
) -> None:
    source = _simulate(demo, name="probe", set={"K": K})
    copy = tmp_path / "elsewhere" / "base"
    shutil.copytree(source, copy)
    held = sorted(path.relative_to(copy) for path in copy.rglob("*"))

    refused = CliRunner().invoke(["run", str(copy / "config.toml"), "--frozen", "-q"])

    assert refused.exit_code != 0
    assert "-w <project>" in refused.stderr
    done = _hmp(demo, str(copy / "config.toml"), "--frozen", "--force", "--no-display")
    assert done.exit_code == 0, done.stderr
    assert _drift(source, demo / "runs" / "probe.v2") == []
    assert sorted(path.relative_to(copy) for path in copy.rglob("*")) == held


def test_a_run_promoted_by_a_calibration_replays_as_one_solve(tmp_path: Path) -> None:
    """The file of the run names its solve, and the heads of a replay are those of the trial."""
    example = Path(__file__).parents[3] / "examples" / "projects" / "01_calibration"
    project = tmp_path / "calibration"
    project.mkdir()
    (project / "project.toml").write_text(
        (example / "project.toml")
        .read_text(encoding="utf-8")
        .replace("max_trials = 20", "max_trials = 3"),
        encoding="utf-8",
    )
    searched = _hmp(project, str(project / "project.toml"), "--no-display")
    assert searched.exit_code == 0, searched.stderr
    promoted = project / "runs" / "calibration_dupuit"

    sealed = _config(promoted)
    assert "calibration" not in sealed
    assert sealed["workflow"]["mode"] == "simulation"
    lineage = _manifest(promoted)["lineage"]
    assert (lineage["kind"], lineage["parent_hint"]) == ("promoted", "sessions/calibration_dupuit")
    assert _manifest(promoted)["checks"]["calibrated_by"]["session_id"] == lineage["session_id"]
    assert "K_aquifer" in _resolved(promoted)[RUN_SEARCH_TABLE]["parameters"]

    again = _hmp(project, str(promoted / "config.toml"), "--frozen")
    assert again.exit_code == 0, again.stderr
    assert "identical" in again.stderr
    replayed = _hmp(project, str(promoted / "config.toml"), "--frozen", "--force", "--no-display")
    assert replayed.exit_code == 0, replayed.stderr

    replay = project / "runs" / "calibration_dupuit.v2"
    assert [path.name for path in (project / "sessions").iterdir()] == ["calibration_dupuit"]
    assert _manifest(replay)["lineage"]["session_id"] is None
    assert _parameter(replay, "K") == _parameter(promoted, "K")
    heads = [
        zarr.open_group(path / "fields.zarr", mode="r")["head"][:] for path in (promoted, replay)
    ]
    assert np.array_equal(*heads, equal_nan=True)


def test_a_default_that_moved_refuses_the_replay_naming_the_key(
    sealed_then_moved: tuple[Path, Path],
) -> None:
    demo, source = sealed_then_moved

    done = _hmp(demo, str(source / "config.toml"), "--frozen")

    assert done.exit_code != 0
    assert "solver.drain_bed_thickness_m: sealed 1.0, now 2.0" in done.stderr
    assert not (demo / "runs" / "probe.v2").exists()


def test_a_default_that_moved_is_warned_on_a_rerun_and_kept_in_its_lineage(
    sealed_then_moved: tuple[Path, Path],
) -> None:
    demo, _source = sealed_then_moved

    done = CliRunner().invoke(["catalog", "rerun", "probe", "--name", "again", "-w", str(demo)])

    assert done.exit_code == 0, done.stderr
    lineage = _manifest(demo / "runs" / "again")["lineage"]
    assert lineage["drift"] == {
        "solver.drain_bed_thickness_m": {"sealed": 1.0, "effective": 2.0},
    }


def test_a_default_engine_that_moved_is_named_too(
    demo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _simulate(demo, name="probe")
    monkeypatch.setattr(terrain_registry, "DEFAULT_ENGINE_ID", "numpy_d8")

    done = _hmp(demo, str(source / "config.toml"), "--frozen")

    assert done.exit_code != 0
    assert "geographic.terrain_engine: sealed 'whitebox_workflows', now 'numpy_d8'" in done.stderr


def test_an_edited_frozen_file_is_refused_by_name(demo: Path) -> None:
    source = _simulate(demo, name="probe", set={"K": K})
    frozen = source / "config.toml"
    frozen.write_text(frozen.read_text().replace(str(K), "0.0034"), encoding="utf-8")

    done = _hmp(demo, str(frozen), "--frozen")

    assert done.exit_code != 0
    assert f"{K_PATH}: sealed {K}, now 0.0034" in done.stderr


def test_a_project_toml_still_answers_to_its_lockfile(demo: Path) -> None:
    done = _hmp(demo, str(demo / "run_demo.toml"), "--frozen")

    assert done.exit_code != 0
    assert "hydromodpy.lock" in done.stderr


def test_a_run_resumed_right_after_its_solver_reads_the_folder_it_solved_in(
    demo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clean = _simulate(demo, name="clean")

    original = ExtractStep.run

    def dies(self, state):
        raise RuntimeError("the process died in extract")

    monkeypatch.setattr(ExtractStep, "run", dies)
    with pytest.raises(StepError, match="died in extract"):
        _simulate(demo, name="killed")
    assert not (demo / "runs" / "killed" / "manifest.json").exists()

    monkeypatch.setattr(ExtractStep, "run", original)
    resumed = _simulate(demo, resume="killed")

    assert resumed.name == "killed"
    assert _manifest(resumed)["run"]["status"] == "completed"
    assert _drift(clean, resumed) == [("run directory", "only in A [], only in B ['attempts']")]


def test_a_named_case_resumes_from_its_frozen_file(demo: Path) -> None:
    """The file writes the name of the run, the first launch read another one."""
    first = _hmp(demo, str(demo / "run_demo.toml"), "--case", "killed", "--until", "run_solver")
    assert first.exit_code == 0, first.stderr

    resumed = _hmp(demo, "--resume", "killed", "--no-display")

    assert resumed.exit_code == 0, resumed.stderr
    assert _manifest(demo / "runs" / "killed")["run"]["status"] == "completed"
    assert not (demo / "runs" / "killed.v2").exists()


def test_the_manifest_and_the_run_name_the_file_the_user_named(demo: Path) -> None:
    done = _hmp(demo, str(demo / "run_demo.toml"), "--set", f"{K_PATH}=2e-4", "--case", "with_set")
    assert done.exit_code == 0, done.stderr
    run_dir = demo / "runs" / "with_set"
    manifest = _manifest(run_dir)
    assert manifest["config"]["source"] == "run_demo.toml"
    assert manifest["lineage"]["overrides"] == {K_PATH: 2e-4}
    assert _config(run_dir)["simulation"]["name"] == "with_set"


def test_a_file_without_a_name_is_named_after_itself_under_set(demo: Path) -> None:
    """The temporary copy used to name the sealed ``simulation.name``."""
    bare = demo / "run_unnamed.toml"
    text = (demo / "run_demo.toml").read_text(encoding="utf-8")
    bare.write_text(text.replace('name = "demo"\n', ""), encoding="utf-8")

    done = _hmp(demo, str(bare), "--set", f"{K_PATH}=2e-4")

    assert done.exit_code == 0, done.stderr
    assert _manifest(demo / "runs" / "run_unnamed")["config"]["source"] == "run_unnamed.toml"
    assert _config(demo / "runs" / "run_unnamed")["simulation"]["name"] == "run_unnamed"


@pytest.mark.parametrize("launch", [{"headless": True}, {"no_display": True}])
def test_a_display_choice_of_the_launch_changes_no_identity_and_no_sealed_config(
    demo: Path, launch: dict[str, bool]
) -> None:
    with hmp.Project(demo / "run_demo.toml") as drawn:
        reference = drawn.simulate(name="drawn").dir
    with hmp.Project(demo / "run_demo.toml", **launch) as quiet:
        assert quiet.config.display.save is True
        run_dir = quiet.simulate(name="quiet").dir

    assert _manifest(run_dir)["config"]["hash"] == _manifest(reference)["config"]["hash"]
    expected = _config(reference)
    actual = _config(run_dir)
    expected["simulation"].pop("name")
    actual["simulation"].pop("name")
    assert actual == expected
    assert (reference / "figures").is_dir()
    assert not (run_dir / "figures").is_dir() or not list((run_dir / "figures").iterdir())


def test_hmp_run_takes_headless_on_a_path(demo: Path) -> None:
    run = hmp.run(demo / "run_demo.toml", name="quiet", headless=True)
    assert not (run.dir / "figures").is_dir() or not list((run.dir / "figures").iterdir())


def test_no_display_keeps_the_terms_the_figures_read(demo: Path) -> None:
    from hydromodpy.core.budget_terms import kept_budget

    consumers = demo / "run_consumers.toml"
    text = (demo / "run_demo.toml").read_text(encoding="utf-8")
    consumers.write_text(
        f"{text}\n[simulation.results]\nkeep_per_cell_budget = false\n", encoding="utf-8"
    )

    with hmp.Project(consumers) as drawn:
        one = drawn.simulate(name="drawn").dir
    with hmp.Project(consumers, no_display=True) as quiet:
        other = quiet.simulate(name="quiet").dir

    terms = [kept_budget(zarr.open_group(path / "fields.zarr", mode="r")) for path in (one, other)]
    assert terms[0] == terms[1]
    assert _manifest(one)["config"]["hash"] == _manifest(other)["config"]["hash"]


@pytest.mark.mf6
@pytest.mark.allow_subprocess
def test_modflow_6_states_what_it_decided_once_built(tmp_path: Path) -> None:
    """The IMS complexity and the XT3D decision are read back from the model."""
    from tests._helpers.island_project import island_toml, run_island

    toml = tmp_path / "island.toml"
    toml.write_text(island_toml("island", keep_solver_files=False), encoding="utf-8")
    run_island(toml)

    provenance = json.loads((tmp_path / "runs" / "island" / "provenance.json").read_text())
    options = provenance["solver"]["options"]
    assert options["ims_complexity"] in {"SIMPLE", "MODERATE", "COMPLEX"}
    assert isinstance(options["xt3d"], bool)
    assert options["xt3d_source"] in {"explicit_on", "explicit_off", "auto_on", "auto_off"}
    assert set(provenance["tool"]["code_fingerprint"]) == set(RUN_LAYERS)
