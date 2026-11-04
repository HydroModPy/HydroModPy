"""Tests of `preflight`."""

from __future__ import annotations

import json
import logging
import re
import textwrap
import tomllib
import warnings
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import hydromodpy as hmp
from hydromodpy.calibration import preflight
from hydromodpy.calibration.config import CalibNetworkExtent, CalibrationConfig
from hydromodpy.calibration.metrics.solver_extract import context_step_days
from hydromodpy.calibration.optim.adapters.bisection_adapter import BisectionAdapter
from hydromodpy.calibration.optim.adapters.grid_adapter import GridAdapter
from hydromodpy.calibration.optim.adapters.lhs_adapter import LhsAdapter
from hydromodpy.calibration.optim.engine import CalibrationEngine
from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion, engine_traits
from hydromodpy.calibration.optim.parameters import (
    CalibParameter,
    ParameterSpace,
    apply_parameter_to_config,
)
from hydromodpy.calibration.preflight import (
    PreflightFinding,
    _check_bounds_against_physics,
    _check_the_budgets,
    preflight_calibration,
)
from hydromodpy.calibration.runners import cli_runner, staged_runner
from hydromodpy.calibration.runners.cli_runner import load_toml_calibration
from hydromodpy.cli.helpers import EXIT_CONFIG
from hydromodpy.config import HydroModPyConfig
from hydromodpy.config.config_migration import fix_config_file, migrate_sealed_config_doc
from hydromodpy.core.exceptions import ConfigError, OptimizerError
from hydromodpy.core.stream_extent import dry_steps, flowing_steps, parse_extent_duration
from hydromodpy.core.time import nominal_step_days
from hydromodpy.display.config import DisplayConfig
from hydromodpy.display.figures.network_extent_bounds_map import extents_from_run
from hydromodpy.physics.flow.sinks_sources.recharge import FlowRechargeConfig
from hydromodpy.project import Project
from hydromodpy.results.derive.network_criterion_settings import network_criterion_settings
from hydromodpy.results.derive.stream_extent import network_extents_from_run, run_step_days
from hydromodpy.workflow.steps.prepare_solver.dispatch import portable_config_document
from tests._helpers.cli_runner import CliRunner
from tests._helpers.sealed_runs import sealed_search
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
from tests.unit.config.test_a_renamed_key_warns_and_a_sealed_one_reads import PROJECT, _project
from tests.unit.results._transient_network_run import transient_run

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


def test_a_whole_file_search_on_the_default_variable_is_refused(tmp_path) -> None:
    findings = preflight_of(tmp_path, _whole_file(tmp_path, variable=None))

    [refused] = _refused(findings)
    assert refused.severity == "error"
    assert refused.where == "[calibration]"
    assert "'head'" in refused.detail
    assert "network outputs: net" in refused.detail


def test_a_steady_run_is_not_blamed_on_an_extent_it_never_reads(tmp_path) -> None:
    doc = _whole_file(tmp_path, variable=None, regime="steady")

    findings = preflight_of(tmp_path, doc)

    assert len(_refused(findings)) == 1
    assert [item for item in findings if "extent table" in item.detail] == []


def test_a_single_metric_phase_on_a_station_variable_is_refused(tmp_path) -> None:
    findings = preflight_of(tmp_path, _one_phase(tmp_path, variable="head"))

    [refused] = _refused(findings)
    assert refused.where == "[[calibration.phases]] 'k_network'"


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
# every such path all the same, so ``hmp config check`` refused what the
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

_OUTSIDE = "modflow6.runtime.mf6_outer_dvclose"


def _outside(tmp_path: Path, path: str) -> Path:
    return write_calibration(
        tmp_path, _FILE.format(path=path), base=PROJECT_BASE + PROCESS, name="calib.toml"
    )


def test_a_value_the_configuration_carries_outside_the_catalogue_warns(tmp_path) -> None:
    (finding,) = run_preflight(_outside(tmp_path, _OUTSIDE))

    assert finding.severity == "warning"
    assert finding.where == "[calibration.parameters.dvclose]"
    assert _OUTSIDE in finding.detail
    assert "hmp config targets" in finding.detail


