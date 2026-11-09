"""A document scores the global backend, played through the real pipeline.

The forward model this file graded is gone: a global model is a solver backend
named by ``solver.backend``, and the pipeline evaluator scores its runs. The
tests keep the questions of ``test_a_document_scores_a_forward_model.py``: the
metric and the weights of the document decide the number, and the best cost is
the one the closed form of the kernel gives. The basin is the one-cell mesh of
the factory, the parameter is the time constant of the reservoir, and the
closed form is restated here rather than imported.
"""

from __future__ import annotations

import difflib
import math
from pathlib import Path

import pytest

from tests.scenarios.factory import basin_files
from tests.scenarios.launcher import Scenario, play

AREA_M2 = 610.0 * 610.0
"""The area of the one cell: the whole domain is the catchment of the run."""

DAY_S = 86400.0
"""Length of one native step of the run, in seconds. Recharge is mm per day."""

TRUE_TAU_DAYS = 30.0
REVISED_TAU_DAYS = 8.0
"""The two recessions the records of the document carry, one each."""

TAU_BOUNDS = (5.0, 90.0)
"""The grid looks for the time constant between 5 and 90 days, in the log space."""


def _rates_m_per_s() -> list[float]:
    """The recharge of every day of the run, in m/s, from the mm-per-day rates."""
    return [(1.0 + (day % 5) * 0.5) * 1e-3 / DAY_S for day in range(20)]


def _discharge_series(tau_days: float) -> list[float]:
    """``Q(t)`` of every period, in m3/s, from the closed form, by hand.

    The state starts on the steady state of the mean recharge, the rule the
    steady start of the run declares, then every day advances
    ``s(t+d) = r·tau + (s(t) - r·tau)·exp(-d/tau)`` and releases
    ``r·d Δs`` in depth, one piece of constant rate per day.
    """
    tau_s = tau_days * DAY_S
    rates = _rates_m_per_s()
    depth = tau_s * (sum(rates) / len(rates))
    discharges: list[float] = []
    for rate in rates:
        end = rate * tau_s + (depth - rate * tau_s) * math.exp(-DAY_S / tau_s)
        discharges.append(AREA_M2 * (rate * DAY_S - (end - depth)) / DAY_S)
        depth = end
    return discharges


def _root_mean_square(first: list[float], second: list[float]) -> float:
    """The rmse of two same-length series, restated rather than imported."""
    squares = sum((left - right) ** 2 for left, right in zip(first, second))
    return math.sqrt(squares / len(first))


def _grid_nodes() -> list[float]:
    """The nine nodes of the grid, in the log space between the bounds."""
    low, high = math.log10(TAU_BOUNDS[0]), math.log10(TAU_BOUNDS[1])
    return [10.0 ** (low + (high - low) * step / 8) for step in range(9)]


def _basin_project() -> str:
    """The basin project, with the twenty daily rates the document scores."""
    rates = ", ".join(f"{rate:g}" for rate in (1.0 + (day % 5) * 0.5 for day in range(20)))
    return basin_files()["project.toml"].replace("values = [1.5]", f"values = [{rates}]")


def _document(
    path: Path,
    *,
    gauge_weight: float = 0.7,
    revised_weight: float = 0.3,
    metric: str = "rmse",
) -> str:
    """Write one calibration document of the basin and return its text.

    Two records of one outlet that disagree: the first is the answer of the
    closed form at ``TRUE_TAU_DAYS``, the second at ``REVISED_TAU_DAYS``. Both
    score the same whole-catchment discharge, so nothing physical tells them
    apart and the weights are the whole of the arbitration.
    """
    gauge = ", ".join(repr(value) for value in _discharge_series(TRUE_TAU_DAYS))
    revised = ", ".join(repr(value) for value in _discharge_series(REVISED_TAU_DAYS))
    text = f"""\
base_config = "project.toml"

[workflow]
mode = "calibration"

[simulation]
name = "basin"

[calibration]
save_runs = "best_n"
use_cache = false

[calibration.parameters.time_constant]
bounds = [{TAU_BOUNDS[0]}, {TAU_BOUNDS[1]}]
search_space = "log"

[calibration.outputs.gauge_record]
support = "point"
variable = "discharge"
x = 305.0
y = 305.0
time = "all"
observed_values = [{gauge}]

[calibration.outputs.revised_record]
support = "point"
variable = "discharge"
x = 305.0
y = 305.0
time = "all"
observed_values = [{revised}]

[[calibration.objective_blocks]]
name = "gauge"
metric = "{metric}"
uses_outputs = ["gauge_record"]
weight = {gauge_weight}

[[calibration.objective_blocks]]
name = "revised"
metric = "{metric}"
uses_outputs = ["revised_record"]
weight = {revised_weight}

[[calibration.phases]]
name = "tau_grid"
parameters = ["time_constant"]
regime = "transient"
objective_blocks = ["gauge", "revised"]
method = "grid"
max_trials = 9
method_options = {{ points_per_dim = 9 }}

[display]
enabled = false
"""
    path.write_text(text, encoding="utf-8")
    return text


