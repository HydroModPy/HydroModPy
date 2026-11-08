"""The parallel calages of one island, played through the real pipeline.

The island is calibrated twice: ``[calibration] parallel = 1``, then
``[calibration] parallel = 2``, both by ``--set`` on the command ``hmp
calibrate``. The scenario checks that each run closes, that the costs the log
holds for its three trials are bit-identical between both runs, and that the best
parameter is the same.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.scenarios.factory import island_files
from tests.scenarios.launcher import Scenario, play


def _session_dirs(played) -> list[Path]:
    """Return the session directories a played calage left behind."""
    root = played.root
    sessions = root / "sessions"
    if not sessions.is_dir():
        return []
    return sorted(path for path in sessions.iterdir() if (path / "trials.jsonl").is_file())


def _trial_lines(session_dir: Path) -> list[dict]:
    """Return the last line of each trial the session journal holds.

    The journal is append-only: a trial linked to the run it became is
    written twice, and the last line of a trial number wins.
    """
    last: dict[int, dict] = {}
    for line in (session_dir / "trials.jsonl").read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        last[int(record["trial"])] = record
    return [last[number] for number in sorted(last)]


def _trial_costs(session_dir: Path) -> list[float]:
    """Return the costs of the trials one session directory holds, in order."""
    return [
        float(record["cost"])
        for record in _trial_lines(session_dir)
        if record.get("cost") is not None
    ]


def _best_parameter(session_dir: Path) -> dict[str, float]:
    """Return the parameters of the best trial in the session."""
    session_json = session_dir / "session.json"
    if session_json.is_file():
        record = json.loads(session_json.read_text(encoding="utf-8"))
        if record.get("best") and "parameters" in record["best"]:
            return {k: float(v) for k, v in record["best"]["parameters"].items()}
    best_cost = None
    best_params: dict[str, float] = {}
    for rec in _trial_lines(session_dir):
        cost = rec.get("cost")
        if cost is not None:
            if best_cost is None or float(cost) < best_cost:
                best_cost = float(cost)
                best_params = {k: float(v["value"]) for k, v in rec.get("params", {}).items()}
    return best_params


def test_a_parallel_calibration_fills_its_workers(tmp_path, scenario_env, scenario_cache) -> None:
    """One island calage with parallel = 1 then parallel = 2 yields identical costs and best."""
    scenario_1 = Scenario(
        name="calage_parallel_1",
        covers="an island calage with [calibration] parallel = 1",
        files=island_files("calage"),
        argv=(
            "calibrate",
            "calib.toml",
            "--set",
            "calibration.parallel=1",
        ),
    )
    played_1 = play(scenario_1, tmp_path / "play_1", scenario_env, scenario_cache)
    assert played_1.returncode == 0, played_1.log.read_text(encoding="utf-8")[-2000:]
    sessions_1 = _session_dirs(played_1)
    assert sessions_1, "the parallel=1 calage closed no session"
    costs_1 = _trial_costs(sessions_1[0])
    assert len(costs_1) == 3, f"parallel=1 ran {len(costs_1)} trials, expected 3"
    best_1 = _best_parameter(sessions_1[0])

    scenario_2 = Scenario(
        name="calage_parallel_2",
        covers="an island calage with [calibration] parallel = 2",
        files=island_files("calage"),
        argv=(
            "calibrate",
            "calib.toml",
            "--set",
            "calibration.parallel=2",
        ),
    )
    played_2 = play(scenario_2, tmp_path / "play_2", scenario_env, scenario_cache)
    assert played_2.returncode == 0, played_2.log.read_text(encoding="utf-8")[-2000:]
    sessions_2 = _session_dirs(played_2)
    assert sessions_2, "the parallel=2 calage closed no session"
    costs_2 = _trial_costs(sessions_2[0])
    assert len(costs_2) == 3, f"parallel=2 ran {len(costs_2)} trials, expected 3"
    best_2 = _best_parameter(sessions_2[0])

    assert costs_1 == costs_2, f"costs mismatch: {costs_1} != {costs_2}"
    assert best_1 == best_2, f"best parameters mismatch: {best_1} != {best_2}"
