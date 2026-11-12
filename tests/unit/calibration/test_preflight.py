"""Tests of `preflight`."""

from __future__ import annotations

import logging
import textwrap
import tomllib
import warnings
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import hydromodpy as hmp
from hydromodpy.calibration import (
    preflight,
    preflight_network,
    preflight_report,
    preflight_searches,
)
from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.config_network import CalibNetworkExtent
from hydromodpy.calibration.metrics.solver_extract import context_step_days
from hydromodpy.calibration.optim.adapters.bisection_adapter import BisectionAdapter
from hydromodpy.calibration.optim.adapters.grid_adapter import GridAdapter
from hydromodpy.calibration.optim.adapters.lhs_adapter import LhsAdapter
from hydromodpy.calibration.optim.engine import CalibrationEngine
from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.calibration.optim.parameters import (
    CalibParameter,
    ParameterSpace,
    apply_parameter_to_config,
)
from hydromodpy.project.trial_pipeline import fill_trial_pipeline

fill_trial_pipeline()
from hydromodpy.calibration.preflight import (
    _check_bounds_against_physics,
    _check_the_budgets,
    preflight_calibration,
)
from hydromodpy.calibration.runners import document, search, staged_report, staged_runner
from hydromodpy.calibration.runners.document import load_toml_calibration
from hydromodpy.catchment.stream_network.extent import parse_extent_duration
from hydromodpy.cli.exit_codes import EXIT_CONFIG
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.diagnostic import Diagnostic
from hydromodpy.core.exceptions import ConfigError, OptimizerError
from hydromodpy.core.time.window import nominal_step_days
from hydromodpy.display.figures.network_extent_bounds_map import extents_from_run
from hydromodpy.model.sinks_sources.recharge import FlowRechargeConfig
from hydromodpy.project.facade import Project
from hydromodpy.results.derive.stream_network.criterion_settings import network_criterion_settings
from hydromodpy.results.derive.stream_network.run_extent import (
    network_extents_from_run,
    run_step_days,
)
from tests._helpers.cli_runner import CliRunner
from tests._helpers.sealed_runs import sealed_search
from tests._helpers.transient_network_run import transient_run
from tests.unit.calibration._factories_config import (
    PROCESS,
    PROJECT_BASE,
    messages,
    preflight_of,
    run_preflight,
    sinks_project,
    soil_project,
    toml_doc,
    write_calibration,
)

# From test_a_network_estimator_names_its_network_output.py
# A network estimator on the single-metric route must name its network output.
#
# A search with no block reads only the output its ``variable`` names. A file
# with ``objective = "distance_gap"``, the default ``variable = "head"`` and a
# network output beside it loads, and the runner guards count that output as
# scored. The extractor never reads it: it takes the station route on ``head``
# and stops at the first trial. Preflight refuses it, and does not blame an
# extent table on an output the search never scores.


_PARAMETERS = """
@KLOG
"""

_NETWORK = """
[calibration.outputs.net]
support = "network"
map.complete = "{maximal}"
map.permanent = "{minimal}"
map.calibrate_on = {{ permanent = 0.5, complete = 0.5 }}
[calibration.outputs.net.model.extent]
"""


def _outputs(tmp_path: Path) -> str:
    folder = tmp_path / "data" / "hydrography"
    folder.mkdir(parents=True, exist_ok=True)
    maximal, minimal = folder / "streams.gpkg", folder / "permanent.gpkg"
    maximal.write_bytes(b"maximal")
    minimal.write_bytes(b"minimal")
    return _NETWORK.format(maximal=maximal.as_posix(), minimal=minimal.as_posix())


def _whole_file(tmp_path: Path, *, variable: str | None, regime: str = "transient") -> str:
    route = f'variable = "{variable}"\n' if variable else ""
    return (
        f'[flow]\nflow_regime = "{regime}"\n'
        '[calibration]\nmethod = "bisection"\nobjective = "distance_gap"\n'
        + route
        + _PARAMETERS
        + _outputs(tmp_path)
    )


def _one_phase(tmp_path: Path, *, variable: str) -> str:
    # The section names the estimator too, or the network output would be
    # refused at load for no criterion reading it.
    return (
        '[calibration]\nmethod = "bisection"\nobjective = "distance_gap"\n'
        + _PARAMETERS
        + _outputs(tmp_path)
        + "\n[[calibration.phases]]\n"
        'name = "k_network"\nmethod = "bisection"\nparameters = ["K"]\n'
        f'variable = "{variable}"\nobjective = "distance_gap"\n'
    )


def _refused(findings) -> list:
    return [item for item in findings if "names none this file declares" in item.detail]


def test_a_steady_run_is_not_blamed_on_an_extent_it_never_reads(tmp_path) -> None:
    doc = _whole_file(tmp_path, variable=None, regime="steady")

    findings = preflight_of(tmp_path, doc)

    assert len(_refused(findings)) == 1
    assert [item for item in findings if "extent table" in item.detail] == []


def test_a_single_metric_phase_on_a_station_variable_is_refused(tmp_path) -> None:
    findings = preflight_of(tmp_path, _one_phase(tmp_path, variable="head"))

    [refused] = _refused(findings)
    assert refused.path == "calibration.phases"
    assert refused.detail.startswith("'k_network': ")


@pytest.mark.parametrize("route", ["whole_file", "phase"])
def test_a_variable_naming_the_network_output_is_no_finding(tmp_path, route: str) -> None:
    if route == "whole_file":
        doc = _whole_file(tmp_path, variable="net")
    else:
        doc = _one_phase(tmp_path, variable="net")

    assert _refused(preflight_of(tmp_path, doc)) == []


# From test_a_path_outside_the_catalogue_warns.py
# A ``path`` outside the catalog warns, since it is the documented way out.
#
# ``hmp config targets`` lists what a project exposes, and a parameter that
# writes its own ``path`` reaches any value the configuration carries: the
# resolution lets it through and the trial writes it. The preflight refused
# every such path all the same, so ``hmp check`` refused what the
# launch accepted, and now that every launch runs the preflight it would have
# refused the launch too. It warns instead. A path that names no field of the
# configuration is still refused, naming the segment that is wrong.


_FILE = """
@GRID
max_trials = 2
method_options = {{ points_per_dim = 2 }}
[calibration.parameters.dvclose]
bounds = [1e-5, 1e-2]
path = "{path}"
"""

_OUTSIDE = "solver.modflow6.runtime.mf6_outer_dvclose"


def _outside(tmp_path: Path, path: str) -> Path:
    return write_calibration(
        tmp_path, _FILE.format(path=path), base=PROJECT_BASE + PROCESS, name="calib.toml"
    )


def test_a_value_the_configuration_carries_outside_the_catalogue_warns(tmp_path) -> None:
    (finding,) = run_preflight(_outside(tmp_path, _OUTSIDE))

    assert finding.severity == "warning"
    assert finding.path == "calibration.parameters.dvclose"
    assert _OUTSIDE in finding.detail
    assert "hmp config targets" in finding.detail


def test_the_launch_goes_on_and_says_it_once(tmp_path, prepared, caplog) -> None:
    with caplog.at_level(logging.WARNING), pytest.raises(_Prepared):
        hmp.calibrate(_outside(tmp_path, _OUTSIDE))

    said = [record for record in caplog.records if _OUTSIDE in record.getMessage()]
    assert len(said) == 1


def test_a_path_that_names_no_field_is_still_refused(tmp_path) -> None:
    (finding,) = run_preflight(_outside(tmp_path, "solver.modflow6.runtime.no_such_option"))

    assert finding.severity == "error"
    assert "no_such_option" in finding.detail


# From test_a_sweep_cut_short_by_its_budget_is_refused.py
# A grid or a Latin hypercube cut short by its budget is refused before any solve.
#
# Both engines stopped on their budget, so a sweep that ``max_trials`` cut short
# closed ``converged`` and a staged calibration froze its best point. A grid cut
# short visits only the first slice of its first parameter, and a Latin hypercube
# cut short loses the one point per stratum it is drawn for. Both count their
# design before the first solve, so the budget is judged against it, by the
# engine and by ``hmp check``, and the search converges on its last point.


def _space() -> ParameterSpace:
    return ParameterSpace(
        [
            CalibParameter(name="K", lower=1e-7, upper=1e-3, search_space="log"),
            CalibParameter(name="Sy", lower=0.01, upper=0.3),
        ]
    )


def _grid() -> GridAdapter:
    return GridAdapter(_space(), points_per_dim=3)


def _lhs() -> LhsAdapter:
    return LhsAdapter(_space(), n_samples=9, seed=1)


