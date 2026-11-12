"""A file of an older shape goes through the register of changes before it runs.

The island of ``prerelease_forms`` writes the solver tables where a pre-release wrote them, the backend
as a table and the settings of MODFLOW 6 at the root. Three things are played through the
real pipeline.

A file in that shape loads with a warning that names the doctor, and the run it makes
writes today's names and the edition of its defaults. A run sealed by a pre-release of 2.0 replays under
``hmp replay`` with no key that drifts, so a table that moved since the seal, and an
``edition`` the seal never wrote, change nothing in the numbers. A project that writes a
key only a pre-release of 2.0 wrote is refused before any solve, with the configuration
exit code and the key it names.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from hydromodpy.config.config_migration import PRERELEASE_FORMS
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.workflow.steps.prepare_solver.resolved import compare_with_sealed
from tests.characterization.comparator import compare_run_dirs
from tests.scenarios.factory import island_files
from tests.scenarios.launcher import Scenario, isolated_env, link_binaries, play

# The module fixture plays the project once, so every test of the file runs
# on the worker that played it.
pytestmark = [pytest.mark.xdist_group(name="older_file")]

RUN = "prerelease_forms"
EXIT_CONFIG = 14
NO_REWRITE = "This version does not rewrite the file."
EDITION_OF_THE_DEFAULTS = "2.0"


@pytest.fixture(scope="module")
def first_run(tmp_path_factory: pytest.TempPathFactory, scenario_cache: Path):
    """Play the island in the shape of a pre-release once, for the cases that read its run."""
    base = tmp_path_factory.mktemp("older_file")
    env = isolated_env(base / "home", scenario_cache, base / "state", base / "tmp")
    scenario = Scenario(
        name=RUN,
        covers="an island whose solver tables are written as a pre-release wrote them",
        files=island_files("prerelease_forms"),
        argv=("run", "project.toml"),
    )
    played = play(scenario, base / "play", env, scenario_cache)
    return played, env


def _read(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def test_a_file_of_pre_release_forms_warns_runs_and_writes_todays_names(first_run) -> None:
    played, _ = first_run

    log = played.log.read_text(encoding="utf-8")
    assert played.returncode == 0, log[-2000:]
    assert "ConfigKeyRenamedWarning" in log
    assert "modflow6 -> [solver.modflow6]" in log
    assert f"hmp doctor --fix-config {played.root / 'project.toml'}" in log

    run_dir = played.root / "runs" / RUN
    for name in ("config.toml", "config.resolved.toml"):
        document = _read(run_dir / name)
        assert "modflow6" not in document, name
        assert document["solver"]["modflow6"]["runtime"]["mf6_ims_complexity"] == "MODERATE", name
        assert document["solver"]["backend"] == "modflow6", name
    assert _read(run_dir / "config.resolved.toml")["edition"] == EDITION_OF_THE_DEFAULTS


def _as_sealed_by_2_0_0(text: str, *, edition: bool) -> str:
    """Put a document back in the shape a pre-release sealed: the tables at their old place."""
    older = text.replace("[solver.modflow6.", "[modflow6.").replace(
        'backend = "modflow6"', 'backend = { kind = "modflow6" }'
    )
    assert older != text
    if edition:
        return older
    kept = [line for line in older.splitlines(keepends=True) if not line.startswith("edition")]
    assert len(kept) == len(older.splitlines(keepends=True)) - 1
    return "".join(kept)


def test_a_run_sealed_by_a_pre_release_replays_with_no_drift(first_run, tmp_path: Path) -> None:
    played, env = first_run
    assert played.returncode == 0, played.log.read_text(encoding="utf-8")[-2000:]
    project = tmp_path / "project"
    shutil.copytree(played.root, project, symlinks=True)
    source = project / "runs" / RUN
    for name, edition in (("config.toml", True), ("config.resolved.toml", False)):
        text = (source / name).read_text(encoding="utf-8")
        (source / name).write_text(_as_sealed_by_2_0_0(text, edition=edition), encoding="utf-8")
    sealed = _read(source / "config.resolved.toml")
    assert "edition" not in sealed
    assert sealed["solver"]["backend"] == {"kind": "modflow6"}
    assert "modflow6" in sealed

    link_binaries(Path(env["HMP_CACHE_HOME"]), ("mf6", "libmf6.so"))
    replay = subprocess.run(
        [
            sys.executable,
            "-m",
            "hydromodpy",
            "replay",
            str(source),
        ],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )

    assert replay.returncode == 0, (replay.stdout + replay.stderr)[-2000:]
    assert "ConfigKeyRenamedWarning" not in replay.stderr
    replayed = project / "runs" / f"{RUN}.v2"
    assert replayed.is_dir()
    # The version suffix of the name, the folder of the project, the lineage of a replay
    # and the request it keeps differ by construction.
    assert [
        (verdict.target, verdict.detail)
        for verdict in compare_run_dirs(source, replayed).drifted
        if not verdict.target.endswith((":version_int", ":project", ":lineage_kind"))
        and verdict.detail != "only in A [], only in B ['request.json']"
    ] == []

    config = HydroModPyConfig.from_toml(source / "config.toml")
    compared = compare_with_sealed(config, source, project_root=project)
    assert compared is not None
    assert compared.drift == ()
    # What the seal never wrote and the replay holds at its default.
    assert set(compared.new_at_default) <= {"edition"}


def test_a_key_only_a_pre_release_wrote_is_refused_before_any_solve(
    tmp_path: Path, scenario_env: dict[str, str], scenario_cache: Path
) -> None:
    form = "flow.active_bc"
    assert form in {known.path for known in PRERELEASE_FORMS}
    scope, _, name = form.rpartition(".")
    files = island_files("prerelease_forms")
    files["project.toml"] = files["project.toml"].replace(
        f"[{scope}]\n", f'[{scope}]\n{name} = ["drainage"]\n', 1
    )
    assert f'{name} = ["drainage"]' in files["project.toml"]
    scenario = Scenario(
        name="a_pre_release_form",
        covers="a project that writes an activation list only a pre-release of 2.0 wrote",
        files=files,
        argv=("run", "project.toml"),
        needs=(),
    )

    played = play(scenario, tmp_path / "play", scenario_env, scenario_cache)

    log = played.log.read_text(encoding="utf-8")
    assert played.returncode == EXIT_CONFIG, log[-2000:]
    assert form in log
    assert NO_REWRITE in log
    assert not (played.root / "runs").exists()
