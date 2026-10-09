"""Shared helpers for lightweight calibration validation tests."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
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
    """
    definition = benchmark.definition
    record_case(definition.case_id)
    tolerances = {str(k): float(v) for k, v in definition.parameter_abs_tolerances.items()}
    parameters = [str(name) for name in definition.truth_params]
    truth = {str(k): float(v) for k, v in definition.truth_params.items()}
    failures: list[str] = []

    def judge(label: str, value: float | None, threshold: float | None, op: str, ok: bool) -> None:
        record_metric(label, value, threshold, op=op if threshold is not None else "")
        if threshold is not None and not ok:
            failures.append(f"{label}: {value} not {op} {threshold}")

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
            judge(
                f"{who}: a sample within tolerance of the truth on every parameter",
                1.0 if in_dist else 0.0,
                1.0,
                ">=",
                in_dist,
            )
        if want_either:
            ok = within_tol or in_dist
            judge(
                f"{who}: best fit or a sample within tolerance of the truth",
                1.0 if ok else 0.0,
                1.0,
                ">=",
                ok,
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
            n = float(sum(bucket["best"]))
            judge(
                f"{method}: runs within tolerance of the truth, out of {len(bucket['best'])}",
                n,
                float(check.min_runs_best),
                ">=",
                n >= check.min_runs_best,
            )
        if check.min_runs_in_distribution is not None:
            n = float(sum(bucket["dist"]))
            judge(
                f"{method}: runs with a sample within tolerance, out of {len(bucket['dist'])}",
                n,
                float(check.min_runs_in_distribution),
                ">=",
                n >= check.min_runs_in_distribution,
            )

    if any_meets_target:
        group = [r for r in benchmark.method_results if r.method_name in set(any_meets_target)]
        n = float(sum(1 for r in group if r.meets_success_target))
        judge(
            "methods reaching their success target, among " + ", ".join(any_meets_target),
            n,
            1.0,
            ">=",
            n >= 1,
        )

    assert not failures, "; ".join(failures)


def assert_lightweight_method_result(result: Any) -> None:
    """Assert that one lightweight pytest benchmark skipped figure generation."""
    assert result.objective_trace_figure is None
    assert result.objective_landscape_figure is None
    assert result.posterior_distribution_figure is None