def _search(optimizer, max_trials: int | str, calls: list[int]) -> CalibrationEngine:
    def evaluate(sugg: ParamSuggestion) -> EvaluationResult:
        calls.append(sugg.trial_id)
        return EvaluationResult(
            trial_id=sugg.trial_id, sim_id=None, cost=float(sugg.values["Sy"]), status="completed"
        )

    return CalibrationEngine(
        space=optimizer.space, optimizer=optimizer, evaluator=evaluate, max_trials=max_trials
    )


@pytest.mark.parametrize("make", [_grid, _lhs])
def test_a_budget_below_the_design_is_refused_before_the_first_solve(make) -> None:
    calls: list[int] = []

    with pytest.raises(OptimizerError, match="max_trials = 4 is below the 9 evaluations"):
        _search(make(), 4, calls).run()

    assert calls == []


@pytest.mark.parametrize(
    ("make", "rule"), [(_grid, "every grid point"), (_lhs, "every design point")]
)
@pytest.mark.parametrize("max_trials", [9, 20, "auto"])
def test_a_budget_that_covers_the_design_converges_on_its_last_point(
    make, rule: str, max_trials: int | str
) -> None:
    calls: list[int] = []

    session = _search(make(), max_trials, calls).run()

    assert session.converged
    assert session.stopping_rule == rule
    assert len(calls) == 9


def _config(method: str, max_trials: int | str, options: dict) -> CalibrationConfig:
    return CalibrationConfig.model_validate(
        {
            "method": method,
            "max_trials": max_trials,
            "method_options": options,
            "parameters": {
                "K": {"bounds": [1e-7, 1e-3], "path": "flow.param.K.field.value"},
                "Sy": {"bounds": [0.01, 0.3], "path": "flow.param.Sy.field.value"},
            },
        }
    )


@pytest.mark.parametrize(
    ("method", "options"),
    [
        ("grid", {"points_per_dim": 3}),
        ("grid", {"points_per_dim": [3, 3]}),
        ("lhs", {"n_samples": 9}),
    ],
)
def test_the_preflight_refuses_a_budget_below_the_design(method: str, options: dict) -> None:
    findings = _check_the_budgets(_config(method, 4, options))

    assert [finding.severity for finding in findings] == ["error"]
    assert "max_trials = 4 is below the 9 evaluations" in findings[0].detail


@pytest.mark.parametrize("max_trials", [9, "auto"])
def test_the_preflight_passes_a_budget_that_covers_the_design(max_trials: int | str) -> None:
    assert _check_the_budgets(_config("lhs", max_trials, {"n_samples": 9})) == []


# From test_engine_traits.py
# An engine says what it can be handed, before the search is built.
#
# A bisection refuses a two-parameter space, refuses a parameter that is not
# searched in log10, and reads a signed residual the criterion has to publish. All
# three refusals live in its constructor, which is right and late: a staged
# calibration builds phase two's optimizer when phase two starts, after phase one
# has spent its whole solve budget on a run that was never going to finish.
#
# The engine now declares the same three facts, and preflight reads them.


_TWO_LOG_PARAMS = """
@KB
[calibration.parameters.Sy]
bounds = [1e-3, 0.35]
@NETROOT
@GAP
"""

_WORKERS_ON_A_ROOT_SEARCH = """
[calibration]
method = "bisection"
parallel = 4
batch_size = 4
@KB
@NETROOT
@GAP
"""


class TestWhatPreflightCatches:
    @pytest.mark.parametrize(
        ("doc", "said"),
        [
            pytest.param(
                '[calibration]\nmethod = "bisection"\n' + _TWO_LOG_PARAMS,
                ["bisection", "K, Sy"],
                id="a_root_search_over_two_parameters",
            ),
            pytest.param(
                """
                [calibration]
                method = "bisection"
                variable = "discharge"
                objective = "nse_log"
                @KB
                """,
                ["signed residual", "nse_log"],
                id="a_metric_with_no_residual",
            ),
            pytest.param(
                # One block publishes the residual, the other does not: every block must.
                """
                [calibration]
                method = "bisection"
                @KB
                @NETROOT
                @GAP
                [[calibration.objective_blocks]]
                name = "level"
                metric = "distance_mean"
                uses_outputs = ["net"]
                """,
                ["signed residual", "distance_mean"],
                id="a_residual_block_beside_a_metric_without_one",
            ),
            pytest.param(
                # The only search space written in this file: the field declares 'log', so
                # a linear parameter has to say so, and what the file states wins.
                """
                [calibration]
                method = "bisection"
                [calibration.parameters.K]
                bounds = [1e-7, 1e-3]
                search_space = "identity"
                @NETROOT
                @GAP
                """,
                ["search space"],
                id="a_linear_parameter",
            ),
            pytest.param(
                '[calibration]\nmethod = "gradient_descent_by_hand"\n@KB',
                ["gradient_descent_by_hand", "this installation serves"],
                id="a_method_nobody_registered",
            ),
            pytest.param(
                '[calibration]\nmethod = "lhs"\n@KB\nsampling = "normal"',
                ["lhs cannot draw", "'K'"],
                id="a_normal_sampling_the_design_cannot_stratify",
            ),
        ],
    )
    def test_a_root_search_the_engine_cannot_run_is_refused(self, tmp_path, doc, said) -> None:
        findings = preflight_of(tmp_path, doc)

        for word in said:
            assert word in messages(findings)

    @pytest.mark.parametrize(
        ("method", "options", "parallel", "said"),
        [
            pytest.param("cma_es", "", 8, "beyond 6", id="cma_es_default_population"),
            pytest.param("cma_es", "popsize = 3", 4, "beyond 3", id="cma_es_own_population"),
            pytest.param("cma_es", "popsize = 3", 3, None, id="cma_es_width_used_whole"),
            pytest.param("scipy_nelder_mead", "", 8, "beyond 4", id="nelder_mead_four_points"),
            pytest.param("scipy_nelder_mead", "", 4, None, id="nelder_mead_width_used_whole"),
            pytest.param("scipy_de", "", 20, "beyond 15", id="differential_evolution_population"),
            pytest.param("scipy_de", "popsize = 2", 5, None, id="de_population_of_five_at_least"),
            pytest.param("bisection", "", 8, None, id="root_search_no_cap"),
        ],
    )
    def test_a_width_beyond_what_the_method_can_use_is_a_warning(
        self, tmp_path, method, options, parallel, said
    ) -> None:
        doc = f'[calibration]\nmethod = "{method}"\nparallel = {parallel}\n@KB\n@NETROOT\n@GAP'
        if options:
            doc += f"\n[calibration.method_options]\n{options}"
        text = messages(preflight_of(tmp_path, doc))

        assert ("buys nothing" in text) is (said is not None)
        if said is not None:
            assert said in text and "0.5 GiB and 3.3 s to start" in text


# From test_extent_rules_are_durations.py
# The two extent rules of a network output are durations, converted by the run's timestep.
#
# ``maximal_flowing_steps`` and ``minimal_dry_steps`` counted timesteps, so the
# same file meant a day on a daily run and a month on a monthly one. Now the
# output writes ``flowing_at_least`` and ``dry_at_most`` ("30 d",
# "1 month") and the run counts its own timesteps: a flowing duration is rounded
# up to whole steps (at least one), a dry one down (at least none). A key renamed
# is refused with the new name, the doctor rewrites the file as ``N`` times the
# ``[simulation.time]`` step, and a sealed run config still reads.


DAY = nominal_step_days(1, "day")
MONTH = nominal_step_days(1, "month")


def _days(text: str) -> float:
    return parse_extent_duration(text)


# -- the file ----------------------------------------------------------------


def test_a_duration_is_read_with_its_unit() -> None:
    extent = CalibNetworkExtent(flowing_at_least="1 month", dry_at_most="0 d")

    assert (extent.flowing_at_least, extent.dry_at_most) == ("1 month", "0 d")


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("flowing_at_least", "30", "carries no unit"),
        ("flowing_at_least", 30, "is not a duration"),
        ("flowing_at_least", "0 d", "longer than zero"),
        ("dry_at_most", "-1 d", "must not be negative"),
        ("dry_at_most", "2 m", "not compatible"),
    ],
)
def test_a_duration_without_a_unit_or_out_of_range_is_refused(field, value, reason) -> None:
    with pytest.raises(ValidationError, match=reason):
        CalibNetworkExtent(**{field: value})


# -- the conversion ----------------------------------------------------------


def test_a_timestep_is_the_step_of_the_time_window_of_the_run() -> None:
    window = SimpleNamespace(step_value=2, step_unit="month")
    ctx = SimpleNamespace(setup=SimpleNamespace(time_grid=SimpleNamespace(window=window)))

    assert context_step_days(ctx) == pytest.approx(2 * MONTH)
    assert context_step_days(SimpleNamespace()) is None


