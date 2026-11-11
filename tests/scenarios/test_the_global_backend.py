"""The global backend of the run, played through the real pipeline on the basin.

The basin of the catchment walks the catchment mesh and hands the whole domain
to the one-cell global model, the linear reservoir the ``[solver]`` section
names. A river trace the mesh engine ignores is refused when the file is read:
the planner would grade a family the mesh never builds.

The run itself closes at the seal: the one cell is the domain in area, the
``discharge`` series reads at the station of the catchment and ``Run.grid``
answers like any run. On a run of five-day periods and a daily recharge, the
recharge of every day of a period still reaches the run: the source's own step
carries its twenty values, and no reading of the period means can answer for
the water. The same run reads back in the form ``time``: one dimension, one
value per period, and the units of the registry.

A global model is a solver backend named by ``solver.backend``, and the
pipeline evaluator scores its runs. A calibration document of the basin decides
the number: the metric and the weights of the document, and the best cost is
the one the closed form of the kernel gives. The parameter is the time constant
of the reservoir, and the closed form is restated here rather than imported. A
grid and a simplex search it, both through the evaluator of the pipeline, with
no forward model.
"""

from __future__ import annotations

import difflib
import json
import math
import re
import tomllib
from pathlib import Path

import pandas as pd
import pytest
import zarr

from hydromodpy.results.field_registry import TIME_SERIES_REGISTRY
from hydromodpy.results.session.descriptor import read_session
from hydromodpy.results.storage.contract import PARQUET_FILE_SUFFIX, TABLES_DIRNAME
from hydromodpy.results.storage.udunits import udunits_spelling
from tests.scenarios.factory import basin_files
from tests.scenarios.launcher import Scenario, play

AREA_M2 = 610.0 * 610.0
"""The area of the one cell: the whole domain is the catchment of the run."""

DAY_S = 86400.0
"""Length of one native step of the run, in seconds. Recharge is mm per day."""

STEADY_DISCHARGE_M3_S = 1.5e-3 * AREA_M2 / DAY_S
"""The steady state of a constant recharge of 1.5 mm per day over the cell."""

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


GRID_PHASE = """\
[[calibration.phases]]
name = "tau_grid"
parameters = ["time_constant"]
regime = "transient"
objective_blocks = ["gauge", "revised"]
method = "grid"
max_trials = 9
method_options = { points_per_dim = 9 }
"""
"""The search of the document by default: nine nodes of a grid on the time constant."""

SIMPLEX_PHASE = """\
[[calibration.phases]]
name = "tau_simplex"
parameters = ["time_constant"]
regime = "transient"
objective_blocks = ["gauge", "revised"]
method = "scipy_nelder_mead"
max_trials = 8
method_options = { xatol = 0.1 }
"""
"""The search of the simplex test: at most eight evaluations, stopped when the simplex is
narrower than 0.1 in the transformed (log) space, so the session closes complete."""


