"""A root search on two bounds closes one root per bound, then solves their mean once.

The residuals are synthetic and monotone: a staircase per bound, positive below
its root and negative above, which never lands on zero, as the criterion does
on a catchment. The minimal (permanent) map needs more water than the maximal
one, so its root sits at a lower conductivity.
"""

from __future__ import annotations

import logging
import math
import textwrap
from pathlib import Path

import pytest

from hydromodpy.calibration.optim.adapters.bisection_adapter import (
    BisectionAdapter,
    root_search_budget,
    roots_scored,
)
from hydromodpy.calibration.optim.engine import CalibrationEngine
from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.optim.stopping import AUTO_BUDGET
from hydromodpy.calibration.preflight import _check_the_budgets
from hydromodpy.calibration.runners.cli_runner import (
    _closes_two_roots,
    _engine_kwargs,
    _roptim_verdict_extra,
    _search_outcome_extra,
    load_toml_calibration,
)
from hydromodpy.core.exceptions import OptimizerError

NANCON_BOUNDS = (1e-7, 1e-3)
ROOT_MIN = 3.0e-6
ROOT_MAX = 2.0e-4
REL_TOL = 0.01


def _space(lower: float = NANCON_BOUNDS[0], upper: float = NANCON_BOUNDS[1]) -> ParameterSpace:
    return ParameterSpace([CalibParameter(name="K", lower=lower, upper=upper, transform="log")])


def _staircase(root: float, value: float) -> float:
    steps = math.floor(math.log10(root / value) * 200.0) + 0.5
    return steps / 200.0


def _two_bounds(
    *,
    root_min: float = ROOT_MIN,
    root_max: float = ROOT_MAX,
    weights: tuple[float, float] = (0.5, 0.5),
    fail: set[int] | None = None,
    seen: list[ParamSuggestion] | None = None,
):
    """Score a trial the way a network output with two bounds publishes it."""
    w_min, w_max = weights

    def evaluate(sugg: ParamSuggestion) -> EvaluationResult:
        if seen is not None:
            seen.append(sugg)
        if fail and sugg.trial_id in fail:
            return EvaluationResult(
                trial_id=sugg.trial_id, sim_id=None, objective_value=1e9, status="failed"
            )
        value = float(sugg.values["K"])
        j_min = _staircase(root_min, value)
        j_max = _staircase(root_max, value)
        return EvaluationResult(
            trial_id=sugg.trial_id,
            sim_id=None,
            objective_value=w_min * abs(j_min) + w_max * abs(j_max),
            status="completed",
            components={
                "net.n_bounds_scored": 2.0,
                "net.weight_minimal": w_min,
                "net.weight_maximal": w_max,
                "net.J_signed_minimal": j_min,
                "net.J_signed_maximal": j_max,
                "net.J_signed_minimal_y2001": j_min,
                "net.roptim_minimal": 1.5,
                "net.roptim_maximal": 2.5,
                "net.L_ref_minimal": 50.0,
                "net.L_ref_maximal": 50.0,
                "net.Doptim_minimal": 75.0,
                "net.Doptim_maximal": 125.0,
                "net.validity_length_m_minimal": 100.0,
                "net.validity_length_m_maximal": 110.0,
                "net.validity_length_provenance_minimal": 0.0,
                "net.validity_length_provenance_maximal": 1.0,
            },
        )

    return evaluate


def _one_bound(root: float = ROOT_MAX, *, n_bounds: bool = True):
    def evaluate(sugg: ParamSuggestion) -> EvaluationResult:
        residual = _staircase(root, float(sugg.values["K"]))
        components = {"net.J_signed": residual, "net.J_signed_maximal": residual}
        if n_bounds:
            components["net.n_bounds_scored"] = 1.0
        return EvaluationResult(
            trial_id=sugg.trial_id,
            sim_id=None,
            objective_value=abs(residual),
            status="completed",
            components=components,
        )

    return evaluate


def _run(adapter: BisectionAdapter, evaluator, max_iter: int | str = AUTO_BUDGET):
    return CalibrationEngine(
        space=adapter.space, optimizer=adapter, evaluator=evaluator, max_iter=max_iter
    ).run()