# -- a stored run ------------------------------------------------------------
def _steps(extents) -> tuple[int, int]:
    return extents.maximal_flowing_steps, extents.minimal_dry_steps


def test_a_stored_monthly_run_counts_its_extents_in_its_own_timesteps() -> None:
    run = transient_run()

    assert run_step_days(run) == pytest.approx(MONTH)
    assert _steps(network_extents_from_run(run)) == (1, 1)
    assert _steps(network_extents_from_run(run, maximal_flowing_duration="5 months")) == (5, 1)
    assert _steps(network_extents_from_run(run, maximal_flowing_duration="45 d")) == (2, 1)
    assert _steps(network_extents_from_run(run, minimal_dry_duration="45 d")) == (1, 1)


def test_a_stored_run_that_sealed_no_timestep_is_refused_by_name() -> None:
    run = transient_run()
    run.config_snapshot = {"simulation": {"time": {}}}

    with pytest.raises(ValueError, match="sealed no timestep"):
        network_extents_from_run(run)


def test_a_rule_longer_than_the_year_is_refused_with_both_durations() -> None:
    with pytest.raises(ValueError, match="maximal_flowing_duration = '13 months'"):
        network_extents_from_run(transient_run(), maximal_flowing_duration="13 months")


def _sealed(extent: dict, *, step: dict | None = None) -> SimpleNamespace:
    time = {"step_value": 1, "step_unit": "month"} if step is None else step
    return SimpleNamespace(
        sim_id="sim-x",
        config_snapshot={"simulation": {"time": time}},
        dir=sealed_search(
            {
                "outputs": {
                    "net": {
                        "support": "network",
                        "observed_network": "data.hydrography",
                        "extent": extent,
                    }
                }
            }
        ),
    )


# -- a file of a pre-release -------------------------------------------------
# A count of time steps under the extent of a network output is a key only a
# pre-release of 2.0 wrote. This version refuses it with every such key and writes
# nothing.
NO_REWRITE = "This version does not rewrite the file."

OLD_FILE = """\
[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2002-12-31"
step_value = 1
step_unit = "month"

[calibration.outputs.seepage_network]
support = "network"
observed_network = "data.hydrography"

[calibration.outputs.seepage_network.extent]
maximal_flowing_steps = 2  # two months at least
minimal_dry_steps = 1
year_quorum = 1.0

[display.overrides.network_extent_bounds_map]
maximal_flowing_steps = 3

[[calibration.phases]]
name = "K"
parameters = ["K"]

[calibration.phases.overrides]
"display.overrides.network_extent_bounds_map.minimal_dry_steps" = 0
"""


# -- a sealed run ------------------------------------------------------------


# -- the figure --------------------------------------------------------------


def test_the_note_of_the_figure_says_the_duration_and_the_timesteps_it_made() -> None:
    run = transient_run()
    settings = network_criterion_settings(run)

    extents = extents_from_run(
        run, settings, maximal_flowing_duration="45 d", minimal_dry_duration="1 month"
    )

    assert (extents.maximal_flowing_duration, extents.maximal_flowing_steps) == ("45 d", 2)
    assert (extents.minimal_dry_duration, extents.minimal_dry_steps) == ("1 month", 1)


def test_the_preflight_refuses_a_duration_the_timestep_cannot_read(monkeypatch) -> None:
    config = SimpleNamespace(
        simulation=SimpleNamespace(time=SimpleNamespace(step_value=1, step_unit="day"))
    )
    extent = SimpleNamespace(flowing_at_least="2 years", dry_at_most=None)
    monkeypatch.setattr(preflight_network, "search_candidates", lambda _c: [(None, "w", [])])
    monkeypatch.setattr(preflight_network, "config_of", lambda _s, _p: config)
    monkeypatch.setattr(
        preflight_network,
        "outputs_scored_by_search",
        lambda _c, _p: {
            "net": SimpleNamespace(support="network", model=SimpleNamespace(extent=extent))
        },
    )

    findings = preflight_network.check_the_extent_durations_fit_the_timestep(object(), {})
    assert len(findings) == 1 and "exceeds" in findings[0].detail

    extent.flowing_at_least = "30 d"
    assert preflight_network.check_the_extent_durations_fit_the_timestep(object(), {}) == []


# From test_preflight.py
# Everything a calibration needs, checked before the first solve.
#
# A calibration is hours of solver time. Until now every check fired where it sat:
# a missing stream geometry when the criterion first ran, a typo in a parameter
# path at the first trial, a phase that cannot describe a runnable calibration
# when its turn came, after the phases before it had spent their whole budget.
# Each one cost the run that had already happened.
#
# Preflight runs the static checks together, before anything solves, and reports
# every problem rather than the first: a file with three mistakes takes one pass
# to fix instead of three overnight runs.


_GOOD = """
@GRID4
@KLOG
"""


_PHASES = """
@GRID
@K
@SY
[[calibration.phases]]
name = "one"
method = "grid"
parameters = ["{first}"]
[[calibration.phases]]
name = "two"
method = "grid"
parameters = ["Sy"]
depends_on = "{depends}"
"""


@pytest.mark.parametrize(
    ("doc", "said"),
    [
        pytest.param(
            "@GRID\n[calibration.parameters.Kh]\nbounds = [1e-7, 1e-3]\n"
            'path = "flow.param.Kh.field.value"',
            ["flow.param.Kh.field.value"],
            id="a_path_the_configuration_does_not_carry",
        ),
        pytest.param(
            "@GRID\n[calibration.parameters.K]\nbounds = [1e-3, 1e-7]\n"
            'path = "flow.param.K.field.value"',
            ["bounds"],
            id="bounds_the_wrong_way_round",
        ),
        pytest.param(
            "@GRID\n[calibration.parameters.Sy]\nbounds = [1e-4, 0.8]\n"
            'path = "flow.param.Sy.field.value"\nunits = "-"',
            ["Sy"],
            id="a_bound_outside_the_physical_range",
        ),
        pytest.param(
            '@GRID\n@K\n[calibration.outputs.net]\nsupport = "network"\n'
            'map.complete = "nowhere.gpkg"\n@GAP',
            ["nowhere.gpkg"],
            id="a_stream_geometry_that_is_not_there",
        ),
        pytest.param(
            # Paired with an unrelated fault: neither may crowd out the other.
            "@GRID\n[calibration.parameters.K]\nbounds = [1e-3, 1e-7]\n"
            'path = "flow.param.K.field.value"\n[calibration.outputs.net]\n'
            'support = "network"\nmap.complete = "geographic.river_network"\n@GAP',
            ["geographic.river_network", "bounds"],
            id="an_observed_network_source_the_project_does_not_carry",
        ),
        pytest.param("@GRID\n@K\n@GHOST", ["ghost"], id="a_block_using_an_output_nobody_declared"),
        pytest.param(
            _PHASES.format(first="ghost", depends="one"),
            ["ghost"],
            id="a_phase_moving_a_parameter_nobody_declared",
        ),
        pytest.param(
            _PHASES.format(first="K", depends="nowhere"),
            ["nowhere"],
            id="a_dependency_that_does_not_exist",
        ),
    ],
)
def test_a_fault_is_named(tmp_path, doc: str, said: list[str]) -> None:
    findings = preflight_of(tmp_path, doc)

    for word in said:
        assert word in messages(findings)


def test_three_mistakes_come_back_together(tmp_path) -> None:
    doc = (
        "@GRID\n[calibration.parameters.Kh]\nbounds = [1e-3, 1e-7]\n"
        'path = "flow.param.Kh.field.value"\n@GHOST'
    )

    assert len(preflight_of(tmp_path, doc)) >= 3


class TestRegimes:
    """A steady window the run cannot read is found without solving."""

    _REGIME = """
    @GRID
    @KLOG
    [[calibration.phases]]
    name = "k_steady"
    method = "grid"
    parameters = ["K"]
    regime = "steady"
    {window}
    """

    def test_a_window_given_backwards_is_one_finding_on_its_phase(self, tmp_path) -> None:
        window = 'steady_window = { start = "2000-12-31", end = "2000-01-01" }'

        findings = preflight_of(tmp_path, self._REGIME.format(window=window))

        assert len(findings) == 1
        assert findings[0].path == "calibration.phases"
        assert findings[0].detail.startswith("'k_steady': ")
        assert "not a forward window" in findings[0].detail


class TestAFileThatWillNotLoad:
    def test_a_file_without_a_calibration_section_says_so(self, tmp_path) -> None:
        path = write_calibration(tmp_path, name="plain.toml")

        findings = run_preflight(path)

        assert "calibration" in messages(findings)