def test_the_launch_goes_on_and_says_it_once(tmp_path, prepared, caplog) -> None:
    with caplog.at_level(logging.WARNING), pytest.raises(_Prepared):
        hmp.calibrate(_outside(tmp_path, _OUTSIDE))

    said = [record for record in caplog.records if _OUTSIDE in record.getMessage()]
    assert len(said) == 1


def test_a_path_that_names_no_field_is_still_refused(tmp_path) -> None:
    (finding,) = run_preflight(_outside(tmp_path, "modflow6.runtime.no_such_option"))

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
# engine and by ``hmp config check``, and the search converges on its last point.


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


def test_the_preflight_counts_the_default_grid() -> None:
    (finding,) = _check_the_budgets(_config("grid", 24, {}))

    assert "below the 25 evaluations of this search, one per grid point" in finding.detail


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


class TestWhatTheEngineDeclares:
    def test_the_bisection_declares_its_three_limits(self) -> None:
        traits = engine_traits("bisection")

        assert traits.max_parameters == 1
        assert traits.required_search_space == "log"
        assert traits.needs_signed_residual is True

    def test_an_engine_that_constrains_nothing_declares_nothing(self) -> None:
        traits = engine_traits("grid")

        assert traits.max_parameters is None
        assert traits.required_search_space is None
        assert traits.needs_signed_residual is False


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
                ["not registered"],
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

    def test_asking_a_serial_engine_for_workers_is_only_a_warning(
        self, tmp_path, monkeypatch
    ) -> None:
        # The root search cuts its bracket side by side now. Declared serial
        # here, it stands for any engine that returns one point at a time.
        monkeypatch.setattr(
            BisectionAdapter, "traits", replace(BisectionAdapter.traits, supports_parallel=False)
        )
        findings = preflight_of(tmp_path, _WORKERS_ON_A_ROOT_SEARCH)

        assert [finding.severity for finding in findings] == ["warning"]
        assert "buys nothing" in findings[0].detail

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

    @pytest.mark.parametrize(
        "doc",
        [
            pytest.param(_WORKERS_ON_A_ROOT_SEARCH, id="takes_workers"),
            pytest.param('[calibration]\nmethod = "bisection"\n@KB\n@NETROOT\n@GAP', id="sound"),
            pytest.param(
                """
                [calibration]
                method = "bisection"
                @KB
                @NETROOT
                @GAP
                [[calibration.objective_blocks]]
                name = "gap_again"
                metric = "distance_gap"
                uses_outputs = ["net"]
                """,
                id="two_residual_blocks",
            ),
        ],
    )
    def test_a_sound_root_search_passes(self, tmp_path, doc) -> None:
        assert preflight_of(tmp_path, doc) == []


def test_a_root_search_on_the_mean_distance_is_refused(tmp_path) -> None:
    """The bracket closes on a zero the mean's minimum does not sit on."""
    findings = preflight_of(
        tmp_path,
        """
        [calibration]
        method = "bisection"
        @KB
        @NETROOT
        [[calibration.objective_blocks]]
        name = "mean"
        metric = "distance_mean"
        uses_outputs = ["net"]
        """,
    )

    message = messages(findings)
    assert "distance_mean" in message
    assert "distance_gap" in message


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
def test_the_extent_names_two_durations_left_unwritten_by_default() -> None:
    extent = CalibNetworkExtent()

    assert (extent.flowing_at_least, extent.dry_at_most) == (None, None)
    assert "maximal_flowing_steps" not in CalibNetworkExtent.model_fields
    assert "minimal_dry_steps" not in CalibNetworkExtent.model_fields


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


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("maximal_flowing_steps", "'flowing_at_least'"),
        ("minimal_dry_steps", "'dry_at_most'"),
    ],
)
def test_the_old_key_is_refused_with_the_name_that_replaces_it(old: str, new: str) -> None:
    with pytest.raises(ValidationError, match="is not accepted any more: renamed") as refused:
        CalibNetworkExtent(**{old: 1})

    assert new in str(refused.value)
    assert "hmp doctor --fix-config" in str(refused.value)