def _two_root_adapter(**kwargs) -> BisectionAdapter:
    return BisectionAdapter(_space(), rel_tol=REL_TOL, roots=2, **kwargs)


# --------------------------------------------------------------------------- #
# Two roots, one sweep, one combined solve
# --------------------------------------------------------------------------- #


def test_each_bound_closes_its_own_bracket_around_its_root() -> None:
    adapter = _two_root_adapter()
    session = _run(adapter, _two_bounds())

    assert session.converged
    brackets = adapter.brackets
    for bound, root in (("minimal", ROOT_MIN), ("maximal", ROOT_MAX)):
        low, high = brackets[bound]
        assert 10.0**low <= root <= 10.0**high
        assert high - low <= math.log10(1.0 + REL_TOL) + 1e-12


def test_the_value_is_the_weighted_geometric_mean_of_the_two_roots_and_was_solved() -> None:
    seen: list[ParamSuggestion] = []
    adapter = _two_root_adapter()
    session = _run(adapter, _two_bounds(seen=seen))
    record = adapter.roots_record()
    best = session.best

    expected = 10.0 ** (
        0.5 * math.log10(record["minimal"]["k_star"])
        + 0.5 * math.log10(record["maximal"]["k_star"])
    )
    assert best is not None
    assert best.trial_id == record["combined_trial_id"] == seen[-1].trial_id
    assert seen[-1].source == "combined"
    assert float(seen[-1].values["K"]) == pytest.approx(expected, rel=1e-12)
    assert record["value"] == pytest.approx(expected, rel=1e-12)
    assert math.isclose(expected, math.sqrt(ROOT_MIN * ROOT_MAX), rel_tol=2 * REL_TOL)
    # Every number beside the value comes from that solve: above the minimal
    # root and below the maximal one, each residual has its own sign.
    assert best.components["net.J_signed_minimal"] < 0.0 < best.components["net.J_signed_maximal"]


def test_the_record_publishes_both_roots_their_spread_and_both_brackets() -> None:
    adapter = _two_root_adapter()
    _run(adapter, _two_bounds())
    record = adapter.roots_record()

    assert record["parameter"] == "K"
    assert record["closed"] is True
    assert record["minimal"]["k_star"] == pytest.approx(ROOT_MIN, rel=REL_TOL)
    assert record["maximal"]["k_star"] == pytest.approx(ROOT_MAX, rel=REL_TOL)
    assert record["delta_log10"] == pytest.approx(math.log10(ROOT_MAX / ROOT_MIN), abs=0.01)
    for bound in ("minimal", "maximal"):
        entry = record[bound]
        assert entry["closed"] is True
        assert entry["low"] <= entry["k_star"] <= entry["high"]
        assert entry["relative_width"] <= REL_TOL + 1e-9
        assert entry["weight"] == 0.5
        assert entry["trial_id"] is not None
    assert adapter.bracket is None
    assert adapter.bracket_record() is None


def test_the_weights_move_the_value_between_the_roots() -> None:
    adapter = _two_root_adapter()
    session = _run(adapter, _two_bounds(weights=(0.25, 0.75)))
    record = adapter.roots_record()

    expected = 10.0 ** (
        0.25 * math.log10(record["minimal"]["k_star"])
        + 0.75 * math.log10(record["maximal"]["k_star"])
    )
    assert session.best is not None
    assert record["value"] == pytest.approx(expected, rel=1e-12)
    assert record["minimal"]["weight"] == 0.25


def test_a_bound_weighted_zero_is_not_searched() -> None:
    # The maximal root lies far outside every expansion: searching it would refuse.
    seen: list[ParamSuggestion] = []
    adapter = BisectionAdapter(_space(), rel_tol=REL_TOL, bracket_expand=0)
    session = _run(adapter, _two_bounds(root_max=1e3, weights=(1.0, 0.0), seen=seen))

    assert session.converged
    assert adapter.roots == 1
    assert adapter.roots_record() is None
    assert all(sugg.source != "combined" for sugg in seen)
    assert float(session.best.components["net.J_signed_minimal"]) == pytest.approx(0.0, abs=0.01)
    low, high = adapter.bracket
    assert 10.0**low <= ROOT_MIN <= 10.0**high