def test_a_linearized_width_on_a_document_that_can_carry_one_is_not_refused(tmp_path) -> None:
    # A presence: nothing at all is wrong with this document.
    assert preflight_of(tmp_path, '@GRID4\nvariable = "gauge"\n@UNC\n@KLOG\n@GAUGE\n') == []


class TestALinearizedWidthOnAPhaseThatNamesNeitherOutputsNorBlocks:
    """A phase naming nothing reads every declared output (``_phase_config``'s

    own default), not only what some OTHER phase's block happens to read. A
    resolved, non-empty block list is not the same fact as this phase having
    named one, and only the latter narrows the outputs this phase scores.
    """

    _DOC = """
@GRID4
@UNC
@KLOG
@GAUGE
[calibration.outputs.other]
variable = "head"
support = "point"
x = 100.0
y = 0.0
[[calibration.objective_blocks]]
name = "block_other"
metric = "rmse"
uses_outputs = ["other"]
normalize_cost = true
[[calibration.phases]]
name = "p1"
method = "grid"
max_trials = 4
method_options = { points_per_dim = 2 }
parameters = ["K"]
"""

    def test_an_output_no_block_reads_still_counts_when_the_phase_names_nothing(
        self, tmp_path
    ) -> None:
        findings = preflight_of(tmp_path, self._DOC)

        assert findings == []


class TestASingleMetricPhaseAlongsideAGloballyObservedOutput:
    """The document DOES name a station -- on its global output -- while the

    single-metric phase still gets no width. ``_phase_config`` empties a
    single-metric phase's ``outputs`` unconditionally, so what the rest of the
    file declares on ``gauge`` is irrelevant to ``p1``; the message must not
    read as if the document had never named a station anywhere.

    ``p2`` scores ``b1``, which reads ``gauge`` and its declared station: it
    gets no finding, proving the document as a whole is not at fault.
    """

    _DOC = """
@GRID4
@UNC
@KLOG
@GAUGE
[[calibration.objective_blocks]]
name = "b1"
metric = "rmse"
uses_outputs = ["gauge"]
normalize_cost = true
[[calibration.phases]]
name = "p1"
method = "grid"
max_trials = 4
method_options = { points_per_dim = 2 }
parameters = ["K"]
variable = "discharge"
objective = "nse"
freeze_on_success = false
[[calibration.phases]]
name = "p2"
method = "grid"
max_trials = 4
method_options = { points_per_dim = 2 }
parameters = ["K"]
objective_blocks = ["b1"]
"""

    def test_p1_is_refused_without_claiming_the_document_never_named_a_station(
        self, tmp_path
    ) -> None:
        # Asserted on a presence, not an absence. An absence passes under the
        # mutation that matters here -- dropping the single-metric branch and
        # emitting the generic detail, which says "no output names a station"
        # on a document that names one, and which contains neither the old
        # false clause nor anything else these assertions would catch.
        findings = preflight_of(tmp_path, self._DOC)

        p1 = [
            item
            for item in findings
            if item.path == "calibration.phases" and item.detail.startswith("'p1': ")
        ]
        assert len(p1) == 1
        assert "inherits none of the calibration's outputs" in p1[0].detail
        assert "_phase_config" in p1[0].detail
        assert "schema forbids naming a station" not in p1[0].detail
        assert "cost_profile" in p1[0].detail

    def test_p2_is_not_named_because_its_block_reads_the_named_station(self, tmp_path) -> None:
        findings = preflight_of(tmp_path, self._DOC)

        assert [
            item
            for item in findings
            if item.path == "calibration.phases" and item.detail.startswith("'p2': ")
        ] == []


class TestTheNetworkCriterionIsNotAskedToPickARidge:
    """A network-only objective that moves two parameters returns one point of a ridge."""

    _TWO_PARAMS = """
    @GRID
    @K
    @SY
    @NET
    @GAP
    """

    @pytest.mark.parametrize(
        "doc",
        [
            pytest.param("@GRID\n@K\n@NET\n@GAP", id="one_parameter_on_a_network_only_objective"),
            pytest.param(
                """
                @GRID
                @K
                @SY
                @NET
                @GAUGE
                [[calibration.objective_blocks]]
                name = "gap"
                metric = "distance_gap"
                uses_outputs = ["net", "gauge"]
                """,
                id="two_parameters_on_a_mixed_objective",
            ),
            pytest.param(
                """
                @GRID
                @K
                @SY
                @NET
                @GAP
                [[calibration.phases]]
                name = "one"
                method = "grid"
                parameters = ["K"]
                objective_blocks = ["gap"]
                """,
                id="a_phase_that_freezes_down_to_one_parameter",
            ),
        ],
    )
    def test_a_well_posed_search_is_not_warned(self, tmp_path, doc: str) -> None:
        assert "ridge" not in messages(preflight_of(tmp_path, doc))


_MEAN = """
[[calibration.objective_blocks]]
name = "mean"
metric = "distance_mean"
uses_outputs = ["net"]
"""
_ON_A_GAUGE = "@GAUGE\n" + _MEAN.replace("mean", "q").replace('"net"', '"gauge"').replace(
    "distance_q", "rmse"
)
_TRADING = "trading excess"
_TWO_METHODS = "depend on the method"


_RIDGE = "form a ridge"
_FACTOR = """
[calibration.parameters."recharge.factor"]
bounds = [0.5, 2.0]
path = "flow.sinks_sources.recharge.factor"
"""


def _factor_beside(regime: str, moved: str, scored: str = "@NETROOT\n@GAP") -> str:
    head = f'[flow]\nflow_regime = "{regime}"\n[flow.sinks_sources.recharge]\nvalues = 1.0\n'
    return f"{head}@GRID\n{moved}{_FACTOR}{scored}\n"


@pytest.mark.parametrize(
    ("project", "values", "said"),
    [
        (soil_project(), False, "there is no rate to multiply"),
        (sinks_project(recharge=FlowRechargeConfig()), False, "there is no rate to multiply"),
        (sinks_project(recharge=FlowRechargeConfig(values=1.0)), True, "an exact ridge"),
        (sinks_project(recharge=FlowRechargeConfig(values=1.0)), False, None),
    ],
)
def test_the_recharge_factor_needs_a_rate_that_nothing_else_moves(project, values, said) -> None:
    parameters = {"recharge.factor": {"path": "flow.sinks_sources.recharge.factor"}}
    if values:
        parameters["recharge.values"] = {"path": "flow.sinks_sources.recharge.values"}
    calibration = CalibrationConfig.model_validate({"parameters": parameters})

    findings = preflight._check_parameters(project, calibration)

    assert [item.severity for item in findings] == (["error"] if said else [])
    assert said is None or said in findings[0].detail


def _two_bounds(tmp_path: Path, method: str, moved: str, weights: str = "0.5") -> str:
    return (
        f'[calibration]\nmethod = "{method}"\nobjective = "distance_gap"\nvariable = "net"\n'
        + moved
        + _outputs(tmp_path).replace("permanent = 0.5", f"permanent = {weights}")
    )


@pytest.mark.parametrize(
    ("doc", "severity", "said"),
    [
        ("@GRID\n@K\n@SY\n@NET\n@GAP", "warning", _TRADING),
        (f"@GRID\n@K\n@NET\n@GAP\n{_MEAN}", "warning", _TRADING),
        ("@GRID\n@K\n@NET\n@GAP", None, _TRADING),
        (f"@GRID\n@K\n@SY\n@NET\n{_MEAN}", None, _TRADING),
        (lambda p: _two_bounds(p, "scipy_nelder_mead", "@KLOG"), "error", _TWO_METHODS),
        (lambda p: _two_bounds(p, "optuna", "@KLOG\n@SY"), None, _TWO_METHODS),
        (lambda p: _two_bounds(p, "scipy_nelder_mead", "@KLOG", "0.0"), None, _TWO_METHODS),
        (lambda p: _two_bounds(p, "bisection", "@KLOG"), None, _TWO_METHODS),
        (
            lambda p: _two_bounds(p, "scipy_nelder_mead", "@KLOG").replace(
                'objective = "distance_gap"', 'objective = "distance_mean"'
            ),
            None,
            _TWO_METHODS,
        ),
        (_factor_beside("steady", "@K\n"), "error", _RIDGE),
        (_factor_beside("transient", "@K\n"), "warning", _RIDGE),
        (_factor_beside("steady", ""), None, _RIDGE),
        (_factor_beside("steady", "@K\n", "@GAUGE\n@NETROOT\n@GAP"), None, _RIDGE),
    ],
)
def test_what_a_search_of_the_network_may_not_do(tmp_path, doc, severity, said) -> None:
    findings = preflight_of(tmp_path, doc(tmp_path) if callable(doc) else doc)

    named = [finding.severity for finding in findings if said in finding.detail]
    assert named == ([severity] if severity else [])