# -- the conversion ----------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "step", "flowing", "dry"),
    [
        pytest.param("30 d", DAY, 30, 30, id="thirty_days_on_a_daily_run"),
        pytest.param("1 month", MONTH, 1, 1, id="a_month_on_a_monthly_run"),
        pytest.param("12 months", MONTH, 12, 12, id="a_year_on_a_monthly_run"),
        pytest.param("45 d", MONTH, 2, 1, id="forty_five_days_on_a_monthly_run"),
        # A written day is one flowing step on a month, and no dry step at all.
        pytest.param("1 d", MONTH, 1, 0, id="a_day_on_a_monthly_run"),
        pytest.param("1 d", nominal_step_days(7, "day"), 1, 0, id="a_day_on_a_weekly_run"),
        pytest.param("1 d", nominal_step_days(1, "hour"), 24, 24, id="a_day_on_an_hourly_run"),
    ],
)
def test_a_duration_is_counted_in_timesteps(text: str, step: float, flowing: int, dry: int) -> None:
    assert flowing_steps(_days(text), step) == flowing
    assert dry_steps(_days(text), step) == dry


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


def test_the_redraw_reads_the_durations_a_run_sealed() -> None:
    settings = network_criterion_settings(
        _sealed({"maximal_flowing_duration": "30 d", "minimal_dry_duration": "1 month"})
    )

    assert settings.extent_rules.maximal_flowing_duration == "30 d"
    assert settings.extent_rules.minimal_dry_duration == "1 month"


def test_the_redraw_reads_the_counts_a_run_sealed_before_as_durations() -> None:
    settings = network_criterion_settings(
        _sealed({"maximal_flowing_steps": 2, "minimal_dry_steps": 1, "year_quorum": 1.0})
    )

    assert settings.extent_rules.maximal_flowing_duration == "2 months"
    assert settings.extent_rules.minimal_dry_duration == "1 month"
    assert settings.extent_rules.year_quorum == 1.0


# -- the doctor --------------------------------------------------------------
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


def test_the_doctor_writes_the_count_as_that_many_steps_of_the_time_window(tmp_path: Path) -> None:
    path = tmp_path / "calibration.toml"
    path.write_text(OLD_FILE, encoding="utf-8")

    changes = fix_config_file(path)

    written = path.read_text(encoding="utf-8")
    document = tomllib.loads(written)
    extent = document["calibration"]["outputs"]["seepage_network"]["model"]["extent"]
    assert extent == {
        "flowing_at_least": "2 months",
        "dry_at_most": "1 month",
        "year_quorum": 1.0,
    }
    assert document["display"]["overrides"]["network_extent_bounds_map"] == {
        "maximal_flowing_duration": "3 months"
    }
    overrides = document["calibration"]["phases"][0]["overrides"]
    assert overrides == {
        "display.overrides.network_extent_bounds_map.minimal_dry_duration": "0 months"
    }
    assert "# two months at least" in written
    assert not re.search(r"_steps\b", written)
    assert len(changes) == 8
    assert fix_config_file(path) == []


def test_the_doctor_writes_a_daily_count_in_days_and_an_hourly_one_in_hours(tmp_path: Path) -> None:
    path = tmp_path / "calibration.toml"
    path.write_text(
        '[simulation.time]\nstep_value = "7 days"\n'
        "[calibration.outputs.net.extent]\nmaximal_flowing_steps = 3\nminimal_dry_steps = 1\n",
        encoding="utf-8",
    )

    fix_config_file(path)

    extent = tomllib.loads(path.read_text(encoding="utf-8"))["calibration"]["outputs"]["net"]
    assert extent["extent"] == {
        "maximal_flowing_duration": "21 days",
        "minimal_dry_duration": "7 days",
    }
    assert flowing_steps(_days("21 days"), nominal_step_days(7, "day")) == 3
    assert dry_steps(_days("7 days"), nominal_step_days(7, "day")) == 1


