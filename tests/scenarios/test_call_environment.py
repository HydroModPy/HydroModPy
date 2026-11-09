"""The call environment of a campaign, played on the permanent island.

Four games, no network: a run whose options name a credentials file, hosts
and a ceiling (code 0, and nothing of them under ``runs/``); the same run
with a credentials file readable by the group (code 14 before the first
step); a calibration file with the same loose credentials (code 14 before
the routing reads the document); and an API call whose bounds refuse the
project root (a ``BoundsError`` that names the root).
"""

from __future__ import annotations

from pathlib import Path

from tests.scenarios.factory import island_files
from tests.scenarios.launcher import Scenario, play

GOOD_CREDENTIALS = """\
[[host]]
prefix = "https://keys.example.org/hmp/"
user = "hmp"
password = "value"
"""  # noqa: E501

LOOSE_CREDENTIALS = GOOD_CREDENTIALS


def _runs_of(played) -> list[Path]:
    return [played.root / path for kind, path in played.targets if kind == "run"]


def test_a_run_carrying_its_options_closes_without_a_trace(tmp_path, scenario_env, scenario_cache):
    credentials = tmp_path / "credentials" / "good.toml"
    credentials.parent.mkdir(parents=True, exist_ok=True)
    credentials.write_text(GOOD_CREDENTIALS, encoding="utf-8")
    credentials.chmod(0o600)
    scenario = Scenario(
        name="island",
        covers="a run whose environment options name a credentials file, hosts and a ceiling",
        files=island_files("gwt"),
        argv=(
            "run",
            "project.toml",
            "--credentials",
            str(credentials),
            "--allow-host",
            "data.geopf.fr",
            "--max-download-bytes",
            "1000000",
        ),
        needs=("mf6", "libmf6.so"),
    )

    played = play(scenario, tmp_path / "play", scenario_env, scenario_cache)

    assert played.returncode == 0, played.log.read_text(encoding="utf-8")[-2000:]
    assert _runs_of(played)
    for run_dir in _runs_of(played):
        for document in run_dir.rglob("*"):
            if document.is_file() and document.suffix in {".json", ".toml", ".txt", ".jsonl"}:
                text = document.read_text(encoding="utf-8", errors="ignore")
                assert "keys.example.org" not in text
                assert "good.toml" not in text
                assert "data.geopf.fr" not in text


def test_a_credentials_file_readable_by_others_refuses_before_any_step(
    tmp_path, scenario_env, scenario_cache
) -> None:
    loose = tmp_path / "credentials" / "loose.toml"
    loose.parent.mkdir(parents=True, exist_ok=True)
    loose.write_text(LOOSE_CREDENTIALS, encoding="utf-8")
    loose.chmod(0o644)
    scenario = Scenario(
        name="island",
        covers="a run whose credentials file the group reads, refused before any step",
        files=island_files("gwt"),
        argv=(
            "run",
            "project.toml",
            "--credentials",
            str(loose),
            "--allow-host",
            "data.geopf.fr",
            "--max-download-bytes",
            "1000000",
        ),
    )

    played = play(scenario, tmp_path / "play", scenario_env, scenario_cache)

    assert played.returncode == 14
    assert "loose.toml" in played.log.read_text(encoding="utf-8")
    assert "chmod 600" in played.log.read_text(encoding="utf-8")
    assert not (played.root / "runs").exists()


def test_a_calibration_with_a_loose_credentials_file_refuses_before_its_routing(
    tmp_path, scenario_env, scenario_cache
) -> None:
    loose = tmp_path / "credentials" / "loose.toml"
    loose.parent.mkdir(parents=True, exist_ok=True)
    loose.write_text(LOOSE_CREDENTIALS, encoding="utf-8")
    loose.chmod(0o644)
    scenario = Scenario(
        name="island",
        covers="a calibration whose credentials file the group reads, refused by its routing",
        files=island_files("calage"),
        argv=("calibrate", "calib.toml", "--credentials", str(loose)),
    )

    played = play(scenario, tmp_path / "play", scenario_env, scenario_cache)

    assert played.returncode == 14
    log = played.log.read_text(encoding="utf-8")
    assert "loose.toml" in log
    assert "chmod 600" in log
    assert not (played.root / "runs").exists()


def test_the_api_refuses_a_project_outside_the_named_roots(
    tmp_path, scenario_env, scenario_cache
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    scenario = Scenario(
        name="island",
        covers="an API run whose bounds refuse the project root outside its roots",
        files=island_files("gwt"),
        python=(
            "import hydromodpy as hmp\n"
            "from hydromodpy.core.runtime.bounds import Bounds\n"
            "from hydromodpy.project.environment import Environment\n"
            f"hmp.run('project.toml', environment=Environment(bounds=Bounds(allowed_roots=({str(elsewhere)!r},))))\n"
        ),
    )

    played = play(scenario, tmp_path / "play", scenario_env, scenario_cache)

    assert played.returncode == 1
    log = played.log.read_text(encoding="utf-8")
    assert "BoundsError" in log
    assert str(elsewhere) in log
    assert not (played.root / "runs").exists()
