"""The README of a run says what the run does not give, read from what the run stored.

The steady island is run once with ``hmp run``. The README it leaves says the run is
one steady state, so there is no change in time to read. The island keeps no flow
between cells and tracks no particle, so the README names both limits, and the first
one gives the key that keeps the flow.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.scenarios.factory import island_files
from tests.scenarios.launcher import Scenario, isolated_env, play

SECTION = "## What this run does not give"
STEADY_LINE = "- A change in time: the run is one steady state."
FACE_FLOW_LINE = "- The flow between two cells. Set `keep_face_flows = true` under `[simulation.results]` to keep it."
PARTICLE_LINE = "- A residence time: the run has no particle tracking."


@pytest.fixture(scope="module")
def readme(tmp_path_factory: pytest.TempPathFactory, scenario_cache: Path) -> str:
    """Play the steady island once and return the README of its run."""
    base = tmp_path_factory.mktemp("limits")
    env = isolated_env(base / "home", scenario_cache, base / "state", base / "tmp")
    files = {name: text for name, text in island_files("calage").items() if name != "calib.toml"}
    scenario = Scenario(
        name="limits",
        covers="the README of a run says what the run does not give",
        files=files,
        argv=("run", "project.toml"),
        expected_s=30.0,
    )
    played = play(scenario, base / "play", env, scenario_cache)
    log = played.log.read_text(encoding="utf-8", errors="replace")[-3000:]
    assert played.returncode == 0, log
    return (played.root / "runs" / "calage" / "README.md").read_text(encoding="utf-8")


def test_the_section_follows_the_checks_and_comes_before_the_cost_of_a_replay(readme) -> None:
    assert SECTION in readme
    assert readme.index("## Checks") < readme.index(SECTION) < readme.index("## Cost of a replay")


def test_a_steady_run_says_it_is_one_state(readme) -> None:
    section = readme.split(SECTION)[1].split("\n## ")[0]

    assert STEADY_LINE in section
    assert "stress period" not in section


def test_a_run_that_stored_no_face_flow_says_how_to_keep_it(readme) -> None:
    assert FACE_FLOW_LINE in readme


def test_a_run_without_particles_says_it_has_no_residence_time(readme) -> None:
    assert PARTICLE_LINE in readme