def test_the_doctor_leaves_a_count_whose_timestep_the_chain_does_not_hold(tmp_path: Path) -> None:
    (tmp_path / "project.toml").write_text("[workflow]\nprofile = false\n", encoding="utf-8")
    path = tmp_path / "calibration.toml"
    path.write_text(
        'base_config = "project.toml"\n'
        "[calibration.outputs.net.extent]\nmaximal_flowing_steps = 3\n",
        encoding="utf-8",
    )

    changes = fix_config_file(path)

    assert len(changes) == 1
    assert "maximal_flowing_steps left: the timestep is not in this file" in changes[0]
    assert "write the duration, such as '1 month'" in changes[0]
    assert "maximal_flowing_steps = 3" in path.read_text(encoding="utf-8")


def test_the_doctor_leaves_a_count_when_a_phase_sets_the_timestep(tmp_path: Path) -> None:
    path = tmp_path / "calibration.toml"
    path.write_text(
        '[simulation.time]\nstep_value = "1 month"\n'
        "[calibration.outputs.net.extent]\nmaximal_flowing_steps = 3\n"
        '[[calibration.phases]]\nname = "a"\n'
        '[calibration.phases.overrides]\n"simulation.time.step_value" = 7\n',
        encoding="utf-8",
    )

    changes = fix_config_file(path)

    assert len(changes) == 1
    assert "a phase overrides the timestep" in changes[0]


def test_the_doctor_leaves_a_rule_written_under_both_names(tmp_path: Path) -> None:
    path = tmp_path / "calibration.toml"
    path.write_text(
        '[simulation.time]\nstep_value = "1 month"\n'
        "[calibration.outputs.net.extent]\nmaximal_flowing_steps = 3\n"
        'maximal_flowing_duration = "2 months"\n',
        encoding="utf-8",
    )

    changes = fix_config_file(path)

    assert changes == [
        "calibration.outputs.net.extent.maximal_flowing_steps left: "
        "'maximal_flowing_duration' is given too, keep one"
    ]


# -- a sealed run ------------------------------------------------------------
def test_a_sealed_document_reads_the_old_counts_as_durations() -> None:
    doc = {
        "simulation": {"time": {"step_value": 1, "step_unit": "month"}},
        "calibration": {
            "outputs": {"net": {"support": "network", "extent": {"maximal_flowing_steps": 2}}}
        },
        "display": {"overrides": {"network_extent_bounds_map": {"minimal_dry_steps": 1}}},
    }

    migrate_sealed_config_doc(doc)

    assert doc["calibration"]["outputs"]["net"]["model"]["extent"] == {
        "flowing_at_least": "2 months"
    }
    assert doc["display"]["overrides"]["network_extent_bounds_map"] == {
        "minimal_dry_duration": "1 month"
    }


def test_a_sealed_count_with_no_timestep_is_dropped_so_the_run_still_reads() -> None:
    doc = {
        "calibration": {
            "outputs": {"net": {"support": "network", "extent": {"minimal_dry_steps": 1}}}
        }
    }

    changes = migrate_sealed_config_doc(doc)

    assert doc["calibration"]["outputs"]["net"]["model"]["extent"] == {}
    assert any("minimal_dry_steps dropped (sealed)" in change for change in changes)