def test_a_bound_without_a_sign_change_is_refused_by_name() -> None:
    adapter = BisectionAdapter(_space(), rel_tol=REL_TOL, roots=2, bracket_expand=1)
    with pytest.raises(OptimizerError, match="maximal bound.*J_signed_maximal"):
        _run(adapter, _two_bounds(root_max=1e3))


def test_a_combined_value_that_fails_to_solve_has_not_converged(caplog) -> None:
    budget = root_search_budget(*NANCON_BOUNDS, roots=2).nominal
    adapter = _two_root_adapter()
    session = _run(adapter, _two_bounds(fail={budget}))

    assert not session.converged
    assert adapter.roots_record()["combined_trial_id"] is None
    assert adapter.roots_record()["value"] is None
    # What stands in is a trial that solved, never the unsolved combined value.
    assert session.best is not None
    assert session.best.status == "completed"


# --------------------------------------------------------------------------- #
# The budget covers two roots
# --------------------------------------------------------------------------- #


def test_the_count_adds_the_second_root_and_the_combined_solve() -> None:
    one = root_search_budget(*NANCON_BOUNDS)
    two = root_search_budget(*NANCON_BOUNDS, roots=2)

    assert one.counts == (15, 17, 19, 21, 23)
    assert two.counts == (24, 26, 28, 30, 32)
    assert _two_root_adapter().counted_budget == two


def test_a_count_of_three_roots_is_refused() -> None:
    with pytest.raises(OptimizerError, match="one or two roots"):
        root_search_budget(*NANCON_BOUNDS, roots=3)
    with pytest.raises(OptimizerError, match="one or two roots"):
        BisectionAdapter(_space(), roots=0)


def test_two_roots_inside_the_bounds_spend_the_nominal_count() -> None:
    adapter = _two_root_adapter()
    session = _run(adapter, _two_bounds())

    assert session.converged
    assert session.extension == 0
    assert len(session.history) == adapter.counted_budget.nominal == 24


@pytest.mark.parametrize(("root_min", "root_max"), [(3e-9, 2e-4), (3e-9, 3e-2), (2e-4, 3e-1)])
def test_auto_covers_two_roots_found_after_expansions(root_min: float, root_max: float) -> None:
    adapter = _two_root_adapter()
    session = _run(adapter, _two_bounds(root_min=root_min, root_max=root_max))

    assert session.converged
    assert session.extension == 0
    assert len(session.history) <= adapter.counted_budget.worst
    record = adapter.roots_record()
    assert record["minimal"]["k_star"] == pytest.approx(root_min, rel=REL_TOL)
    assert record["maximal"]["k_star"] == pytest.approx(root_max, rel=REL_TOL)


def test_the_halvings_left_count_both_brackets_and_the_combined_solve() -> None:
    adapter = _two_root_adapter()
    evaluate = _two_bounds()
    for _ in range(7):
        adapter.tell([evaluate(sugg) for sugg in adapter.ask(1)])

    # Two brackets a sweep step wide, eight halvings each, and the combined solve.
    assert adapter.evaluations_remaining == 8 + 8 + 1


def test_a_budget_counted_for_one_root_says_so_and_still_converges(caplog) -> None:
    adapter = BisectionAdapter(_space(), rel_tol=REL_TOL)
    with caplog.at_level(logging.WARNING):
        session = _run(adapter, _two_bounds(), max_iter=40)

    assert "counted for 1 root(s) and the outputs score 2" in caplog.text
    assert session.converged
    assert adapter.roots == 2


def test_a_residual_named_by_hand_is_one_root() -> None:
    adapter = BisectionAdapter(
        _space(), rel_tol=REL_TOL, roots=2, signed_component="J_signed_maximal"
    )
    session = _run(adapter, _two_bounds())

    assert adapter.counted_budget == root_search_budget(*NANCON_BOUNDS)
    assert adapter.roots_record() is None
    low, high = adapter.bracket
    assert 10.0**low <= ROOT_MAX <= 10.0**high
    assert session.converged


# --------------------------------------------------------------------------- #
# One bound keeps today's search exactly
# --------------------------------------------------------------------------- #


