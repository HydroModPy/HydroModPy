"""A grid calibration solves its first trial by a build and reruns the next ones.

``hmp calibrate calib.toml`` plays a grid of three values. The first trial of a lane
builds its MODFLOW 6 model, and a trial that moves only K or Sy runs the previous
trial of the lane again through ``rerun``. The first case is the steady island that
calibrates K, and its three costs are the ones the 2.0.0 wrote, to the last bit. The
second case is the transient island of three months that calibrates Sy, starting from
the head rule and never from a steady or a cyclic start, which ``rerun`` refuses.

The journal holds one line per event: ``proposed`` when the optimizer asks, ``finished``
with the cost, its components, the rule and window it was scored under and the profile,
``linked`` when a trial became a run. The profile of each ``finished`` line names, in
its ``solve`` line, whether the run was built or rerun.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from hydromodpy.results.session.journal import TRIAL_SCHEMA, read_trials
from hydromodpy.results.session.trial_series import read_trial_series
from tests.scenarios.factory import island_files
from tests.scenarios.launcher import Scenario, play

REFERENCE_COSTS = (4.946107160722614, 0.945487753170152, 0.8971488644483185)
"""The three costs of the ``calage`` reference of 2.0.0, read in its journal."""


def _play(variant: str, tmp_path: Path, scenario_env, scenario_cache) -> tuple[Path, list[dict]]:
    """Play ``hmp calibrate calib.toml`` and return the session folder and its raw journal lines."""
    scenario = Scenario(
        name=variant,
        covers="a grid calibration whose trials rerun the previous one",
        files=island_files(variant),
        argv=("calibrate", "calib.toml"),
        expected_s=60.0,
    )
    played = play(scenario, tmp_path / "play", scenario_env, scenario_cache)
    log = played.log.read_text(encoding="utf-8", errors="replace")[-3000:]
    assert played.returncode == 0, log
    session = played.root / "sessions" / variant
    lines = [
        json.loads(text)
        for text in (session / "trials.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    return session, lines


def _solve_reuse(line: dict[str, Any]) -> list[str]:
    return [item["reused"] for item in line["profile"] if item["kind"] == "solve"]


def _finished(lines: list[dict]) -> dict[int, dict]:
    return {line["trial"]: line for line in lines if line["event"] == "finished"}


def test_the_calage_trials_cost_what_2_0_0_cost_and_rerun_after_the_first(
    tmp_path: Path, scenario_env, scenario_cache
) -> None:
    session, lines = _play("calage", tmp_path, scenario_env, scenario_cache)

    assert {line["schema"] for line in lines} == {TRIAL_SCHEMA}
    assert Counter(line["event"] for line in lines) == {"proposed": 3, "finished": 3, "linked": 1}

    trials = read_trials(session)
    assert [trial.trial for trial in trials] == [1, 2, 3]
    assert [trial.cost for trial in trials] == list(REFERENCE_COSTS)

    finished = _finished(lines)
    assert _solve_reuse(finished[1]) == ["no"]
    assert _solve_reuse(finished[2]) == ["rerun"]
    assert _solve_reuse(finished[3]) == ["rerun"]
    for line in finished.values():
        assert line["cases"], "a finished line carries its case"
        for case in line["cases"].values():
            assert case["rule"] == "2"
            assert case["window"] == "calibration"

    assert len(read_trial_series(session)["trial"].unique()) == 3


def test_the_calage_sy_trials_rerun_and_each_costs_a_different_number(
    tmp_path: Path, scenario_env, scenario_cache
) -> None:
    session, lines = _play("calage_sy", tmp_path, scenario_env, scenario_cache)

    assert Counter(line["event"] for line in lines)["finished"] == 3
    finished = _finished(lines)
    assert _solve_reuse(finished[1]) == ["no"]
    assert _solve_reuse(finished[2]) == ["rerun"]
    assert _solve_reuse(finished[3]) == ["rerun"]

    costs = [trial.cost for trial in read_trials(session)]
    assert len(costs) == 3
    assert all(cost is not None and cost == cost and abs(cost) != float("inf") for cost in costs)
    assert len(set(costs)) == 3, f"the three values of Sy gave the costs {costs}"