def test_a_frozen_run_with_the_old_counts_reads_back(tmp_path: Path) -> None:
    project = _project(tmp_path)
    toml = project / "project.toml"
    toml.write_text(
        PROJECT.replace(
            'complete = "nancon_stream_network.gpkg"\n',
            'complete = "nancon_stream_network.gpkg"\n'
            "[calibration.outputs.seepage_network.model.extent]\n"
            'flowing_at_least = "2 months"\ndry_at_most = "1 month"\n',
        ),
        encoding="utf-8",
    )
    cfg = HydroModPyConfig.from_toml(toml)
    run_dir = project / "runs" / "nancon"
    run_dir.mkdir(parents=True)
    frozen = portable_config_document(cfg, run_dir, project)
    old = re.sub(r"^flowing_at_least = .*$", "maximal_flowing_steps = 2", frozen, flags=re.M)
    old = re.sub(r"^dry_at_most = .*$", "minimal_dry_steps = 1", old, flags=re.M)
    old = old.replace("seepage_network.model.extent]", "seepage_network.extent]")
    assert old != frozen
    assert "flowing_at_least" not in old
    sealed = run_dir / "config.toml"
    sealed.write_text(old, encoding="utf-8")

    replayed = HydroModPyConfig.from_toml(sealed)

    extent = replayed.calibration.outputs["seepage_network"].model.extent
    assert (extent.flowing_at_least, extent.dry_at_most) == ("2 months", "1 month")


# -- the figure --------------------------------------------------------------
def test_the_figure_takes_the_durations_and_refuses_the_old_counts() -> None:
    DisplayConfig(
        overrides={
            "network_extent_bounds_map": {
                "maximal_flowing_duration": "5 months",
                "minimal_dry_duration": "0 d",
            }
        }
    )
    with pytest.raises(ValidationError, match="has no option 'maximal_flowing_steps'") as refused:
        DisplayConfig(overrides={"network_extent_bounds_map": {"maximal_flowing_steps": 5}})

    assert "maximal_flowing_duration" in str(refused.value)


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
    monkeypatch.setattr(preflight, "_search_candidates", lambda _c: [(None, "w", [])])
    monkeypatch.setattr(preflight, "_config_of", lambda _s, _p: config)
    monkeypatch.setattr(
        preflight,
        "_outputs_scored_by_search",
        lambda _c, _p: {
            "net": SimpleNamespace(support="network", model=SimpleNamespace(extent=extent))
        },
    )

    findings = preflight._check_the_extent_durations_fit_the_timestep(object(), {})
    assert len(findings) == 1 and "exceeds" in findings[0].detail

    extent.flowing_at_least = "30 d"
    assert preflight._check_the_extent_durations_fit_the_timestep(object(), {}) == []


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


class TestAFileThatIsFine:
    def test_it_reports_nothing(self, tmp_path) -> None:
        assert preflight_of(tmp_path, _GOOD) == []


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
        assert "'k_steady'" in findings[0].where
        assert "not a forward window" in findings[0].detail

    @pytest.mark.parametrize(
        "window", ["", 'steady_window = { start = "2000-01-01", end = "2000-06-30" }']
    )
    def test_a_readable_window_is_no_finding(self, tmp_path, window: str) -> None:
        assert preflight_of(tmp_path, self._REGIME.format(window=window)) == []


class TestAFileThatWillNotLoad:
    def test_it_says_so_once_rather_than_guessing(self, tmp_path) -> None:
        path = tmp_path / "broken.toml"
        path.write_text("[calibration]\nnot_a_key = 1\n", encoding="utf-8")

        findings = run_preflight(path)

        assert len(findings) == 1
        assert findings[0].severity == "error"

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