def test_one_bound_asks_the_same_points_as_the_paper_search() -> None:
    today: list[ParamSuggestion] = []
    now: list[ParamSuggestion] = []
    plain = _one_bound(n_bounds=False)
    counted = _one_bound(n_bounds=True)
    first = BisectionAdapter(_space(), rel_tol=REL_TOL)
    second = BisectionAdapter(_space(), rel_tol=REL_TOL)
    CalibrationEngine(
        space=first.space,
        optimizer=first,
        evaluator=lambda sugg: (today.append(sugg), plain(sugg))[1],
        max_iter=AUTO_BUDGET,
    ).run()
    session = CalibrationEngine(
        space=second.space,
        optimizer=second,
        evaluator=lambda sugg: (now.append(sugg), counted(sugg))[1],
        max_iter=AUTO_BUDGET,
    ).run()

    assert [dict(sugg.values) for sugg in now] == [dict(sugg.values) for sugg in today]
    assert [sugg.source for sugg in now] == [sugg.source for sugg in today]
    assert len(now) == 15
    assert session.best.trial_id == first.best().trial_id
    assert second.roots_record() is None
    assert second.bracket_record() == first.bracket_record()


# --------------------------------------------------------------------------- #
# The report
# --------------------------------------------------------------------------- #


def test_the_report_publishes_the_roots_and_no_single_bracket() -> None:
    adapter = _two_root_adapter()
    session = _run(adapter, _two_bounds())

    extra = _search_outcome_extra(session)

    assert "bracket" not in extra
    assert extra["roots"] == adapter.roots_record()
    assert extra["search"]["converged"] is True
    assert extra["search"]["n_evaluations"] == 24


def test_no_interval_of_trials_is_put_around_a_value_between_two_roots() -> None:
    two = _two_root_adapter()
    one = BisectionAdapter(_space(), rel_tol=REL_TOL)

    assert _closes_two_roots(_run(two, _two_bounds())) is True
    assert _closes_two_roots(_run(one, _one_bound())) is False


class _Output:
    support = "network"
    on_roptim_violation = "warn"


def test_eq4_is_read_on_each_bound_in_the_cost() -> None:
    adapter = _two_root_adapter()
    session = _run(adapter, _two_bounds())

    extra = _roptim_verdict_extra({"net": _Output()}, session.best.components)

    verdicts = extra["roptim_verdict"]
    assert set(verdicts) == {"net_minimal", "net_maximal"}
    assert verdicts["net_minimal"]["valid"] is True
    assert verdicts["net_minimal"]["Doptim"] == 75.0
    assert verdicts["net_maximal"]["valid"] is False
    assert verdicts["net_maximal"]["value"] == 2.5
    # Each bound is read against the length its own map resolved.
    assert verdicts["net_minimal"]["validity_length_m"] == 100.0
    assert verdicts["net_maximal"]["validity_length_m"] == 110.0
    assert verdicts["net_maximal"]["provenance"] == "auto_floor"


def test_eq4_skips_a_bound_weighted_zero() -> None:
    components = dict(
        _two_bounds(weights=(1.0, 0.0))(ParamSuggestion(trial_id=1, values={"K": 1e-5})).components
    )

    verdicts = _roptim_verdict_extra({"net": _Output()}, components)["roptim_verdict"]

    assert set(verdicts) == {"net_minimal"}


# --------------------------------------------------------------------------- #
# Read off the declarations, before any solve
# --------------------------------------------------------------------------- #

_TOML = """
[calibration]
method = "bisection"
max_iter = {max_iter}

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
transform = "log"
units = "m/s"

[calibration.outputs.net]
support = "network"
stream_geometry_path = "complete.gpkg"
{minimal}
{extent}

[[calibration.objective_blocks]]
name = "network"
metric = "distance_gap"
uses_outputs = ["net"]
"""

_EXTENT = "[calibration.outputs.net.extent]"
_MINIMAL = 'minimal_stream_geometry_path = "permanent.gpkg"'


