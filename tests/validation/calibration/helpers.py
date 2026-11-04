"""Shared helpers for lightweight calibration validation tests."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from tests.validation.helpers.results import record_case, record_metric, record_samples
from validation_cases.calibration.shared.runtime import run_twin_benchmark_case


@dataclass(frozen=True, slots=True)
class TwinCheck:
    """What a twin test asserts about every run of one method.

    ``meets_target`` asserts the success metric of the method profile.
    ``best_within`` asserts that the best candidate lies within that multiple of
    the case tolerance on every parameter. ``in_distribution`` asserts that one
    evaluated sample lies within the tolerance on every parameter at once.
    ``second_smallest_within`` bounds the second smallest error to tolerance
    ratio. ``min_runs_best`` and ``min_runs_in_distribution`` assert the
    count over the seeds of a repeated method instead of every run.
    """

    meets_target: bool = False
    best_within: float | None = None
    in_distribution: bool = False
    second_smallest_within: float | None = None
    min_runs_best: int | None = None
    min_runs_in_distribution: int | None = None


def run_lightweight_twin_benchmark_case(
    definition: Any,
    *,
    caller_file: str | Path,
    checks: Mapping[str, TwinCheck] | None = None,
    any_meets_target: Sequence[str] = (),
    **kwargs: Any,
):
    """Run one twin benchmark via the v1 :meth:`Project.calibrate` API.

    ``checks`` maps a method name to what the test asserts about it. The
    asserts and the recorded thresholds both come from it, so the page shows
    what the test checks. ``any_meets_target`` names methods of which at
    least one must reach its success target.
    """
    benchmark = run_twin_benchmark_case(
        definition,
        caller_file=caller_file,
        case_figures=False,
        **kwargs,
    )
    assert benchmark.summary_path.is_file()
    assert benchmark.configuration_figure is None
    assert benchmark.reference_objective_path is None
    assert benchmark.pruned_artifacts
    check_twin_recovery(benchmark, checks or {}, any_meets_target=any_meets_target)
    return benchmark


def _samples_of(result: Any, parameters: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """Read the completed evaluations of one method from its iteration history."""
    path = result.iteration_history_path
    rows: list[list[float]] = []
    costs: list[float] = []
    if path is None or not Path(path).is_file():
        return np.empty((0, len(parameters))), np.empty(0)
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        named = item.get("params_named") or {}
        cost = item.get("objective_total")
        if item.get("status") != "completed" or cost is None:
            continue
        if any(name not in named for name in parameters):
            continue
        rows.append([float(named[name]) for name in parameters])
        costs.append(float(cost))
    return np.asarray(rows, dtype=float).reshape(-1, len(parameters)), np.asarray(costs)


def check_twin_recovery(
    benchmark: Any,
    checks: Mapping[str, TwinCheck],
    *,
    any_meets_target: Sequence[str] = (),
) -> None:
    """Record every twin metric, then assert what ``checks`` declares.

    A distance is recorded with a threshold only when a check asserts it.
    Every other distance is information: it carries no threshold and no
    operator, so the page does not read it as a pass or a fail.

    A count, and a yes or no read as a count of one, is recorded as above the
    largest count that fails, with the number of runs as its ideal value. The
    page then reads the share of the margin a result used: 0 when every run
    succeeds, 1 at the failing count. Recorded as at least the smallest count
    that passes, a single success would read as the whole margin used.
    """
    definition = benchmark.definition
    record_case(definition.case_id)
    tolerances = {str(k): float(v) for k, v in definition.parameter_abs_tolerances.items()}
    parameters = [str(name) for name in definition.truth_params]
    truth = {str(k): float(v) for k, v in definition.truth_params.items()}
    failures: list[str] = []

    def judge(
        label: str,
        value: float | None,
        threshold: float | None,
        op: str,
        ok: bool,
        *,
        ideal: float | None = None,
    ) -> None:
        record_metric(label, value, threshold, op=op if threshold is not None else "", ideal=ideal)
        if threshold is not None and not ok:
            failures.append(f"{label}: {value} not {op} {threshold}")

    def judge_count(label: str, count: int, minimum: int, out_of: int) -> None:
        """Judge ``count >= minimum``, recorded as above ``minimum - 1``."""
        judge(
            label,
            float(count),
            float(minimum - 1),
            ">",
            count >= minimum,
            ideal=float(out_of),
        )

    counts: dict[str, dict[str, list[bool]]] = {}
    for result in benchmark.method_results:
        check = checks.get(result.method_name, TwinCheck())
        who = result.method_instance_name
        best = dict(result.param_abs_error)
        closest = dict(result.truth_distribution_min_abs_error)
        has_samples = result.model_distribution_sample_count > 0
        profile_metric = result.success_metric

        factors = [f for f in (check.best_within,) if f is not None]
        if check.meets_target and profile_metric == "best_fit":
            factors.append(1.0)
        factor = min(factors) if factors else None
        grouped_best = check.min_runs_best is not None
        want_dist = check.in_distribution or (
            check.meets_target and profile_metric == "distribution"
        )
        want_either = check.meets_target and profile_metric == "best_fit_or_distribution"

        judge(f"{who}: evaluations used", float(result.n_evaluations), None, "", True)
        for name, tol in tolerances.items():
            value = best.get(name)
            if value is None:
                continue
            threshold = None if (factor is None or grouped_best) else factor * tol
            judge(
                f"{who}: best fit, distance of {name} to the truth",
                value,
                threshold,
                "<=",
                threshold is None or value <= threshold,
            )
            if has_samples and closest.get(name) is not None:
                judge(
                    f"{who}: closest sample, distance of {name} to the truth",
                    closest[name],
                    None,
                    "",
                    True,
                )
        within_tol = all(best.get(n, math.inf) <= t for n, t in tolerances.items())
        in_dist = result.truth_in_distribution is True
        bucket = counts.setdefault(result.method_name, {"best": [], "dist": []})
        bucket["best"].append(within_tol)
        bucket["dist"].append(in_dist)
        if want_dist and not check.min_runs_in_distribution:
            judge_count(
                f"{who}: a sample within tolerance of the truth on every parameter",
                int(in_dist),
                1,
                1,
            )
        if want_either:
            judge_count(
                f"{who}: best fit or a sample within tolerance of the truth",
                int(within_tol or in_dist),
                1,
                1,
            )
        if check.second_smallest_within is not None:
            ratios = sorted(best.get(n, math.inf) / t for n, t in tolerances.items())
            second = ratios[1] if len(ratios) > 1 else ratios[0]
            judge(
                f"{who}: second smallest error to tolerance ratio",
                second,
                check.second_smallest_within,
                "<=",
                second <= check.second_smallest_within,
            )

        points, objective = _samples_of(result, parameters)
        record_samples(who, parameters, points, objective, truth)

    for method, check in checks.items():
        bucket = counts.get(method)
        if bucket is None:
            failures.append(f"{method}: no result")
            continue
        if check.min_runs_best is not None:
            judge_count(
                f"{method}: runs within tolerance of the truth, out of {len(bucket['best'])}",
                sum(bucket["best"]),
                check.min_runs_best,
                len(bucket["best"]),
            )
        if check.min_runs_in_distribution is not None:
            judge_count(
                f"{method}: runs with a sample within tolerance, out of {len(bucket['dist'])}",
                sum(bucket["dist"]),
                check.min_runs_in_distribution,
                len(bucket["dist"]),
            )

    if any_meets_target:
        group = [r for r in benchmark.method_results if r.method_name in set(any_meets_target)]
        judge_count(
            "methods reaching their success target, among " + ", ".join(any_meets_target),
            sum(1 for r in group if r.meets_success_target),
            1,
            len(group),
        )

    assert not failures, "; ".join(failures)


def assert_lightweight_method_result(result: Any) -> None:
    """Assert that one lightweight pytest benchmark skipped figure generation."""
    assert result.objective_trace_figure is None
    assert result.objective_landscape_figure is None
    assert result.posterior_distribution_figure is None


NETWORK_OUTPUT = "seepage_network"
"""The network output of the stream-network twins."""

NETWORK_TWIN_TOML = """\
[workflow]
mode = "{mode}"