class TestTheNetworkSearchCanTrustItsReleasePackages:
    """SFR and LAK build their own conductance, never derived from K."""

    _SFR = """
    [flow.sinks_sources.sfr.net]
    @GRID
    @K
    @NET
    @GAP
    """

    def test_an_active_sfr_moving_k_is_named(self, tmp_path) -> None:
        findings = preflight_of(tmp_path, self._SFR)

        named = [item for item in findings if "SFR" in item.detail]
        assert len(named) == 1
        assert named[0].severity == "error"
        assert named[0].path == "calibration"
        assert "future work" in named[0].detail

    def test_an_active_lake_moving_k_is_named(self, tmp_path) -> None:
        doc = self._SFR.replace("sfr.net]", "lakes.lac0]\ninitial_stage = 1.0\nbedleak = 0.1")

        assert "LAK" in messages(preflight_of(tmp_path, doc))


_GAUGED = """
@GRID4
@K
[calibration.outputs.hydrograph]
support = "point"
variable = "discharge"
observes = "GAUGE"
[[calibration.objective_blocks]]
name = "hydrograph"
metric = "nse"
uses_outputs = ["hydrograph"]
"""


class TestTheObservedStationIsLoaded:
    def test_a_station_no_source_lists_is_named(self, tmp_path) -> None:
        doc = (
            """
            [data]
            types = ["hydrometry"]

            [[data.hydrometry.sources]]
            source = "file"
            path = "inputs/hydrometry"
            station_ids = ["OTHER"]
            """
            + _GAUGED
        )
        findings = preflight_of(tmp_path, doc)

        named = [item for item in findings if "GAUGE" in item.detail]
        assert len(named) == 1
        assert named[0].path == "calibration.outputs.hydrograph"
        assert "Listed: OTHER" in named[0].detail


class TestTheWindowBoundsHoldsADateOfTheRun:
    def test_a_window_after_the_run_is_named(self, tmp_path) -> None:
        doc = _GAUGED + '\n[calibration.window]\nstart = "2010-01-01"\n'
        findings = preflight_of(tmp_path, doc)

        named = [item for item in findings if "holds no date of the run" in item.detail]
        assert len(named) == 1
        assert named[0].severity == "error"
        assert "2010-01-01" in named[0].detail


class TestASamplerScoredOnAnotherMetricThanItsLikelihood:
    def _doc(self, metric: str) -> str:
        return f"""
        [calibration]
        method = "da_mh_gp"

        [calibration.parameters.K]
        bounds = [1e-7, 1e-3]
        path = "flow.param.K.field.value"

        [calibration.outputs.hydrograph]
        support = "point"
        variable = "discharge"
        observes = "GAUGE"

        [[calibration.objective_blocks]]
        name = "hydrograph"
        metric = "{metric}"
        uses_outputs = ["hydrograph"]
        """

    def test_an_efficiency_score_is_warned(self, tmp_path) -> None:
        findings = preflight_of(tmp_path, self._doc("nse"))

        named = [item for item in findings if "reads its cost as rmse" in item.detail]
        assert len(named) == 1
        assert named[0].severity == "warning"


# From test_scale_bounds_are_factors.py
# The bounds of ``mode = "scale"`` are factors, faced with nothing physical.
#
# A scale multiplies the base value of the file, so ``[0.5, 2]`` on a specific
# yield says "half to twice". The bounds were faced with the physical ceiling of
# the property as if they were its values, and ``Sy`` scaled by ``[0.5, 2]`` was
# refused, "upper bound 2.0 outside [0.0001, 0.5]", while the product the run
# writes is checked anyway.


def _space__scale_bounds(mode: str) -> ParameterSpace:
    return ParameterSpace.from_toml_mapping(
        {"Sy": {"bounds": [0.5, 2.0], "mode": mode, "path": "flow.sy"}}
    )


def test_a_scale_of_half_to_twice_is_accepted() -> None:
    (parameter,) = _space__scale_bounds("scale").parameters

    assert (parameter.lower, parameter.upper, parameter.mode) == (0.5, 2.0, "scale")


def test_the_same_bounds_as_values_are_still_refused() -> None:
    with pytest.raises(ValueError, match="upper bound 2.0"):
        _space__scale_bounds("replace")


def test_the_product_is_still_faced_with_the_ceiling() -> None:
    (parameter,) = _space__scale_bounds("scale").parameters
    cfg = SimpleNamespace(flow=SimpleNamespace(sy=0.3))

    apply_parameter_to_config(cfg, parameter, 1.5)
    assert cfg.flow.sy == pytest.approx(0.45)
    with pytest.raises(ValueError, match="candidate"):
        apply_parameter_to_config(cfg, parameter, 2.0)


def test_the_check_says_nothing_of_a_scale() -> None:
    decl = SimpleNamespace(mode="scale", units=None, search_space="identity")

    assert _check_bounds_against_physics("calibration.parameters.Sy", "Sy", decl, [0.5, 2.0]) == []


PROJECT__scale_bounds = """\
[site]
name = "p"

[geographic]
crs_project = "EPSG:2154"

[geographic.catchment]
kind = "from_outlet_coord"
x_outlet = 389285.9
y_outlet = 6816518.7
snap_dist = "150 m"
buff_area = "10%"

[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2002-12-31"
step_value = 1
step_unit = "month"

[flow]
param_list = ["K", "Sy"]

[flow.param.K.field]
kind = "homogeneous"
unit = "m/s"
value = 5e-5

[flow.param.Sy.field]
kind = "homogeneous"
unit = "-"
value = 0.05

[workflow]
mode = "calibration"

[calibration.parameters.Sy]
bounds = [0.5, 2.0]
mode = "scale"
"""


def test_a_scale_on_a_catalogue_name_loads(tmp_path) -> None:
    (tmp_path / "data" / "dem").mkdir(parents=True)
    (tmp_path / "data" / "dem" / "DEM.tif").write_bytes(b"x")
    project = tmp_path / "projects" / "p"
    project.mkdir(parents=True)
    (project / "project.toml").write_text(PROJECT__scale_bounds, encoding="utf-8")

    cfg = HydroModPyConfig.from_toml(project / "project.toml")

    assert cfg.calibration.parameters["Sy"].bounds == [0.5, 2.0]


# From test_the_precision_reaches_the_stages.py
# The precision has to travel from the TOML to the engine that stops on it.
#
# Two routes reach an optimizer, the protocol writing stages and a file writing
# them by hand, and both funnel through one build site. What is gated here is the
# journey: a precision declared on a protocol stage has to arrive on the phase, and
# one that no engine can honor has to be refused before the first solve rather
# than when that phase finally starts.


_HEAD = """
[workspace]
name = "precision_probe"

[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2000-12-31"
step_value = 1
step_unit = "day"

[[data.hydrometry.sources]]
station_ids = ["G1"]
"""

_PARAMETERS__precision_reaches = """
[calibration.parameters.K]
bounds = [1e-8, 1e-2]
search_space = "log"
units = "m/s"
[calibration.parameters.Sy]
bounds = [1e-4, 0.5]
search_space = "log"
units = "-"
"""

_NETWORK_OUTPUT = """
[calibration.outputs.seepage_network]
support = "network"
map.complete = "network.gpkg"
"""


def _loaded(tmp_path: Path, calibration: str, *, network: bool = True):
    path = tmp_path / "precision.toml"
    tail = _PARAMETERS__precision_reaches + (_NETWORK_OUTPUT if network else "")
    path.write_text(toml_doc(_HEAD + calibration + tail), encoding="utf-8")
    (tmp_path / "network.gpkg").write_bytes(b"")
    return load_toml_calibration(path)


@pytest.mark.parametrize(
    ("doc", "said"),
    [
        (
            """
            @GRID
            [[calibration.phases]]
            name = "sweep_k"
            method = "grid"
            parameters = ["K"]
            precision = 0.01
            variable = "discharge"
            objective = "nse"
            """,
            "stops on its evaluation budget",
        ),
        (
            """
            @GRID
            [[calibration.phases]]
            name = "steady_k"
            method = "scipy_nelder_mead"
            parameters = ["K"]
            precision = 0.01
            variable = "discharge"
            objective = "nse"
            [calibration.phases.method_options]
            xatol = 0.3
            """,
            "both set the stopping rule",
        ),
    ],
    ids=["an_engine_cannot_stop_on_it", "said_twice"],
)
def test_a_precision_that_cannot_be_kept_is_refused_before_the_first_solve(
    tmp_path: Path, doc: str, said: str
) -> None:
    cfg, _raw = _loaded(tmp_path, doc, network=False)
    findings = _findings_for(cfg, tmp_path)
    assert any(said in finding.detail for finding in findings)