def _changed_lines(first: str, second: str) -> list[str]:
    """Return the lines that differ between two documents, markers included."""
    return [
        line
        for line in difflib.unified_diff(first.splitlines(), second.splitlines(), n=0)
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    ]


def _sessions(played) -> list[Path]:
    """Return the session directories a played calage left, in order."""
    root = played.root
    if not (root / "sessions").is_dir():
        return []
    return sorted(path for path in (root / "sessions").iterdir() if path.is_dir())


def _completed(session_dir: Path) -> list[tuple[float, float]]:
    """The completed trials of one session, as ``(tau, cost)`` pairs."""
    import json

    best: dict[int, dict] = {}
    for line in (session_dir / "trials.jsonl").read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        best[int(record["trial"])] = record
    pairs = []
    for record in (best[number] for number in sorted(best)):
        cost = record.get("cost")
        if cost is None:
            continue
        params = record.get("params", {})
        tau = next(iter(params.values()))["value"]
        pairs.append((float(tau), float(cost)))
    return pairs


def _best(session_dir: Path) -> tuple[float, float]:
    """The ``(tau, cost)`` of the best trial one session recorded."""
    import json

    best = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))["best"]
    if best is not None and best.get("parameters"):
        tau = next(iter(best["parameters"].values()))
        return float(tau), float(best["cost"])
    costs = _completed(session_dir)
    return min(costs, key=lambda pair: pair[1])


def _play(
    tmp_path: Path,
    scenario_env: dict[str, str],
    scenario_cache: Path,
    name: str,
    **document: object,
):
    """Write the basin project and one document beside it, calibrate, and report."""
    files = {"project.toml": _basin_project()}
    document_path = tmp_path / f"{name}.toml"
    text = _document(document_path, **document)  # type: ignore[arg-type]
    files["project.toml"] = files["project.toml"].replace('name = "basin"', f'name = "{name}"')
    files[f"{name}.toml"] = text
    scenario = Scenario(
        name=name,
        covers="a calibration of the global backend, scored by its document",
        files=files,
        argv=("calibrate", f"{name}.toml"),
        needs=(),
        timeout_s=300.0,
    )
    played = play(scenario, tmp_path / "play", scenario_env, scenario_cache)
    assert played.returncode == 0, played.log.read_text(encoding="utf-8")[-2000:]
    sessions = _sessions(played)
    assert len(sessions) == 1, played.log.read_text(encoding="utf-8")[-2000:]
    return sessions[0]


def test_the_grid_of_the_document_lands_where_the_closed_form_says(
    tmp_path: Path, scenario_env: dict[str, str], scenario_cache: Path
) -> None:
    """Nine trials, and the best cost is the one the closed form recomputes.

    The two records carry the answer of the closed form at their time
    constants, and the cost is the sum of the two rmse weighted 0.7 and 0.3,
    the default weights of the document. The node it pulls to and its cost are
    that recomputation over the grid.
    """
    session = _play(tmp_path, scenario_env, scenario_cache, "rmse_doc")

    tau, cost = _best(session)

    def weighted_cost(node: float) -> float:
        simulated = _discharge_series(node)
        gauge = _root_mean_square(simulated, _discharge_series(TRUE_TAU_DAYS))
        revised = _root_mean_square(simulated, _discharge_series(REVISED_TAU_DAYS))
        return 0.7 * gauge + 0.3 * revised

    expected_tau, expected_cost = min(
        ((node, weighted_cost(node)) for node in _grid_nodes()),
        key=lambda pair: pair[1],
    )
    assert tau == pytest.approx(expected_tau, rel=1e-4)
    assert cost == pytest.approx(expected_cost, rel=1e-9)