[simulation]
name = "{name}"

[[simulation.process]]
id = "flow"
kind = "flow"
solvers = ["{solver_id}"]

# The round trip compares the recharge read back to 1e-9: compact storage
# keeps 16 mantissa bits, about 1e-5.
[simulation.results.persistence]
field_precision = "exact"

[workspace]

{geographic}
[domain.depth_model]
kind = "constant_thickness"
thickness = "{thickness_m} m"

[flow]
flow_regime = "steady"
param_list = ["K"]

[flow.param.K.field]
kind = "homogeneous"
unit = "m/s"
value = {k_m_s!r}

[flow.ic]
kind = "top"

# A conductance of zero selects the fallback K * cell area / bed thickness,
# the one that keeps the network a function of K/R.
[flow.bc.drainage]
application_domain = "top"
kind = "drain"
value = "0.0 m2/s"

[flow.sinks_sources.recharge]
first_clim = "mean"

[data]
types = ["recharge"]
inference_mode = "warn"

[[data.recharge.sources]]
source = "synthetic"
values = [{recharge_mm_day!r}]

{solver_blocks}
[display]
enabled = false
"""
"""The project of a stream-network twin, whatever its surface."""

MODFLOW6_RUNTIME_TOML = """\
[modflow6.runtime]
mf_verbose = false
mf6_ims_complexity = "COMPLEX"
"""


def recharge_read_back_rel(solver: str) -> float:
    """Return the relative error of the recharge read back from the solver files.

    MODFLOW 6 writes double precision and returns the input to 1e-9. MODFLOW-NWT
    writes its flow terms in single precision, whose rounding is 6e-8.
    """
    from tests._helpers.tolerances import tol

    if solver == "modflow_nwt":
        return tol(
            "twin_stream_network_calibration_modflow_nwt__"
            "recharge_read_back_from_the_solver_files_rel_against_the_input"
        )
    return 1.0e-9


def require_network_twin_executables(solver: str) -> None:
    """Skip or fail as the suite does when the solver of a column is missing."""
    from tests.regression.golden_utils import assert_required_executables

    assert_required_executables(
        require_modflow=solver == "modflow_nwt",
        require_modflow6=solver.startswith("modflow6"),
        require_modpath=False,
        require_mt3dms=False,
    )


def simulated_network(
    sim: Any, *, centres_of: Callable[[np.ndarray], np.ndarray] | None = None
) -> tuple[Any, Any, np.ndarray, np.ndarray, np.ndarray, float]:
    """Build the network of a finished run with the criterion's own functions.

    The mapped network does not enter the simulated one: it only feeds the
    distances. The geometry builder still wants a non-empty mask, so every
    cell is passed. The defaults are the calibration output's, read from the
    same model it reads them from. ``centres_of`` gives the points the criterion
    samples the top at, the polygon centroids by default.
    """
    from hydromodpy.core.stream_criterion_defaults import STREAM_CRITERION_DEFAULTS
    from hydromodpy.core.stream_geometry import build_network_geometry
    from hydromodpy.core.stream_network import build_simulated_network
    from hydromodpy.spatial.mesh.model.geometry import cell_polygons

    mesh = sim.mesh
    vertices = np.asarray(mesh.vertices, dtype=float)
    connectivity = np.asarray(mesh.face_node_connectivity)
    topography = np.asarray(mesh.topography, dtype=float).reshape(-1)
    polygons = cell_polygons(vertices, connectivity)
    areas = np.asarray([polygon.area for polygon in polygons], dtype=float)
    centroids = (
        np.asarray([[p.centroid.x, p.centroid.y] for p in polygons], dtype=float)
        if centres_of is None
        else centres_of(polygons)
    )

    # Read back from the budget the solver wrote, as the results layer does.
    recharge = np.asarray(sim.field("recharge", time=-1), dtype=float).reshape(-1)
    recharge_m_s = float(np.mean(recharge / areas))

    geometry = build_network_geometry(
        topography=topography,
        face_node_connectivity=connectivity,
        vertices=vertices,
        observed=np.ones(topography.size, dtype=bool),
        cell_area_m2=areas,
        cell_centroids=centroids,
        mean_recharge_m_s=recharge_m_s,
        tau_specific_ratio=STREAM_CRITERION_DEFAULTS.tau_specific_ratio,
        diagonal_neighbors=STREAM_CRITERION_DEFAULTS.diagonal_neighbors,
    )
    release = np.asarray(sim.field("release_flux", time=-1), dtype=float).reshape(-1)
    simulated = build_simulated_network(
        release, threshold_m3_s=geometry.threshold_m3_s, metric=geometry.metric
    )
    return simulated, geometry, polygons, topography, centroids, recharge_m_s


def trial_metrics(report: Any, k_value: float) -> dict[str, float]:
    """Return the published components of the trial evaluated at ``k_value``."""
    rows = report.trials
    for _, row in rows.iterrows():
        if math.isclose(float(row["parameters"]["K"]["value"]), k_value, rel_tol=1e-12):
            return dict(row["components"])
    raise AssertionError(f"no trial at K = {k_value!r} among {len(rows)} trials.")


def best_values(session: Any) -> dict[str, float]:
    """Return the parameters of the best completed trial of a standalone experiment."""
    completed = [r for r in session.history if r.status == "completed"]
    assert completed, "calibration produced no completed trials"
    best = min(completed, key=lambda r: r.cost)
    values = best.metadata.get("values") if best.metadata else None
    assert values, "evaluator did not stash values in metadata"
    return dict(values)


def network_metric(metrics: Mapping[str, float], key: str) -> float:
    """Return one component of the network output from what a trial published."""
    return float(metrics[f"{NETWORK_OUTPUT}.{key}"])