def _findings_for(calibration, tmp_path: Path):
    class _Config:
        pass

    config = _Config()
    config.calibration = calibration
    return preflight_calibration(config, source=tmp_path / "precision.toml")


def test_a_precision_a_nelder_mead_stage_can_honour_passes_the_preflight(tmp_path: Path) -> None:
    cfg, _raw = _loaded(
        tmp_path,
        """
        [calibration.protocol]
        name = "matching_hydrographic_network"
        steady_method = "scipy_nelder_mead"
        steady_precision = 0.02
        """,
    )
    findings = _findings_for(cfg, tmp_path)
    assert not [finding for finding in findings if "precision" in finding.detail]


@pytest.mark.parametrize("precision", [0.0, -0.1])
def test_a_precision_that_is_not_positive_is_refused_at_load(
    tmp_path: Path, precision: float
) -> None:
    with pytest.raises(ConfigError, match="greater than 0"):
        _loaded(
            tmp_path,
            f"""
            [calibration.protocol]
            name = "matching_hydrographic_network"
            steady_precision = {precision}
            """,
        )


# From test_the_preflight_runs_at_every_launch.py
# The preflight runs at the start of every launch, on the document the launch runs.
#
# ``hmp check`` was the only caller of the preflight. ``hmp calibrate``,
# ``hmp run``, ``--dry-run`` and the API went straight to the preparation of the
# model, so a file the check refused was launched anyway, and refused only when
# the faulty part was reached, sometimes after hours of solves. Every launch now
# passes one gate first, on the effective document (``--set``, ``--overlay`` and
# ``HMP_SET_*`` written in, the protocol expanded) and phase by phase, with the
# overrides of each phase. Its errors stop the launch on the config code before
# anything is prepared, its warnings print once.


_REPO = Path(__file__).resolve().parents[3]
_EXAMPLE_21 = _REPO / "examples/projects/21_nancon_network_calibration/auto_sfr_drn.toml"

_PARAMETERS__preflight_runs = """
@GRID4
@KLOG
"""

# A block reading an output nobody declared: the file loads, the preflight refuses it.
_GHOST_BLOCK = """
@GHOST
"""

_PHASE = """
[[calibration.phases]]
name = "only"
method = "grid"
parameters = ["K"]
method_options = { points_per_dim = 2 }
max_trials = 4
"""

# A network output whose geometry is there: the file passes the preflight.
_NETWORK__preflight_runs = """
[calibration.parameters.Sy]
bounds = [1e-3, 0.3]
path = "flow.param.Sy.field.value"
units = "-"
[calibration.outputs.net]
support = "network"
map.complete = "here.gpkg"
@GAP
"""


class _Prepared(RuntimeError):
    """Raised in place of the preparation of the model: the launch got past the gate."""


@pytest.fixture
def prepared(monkeypatch) -> list[str]:
    """Record every preparation the launch reaches, and stop there."""
    reached: list[str] = []

    def _prepare(cfg_path, **_kwargs):
        reached.append(Path(cfg_path).name)
        raise _Prepared("the launch reached the preparation of the model")

    for module in (search, staged_runner):
        monkeypatch.setattr(module, "prepare_trials", _prepare)
    return reached


def _write__preflight_runs(tmp_path: Path, *sections: str, name: str = "calib.toml") -> Path:
    path = write_calibration(tmp_path, *sections, base=PROJECT_BASE + PROCESS, name=name)
    (tmp_path / "here.gpkg").write_text("", encoding="utf-8")
    return path


def _refused__preflight_runs(tmp_path: Path, *, phased: bool = False) -> Path:
    return _write__preflight_runs(
        tmp_path, _PARAMETERS__preflight_runs, _GHOST_BLOCK, *((_PHASE,) if phased else ())
    )


class TestEveryLaunchPathRunsIt:
    """Each launch refuses the ghost block before the model is prepared."""

    @pytest.mark.parametrize("phased", [False, True], ids=["one_search", "phases"])
    def test_hmp_calibrate_dry_run(self, tmp_path, prepared, phased: bool) -> None:
        result = CliRunner().invoke(
            ["calibrate", str(_refused__preflight_runs(tmp_path, phased=phased)), "--dry-run"]
        )

        assert result.exit_code == EXIT_CONFIG, result.output
        assert "ghost" in result.stderr
        assert "session:" not in result.stderr

    def test_hmp_run_in_calibration_mode(self, tmp_path, prepared) -> None:
        result = CliRunner().invoke(["run", str(_refused__preflight_runs(tmp_path))])

        assert result.exit_code == EXIT_CONFIG, result.output
        assert "ghost" in result.stderr
        assert prepared == []

    def test_hmp_run_dry_run_in_calibration_mode(self, tmp_path, prepared) -> None:
        result = CliRunner().invoke(["run", str(_refused__preflight_runs(tmp_path)), "--dry-run"])

        assert result.exit_code == EXIT_CONFIG, result.output
        assert "ghost" in result.stderr

    def test_project_calibrate_on_a_file(self, tmp_path, prepared) -> None:
        path = _refused__preflight_runs(tmp_path)
        with Project(path, headless=True) as project, pytest.raises(ConfigError, match="ghost"):
            project.calibrate(config_path=path)
        assert prepared == []

    def test_project_calibrate_on_its_own_configuration(self, tmp_path, prepared) -> None:
        config = HydroModPyConfig.from_toml(_refused__preflight_runs(tmp_path))

        with pytest.raises(ConfigError, match="ghost"):
            hmp.calibrate(config)
        assert prepared == []

    def test_project_calibrate_in_python_mode(self, tmp_path, prepared) -> None:
        with Project(_write__preflight_runs(tmp_path), headless=True) as project:
            with pytest.raises(ConfigError, match="ghost"):
                project.calibrate(
                    parameters={"K": {"bounds": [1e-7, 1e-3]}},
                    objective_blocks=[{"name": "gap", "metric": "rmse", "uses_outputs": ["ghost"]}],
                )
        assert prepared == []

    def test_a_file_that_passes_reaches_the_preparation(self, tmp_path, prepared) -> None:
        with pytest.raises(_Prepared):
            hmp.calibrate(
                _write__preflight_runs(
                    tmp_path, _PARAMETERS__preflight_runs, _NETWORK__preflight_runs
                )
            )
        assert prepared == ["calib.toml"]


class TestTheEffectiveDocument:
    """What the launch runs is what is checked: overrides and overlays included."""

    def test_a_set_that_breaks_the_file_is_refused(self, tmp_path, prepared) -> None:
        path = _write__preflight_runs(
            tmp_path, _PARAMETERS__preflight_runs, _NETWORK__preflight_runs
        )

        result = CliRunner().invoke(
            [
                "calibrate",
                str(path),
                "--set",
                'calibration.outputs.net.map.complete="nowhere.gpkg"',
            ]
        )

        assert result.exit_code == EXIT_CONFIG, result.output
        assert "nowhere.gpkg" in result.stderr
        assert prepared == []

    def test_an_environment_override_is_checked(self, tmp_path, prepared, monkeypatch) -> None:
        path = _write__preflight_runs(
            tmp_path, _PARAMETERS__preflight_runs, _NETWORK__preflight_runs
        )
        monkeypatch.setenv("HMP_SET_calibration__outputs__net__map__complete", "nowhere.gpkg")

        result = CliRunner().invoke(["calibrate", str(path), "--dry-run"])

        assert result.exit_code == EXIT_CONFIG, result.output
        assert "nowhere.gpkg" in result.stderr

    def test_an_overlay_is_checked(self, tmp_path, prepared) -> None:
        path = _write__preflight_runs(
            tmp_path, _PARAMETERS__preflight_runs, _NETWORK__preflight_runs
        )
        overlay = tmp_path / "broken.toml"
        overlay.write_text(
            '[calibration.outputs.net]\nmap.complete = "nowhere.gpkg"\n', encoding="utf-8"
        )

        result = CliRunner().invoke(["run", str(path), "--overlay", str(overlay)])

        assert result.exit_code == EXIT_CONFIG, result.output
        assert "nowhere.gpkg" in result.stderr
        assert prepared == []


@pytest.fixture(scope="module")
def config() -> HydroModPyConfig:
    """Example 21 as the run loads it."""
    if not _EXAMPLE_21.is_file():
        pytest.skip("example 21 is not in this checkout")
    with warnings.catch_warnings():
        # A renamed key it still spells the old way is not what this file tests.
        warnings.simplefilter("ignore")
        return HydroModPyConfig.from_toml(_EXAMPLE_21)