def _load(tmp_path: Path, *, max_iter: int = 20, minimal: bool = True, extent: str = _EXTENT):
    path = tmp_path / "calibration.toml"
    text = _TOML.format(max_iter=max_iter, minimal=_MINIMAL if minimal else "", extent=extent)
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    for name in ("complete.gpkg", "permanent.gpkg"):
        (tmp_path / name).write_bytes(b"")
    cfg, _raw = load_toml_calibration(path)
    return cfg


def test_two_bounds_are_counted_as_two_roots(tmp_path: Path) -> None:
    cfg = _load(tmp_path)

    assert roots_scored(cfg.outputs.values()) == 2
    assert _engine_kwargs(cfg, _space(), start_at=None)["roots"] == 2


@pytest.mark.parametrize(
    ("minimal", "extent"),
    [
        (False, _EXTENT),
        (True, ""),
        (True, _EXTENT + "\nweights = { minimal = 1.0, maximal = 0.0 }"),
    ],
)
def test_anything_short_of_two_weighted_bounds_is_one_root(
    tmp_path: Path, minimal: bool, extent: str
) -> None:
    cfg = _load(tmp_path, minimal=minimal, extent=extent)

    assert _engine_kwargs(cfg, _space(), start_at=None)["roots"] == 1


def test_the_preflight_counts_two_roots(tmp_path: Path) -> None:
    findings = _check_the_budgets(_load(tmp_path, max_iter=20))

    assert [finding.severity for finding in findings] == ["error"]
    assert "below the 24 evaluations" in findings[0].detail


def test_the_preflight_counts_one_root_without_the_minimal_map(tmp_path: Path) -> None:
    findings = _check_the_budgets(_load(tmp_path, max_iter=20, minimal=False))

    assert [finding.severity for finding in findings] == ["warning"]


_SINGLE_METRIC_TOML = """
[calibration]
method = "bisection"
max_iter = {max_iter}
variable = "net"
objective = "distance_gap"

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
transform = "log"
units = "m/s"

[calibration.outputs.net]
support = "network"
stream_geometry_path = "complete.gpkg"
minimal_stream_geometry_path = "permanent.gpkg"

[calibration.outputs.net.extent]
{phase}
"""

_SINGLE_METRIC_PHASE = """
[[calibration.phases]]
name = "steady"
parameters = ["K"]
variable = "net"
objective = "distance_gap"
max_iter = {max_iter}
"""


def _load_single_metric(tmp_path: Path, *, max_iter: int | str = 20, phase: bool = False):
    budget = f'"{max_iter}"' if isinstance(max_iter, str) else str(max_iter)
    text = _SINGLE_METRIC_TOML.format(
        max_iter=budget,
        phase=_SINGLE_METRIC_PHASE.format(max_iter=budget) if phase else "",
    )
    path = tmp_path / "calibration.toml"
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    for name in ("complete.gpkg", "permanent.gpkg"):
        (tmp_path / name).write_bytes(b"")
    cfg, _raw = load_toml_calibration(path)
    return cfg


def test_the_variable_route_counts_two_roots(tmp_path: Path) -> None:
    # The whole-file (objective, variable) pair keeps its output, so the
    # engine and the preflight count the same two roots.
    cfg = _load_single_metric(tmp_path)

    assert _engine_kwargs(cfg, _space(), start_at=None)["roots"] == 2
    findings = _check_the_budgets(cfg)
    assert [finding.severity for finding in findings] == ["error"]
    assert "below the 24 evaluations" in findings[0].detail


def test_the_preflight_counts_two_roots_on_a_single_metric_phase(tmp_path: Path) -> None:
    cfg = _load_single_metric(tmp_path, phase=True)

    findings = _check_the_budgets(cfg)
    assert [finding.severity for finding in findings] == ["error"]
    assert "below the 24 evaluations" in findings[0].detail


def test_a_single_metric_phase_on_two_bounds_is_counted_as_two_roots(tmp_path: Path) -> None:
    # The phase keeps the output its variable names, so the engine counts the
    # two roots the preflight counts.
    from hydromodpy.calibration.runners.staged_runner import _phase_config

    cfg = _load_single_metric(tmp_path, max_iter=AUTO_BUDGET, phase=True)
    phase_cfg = _phase_config(cfg, cfg.phases[0])

    assert _engine_kwargs(phase_cfg, _space(), start_at=None)["roots"] == 2