class TestALinearizedWidthOnASingleMetricPhase:
    """A single-metric phase builds no residual vector, ever: ``_phase_config``

    empties its ``outputs`` unconditionally when it declares its own
    ``variable``/``objective``, so the remedy pointed at for a document-level
    failure -- declare ``observes`` on an output -- is not one here, whatever
    the schema does or does not forbid on that phase's own selection.
    """

    _DOC = """
@GRID4
@UNC
@KLOG
[[calibration.phases]]
name = "p1"
method = "grid"
max_trials = 4
method_options = { points_per_dim = 2 }
parameters = ["K"]
variable = "discharge"
objective = "nse"
"""

    def test_the_message_never_points_at_a_field_the_schema_forbids(self, tmp_path) -> None:
        # Negative control: put back the literal old branch (`"and the schema
        # forbids naming a station on the outputs of a single-metric phase, so
        # that is not a remedy here"` instead of the `_phase_config` mechanism)
        # and both assertions below go red.
        findings = preflight_of(tmp_path, self._DOC)

        detail = messages(findings)
        assert "cost_profile" in detail
        assert "schema forbids" not in detail
        assert "declare observes" not in detail.lower()


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

        p1 = [item for item in findings if item.where == "[[calibration.phases]] 'p1'"]
        assert len(p1) == 1
        assert "inherits none of the calibration's outputs" in p1[0].detail
        assert "_phase_config" in p1[0].detail
        assert "schema forbids naming a station" not in p1[0].detail
        assert "cost_profile" in p1[0].detail

    def test_p2_is_not_named_because_its_block_reads_the_named_station(self, tmp_path) -> None:
        findings = preflight_of(tmp_path, self._DOC)

        assert "[[calibration.phases]] 'p2'" not in {item.where for item in findings}


class TestTheNetworkCriterionIsNotAskedToPickARidge:
    """A network-only objective that moves two parameters returns one point of a ridge."""

    _TWO_PARAMS = """
    @GRID
    @K
    @SY
    @NET
    @GAP
    """

    def test_two_parameters_on_a_network_only_objective_is_a_warning(self, tmp_path) -> None:
        findings = preflight_of(tmp_path, self._TWO_PARAMS)

        ridge = [item for item in findings if "ridge" in item.detail]
        assert len(ridge) == 1
        assert ridge[0].severity == "warning"
        assert ridge[0].where == "[calibration]"

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
_ON_THE_NETWORK = f"@NETROOT\n@GAP\n{_MEAN}"
_ON_A_GAUGE = "@GAUGE\n" + _MEAN.replace("mean", "q").replace('"net"', '"gauge"').replace(
    "distance_q", "rmse"
)
_KV = """
[calibration.parameters.Kv]
bounds = [1e-7, 1e-3]
search_space = "log"
path = "flow.param.Kv.field.value"
"""
_REFUSED_BALANCE = "a balanced evaluation"
_TRADING = "trading excess"
_TWO_METHODS = "depend on the method"
_UNCOUNTED = "cannot count its points"


def _balanced(
    parameters: str,
    block: str,
    scored: str = _ON_THE_NETWORK,
    method: str = "grid",
    trials: int | str = 3,
) -> str:
    """A grid of three points is enough, since it walks the structure alone."""
    options = "method_options = { points_per_dim = 3 }\n" if method == "grid" else ""
    return (
        f"@GRID\n@K\n@SY\n{scored}\n[[calibration.phases]]\n"
        f'name = "s"\nmethod = "{method}"\nmax_trials = {json.dumps(trials)}\n{options}'
        f'parameters = {parameters}\nobjective_blocks = ["{block}"]\nbalanced_evaluation = true\n'
    )


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
        (_balanced('["K", "Sy"]', "mean"), None, _REFUSED_BALANCE),
        (_balanced('["K"]', "mean"), "error", _REFUSED_BALANCE),
        (_balanced('["Sy"]', "mean"), "error", _REFUSED_BALANCE),
        (_balanced('["K", "Kv"]', "mean", _ON_THE_NETWORK + _KV), "error", _REFUSED_BALANCE),
        (_balanced('["K", "Sy"]', "gap"), "error", _REFUSED_BALANCE),
        (_balanced('["K", "Sy"]', "q", _ON_A_GAUGE), "error", _REFUSED_BALANCE),
        (_balanced('["K", "Sy"]', "mean", method="grid", trials="auto"), None, _UNCOUNTED),
        (
            _balanced('["K", "Sy"]', "mean", method="scipy_nelder_mead", trials="auto"),
            "error",
            _UNCOUNTED,
        ),
        (_balanced('["K", "Sy"]', "mean", method="scipy_nelder_mead", trials=5), None, _UNCOUNTED),
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