class TestExample21:
    """Its first phase turns the SFR reaches off in its own overrides.

    The preflight read the project's base ``flow.active_bc``, where SFR is on,
    and refused the K-moving network search of that phase, which runs without
    it. Each phase is now checked with its overrides written in.
    """

    def test_it_is_not_refused(self, config) -> None:
        errors = [
            finding
            for finding in preflight_calibration(config, source=_EXAMPLE_21)
            if finding.severity == "error"
        ]

        assert errors == []


# -- the published method a file runs, as the check says it ------------------
_PROTOCOL_SECTION = """
[calibration]
protocol = {{ name = "matching_hydrographic_network"{options} }}
@KLOG
@SY
[calibration.outputs.seepage_network]
support = "network"
map.complete = "streams.gpkg"
"""


def _protocol_cfg(tmp_path: Path, options: str = ""):
    base = PROJECT_BASE.replace("2000-12-31", "2002-12-31")
    path = write_calibration(tmp_path, _PROTOCOL_SECTION.format(options=options), base=base)
    return HydroModPyConfig.from_toml(path)


def test_the_lines_of_a_method_name_its_departures_and_the_options_moved_off_its_recipe(
    tmp_path: Path,
) -> None:
    window = 'window = { start = "2001-01-01", end = "2002-12-31" }'
    cfg = _protocol_cfg(tmp_path, f", steady_max_trials = 33, {window}")

    normal, verbose = preflight_report.protocol_lines(cfg)

    assert (
        normal[0]
        == "protocol: matching_hydrographic_network@1.3 - Matching the hydrographic network"
    )
    assert "  option away from the recipe: steady_max_trials = 33 (recipe: 'auto')" in normal
    assert normal[-2].startswith(
        "  always differs from the paper on: outlet_sealed_into_d_so_target"
    )
    assert (
        "  option written as the recipe runs it: window = {'start': '2001-01-01', 'end': '2002-12-31'}"
        in verbose
    )
    assert "  differs from the paper on map.drawn_by" in {line.split(":")[0] for line in normal}
    assert {
        "  stage 1",
        "  cite",
        "  reads the paper on map.position_accuracy",
        "  as the paper on model.weighting",
        "  always differs from the paper on d_os_support",
    } <= {line.split(":")[0] for line in verbose}


@pytest.mark.parametrize(
    ("backend", "named"),
    [
        ("boussinesq", True),
        (SimpleNamespace(value="boussinesq"), True),
        ("modflow6", False),
        (None, False),
    ],
)
def test_a_backend_the_method_was_never_run_on_is_named(tmp_path: Path, backend, named) -> None:
    cfg = _protocol_cfg(tmp_path)
    shown = SimpleNamespace(
        calibration=cfg.calibration,
        geographic=cfg.geographic,
        simulation=cfg.simulation,
        solver=SimpleNamespace(backend_name=backend),
    )

    normal, _ = preflight_report.protocol_lines(shown)

    # The backend says why itself: Boussinesq serves no per-cell saturation excess.
    said = [line for line in normal if line.startswith("  on boussinesq: unsupported - ")]
    assert bool(said) is named
    assert all("saturation excess" in line for line in said)


@pytest.mark.parametrize(
    ("where", "path", "detail"),
    [
        ("[calibration]", "calibration", "bad"),
        ("[calibration.outputs.net]", "calibration.outputs.net", "bad"),
        ("[[calibration.phases]] 'k'", "calibration.phases", "'k': bad"),
        ("[[calibration.phases]] 'k' overrides", "calibration.phases", "'k' overrides: bad"),
        ("[calibration.parameters.K] bounds", "calibration.parameters.K", "bounds: bad"),
        ("calib.toml", "calib.toml", "bad"),
    ],
)
def test_a_finding_is_a_diagnostic_of_the_calibration_preflight(
    where: str, path: str, detail: str
) -> None:
    found = preflight_report.finding("error", where, "bad")

    assert found == Diagnostic(
        path=path, code="calibration_preflight", severity="error", detail=detail
    )


def test_a_finding_prints_as_one_line() -> None:
    assert (
        preflight_report.finding("error", "[calibration]", "bad").line()
        == "ERROR   calibration: bad"
    )


def test_the_launch_says_once_what_it_warns_of_and_where_it_leaves_the_paper(
    tmp_path: Path, monkeypatch, caplog
) -> None:
    cfg = _protocol_cfg(tmp_path)
    warning = preflight_report.finding("warning", "[calibration]", "twice written")
    monkeypatch.setattr(preflight, "preflight_calibration", lambda *_a, **_k: [warning, warning])

    with caplog.at_level(logging.INFO):
        preflight.refuse_what_the_preflight_refuses(cfg, source=tmp_path / "calib.toml")

    assert caplog.text.count("calibration: twice written") == 1
    assert "protocol: matching_hydrographic_network@1.3" in caplog.text


@pytest.mark.parametrize(
    ("value", "shown"), [(None, "unset"), (3, "3"), ("auto", "'auto'")], ids=str
)
def test_an_option_is_shown_as_the_file_wrote_it(value: object, shown: str) -> None:
    assert preflight_report._rendered(value) == shown


def test_a_file_without_calibration_compares_nothing_and_a_search_without_table_adds_no_block(
    monkeypatch,
) -> None:
    assert preflight_report.comparison_lines(SimpleNamespace(), Path("calib.toml")) == []
    monkeypatch.setattr(document, "resolve_stream_geometry_paths", lambda *_a: None)
    monkeypatch.setattr(staged_report, "objective_comparison_table", lambda *_a: [])

    lines = preflight_report.comparison_lines(
        SimpleNamespace(calibration=SimpleNamespace(phases=None)), Path("calib.toml")
    )

    assert lines == ["[metrics] window: unset, the run carries no score"]


@pytest.mark.parametrize(
    ("config", "path", "said"),
    [
        ({"a": {"b": 1}}, "a.b", None),
        ({"a": {}}, "a.b", None),
        ({"a": {"x": 1}}, "a.c.d", "no 'c' under a, which holds x"),
    ],
)
def test_a_path_is_walked_through_mappings_and_a_last_key_may_be_new(config, path, said) -> None:
    assert preflight._no_field_on_the_way(config, path) == said


@pytest.mark.parametrize(
    ("name", "decl", "bounds", "said"),
    [
        ("Sy", {"units": "-"}, [-1.0, 0.5], "lower bound -1.0: specific yield"),
        (
            "foo",
            {"units": None, "search_space": "log"},
            [0.0, 1.0],
            "needs a lower bound above zero",
        ),
        ("foo", {"units": None, "mode": "scale"}, [0.0, 1.0], None),
    ],
)
def test_bounds_are_faced_with_the_physics_and_the_log_space(name, decl, bounds, said) -> None:
    declared = SimpleNamespace(**{"mode": "replace", "search_space": "identity", **decl})

    found = preflight._check_bounds_against_physics("w", name, declared, bounds)

    assert (found[0].detail if found else None) is None if said is None else said in found[0].detail


def test_a_regime_read_from_a_file_that_cannot_be_read_is_refused_by_name(tmp_path: Path) -> None:
    phase = SimpleNamespace(name="k", regime="steady")
    calibration = SimpleNamespace(phases=[phase])

    found = preflight._check_the_regimes(calibration, SimpleNamespace(), tmp_path / "gone.toml")

    assert [(item.path, "gone.toml, which cannot be read" in item.detail) for item in found] == [
        ("simulation.time", True)
    ]


def test_a_phase_regime_that_cannot_be_read_leaves_its_search_on_the_file_as_it_is(
    tmp_path: Path,
) -> None:
    phase = SimpleNamespace(name="k", regime="steady", steady_window=None, overrides=None)
    config = SimpleNamespace()

    searched, found = preflight._search_configs(
        config, SimpleNamespace(phases=[phase]), tmp_path / "gone.toml"
    )

    assert (searched, found) == ({"k": config}, [])


def test_a_configuration_held_in_memory_is_its_own_raw_document(tmp_path: Path) -> None:
    held = SimpleNamespace(model_dump=lambda **_kw: {"flow": {}})

    assert preflight_searches.raw_document(held, tmp_path / "gone.toml") == {"flow": {}}


@pytest.mark.parametrize(
    ("doc", "said"),
    [
        (
            """
    @GRID4
    @KLOG
    [calibration.outputs.o]
    variable = "head"
    support = "point"
    x = 100.0
    y = 0.0
    [[calibration.objective_blocks]]
    name = "b"
    metric = "rmse"
    uses_outputs = ["o"]
    normalize_cost = true
    [[calibration.objective_blocks]]
    name = "b"
    metric = "nse"
    uses_outputs = ["o"]
    """,
            "two blocks share this name.",
        ),
        (
            '@GRID4\n@KLOG\n[calibration.uncertainty]\nmethod = "multistart"\nrestarts = 3',
            "returns the same answer every time",
        ),
    ],
    ids=["two_blocks_of_one_name", "restarts_of_a_search_they_cannot_move"],
)
def test_a_declaration_that_cannot_run_as_written_is_refused(
    tmp_path: Path, doc: str, said: str
) -> None:
    assert said in messages(preflight_of(tmp_path, doc))