def _document(
    path: Path,
    *,
    gauge_weight: float = 0.7,
    revised_weight: float = 0.3,
    metric: str = "rmse",
    search: str = GRID_PHASE,
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

{search}
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


def _runs(played) -> dict[str, Path]:
    """Return the run folders a played scenario left, by run name."""
    return {Path(path).name: played.root / path for kind, path in played.targets if kind == "run"}


def _open(run_dir: Path):
    """Open one run folder with the facade, from the test process."""
    import hydromodpy as hmp

    return hmp.open(run_dir)


def test_the_basin_runs_its_global_backend_to_the_seal(tmp_path, scenario_env, scenario_cache):
    """The daily basin closes with the global model and reads its series back."""
    scenario = Scenario(
        name="basin_daily",
        covers="a basin run of the catchment, global model on, closed at the seal",
        files=basin_files(),
        argv=("run", "project.toml"),
    )

    played = play(scenario, tmp_path / "play", scenario_env, scenario_cache)

    assert played.returncode == 0, played.log.read_text(encoding="utf-8")[-2000:]
    runs = _runs(played)
    assert list(runs) == ["basin"]
    run = _open(runs["basin"])

    # The one cell of the engine is the whole synthetic domain: 610 m by 610 m.
    assert abs(float(run.grid.catchment_area_m2) - AREA_M2) < 1.0

    discharge = run.read("discharge", sel={"station": "catchment"})
    assert isinstance(discharge, pd.Series)
    assert discharge.size == 20
    assert float(discharge.iloc[-1]) == pytest.approx(STEADY_DISCHARGE_M3_S, rel=1e-6)


def test_a_recharge_written_at_its_own_step_reaches_the_run_in_twenty_values(
    tmp_path, scenario_env, scenario_cache
):
    """A 5-day run keeps the daily step of its source: 20 native values, not 4."""
    scenario = Scenario(
        name="basin_5d",
        covers="a basin run on five-day periods, the recharge at the step of its source",
        files=basin_files(with_daily_recharge=True),
        argv=("run", "project.toml"),
        timeout_s=300.0,
    )

    played = play(scenario, tmp_path / "play", scenario_env, scenario_cache)

    assert played.returncode == 0, played.log.read_text(encoding="utf-8")[-2000:]
    runs = _runs(played)
    assert list(runs) == ["basin_5d"]
    fields = zarr.open(str(runs["basin_5d"] / "fields.zarr"), mode="r")
    # A point source is kept under its station id, the one row of the
    # station table the factory writes.
    recharge = fields["forcing"]["recharge"]
    assert sorted(recharge.group_keys()) == ["BASIN_5D"]
    forcing = recharge["BASIN_5D"]

    values = forcing["values"][:]
    timestamps = forcing["timestamps"][:].astype("datetime64[ns]")
    assert values.size == 20
    steps = pd.Series(timestamps).diff().dropna()
    assert bool((steps == pd.Timedelta(days=1)).all())

    # The series reads back in the form ``time``: one dimension, one value per
    # period of five days, never one per value of the source.
    run = _open(runs["basin_5d"])
    discharge = run.read("discharge", sel={"station": "catchment"})
    assert isinstance(discharge, pd.Series)
    assert discharge.ndim == 1
    assert isinstance(discharge.index, pd.DatetimeIndex)
    assert discharge.index.is_unique
    assert discharge.size == 4
    table = pd.read_parquet(runs["basin_5d"] / TABLES_DIRNAME / f"timeseries{PARQUET_FILE_SUFFIX}")
    simulated = table[table["source"] == "simulated"]
    for variable in ("discharge", "reservoir_storage"):
        units = set(simulated.loc[simulated["variable"] == variable, "unit"])
        assert units == {udunits_spelling(TIME_SERIES_REGISTRY[variable].units)}


def test_a_river_trace_written_beside_the_basin_is_refused(tmp_path, scenario_env, scenario_cache):
    """A family the mesh engine ignores is refused with its own sentence."""
    files = basin_files()
    files["project.toml"] = files["project.toml"].replace(
        "[data]",
        '[mesh.families]\nrivers = "cell"\n\n[data]',
    )
    scenario = Scenario(
        name="basin_rivers",
        covers="a basin run whose mesh carries a river trace the basin engine ignores",
        files=files,
        argv=("run", "project.toml"),
    )

    played = play(scenario, tmp_path / "play", scenario_env, scenario_cache)

    log = played.log.read_text(encoding="utf-8")
    assert played.returncode != 0, log[-2000:]
    said = re.search(
        r"rivers = [\"']cell[\"'], and the mesh engine\s+'?catchment'? ignores it", log
    )
    assert said is not None, log[-2000:]


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


def test_a_simplex_calibrates_the_global_backend(
    tmp_path: Path, scenario_env: dict[str, str], scenario_cache: Path
) -> None:
    """A Nelder-Mead search moves the time constant, scored by the pipeline evaluator.

    The simplex has a budget of eight evaluations. It tries more than two
    time constants, ends on a cost no worse than its first try, and runs the
    one-cell backend through the evaluator of the pipeline, with no forward
    model.
    """
    session = _play(tmp_path, scenario_env, scenario_cache, "simplex_doc", search=SIMPLEX_PHASE)

    trials = _completed(session)
    assert 3 <= len(trials) <= 8
    assert len({tau for tau, _ in trials}) >= 3
    _, best_cost = _best(session)
    assert best_cost <= trials[0][1]

    with (session / "config.toml").open("rb") as handle:
        frozen = tomllib.load(handle)
    assert frozen["solver"]["backend"] == "linear_reservoir"
    assert frozen["calibration"].get("evaluator") in (None, "hydromodpy_pipeline")
    assert "forward_model" not in frozen["calibration"]