def test_a_balanced_grid_counts_its_points_on_the_structure_alone(tmp_path) -> None:
    findings = preflight_of(tmp_path, _balanced('["K", "Sy"]', "mean"))

    assert [finding for finding in findings if finding.severity == "error"] == []


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
        assert named[0].where == "[calibration]"
        assert "future work" in named[0].detail

    def test_an_active_lake_moving_k_is_named(self, tmp_path) -> None:
        doc = self._SFR.replace("sfr.net]", "lakes.lac0]\ninitial_stage = 1.0\nbedleak = 0.1")

        assert "LAK" in messages(preflight_of(tmp_path, doc))

    @pytest.mark.parametrize(
        "doc",
        [
            pytest.param("[flow.sinks_sources.sfr.net]\n@GRID\n@SY\n@NET\n@GAP", id="sfr_and_sy"),
            pytest.param(
                """
                [flow.sinks_sources.sfr.net]
                @GRID
                @K
                @GAUGE
                [[calibration.objective_blocks]]
                name = "gap"
                metric = "rmse"
                uses_outputs = ["gauge"]
                """,
                id="a_k_search_on_a_non_network_output",
            ),
            pytest.param(_SFR.replace("sinks_sources.sfr.net", "bc.drainage"), id="drainage_alone"),
        ],
    )
    def test_a_search_with_nothing_to_trust_is_not_named(self, tmp_path, doc: str) -> None:
        said = messages(preflight_of(tmp_path, doc))

        assert "SFR" not in said
        assert "LAK" not in said