_UNOBSERVED = TestALinearizedWidthOnAPhaseThatNamesNeitherOutputsNorBlocks._DOC.replace(
    "@GAUGE\n", ""
)


@pytest.mark.parametrize(
    "doc",
    [_UNOBSERVED.split("[[calibration.phases]]")[0], _UNOBSERVED + 'outputs = ["other"]'],
    ids=["section", "phase_outputs"],
)
def test_a_width_taken_from_outputs_no_station_names_is_refused(tmp_path: Path, doc: str) -> None:
    assert "no output names a station to be compared" in messages(preflight_of(tmp_path, doc))


def test_a_budget_the_counting_cannot_read_is_left_to_the_checks_that_refuse_its_inputs(
    monkeypatch,
) -> None:
    def _unreadable(*_args):
        raise ValueError("bounds")

    monkeypatch.setattr(preflight, "_counted_budget", _unreadable)

    assert preflight._check_the_budgets(_config("grid", 2, {})) == []


def test_a_root_search_on_a_parameter_without_two_bounds_has_no_nominal_count() -> None:
    calibration = SimpleNamespace(parameters={})

    assert preflight._counted_budget(calibration, None, "bisection", ["K"], None, {}) is None


def test_a_backend_that_cannot_serve_an_output_is_named_once(tmp_path: Path, monkeypatch) -> None:
    cfg = HydroModPyConfig.from_toml(write_calibration(tmp_path, "@GRID4\n@KLOG\n@NETROOT\n@GAP"))
    unserved = SimpleNamespace(name="release_flux", is_servable_now=False, reason="no flux")
    adapter = SimpleNamespace(declared_observables=lambda _active: [unserved])
    monkeypatch.setattr(preflight, "_flow_adapter_for", lambda _cfg: adapter)
    twice = [(None, "", []), (None, "", [])]
    monkeypatch.setattr(preflight, "search_candidates", lambda _calibration: twice)

    found = preflight._check_the_backend_can_serve_the_outputs(cfg.calibration, {None: cfg})

    assert [
        (item.path, item.detail.endswith("serve as configured: no flux")) for item in found
    ] == [("calibration.outputs.net", True)]


def test_a_backend_no_adapter_is_registered_for_serves_nothing() -> None:
    unknown = SimpleNamespace(solver=SimpleNamespace(backend_name="nope"))

    assert preflight._flow_adapter_for(unknown) is None


def test_an_extent_the_timestep_cannot_read_is_left_to_the_refusal_of_its_own_check(
    tmp_path: Path, monkeypatch
) -> None:
    cfg = HydroModPyConfig.from_toml(write_calibration(tmp_path, "@GRID4\n@KLOG\n@NETROOT\n@GAP"))
    odd = SimpleNamespace(flowing_at_least="soon", dry_at_most="1 d")
    monkeypatch.setattr(preflight_network, "_extents_scored_by", lambda *_a: [("net", odd)])

    assert (
        preflight_network.check_the_extent_durations_fit_the_timestep(cfg.calibration, {None: cfg})
        == []
    )


def test_a_steady_phase_that_cannot_be_dated_and_a_grid_that_cannot_be_read_date_nothing(
    tmp_path: Path, monkeypatch
) -> None:
    steady = SimpleNamespace(regime="steady")
    where = tmp_path / "gone.toml"
    held: list = []

    assert preflight_network._search_edges(SimpleNamespace(), steady, where, held) is None
    assert held == [None]

    from hydromodpy.calibration.runners import phase_regime

    def _refused(*_args):
        raise ValueError("backwards")

    monkeypatch.setattr(phase_regime, "regime_overrides", _refused)
    assert preflight_network._search_edges(SimpleNamespace(), steady, where, [{}]) is None
    assert preflight_network._search_edges(SimpleNamespace(), None, where, []) is None

    from hydromodpy.core.time import window

    def _unreadable(_config):
        raise ValueError("no grid")

    monkeypatch.setattr(window, "resolve_simulation_time_grid", _unreadable)
    assert preflight_network._search_edges(SimpleNamespace(), None, where, []) is None


def test_two_parameters_that_move_no_declared_output_form_no_ridge(tmp_path: Path) -> None:
    assert preflight_of(tmp_path, "@GRID\n@KLOG\n@SY") == []


_MONO, _PHASE_S = ("calibration", ""), ("calibration.phases", "'s': ")


@pytest.mark.parametrize(
    ("doc", "severity", "key", "said"),
    [
        ('[calibration]\nmethod = "bisection"\n' + _TWO_LOG_PARAMS, "error", _MONO, "moves 1"),
        (
            '[calibration]\nmethod = "nope"\n@KB',
            "error",
            ("calib.toml", ""),
            "this installation serves",
        ),
        (
            '[calibration]\nmethod = "lhs"\n@KB\nsampling = "normal"',
            "error",
            _MONO,
            "lhs cannot draw",
        ),
        (
            '[calibration]\nmethod = "bisection"\n'
            + _TWO_LOG_PARAMS
            + '[[calibration.phases]]\nname = "a"\nmethod = "grid"\nparameters = ["K"]\n'
            'objective_blocks = ["gap"]\n[[calibration.phases]]\nname = "b"\n'
            'method = "bisection"\nparameters = ["K", "Sy"]\nobjective_blocks = ["gap"]\n',
            "error",
            ("calibration.phases", "'b': "),
            "moves 1 parameter(s)",
        ),
        (
            '[calibration]\nmethod = "bisection"\n[calibration.parameters.K]\n'
            'bounds = [1e-7, 1e-3]\nsearch_space = "identity"\n@NETROOT\n@GAP',
            "error",
            _MONO,
            "K declare(s) another search space",
        ),
        (
            '[calibration]\nmethod = "bisection"\nvariable = "discharge"\nobjective = "nse_log"\n@KB',
            "error",
            _MONO,
            "scored on nse_log. Score it on",
        ),
        (
            '[calibration]\nmethod = "da_mh_gp"\nvariable = "discharge"\nobjective = "nse_log"\n@KB',
            "warning",
            _MONO,
            "this search is scored on nse_log. The chain",
        ),
    ],
)
def test_an_engine_finding_names_its_severity_and_its_search(
    tmp_path, doc, severity, key, said
) -> None:
    path, head = key
    found = [f for f in preflight_of(tmp_path, doc) if said in f.detail]

    assert [(f.severity, f.path) for f in found] == [(severity, path)]
    assert found[0].detail.startswith(head)


def test_an_engine_refuses_an_unregistered_method_on_constructed_config() -> None:
    config = CalibrationConfig.model_construct(
        method="nope",
        parameters={"K": {"bounds": [1e-7, 1e-3]}},
    )

    found = [f for f in preflight._check_engines(config) if "not registered" in f.detail]

    assert [(f.severity, f.path) for f in found] == [("error", "calibration")]


def test_a_serial_engine_asked_for_two_workers_can_use_one(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        BisectionAdapter, "traits", replace(BisectionAdapter.traits, supports_parallel=False)
    )
    doc = _WORKERS_ON_A_ROOT_SEARCH.replace("parallel = 4", "parallel = 2")

    found = [f for f in preflight_of(tmp_path, doc) if "buys nothing" in f.detail]

    assert [(f.severity, f.path) for f in found] == [("warning", _MONO[0])]
    assert "can use 1 solves at once, so parallel = 2" in found[0].detail


def test_a_phase_that_scores_the_gauge_alone_closes_one_root_whatever_the_file_declares(
    tmp_path,
) -> None:
    phase = (
        '[[calibration.phases]]\nname = "s"\nmethod = "scipy_nelder_mead"\nparameters = ["K"]\n'
        'objective_blocks = ["gap", "q"]\noutputs = ["gauge"]\n'
    )
    doc = (
        '[calibration]\nmethod = "bisection"\n@KLOG\n@GAUGE\n@GAP\nnormalize_cost = true\n'
        + _outputs(tmp_path)
        + _ON_A_GAUGE.removeprefix("@GAUGE\n")
        + "normalize_cost = true\n"
        + phase
    )

    found = [f.detail for f in preflight_of(tmp_path, doc)]

    assert [text for text in found if _TWO_METHODS in text or "does not load" in text] == []