def test_the_metric_of_the_document_moves_the_cost(
    tmp_path: Path, scenario_env: dict[str, str], scenario_cache: Path
) -> None:
    """Two runs, one metric changed, and the number the search reports moves.

    ``kge`` is an efficiency turned into a cost and ``rmse`` a distance, so the
    same nine runs cannot report the same number under both: what changed is
    who scores, not what ran.
    """
    rmse_session = _play(tmp_path, scenario_env, scenario_cache, "metric_rmse")
    kge_session = _play(tmp_path, scenario_env, scenario_cache, "metric_kge", metric="kge")

    squared_error = _best(rmse_session)
    efficiency = _best(kge_session)

    assert squared_error[1] != pytest.approx(efficiency[1], rel=1e-6)
    assert {tau for tau, _ in _completed(rmse_session)} == {
        tau for tau, _ in _completed(kge_session)
    }


def test_the_weights_of_the_document_choose_which_record_the_search_believes(
    tmp_path: Path, scenario_env: dict[str, str], scenario_cache: Path
) -> None:
    """Two runs, two weights swapped, and the search lands on a different constant.

    The two records are irreconcilable by construction: the reservoir at one
    time constant cannot reproduce both. The grid plays every node of both
    documents, so the weighting alone decides which record the winner fits.
    """
    trusts_gauge = _play(tmp_path, scenario_env, scenario_cache, "gauge_first")
    trusts_revision = _play(
        tmp_path,
        scenario_env,
        scenario_cache,
        "revision_first",
        gauge_weight=0.3,
        revised_weight=0.7,
    )

    gauge_tau, _ = _best(trusts_gauge)
    revision_tau, _ = _best(trusts_revision)

    # Every hard-coded weight is a document line: two lines of the first
    # document became two other lines of the second one, and nothing else.
    gauge_doc = (tmp_path / "gauge_first.toml").read_text(encoding="utf-8")
    revision_doc = (tmp_path / "revision_first.toml").read_text(encoding="utf-8")
    assert _changed_lines(gauge_doc, revision_doc) == [
        "-weight = 0.7",
        "+weight = 0.3",
        "-weight = 0.3",
        "+weight = 0.7",
    ]

    def weighted(w_gauge: float, w_revised: float) -> float:
        """The argmin the weighted rmse of two records gives over the grid."""
        return min(
            _grid_nodes(),
            key=lambda node: (
                w_gauge
                * _root_mean_square(_discharge_series(node), _discharge_series(TRUE_TAU_DAYS))
                + w_revised
                * _root_mean_square(_discharge_series(node), _discharge_series(REVISED_TAU_DAYS))
            ),
        )

    assert gauge_tau == pytest.approx(weighted(0.7, 0.3), rel=1e-4)
    assert revision_tau == pytest.approx(weighted(0.3, 0.7), rel=1e-4)
    assert gauge_tau != pytest.approx(revision_tau, rel=1e-3)


def test_the_session_records_what_ran(
    tmp_path: Path, scenario_env: dict[str, str], scenario_cache: Path
) -> None:
    """What ran has to be readable afterwards, and the backend is what names it.

    The frozen document carries what the file wrote: the backend of the run is
    the solver the project named, and the key that once named a forward model
    is refused on load, so nothing of it can stay.
    """
    import tomllib

    from hydromodpy.results.session.descriptor import read_session

    session = _play(tmp_path, scenario_env, scenario_cache, "recorded")

    descriptor = read_session(session)
    assert descriptor.session_id is not None
    assert descriptor.status == "completed"
    with (session / "config.toml").open("rb") as handle:
        frozen = tomllib.load(handle)
    assert frozen["solver"]["backend"] == "linear_reservoir"
    assert "forward_model" not in frozen["calibration"]
    evaluator = frozen["calibration"].get("evaluator")
    assert evaluator is None or evaluator != "scored_forward_model"