class TestASingleMetricPhaseScoringANetworkOutput:
    """A phase naming its own ``variable``/``objective`` never becomes an
    ``objective_blocks`` entry, but it still scores whatever output that
    ``variable`` names, and both checks above must read it there too.
    """

    def test_two_parameters_on_a_single_metric_network_phase_is_a_ridge_warning(
        self, tmp_path
    ) -> None:
        doc = """
        @GRID
        variable = "net"
        objective = "distance_gap"
        @K
        @SY
        @NET
        [[calibration.phases]]
        name = "one"
        method = "grid"
        parameters = ["K", "Sy"]
        variable = "net"
        objective = "distance_gap"
        """
        findings = preflight_of(tmp_path, doc)

        ridge = [item for item in findings if "ridge" in item.detail]
        assert len(ridge) == 1
        assert ridge[0].severity == "warning"
        assert ridge[0].where == "[[calibration.phases]] 'one'"

    def test_a_single_metric_network_phase_next_to_an_active_sfr_is_named(self, tmp_path) -> None:
        doc = """
        [flow.sinks_sources.sfr.net]
        [calibration]
        method = "grid"
        variable = "net"
        objective = "distance_gap"
        @K
        @NET
        [[calibration.phases]]
        name = "one"
        method = "grid"
        parameters = ["K"]
        variable = "net"
        objective = "distance_gap"
        """
        findings = preflight_of(tmp_path, doc)

        named = [item for item in findings if "SFR" in item.detail]
        assert len(named) == 1
        assert named[0].severity == "error"
        assert named[0].where == "[[calibration.phases]] 'one'"


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
            source = "custom"
            path = "hydrometry"
            station_ids = ["OTHER"]
            """
            + _GAUGED
        )
        findings = preflight_of(tmp_path, doc)

        named = [item for item in findings if "GAUGE" in item.detail]
        assert len(named) == 1
        assert named[0].where == "[calibration.outputs.hydrograph]"
        assert "Listed: OTHER" in named[0].detail

    def test_a_listed_station_passes(self, tmp_path) -> None:
        doc = (
            """
            [data]
            types = ["hydrometry"]

            [[data.hydrometry.sources]]
            source = "custom"
            path = "hydrometry"
            station_ids = ["GAUGE"]
            """
            + _GAUGED
        )
        findings = preflight_of(tmp_path, doc)

        assert not any("GAUGE" in item.detail for item in findings)


class TestTheWindowBoundsHoldsADateOfTheRun:
    def test_a_window_after_the_run_is_named(self, tmp_path) -> None:
        doc = _GAUGED + '\n[calibration.window]\nstart = "2010-01-01"\n'
        findings = preflight_of(tmp_path, doc)

        named = [item for item in findings if "holds no date of the run" in item.detail]
        assert len(named) == 1
        assert named[0].severity == "error"
        assert "2010-01-01" in named[0].detail

    def test_a_window_inside_the_run_passes(self, tmp_path) -> None:
        doc = _GAUGED + '\n[calibration.window]\nstart = "2000-03-01"\n'
        findings = preflight_of(tmp_path, doc)

        assert not any("holds no date of the run" in item.detail for item in findings)


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

    def test_an_rmse_passes(self, tmp_path) -> None:
        findings = preflight_of(tmp_path, self._doc("rmse"))

        assert not any("reads its cost as" in item.detail for item in findings)


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
dem_init_path = "DEM.tif"
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


def test_a_stage_precision_arrives_on_the_phase(tmp_path: Path) -> None:
    cfg, _raw = _loaded(
        tmp_path,
        """
        [calibration.protocol]
        name = "matching_hydrographic_network"
        steady_precision = 0.02
        transient_precision = 0.05
        """,
    )
    assert [phase.precision for phase in cfg.phases] == [0.02, 0.05]


def test_an_unstated_precision_leaves_the_engine_its_own_default(tmp_path: Path) -> None:
    cfg, _raw = _loaded(
        tmp_path,
        """
        [calibration.protocol]
        name = "matching_hydrographic_network"
        """,
    )
    assert [phase.precision for phase in cfg.phases] == [None, None]


def test_a_precision_an_engine_cannot_stop_on_is_refused_before_the_first_solve(
    tmp_path: Path,
) -> None:
    cfg, _raw = _loaded(
        tmp_path,
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
        network=False,
    )
    findings = _findings_for(cfg, tmp_path)
    assert any("stops on its evaluation budget" in finding.detail for finding in findings)


def test_saying_the_precision_twice_is_refused_before_the_first_solve(tmp_path: Path) -> None:
    cfg, _raw = _loaded(
        tmp_path,
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
        network=False,
    )
    findings = _findings_for(cfg, tmp_path)
    assert any("both set the stopping rule" in finding.detail for finding in findings)


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
# ``hmp config check`` was the only caller of the preflight. ``hmp calibrate``,
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

    for module in (cli_runner, staged_runner):
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
    def test_hmp_calibrate(self, tmp_path, prepared, phased: bool) -> None:
        result = CliRunner().invoke(
            ["calibrate", str(_refused__preflight_runs(tmp_path, phased=phased))]
        )

        assert result.exit_code == EXIT_CONFIG, result.output
        assert "ghost" in result.stderr
        assert prepared == []

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

    @pytest.mark.parametrize("phased", [False, True], ids=["one_search", "phases"])
    def test_hmp_calibrate_from_python(self, tmp_path, prepared, phased: bool) -> None:
        with pytest.raises(ConfigError, match="ghost"):
            hmp.calibrate(_refused__preflight_runs(tmp_path, phased=phased))
        assert prepared == []

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


class TestWarnings:
    def test_a_warning_prints_once_and_the_launch_goes_on(self, tmp_path, prepared, caplog) -> None:
        path = _write__preflight_runs(
            tmp_path, _PARAMETERS__preflight_runs, _NETWORK__preflight_runs
        )

        with caplog.at_level(logging.WARNING), pytest.raises(_Prepared):
            hmp.calibrate(path)

        ridge = [record for record in caplog.records if "form a ridge" in record.getMessage()]
        assert len(ridge) == 1
        assert prepared == ["calib.toml"]


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

    def test_the_same_phase_without_its_overrides_is_refused(self, config) -> None:
        stripped = config.model_copy(deep=True)
        stripped.calibration.phases[0].overrides = {}

        details = " ".join(
            finding.detail
            for finding in preflight_calibration(stripped, source=_EXAMPLE_21)
            if finding.severity == "error"
        )

        assert "SFR (routed stream reaches) is active" in details
