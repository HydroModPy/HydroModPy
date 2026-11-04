"""Tests of `config`."""

from __future__ import annotations

import inspect
import json
import math
import re
import tomllib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError

from hydromodpy.calibration.config import (
    CalibNetworkExtent,
    CalibObjectiveBlockDecl,
    CalibOutputCell,
    CalibOutputNetwork,
    CalibParameterDecl,
    CalibPhaseDecl,
    CalibPhaseUncertaintyDecl,
    CalibrationConfig,
    CalibrationProtocolDecl,
    CalibUncertaintyDecl,
    apply_project_defaults,
    validate_calib_output,
)
from hydromodpy.calibration.optim.optimizer import available_optimizers
from hydromodpy.calibration.protocols import options_the_recipe_already_runs
from hydromodpy.config import HydroModPyConfig
from hydromodpy.config.config_migration import fix_config_file, migrate_sealed_config_doc
from hydromodpy.config.metrics_config import MetricsWindow
from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.cost_margin import parse_cost_margin
from hydromodpy.core.site.gauge import GaugeConflictError
from hydromodpy.core.stream_criterion_defaults import STREAM_CRITERION_DEFAULTS
from hydromodpy.core.stream_extent import dry_steps, flowing_steps, parse_extent_duration
from hydromodpy.core.stream_geometry import build_network_geometry
from hydromodpy.core.stream_network import build_simulated_network
from hydromodpy.core.time import nominal_step_days
from hydromodpy.core.topographic_distance import build_downslope_metric
from hydromodpy.display.figures._routing_surface import routing_surface_from_run
from hydromodpy.display.figures.depression_map import DepressionMap
from hydromodpy.results.derive.network_criterion_settings import (
    DEFAULT_EXTENT_RULES,
    network_criterion_settings,
)
from hydromodpy.results.derive.stream_extent import network_extents_from_run
from hydromodpy.results.derive.stream_network import network_comparison_from_run
from hydromodpy.workflow.steps.prepare_solver.dispatch import portable_config_document
from tests._helpers.sealed_runs import sealed_search
from tests._helpers.ugrid_meshes import quad_mesh
from tests.unit.config.test_a_renamed_key_warns_and_a_sealed_one_reads import PROJECT, _project
from tests.unit.results._transient_network_run import transient_run

# From test_a_calibration_takes_the_gauge_of_the_site.py
# ``[site] gauge`` is the station a calibration scores at, unless the document says otherwise.
#
# ``apply_project_defaults`` writes the gauge into ``observed_station_id`` (on
# the section, on each phase) and into ``observes`` of a point output that
# names no station, no position and no observed values. A written station that
# is not the gauge is refused with both keys. ``[metrics] window`` is the
# default scoring window.


GAUGE = "J0014010"


def _defaults(section: dict, *, gauge: str | None = GAUGE, window: dict | None = None) -> dict:
    return apply_project_defaults(section, site_gauge=gauge, metrics_window=window)


class TestTheSectionAndThePhases:
    def test_the_gauge_is_the_station_when_none_is_written(self) -> None:
        resolved = _defaults({"phases": [{"name": "steady_k"}, {"name": "sy"}]})

        assert resolved["observed_station_id"] == GAUGE
        assert [phase["observed_station_id"] for phase in resolved["phases"]] == [GAUGE, GAUGE]

    def test_a_phase_that_writes_the_gauge_keeps_it(self) -> None:
        resolved = _defaults({"phases": [{"name": "sy", "observed_station_id": GAUGE}]})

        assert resolved["phases"][0]["observed_station_id"] == GAUGE

    def test_a_phase_that_names_another_station_is_refused_with_both_keys(self) -> None:
        with pytest.raises(GaugeConflictError) as caught:
            _defaults({"phases": [{"name": "sy", "observed_station_id": "J9999999"}]})

        assert "site.gauge = 'J0014010'" in str(caught.value)
        assert "calibration.phases.sy.observed_station_id = 'J9999999'" in str(caught.value)

    def test_a_section_that_names_another_station_is_refused_with_both_keys(self) -> None:
        with pytest.raises(GaugeConflictError, match="calibration.observed_station_id"):
            _defaults({"observed_station_id": "J9999999"})

    def test_without_a_gauge_nothing_is_written(self) -> None:
        section = {"observed_station_id": "J9999999", "phases": [{"name": "sy"}]}

        assert _defaults(section, gauge=None) == section


class TestThePointOutputs:
    def test_an_output_with_neither_station_nor_position_observes_the_gauge(self) -> None:
        resolved = _defaults({"outputs": {"q": {"support": "point", "variable": "discharge"}}})

        assert resolved["outputs"]["q"]["observes"] == GAUGE

    @pytest.mark.parametrize(
        "located",
        [{"x": 1.0, "y": 2.0}, {"geometry": "POINT (1 2)"}, {"observed_values": [1.0, 2.0]}],
        ids=["x_y", "geometry", "observed_values"],
    )
    def test_an_output_that_locates_or_scores_itself_takes_no_gauge(self, located) -> None:
        output = {"support": "point", "variable": "head", **located}

        resolved = _defaults({"outputs": {"piezo": output}})

        assert resolved["outputs"]["piezo"] == output
        assert "observes" not in resolved["outputs"]["piezo"]

    def test_an_output_with_its_own_position_and_another_station_is_left_alone(self) -> None:
        output = {"support": "point", "variable": "head", "x": 1.0, "y": 2.0, "observes": "P1"}

        assert _defaults({"outputs": {"piezo": output}})["outputs"]["piezo"] == output

    def test_an_output_that_names_another_station_without_a_position_is_refused(self) -> None:
        with pytest.raises(GaugeConflictError, match="calibration.outputs.q.observes = 'J9'"):
            _defaults({"outputs": {"q": {"support": "point", "observes": "J9"}}})

    def test_a_network_output_is_not_a_point(self) -> None:
        output = {"support": "network", "stream_geometry_path": "streams.gpkg"}

        assert _defaults({"outputs": {"net": output}})["outputs"]["net"] == output


class TestTheScoringWindow:
    WINDOW = {"start": "2001-01-01", "end": "2002-12-31"}

    def test_the_metrics_window_is_the_default(self) -> None:
        resolved = _defaults({}, window=self.WINDOW)

        assert resolved["scoring_window"] == {"start": "2001-01-01", "end": "2002-12-31"}

    def test_a_written_window_or_a_warmup_wins(self) -> None:
        own = {"start": "2010-01-01", "end": "2010-12-31"}

        assert _defaults({"scoring_window": own}, window=self.WINDOW)["scoring_window"] == own
        assert "scoring_window" not in _defaults({"warmup_periods": 12}, window=self.WINDOW)

    def test_each_phase_but_a_steady_one_takes_the_metrics_window(self) -> None:
        own = {"start": "2002-01-01", "end": "2002-12-31"}
        phases = [
            {"name": "steady_k", "regime": "steady"},
            {"name": "transient_sy", "regime": "transient"},
            {"name": "own", "scoring_window": own},
        ]

        resolved = _defaults({"phases": phases}, window=self.WINDOW)

        assert "scoring_window" not in resolved
        steady, transient, written = resolved["phases"]
        assert "scoring_window" not in steady
        assert transient["scoring_window"] == {"start": "2001-01-01", "end": "2002-12-31"}
        assert written["scoring_window"] == own

    def test_a_half_window_is_no_default(self) -> None:
        assert "scoring_window" not in _defaults({}, window={"start": "2001-01-01", "end": None})


# From test_a_flat_cell_id_is_refused.py
# A calibration cell output names its cell by row and col; cell_id is refused.
#
# No solver read a flat cell index: every run refused the output it named.


def test_cell_id_is_refused_with_the_keys_to_write() -> None:
    with pytest.raises(ValidationError) as excinfo:
        CalibOutputCell(variable="head", cell_id=7)
    message = str(excinfo.value)
    assert "'cell_id' is not accepted any more" in message
    assert "row and col" in message
    assert "support = 'point'" in message


def test_a_cell_output_without_row_and_col_is_refused() -> None:
    with pytest.raises(ValidationError, match="row"):
        CalibOutputCell(variable="head")


def test_row_and_col_name_the_cell() -> None:
    output = CalibOutputCell(variable="head", row=3, col=4, layer=1)
    assert (output.layer, output.row, output.col) == (1, 3, 4)


def test_a_model_without_refused_keys_accepts_its_fields() -> None:
    class _Plain(HydroModelBase):
        value: int = 0

    assert _Plain(value=2).value == 2


# From test_a_sum_of_units_is_refused.py
# Adding a cost in meters to a cost in m3/s lets the unit set the weighting.
#
# ``normalize_cost`` exists for exactly this: it divides a block's cost by a
# reference scale so that two blocks become comparable. Nothing enforced it. A file
# could weight a head RMSE in meters at 0.5 and a discharge RMSE in m3/s at 0.5,
# believe it had split the cost evenly, and hand the meters whatever share their
# own magnitude happened to buy.
#
# The criterion now declares the unit of its cost, so the composite can see the
# mix and refuse it. Two costs in the same unit add up fine. Dimensionless ones add
# up fine. A mix is refused unless every dimensionful member is normalized, which
# is what makes the weights mean what they say.


def _config(blocks: list[dict[str, object]]) -> dict[str, object]:
    return {
        "parameters": {"K": {"bounds": [1e-8, 1e-2]}},
        "outputs": {
            "head": {
                "variable": "head",
                "support": "cell",
                "row": 0,
                "col": 0,
                "observed_values": [1.0, 2.0],
            },
            "q": {
                "variable": "discharge",
                "support": "boundary",
                "boundary_id": "outlet",
                "observed_values": [1.0, 2.0],
            },
        },
        "objective_blocks": blocks,
    }


def _rmse(name: str, output: str, **extra: object) -> dict[str, object]:
    return {"name": name, "metric": "rmse", "uses_outputs": [output], **extra}


class TestWhatIsRefused:
    def test_two_dimensionful_costs_from_different_families_are_refused(self) -> None:
        with pytest.raises(ValueError, match="unit"):
            CalibrationConfig.model_validate(_config([_rmse("heads", "head"), _rmse("flows", "q")]))

    def test_the_refusal_names_both_blocks_and_the_way_out(self) -> None:
        with pytest.raises(ValueError) as caught:
            CalibrationConfig.model_validate(_config([_rmse("heads", "head"), _rmse("flows", "q")]))

        message = str(caught.value)
        assert "heads" in message and "flows" in message
        assert "normalize_cost" in message


class TestWhatIsAccepted:
    def test_normalising_every_dimensionful_member_makes_it_legitimate(self) -> None:
        cfg = CalibrationConfig.model_validate(
            _config(
                [
                    _rmse("heads", "head", normalize_cost=True),
                    _rmse("flows", "q", normalize_cost=True),
                ]
            )
        )

        assert len(cfg.objective_blocks) == 2

    def test_mixing_a_dimensionless_score_with_a_normalised_residual_is_fine(self) -> None:
        cfg = CalibrationConfig.model_validate(
            _config(
                [
                    {"name": "flows", "metric": "nse_log", "uses_outputs": ["q"]},
                    _rmse("heads", "head", normalize_cost=True),
                ]
            )
        )

        assert len(cfg.objective_blocks) == 2

    def test_two_dimensionless_scores_add_up_without_a_word(self) -> None:
        cfg = CalibrationConfig.model_validate(
            _config(
                [
                    {"name": "flows", "metric": "nse_log", "uses_outputs": ["q"]},
                    {"name": "heads", "metric": "kge", "uses_outputs": ["head"]},
                ]
            )
        )

        assert len(cfg.objective_blocks) == 2

    def test_a_single_block_is_never_a_mix(self) -> None:
        cfg = CalibrationConfig.model_validate(_config([_rmse("heads", "head")]))

        assert len(cfg.objective_blocks) == 1

    def test_two_residual_costs_on_the_same_family_add_up(self) -> None:
        """Same unit, so nothing to reconcile."""
        cfg = CalibrationConfig.model_validate(
            _config([_rmse("a", "q"), {"name": "b", "metric": "mae", "uses_outputs": ["q"]}])
        )

        assert len(cfg.objective_blocks) == 2


def test_the_declaration_stands_alone() -> None:
    """The check is on the calibration, not on one block: a block has no siblings."""
    assert CalibObjectiveBlockDecl(name="b", metric="rmse", uses_outputs=["q"]) is not None


# From test_an_extent_rule_left_unwritten_is_one_timestep.py
# An extent rule a user writes no duration for counts one timestep, on any step.
#
# The first default of the duration rules was "1 d". On a monthly run that made the
# dry rule floor(1 d / 1 month) = 0 timestep instead of 1, and on an hourly run it
# made both rules 24 timesteps instead of 1. A rule left out is now one timestep,
# exactly the count a run made before the rules were durations.


STEPS = {
    "hourly": nominal_step_days(1, "hour"),
    "daily": nominal_step_days(1, "day"),
    "weekly": nominal_step_days(7, "day"),
    "monthly": nominal_step_days(1, "month"),
}


def test_a_rule_left_out_has_no_duration() -> None:
    extent = CalibNetworkExtent()

    assert (extent.maximal_flowing_duration, extent.minimal_dry_duration) == (None, None)
    assert CalibNetworkExtent(maximal_flowing_duration=None).maximal_flowing_duration is None


@pytest.mark.parametrize("step", STEPS)
def test_no_duration_is_one_flowing_and_one_dry_timestep_on_any_step(step: str) -> None:
    unset = parse_extent_duration(None)

    assert (flowing_steps(unset, STEPS[step]), dry_steps(unset, STEPS[step])) == (1, 1)


def test_a_written_day_is_still_converted_by_the_step() -> None:
    day = parse_extent_duration("1 d")

    assert (flowing_steps(day, STEPS["hourly"]), dry_steps(day, STEPS["hourly"])) == (24, 24)
    assert (flowing_steps(day, STEPS["monthly"]), dry_steps(day, STEPS["monthly"])) == (1, 0)


def test_a_stored_monthly_run_with_no_rule_counts_one_and_one() -> None:
    extents = network_extents_from_run(transient_run())

    assert (extents.maximal_flowing_steps, extents.minimal_dry_steps) == (1, 1)
    assert (extents.maximal_flowing_duration, extents.minimal_dry_duration) == (None, None)


def test_a_stored_run_that_sealed_a_table_without_the_rules_reads_none() -> None:
    run = SimpleNamespace(
        sim_id="sim-x",
        config_snapshot={"simulation": {"time": {"step_value": 1, "step_unit": "month"}}},
        dir=sealed_search(
            {
                "outputs": {
                    "net": {
                        "support": "network",
                        "observed_network": "data.hydrography",
                        "extent": {"year_quorum": 1.0},
                    }
                }
            }
        ),
    )
    rules = network_criterion_settings(run).extent_rules

    assert (rules.maximal_flowing_duration, rules.minimal_dry_duration) == (None, None)
    assert DEFAULT_EXTENT_RULES.maximal_flowing_duration is None


# From test_an_observed_network_names_its_source.py
# An observed network output must name exactly one source for its geometry.


def _kwargs(**overrides: object) -> dict[object, object]:
    base = {"support": "network"}
    base.update(overrides)
    return base


def test_observed_network_data_hydrography_validates() -> None:
    output = CalibOutputNetwork(**_kwargs(observed_network="data.hydrography"))
    assert output.observed_network == "data.hydrography"
    assert output.stream_geometry_path is None


def test_observed_network_geographic_river_network_validates() -> None:
    output = CalibOutputNetwork(**_kwargs(observed_network="geographic.river_network"))
    assert output.observed_network == "geographic.river_network"
    assert output.stream_geometry_path is None


def test_stream_geometry_path_alone_validates() -> None:
    """Every file in the repository declares only this field today."""
    output = CalibOutputNetwork(**_kwargs(stream_geometry_path="streams.gpkg"))
    assert str(output.stream_geometry_path) == "streams.gpkg"
    assert output.observed_network is None


def test_both_declared_refuses_naming_both_values() -> None:
    with pytest.raises(ValidationError) as excinfo:
        CalibOutputNetwork(
            **_kwargs(observed_network="data.hydrography", stream_geometry_path="streams.gpkg")
        )
    message = str(excinfo.value)
    assert "data.hydrography" in message
    assert "streams.gpkg" in message


def test_neither_declared_refuses_naming_the_three_routes() -> None:
    with pytest.raises(ValidationError) as excinfo:
        CalibOutputNetwork(**_kwargs())
    message = str(excinfo.value)
    assert "data.hydrography" in message
    assert "geographic.river_network" in message
    assert "stream_geometry_path" in message


# From test_an_output_option_nothing_reads_is_refused.py
# An output option that nothing reads is refused, not ignored.
#
# Beside ``observes``, the record is paired with the simulated series step by
# step and the paired series is scored: a ``reducer`` was applied, then
# overwritten, so ``none``, ``mean`` and ``sum`` gave the same cost. A list of
# dates in ``time`` was accepted and documented, and read as ``"all"``.


SUPPORTS = [
    ("point", {"variable": "head", "x": 0.0, "y": 0.0}),
    ("boundary", {"variable": "discharge", "boundary_id": "drainage"}),
    ("cell", {"variable": "head", "row": 0, "col": 0}),
    ("lake", {"variable": "stage", "lake_id": "lac0"}),
]


@pytest.mark.parametrize(("support", "where"), SUPPORTS)
@pytest.mark.parametrize("reducer", ["mean", "sum", "last"])
def test_a_reducer_beside_observes_is_refused(support: str, where: dict, reducer: str) -> None:
    with pytest.raises(ValidationError, match="reduced value is never scored"):
        validate_calib_output({"support": support, "observes": "PZ1", "reducer": reducer, **where})


def test_a_reducer_on_a_written_vector_still_reduces() -> None:
    decl = validate_calib_output(
        {
            "variable": "stage",
            "support": "lake",
            "lake_id": "lac0",
            "reducer": "mean",
            "observed_values": [10.0],
        }
    )

    assert decl.reducer == "mean"


@pytest.mark.parametrize(("support", "where"), SUPPORTS)
def test_a_list_of_dates_is_refused(support: str, where: dict) -> None:
    with pytest.raises(ValidationError, match="selects nothing"):
        validate_calib_output({"support": support, "time": ["2020-01-01"], **where})


@pytest.mark.parametrize("time", ["all", "first", "last"])
def test_the_named_instants_stay(time: str) -> None:
    decl = validate_calib_output(
        {"variable": "head", "support": "cell", "row": 0, "col": 0, "time": time}
    )

    assert decl.time == time


# From test_an_output_the_station_route_leaves_aside_is_refused.py
# An output the one-line form never reads is refused when the file loads.
#
# With no objective block, ``variable`` says what a calibration scores: the
# output it names, or every loaded station of that variable. A file that
# declared ``[calibration.outputs.h]`` and left ``variable`` at its default
# ``"head"`` used to fit the loaded piezometers, never ``h``, and
# ``hmp config check`` answered OK.


H = {"variable": "head", "support": "point", "x": 10.0, "y": 20.0, "observed_values": [1.0, 2.0]}


def _config__output_station(**section: object) -> CalibrationConfig:
    payload = {"parameters": {"K": {"bounds": [1e-7, 1e-3], "path": "flow.param.K.field.value"}}}
    payload.update(section)
    return CalibrationConfig.model_validate(payload)


def test_an_output_beside_the_default_variable_is_refused() -> None:
    with pytest.raises(ValidationError, match=r"\['h'\] are declared and nothing scores them"):
        _config__output_station(outputs={"h": H})


def test_naming_the_output_in_variable_scores_it() -> None:
    cfg = _config__output_station(outputs={"h": H}, variable="h")

    assert [block.uses_outputs for block in cfg.objective_blocks] == [["h"]]


def test_an_output_beside_a_block_may_feed_the_residuals() -> None:
    cfg = _config__output_station(
        outputs={"h": H, "spare": H},
        objective_blocks=[{"name": "fit", "metric": "rmse", "uses_outputs": ["h"]}],
    )

    assert set(cfg.outputs) == {"h", "spare"}


# From test_config_enrichment.py
# Tests for the enriched [calibration] TOML schema.
#
# Covers the Phase 1 additions to :mod:`hydromodpy.calibration.config`:
#
# - CalibParameterDecl gains target / mode.
# - CalibOutputDecl and CalibObjectiveBlockDecl are new Pydantic models.
# - CalibrationConfig grows outputs, objective_blocks, persist_* and
#   materialize_* fields.
# - An implicit objective block is synthesized when none is declared.


# ---------------------------------------------------------------------------
# Literal fields: the values they accept and the ones they refuse
# ---------------------------------------------------------------------------
_BLOCK = {"name": "b", "uses_outputs": ["x"]}
LITERALS = [
    (CalibParameterDecl, {}, "mode", ["replace", "scale"], ["override", "multiply", "", "REPLACE"]),
    (
        CalibParameterDecl,
        {},
        "search_space",
        ["identity", "log", "logit"],
        ["sqrt", "inverse", "power", ""],
    ),
    (
        CalibParameterDecl,
        {},
        "sampling",
        ["uniform", "log_uniform", "normal"],
        ["jeffreys", "beta", ""],
    ),
    (CalibObjectiveBlockDecl, _BLOCK, "cost_transform", ["identity", "log", "inverse"], ["power"]),
    (CalibObjectiveBlockDecl, _BLOCK, "metric", ["rmse", "nse", "kge", "mae"], ["rsme"]),
    (CalibrationConfig, {}, "method", ["grid", "random_search", "optuna"], [""]),
    (CalibrationConfig, {}, "save_runs", ["none", "best_n", "all"], ["top_n", "best", "", "ALL"]),
]
ACCEPTED, REFUSED = [], []
for _model, _base, _field, _good, _bad in LITERALS:
    ACCEPTED += [pytest.param(_model, _base, _field, v, id=f"{_field}-{v}") for v in _good]
    REFUSED += [pytest.param(_model, _base, _field, v, id=f"{_field}-{v}") for v in _bad]


@pytest.mark.parametrize(("model", "base", "field", "value"), ACCEPTED)
def test_a_literal_accepts_its_values(model, base, field, value) -> None:
    assert getattr(model.model_validate({**base, field: value}), field) == value


@pytest.mark.parametrize(("model", "base", "field", "value"), REFUSED)
def test_a_literal_refuses_the_others(model, base, field, value) -> None:
    with pytest.raises(ValidationError, match=field):
        model.model_validate({**base, field: value})


# ---------------------------------------------------------------------------
# CalibParameterDecl extended
# ---------------------------------------------------------------------------
class TestCalibParameterDeclExtensions:
    def test_target_is_optional_and_defaults_to_none(self):
        decl = CalibParameterDecl.model_validate({})
        assert decl.target is None
        assert decl.mode == "replace"

    def test_target_alias_wins_over_path(self):
        decl = CalibParameterDecl.model_validate(
            {"path": "flow.properties.k_aquifer", "target": "flow.param.K.field.value"}
        )
        assert decl.resolve_target() == "flow.param.K.field.value"

    def test_path_used_when_target_absent(self):
        decl = CalibParameterDecl.model_validate({"path": "flow.properties.k_aquifer"})
        assert decl.resolve_target() == "flow.properties.k_aquifer"


# ---------------------------------------------------------------------------
# CalibOutputDecl
# ---------------------------------------------------------------------------
class TestCalibOutputDecl:
    def test_minimal_declaration_defaults(self):
        decl = validate_calib_output({"variable": "head", "support": "cell", "row": 0, "col": 0})
        assert decl.variable == "head"
        assert decl.support == "cell"
        assert decl.time == "all"
        assert decl.reducer == "none"
        assert decl.observed_values is None

    def test_observed_values_round_trip(self):
        decl = validate_calib_output(
            {
                "variable": "head",
                "support": "point",
                "x": 150.0,
                "y": 0.0,
                "observed_values": [42.1, 41.8, 41.5],
            }
        )
        assert decl.observed_values == [42.1, 41.8, 41.5]
        assert decl.x.to("m").magnitude == 150.0

    def test_x_accepts_pint_string(self):
        decl = validate_calib_output(
            {"variable": "head", "support": "point", "x": "100 m", "y": "0 m"}
        )
        assert decl.x.to("m").magnitude == 100.0

    def test_time_refuses_a_list_of_timestamps(self):
        with pytest.raises(ValidationError, match="selects nothing"):
            validate_calib_output(
                {
                    "variable": "head",
                    "support": "cell",
                    "row": 0,
                    "col": 0,
                    "time": ["2020-01-01", "2020-06-01"],
                }
            )

    @pytest.mark.parametrize(
        "support, extra",
        [
            ("point", {"x": 0.0, "y": 0.0}),
            ("boundary", {"boundary_id": "outlet"}),
            ("cell", {"row": 0, "col": 0}),
        ],
    )
    def test_support_literal(self, support: str, extra: dict):
        decl = validate_calib_output({"variable": "head", "support": support, **extra})
        assert decl.support == support

    def test_rejects_unknown_support(self):
        with pytest.raises(ValidationError, match="support"):
            validate_calib_output({"variable": "head", "support": "area"})

    def test_rejects_extra_keys(self):
        with pytest.raises(ValidationError, match="Extra inputs"):
            validate_calib_output(
                {"variable": "head", "support": "cell", "row": 0, "col": 0, "legacy_hint": True}
            )

    def test_point_support_requires_xy(self):
        with pytest.raises(ValidationError, match="support='point' requires"):
            validate_calib_output({"variable": "head", "support": "point"})
        with pytest.raises(ValidationError, match="support='point' requires"):
            validate_calib_output({"variable": "head", "support": "point", "x": 1.0})

    def test_boundary_support_requires_boundary_id(self):
        with pytest.raises(ValidationError, match="boundary_id"):
            validate_calib_output({"variable": "head", "support": "boundary"})


# ---------------------------------------------------------------------------
# CalibObjectiveBlockDecl
# ---------------------------------------------------------------------------
class TestCalibObjectiveBlockDecl:
    def test_minimal_block(self):
        decl = CalibObjectiveBlockDecl.model_validate(
            {"name": "head_block", "uses_outputs": ["head_A"]}
        )
        assert decl.metric == "rmse"
        assert decl.weight == 1.0
        assert decl.normalize_cost is False
        assert decl.cost_transform == "identity"

    def test_weight_must_be_positive(self):
        with pytest.raises(ValidationError, match="weight"):
            CalibObjectiveBlockDecl.model_validate(
                {"name": "b", "weight": 0.0, "uses_outputs": ["x"]}
            )

    def test_rejects_extra_keys(self):
        with pytest.raises(ValidationError, match="Extra inputs"):
            CalibObjectiveBlockDecl.model_validate(
                {"name": "b", "uses_outputs": ["x"], "legacy_toggle": True}
            )


# ---------------------------------------------------------------------------
# CalibrationConfig: outputs + objective_blocks + implicit block
# ---------------------------------------------------------------------------
class TestCalibrationConfigEnriched:
    def test_outputs_and_objective_blocks_round_trip(self):
        cfg = CalibrationConfig.model_validate(
            {
                "method": "cma_es",
                "max_trials": 80,
                "objective": "rmse",
                "variable": "head",
                "outputs": {
                    "head_A": {
                        "variable": "head",
                        "support": "point",
                        "x": 100.0,
                        "y": 0.0,
                        "observed_values": [42.1, 41.8, 41.5],
                    }
                },
                "objective_blocks": [
                    {
                        "name": "head_block",
                        "metric": "rmse",
                        "weight": 1.0,
                        "uses_outputs": ["head_A"],
                    }
                ],
            }
        )
        assert cfg.method == "cma_es"
        assert "head_A" in cfg.outputs
        assert cfg.outputs["head_A"].observed_values == [42.1, 41.8, 41.5]
        assert len(cfg.objective_blocks) == 1
        assert cfg.objective_blocks[0].name == "head_block"

    def test_persist_knobs_round_trip(self):
        cfg = CalibrationConfig.model_validate(
            {"persist_iteration_detail": "full", "materialize_candidates": True}
        )
        assert cfg.persist_iteration_detail == "full"
        assert cfg.materialize_candidates is True

    @pytest.mark.parametrize(
        ("key", "advice"),
        [
            ("rerun_best_with_outputs", "promoted by default"),
            ("candidates_root", "sessions/<case>/candidates/"),
            ("reuse_completed_phases", "--resume"),
        ],
    )
    def test_a_retired_key_is_refused_with_what_replaces_it(self, key, advice):
        with pytest.raises(ValidationError, match=key) as caught:
            CalibrationConfig.model_validate({key: True})
        assert advice in str(caught.value)

    def test_resume_session_field_is_rejected(self):
        with pytest.raises(ValidationError):
            CalibrationConfig.model_validate({"resume_session": "abcdef01"})

    def test_implicit_objective_block_built_from_objective_variable(self):
        cfg = CalibrationConfig.model_validate(
            {
                "objective": "nse",
                "variable": "discharge",
                "outputs": {
                    "discharge": {
                        "variable": "discharge",
                        "support": "boundary",
                        "boundary_id": "outlet",
                    }
                },
            }
        )
        assert len(cfg.objective_blocks) == 1
        block = cfg.objective_blocks[0]
        assert block.metric == "nse"
        assert block.uses_outputs == ["discharge"]

    def test_no_implicit_block_when_no_matching_output(self):
        cfg = CalibrationConfig.model_validate({"objective": "nse", "variable": "head"})
        assert cfg.objective_blocks == []

    def test_explicit_blocks_preserved_over_implicit(self):
        cfg = CalibrationConfig.model_validate(
            {
                "objective": "nse",
                "variable": "head",
                "outputs": {"head": {"variable": "head", "support": "cell", "row": 0, "col": 0}},
                "objective_blocks": [
                    {"name": "custom", "metric": "rmse", "uses_outputs": ["head"]}
                ],
            }
        )
        assert len(cfg.objective_blocks) == 1
        assert cfg.objective_blocks[0].name == "custom"

    def test_output_support_tag_is_required(self):
        payload = {"outputs": {"head_A": {"variable": "head", "x": 100.0, "y": 0.0}}}
        with pytest.raises(ValidationError, match="support"):
            CalibrationConfig.model_validate(payload)


# ---------------------------------------------------------------------------
# TOML round-trip with the enriched schema
# ---------------------------------------------------------------------------
class TestEnrichedTomlRoundTrip:
    def test_full_twin_benchmark_like_toml(self):
        toml_src = """
        [calibration]
        method   = "cma_es"
        max_trials = 80
        seed     = 42
        objective = "rmse"
        variable = "head"
        persist_iteration_detail = "full"
        materialize_candidates = true

        [calibration.parameters.K_aquifer]
        bounds = [1e-6, 1e-3]
        search_space = "log"
        target = "flow.param.K.field.value"
        mode   = "replace"

        [calibration.parameters.K_mult]
        bounds = [0.1, 10.0]
        target = "flow.param.K.field.value"
        mode   = "scale"

        [calibration.outputs.head_A]
        variable = "head"
        support  = "point"
        x        = 100.0
        y        = 0.0
        observed_values = [42.1, 41.8, 41.5]

        [calibration.outputs.outlet]
        variable    = "outlet_discharge"
        support     = "boundary"
        boundary_id = "outlet_drain"
        observed_values = [1.2, 1.1, 1.0]

        [[calibration.objective_blocks]]
        name   = "head_block"
        metric = "rmse"
        weight = 2.0
        uses_outputs = ["head_A"]
        normalize_cost = true

        [[calibration.objective_blocks]]
        name   = "discharge_block"
        metric = "nse"
        weight = 1.0
        uses_outputs = ["outlet"]
        """
        data = tomllib.loads(toml_src)
        cfg = CalibrationConfig.model_validate(data["calibration"])
        assert cfg.method == "cma_es"
        assert cfg.persist_iteration_detail == "full"
        assert cfg.materialize_candidates is True
        assert cfg.parameters["K_aquifer"].mode == "replace"
        assert cfg.parameters["K_aquifer"].target == "flow.param.K.field.value"
        assert cfg.parameters["K_mult"].mode == "scale"
        assert cfg.outputs["head_A"].x.to("m").magnitude == 100.0
        assert cfg.outputs["outlet"].boundary_id == "outlet_drain"
        assert len(cfg.objective_blocks) == 2
        assert cfg.objective_blocks[0].normalize_cost is True
        assert cfg.objective_blocks[1].metric == "nse"

    def test_extra_field_still_rejected_in_enriched_schema(self):
        payload = {
            "outputs": {
                "head_A": {
                    "variable": "head",
                    "support": "point",
                    "x": 100.0,
                    "y": 0.0,
                    "unknown_key": 1.0,
                }
            }
        }
        with pytest.raises(ValidationError, match="Extra inputs"):
            CalibrationConfig.model_validate(payload)


# ---------------------------------------------------------------------------
# Tightening validators (Phase 3)
# ---------------------------------------------------------------------------
class TestParameterDeclTightenings:
    def test_bounds_must_be_pair(self):
        with pytest.raises(ValidationError, match="bounds"):
            CalibParameterDecl.model_validate({"bounds": [1.0]})
        with pytest.raises(ValidationError, match="bounds"):
            CalibParameterDecl.model_validate({"bounds": [1.0, 2.0, 3.0]})

    def test_bounds_pair_accepted(self):
        decl = CalibParameterDecl.model_validate({"bounds": [1.0, 2.0]})
        assert decl.bounds == [1.0, 2.0]


class TestObjectiveBlockTightenings:
    def test_uses_outputs_must_not_be_empty(self):
        with pytest.raises(ValidationError, match="uses_outputs"):
            CalibObjectiveBlockDecl.model_validate({"name": "b", "uses_outputs": []})


class TestCalibrationConfigCrossFieldValidators:
    def test_uses_outputs_must_reference_declared_output(self):
        with pytest.raises(ValidationError, match="uses_outputs"):
            CalibrationConfig.model_validate(
                {
                    "outputs": {
                        "head_A": {"variable": "head", "support": "point", "x": 0.0, "y": 0.0}
                    },
                    "objective_blocks": [
                        {"name": "b", "metric": "rmse", "uses_outputs": ["unknown"]}
                    ],
                }
            )

    def test_materialize_candidates_needs_no_root(self):
        cfg = CalibrationConfig.model_validate({"materialize_candidates": True})
        assert cfg.materialize_candidates is True


# From test_method_names_are_published.py
# Every optimizer the package registers is named in the schema.
#
# ``method`` is a free string so an out-of-tree optimizer stays possible, which
# means nothing but the description tells a reader which names work. The name of
# the stream-network stage, ``bisection``, used to appear in no description, in no
# ``Literal`` and in no generated page, so the only way to find it was to read the
# adapter decorators.


def _description(model: type, field_name: str) -> str:
    return model.model_fields[field_name].description or ""


def test_the_section_method_names_every_registered_optimizer() -> None:
    text = _description(CalibrationConfig, "method")

    missing = [name for name in available_optimizers() if f"'{name}'" not in text]
    assert missing == []


def test_the_phase_method_names_every_registered_optimizer() -> None:
    text = _description(CalibPhaseDecl, "method")

    missing = [name for name in available_optimizers() if f"'{name}'" not in text]
    assert missing == []


def test_the_stream_network_stage_is_findable() -> None:
    for model in (CalibrationConfig, CalibPhaseDecl):
        assert "bisection" in _description(model, "method")


# From test_network_output_reads_one_state.py
# A network output's ``time`` reads exactly one state: 'last', 'first' or a date.
#
# Decision 9 (etude-reseau-observe-2026-09-27.md, option B): 'all' and a list of
# dates used to reach the criterion as the whole stack, silently scored at its
# last state instead of the one named. Both are refused at configuration load.
# One date names one state, the period that holds it, and is served that row
# (``test_metrics_solver_extract.py``).


def _kwargs__network_output(**overrides: object) -> dict[object, object]:
    base: dict[object, object] = {"support": "network", "stream_geometry_path": "streams.gpkg"}
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    ("overrides", "time"), [({}, "last"), ({"time": "last"}, "last"), ({"time": "first"}, "first")]
)
def test_a_network_output_reads_one_state(overrides: dict, time: str) -> None:
    assert CalibOutputNetwork(**_kwargs__network_output(**overrides)).time == time


@pytest.mark.parametrize(
    ("time", "said"),
    [
        ("all", ["one state", "'last', 'first' or one date", "'extent' table"]),
        (["2002-08-31"], ["one state", "'last', 'first' or one date"]),
    ],
    ids=["all", "list_of_dates"],
)
def test_a_network_time_of_several_states_is_refused(time, said: list[str]) -> None:
    with pytest.raises(ValidationError) as excinfo:
        CalibOutputNetwork(**_kwargs__network_output(time=time))
    for text in said:
        assert text in str(excinfo.value)


# From test_phase_schema.py
# What a phase table has to say before the first solve runs.


def _config__phase_schema(phases: list[dict], **overrides) -> CalibrationConfig:
    payload = {
        "method": "grid",
        "parameters": {
            "K": {
                "bounds": [1e-9, 1e-3],
                "search_space": "log",
                "path": "flow.param.K.field.value",
            },
            "Sy": {"bounds": [1e-3, 3e-1], "path": "flow.param.Sy.field.value"},
        },
        "outputs": {
            "q": {
                "variable": "discharge",
                "support": "boundary",
                "boundary_id": "outlet",
                "observed_values": [1.0, 2.0],
            }
        },
        "objective_blocks": [{"name": "b", "metric": "rmse", "uses_outputs": ["q"]}],
        "phases": phases,
        **overrides,
    }
    return CalibrationConfig.model_validate(payload)


STEADY = {
    "name": "steady_k_over_r",
    "method": "bisection",
    "parameters": ["K"],
    "freeze_on_success": True,
}
TRANSIENT = {
    "name": "transient_sy",
    "method": "grid",
    "parameters": ["Sy"],
    "depends_on": "steady_k_over_r",
}


class TestDefault:
    def test_a_configuration_without_phases_is_unchanged(self) -> None:
        cfg = CalibrationConfig.model_validate({"method": "grid"})
        assert cfg.phases is None

    def test_an_absent_table_leaves_the_resume_hash_untouched(self) -> None:
        # The resume lock hashes the configuration with exclude_none, so the
        # field has to default to None and not to an empty list, otherwise
        # every checkpoint in the wild stops being resumable.
        cfg = CalibrationConfig.model_validate({"method": "grid"})
        assert "phases" not in json.loads(cfg.model_dump_json(exclude_none=True))


class TestAccepted:
    def test_two_phases_in_order(self) -> None:
        cfg = _config__phase_schema(
            [{**STEADY, "objective_blocks": ["b"]}, {**TRANSIENT, "variable": "head"}]
        )
        assert [phase.name for phase in cfg.phases] == ["steady_k_over_r", "transient_sy"]
        assert cfg.phases[0].method == "bisection"
        assert cfg.phases[1].depends_on == "steady_k_over_r"

    def test_a_phase_selects_outputs_and_blocks_by_name(self) -> None:
        cfg = _config__phase_schema([{**STEADY, "outputs": ["q"], "objective_blocks": ["b"]}])
        assert cfg.phases[0].outputs == ["q"]

    def test_a_parameter_that_names_its_quantity_instead_of_a_path(self) -> None:
        """The name is resolved against the project catalog once it is loaded.

        This section is validated on its own, without the project it belongs to,
        so a missing path is not something it can judge. What would be injected
        is settled by the resolution, and by the preflight after it.
        """
        cfg = CalibrationConfig.model_validate(
            {
                "method": "grid",
                "parameters": {"K": {"bounds": [1.0, 2.0]}},
                "phases": [{"name": "p", "parameters": ["K"]}],
            }
        )

        assert cfg.parameters["K"].resolve_target() is None

    def test_two_phases_may_freeze_the_same_path(self) -> None:
        # The second moves K again from the value the first passed on, and the
        # later value wins. The staged report names both.
        cfg = _config__phase_schema(
            [
                {**STEADY, "objective_blocks": ["b"]},
                {
                    "name": "again",
                    "parameters": ["K"],
                    "objective_blocks": ["b"],
                    "freeze_on_success": True,
                },
            ]
        )

        assert [phase.name for phase in cfg.phases] == ["steady_k_over_r", "again"]

    def test_an_empty_selection_means_every_declaration(self) -> None:
        cfg = _config__phase_schema([STEADY])
        assert cfg.phases[0].outputs == []
        assert cfg.phases[0].objective_blocks == []


class TestRefused:
    @pytest.mark.parametrize(
        ("phases", "overrides", "match"),
        [
            pytest.param(
                # Silence reads "every declared block", which is what a lone phase wants
                # and what a staged table must never do: the second stage would carry
                # the criterion the first one was built for, and still report a number.
                [{**STEADY, "objective_blocks": ["b"]}, TRANSIENT],
                {},
                "names neither objective_blocks",
                id="a_staged_phase_that_names_no_criterion",
            ),
            pytest.param([STEADY, {**STEADY}], {}, "declared twice", id="a_duplicate_phase_name"),
            pytest.param(
                [{**STEADY, "parameters": ["Kv"]}],
                {},
                "undeclared parameter",
                id="an_undeclared_parameter",
            ),
            pytest.param(
                # The calibrated value would be overwritten, and nothing downstream
                # would say which one the model ran with.
                [
                    {**STEADY, "objective_blocks": ["b"]},
                    {
                        **TRANSIENT,
                        "objective_blocks": ["b"],
                        "overrides": {"flow.param.K.field.value": 1e-5},
                    },
                ],
                {},
                "which phase 'steady_k_over_r' freezes",
                id="an_override_on_a_path_an_earlier_phase_froze",
            ),
            pytest.param(
                [TRANSIENT, STEADY],
                {},
                "not declared before it",
                id="a_dependency_declared_after_its_dependant",
            ),
            pytest.param(
                [{**TRANSIENT, "depends_on": "nowhere"}],
                {},
                "not declared before it",
                id="a_dependency_on_an_unknown_phase",
            ),
            pytest.param(
                [{**STEADY, "outputs": ["heads"]}],
                {},
                "undeclared output",
                id="an_undeclared_output",
            ),
            pytest.param(
                [{**STEADY, "objective_blocks": ["nowhere"]}],
                {},
                "undeclared objective block",
                id="an_undeclared_objective_block",
            ),
            pytest.param(
                [{**STEADY, "scoring_window": {"start": "2012-01-01"}}],
                {"warmup_periods": 5},
                "pick one convention",
                id="a_window_and_a_sample_count_together",
            ),
        ],
    )
    def test_a_phase_table_that_cannot_run_is_refused(self, phases, overrides, match) -> None:
        with pytest.raises(ValueError, match=match):
            _config__phase_schema(phases, **overrides)

    def test_a_lone_phase_may_stay_silent(self) -> None:
        cfg = _config__phase_schema([STEADY])

        assert cfg.phases[0].objective_blocks == []


class TestNetworkCriterionPairing:
    """A criterion reads the supports it declares, and no list says which.

    The pairing used to be a tuple of metric names written in the validator.
    It comes from the criterion now, so the two refusals below are one rule read
    from either side, and the message names what could read the output rather
    than repeating a list held here.
    """

    def _network_config(self, blocks: list[dict]) -> CalibrationConfig:
        return CalibrationConfig.model_validate(
            {
                "method": "bisection",
                "parameters": {"K": {"bounds": [1e-9, 1e-3], "path": "flow.param.K.field.value"}},
                "outputs": {
                    "net": {"support": "network", "stream_geometry_path": "streams.gpkg"},
                    "q": {
                        "variable": "discharge",
                        "support": "boundary",
                        "boundary_id": "outlet",
                        "observed_values": [1.0, 2.0],
                    },
                },
                "objective_blocks": blocks,
            }
        )

    def test_the_gap_metric_on_a_network_output_is_accepted(self) -> None:
        cfg = self._network_config(
            [
                {"name": "network", "metric": "distance_gap", "uses_outputs": ["net"]},
                # nse rather than rmse: a cost in meters and one in m3/s do not
                # add up, and that refusal is a different rule from this one.
                {"name": "discharge", "metric": "nse", "uses_outputs": ["q"]},
            ]
        )
        assert cfg.objective_blocks[0].metric == "distance_gap"

    @pytest.mark.parametrize(
        ("block", "match"),
        [
            pytest.param(
                # distance_gap reads the pair (D_so, D_os); a discharge series is not
                # that pair, and scoring it would produce a number with no meaning.
                {"name": "wrong", "metric": "distance_gap", "uses_outputs": ["q"]},
                "that criterion reads",
                id="the_gap_metric_on_anything_else",
            ),
            pytest.param(
                {"name": "b", "metric": "rmse", "uses_outputs": ["q"]},
                "can be read by none of the criteria",
                id="a_network_output_nobody_scores",
            ),
            pytest.param(
                # Read off the registry, so a criterion added for the network appears
                # here without a second list to remember.
                {"name": "b", "metric": "rmse", "uses_outputs": ["q"]},
                "distance_gap, distance_mean",
                id="the_refusal_names_what_could_have_read_it",
            ),
            pytest.param(
                # The other side of the same rule: it used to be unwritten, and scoring
                # the pair against an observed vector returns a number all the same.
                {"name": "b", "metric": "rmse", "uses_outputs": ["net", "q"]},
                "that criterion reads",
                id="a_series_metric_on_a_network_output",
            ),
        ],
    )
    def test_a_block_that_pairs_the_wrong_supports_is_refused(self, block, match) -> None:
        with pytest.raises(ValueError, match=match):
            self._network_config([block])


# From test_precision_and_cost_margin_name_what_they_bound.py
# ``precision`` bounds the parameter, ``cost_margin`` bounds the cost.
#
# ``tolerance`` named both: how finely a search pins a parameter, and how far a
# cost may sit from the best before a trial stops counting as tied with it. The
# first is a ``precision`` on the parameter. The second is a ``cost_margin``
# that carries its unit, ``"5%"`` of the best cost or ``"75 m"`` of network
# distance, so the ``mode`` key that said how to read a bare number is gone. A
# key renamed is refused with the new name, the doctor rewrites the file, and a
# sealed run config still reads.


PROTOCOL = "matching_hydrographic_network"
K = {"K": {"bounds": [1e-7, 1e-3]}}


def _section(**fields: Any) -> CalibrationConfig:
    return CalibrationConfig.model_validate({"parameters": K, **fields})


def _phase(**fields: Any) -> CalibPhaseDecl:
    return CalibPhaseDecl.model_validate({"name": "sy", "parameters": ["K"], **fields})


# -- precision ---------------------------------------------------------------
def test_the_section_a_phase_and_the_protocol_name_precision() -> None:
    assert _section(precision=0.01).precision == 0.01
    assert _phase(precision=0.05).precision == 0.05
    declared = CalibrationProtocolDecl.model_validate(
        {"name": PROTOCOL, "steady_precision": 0.01, "transient_precision": 0.05}
    )
    assert (declared.steady_precision, declared.transient_precision) == (0.01, 0.05)


@pytest.mark.parametrize(
    ("build", "new"),
    [
        (lambda: _section(tolerance=0.01), "'precision'"),
        (lambda: _phase(tolerance=0.01), "'precision'"),
        (
            lambda: CalibrationProtocolDecl.model_validate(
                {"name": PROTOCOL, "steady_tolerance": 0.01}
            ),
            "'steady_precision'",
        ),
        (
            lambda: CalibrationProtocolDecl.model_validate(
                {"name": PROTOCOL, "transient_tolerance": 0.01}
            ),
            "'transient_precision'",
        ),
    ],
)
def test_tolerance_is_refused_with_the_name_that_replaces_it(build: Any, new: str) -> None:
    with pytest.raises(ValidationError, match="is not accepted any more: renamed") as refused:
        build()

    assert new in str(refused.value)
    assert "hmp doctor --fix-config" in str(refused.value)


# -- cost_margin: what a file may write --------------------------------------
@pytest.mark.parametrize("text", ["5%", " 5 % ", "0.5%", "75 m", "25m", "0.1 km", "1e2 m"])
def test_a_margin_is_a_share_of_the_best_cost_or_a_length(text: str) -> None:
    decl = CalibUncertaintyDecl.model_validate({"cost_margin": text})

    assert decl.cost_margin is not None
    assert CalibPhaseUncertaintyDecl.model_validate({"cost_margin": text}).cost_margin


def test_the_margin_is_read_into_its_kind_and_its_value() -> None:
    share = parse_cost_margin("5%")
    assert (share.kind, share.value) == ("relative", pytest.approx(0.05))
    length = parse_cost_margin("0.1 km")
    assert (length.kind, length.value) == ("absolute", pytest.approx(100.0))


@pytest.mark.parametrize("value", [0.05, 25, 25.0, "0.05", "25", True])
def test_a_bare_number_is_refused_because_it_has_no_unit(value: object) -> None:
    with pytest.raises(ValidationError, match=r"write '5%' or '25 m'"):
        CalibUncertaintyDecl.model_validate({"cost_margin": value})
    with pytest.raises(ValidationError, match=r"write '5%' or '25 m'"):
        CalibPhaseUncertaintyDecl.model_validate({"cost_margin": value})


@pytest.mark.parametrize("text", ["0%", "-5%", "0 m", "-3 m", "abc", "5 s", "% 5", "", "nan %"])
def test_a_margin_that_is_not_a_positive_share_or_length_is_refused(text: str) -> None:
    with pytest.raises(ValidationError, match="cost_margin"):
        CalibUncertaintyDecl.model_validate({"cost_margin": text})


def test_tolerance_and_mode_of_the_uncertainty_are_refused_naming_cost_margin() -> None:
    for model in (CalibUncertaintyDecl, CalibPhaseUncertaintyDecl):
        for key, value in (("tolerance", 0.05), ("mode", "relative")):
            with pytest.raises(ValidationError, match="renamed to 'cost_margin'") as refused:
                model.model_validate({key: value})
            assert "hmp doctor --fix-config" in str(refused.value)


def test_a_phase_keeps_the_error_of_a_bad_section_margin_out_of_its_name() -> None:
    with pytest.raises(ValidationError, match="cost_margin"):
        _section(uncertainty={"cost_margin": 0.05})


# -- cost_margin: what a search scores ---------------------------------------
def test_a_length_margin_is_refused_on_a_search_that_is_not_a_network_distance() -> None:
    with pytest.raises(ValidationError, match="network distance"):
        _section(uncertainty={"cost_margin": "75 m"})
    with pytest.raises(ValidationError, match="network distance"):
        _section(
            phases=[{"name": "sy", "parameters": ["K"], "uncertainty": {"cost_margin": "75 m"}}]
        )

    assert _section(objective="distance_gap", uncertainty={"cost_margin": "75 m"})
    assert _section(uncertainty={"cost_margin": "5%"})


def test_the_width_a_search_reads_follows_the_margin_it_was_given() -> None:
    cfg = _section(uncertainty={"cost_margin": "5%"})
    width = cfg.interval_width_for()
    assert (width.margin, width.kind, width.source) == (pytest.approx(0.05), "relative", "section")

    cfg = _section(objective="distance_gap", uncertainty={"cost_margin": "75 m"})
    width = cfg.interval_width_for()
    assert (width.margin, width.kind, width.source) == (pytest.approx(75.0), "absolute", "section")
    assert width.on_distances is True

    width = _section().interval_width_for()
    assert (width.margin, width.kind, width.source) == (pytest.approx(0.05), "relative", "default")
    width = _section(objective="distance_gap").interval_width_for()
    assert (width.margin, width.kind, width.rule) == (None, "absolute", "one mesh cell")
    assert set(width.to_dict()) == {"margin", "kind", "source", "on_distances", "rule"}


def test_a_length_margin_of_the_section_is_read_by_the_phases_that_score_distances() -> None:
    cfg = _section(
        outputs={
            "net": {"support": "network", "stream_geometry_path": "s.gpkg"},
            "q": {
                "variable": "discharge",
                "support": "boundary",
                "boundary_id": "outlet",
                "observed_values": [1.0, 2.0, 3.0],
            },
        },
        objective_blocks=[
            {"name": "network", "metric": "distance_gap", "uses_outputs": ["net"]},
            {"name": "hydrograph", "metric": "nse_log", "uses_outputs": ["q"]},
        ],
        phases=[
            {"name": "k", "parameters": ["K"], "objective_blocks": ["network"]},
            {"name": "sy", "parameters": ["K"], "objective_blocks": ["hydrograph"]},
        ],
        uncertainty={"cost_margin": "150 m"},
    )
    k_phase, sy_phase = cfg.phases

    assert cfg.interval_width_for(k_phase).margin == pytest.approx(150.0)
    assert cfg.interval_width_for(sy_phase).source == "default"
    assert cfg.uncertainty_for(sy_phase).cost_margin is None


# -- the doctor --------------------------------------------------------------
DISTANCES = '[calibration]\nobjective = "distance_gap"\n[calibration.uncertainty]\n{uncertainty}\n'
EFFICIENCY = "[calibration]\n[calibration.uncertainty]\n{uncertainty}\n"


@pytest.mark.parametrize(
    ("template", "uncertainty", "expected"),
    [
        (EFFICIENCY, "tolerance = 0.05", "5%"),
        (EFFICIENCY, 'tolerance = 0.1\nmode = "relative"', "10%"),
        (EFFICIENCY, "tolerance = 0.07", "7%"),
        (DISTANCES, "tolerance = 75.0", "75 m"),
        (DISTANCES, 'mode = "absolute"\ntolerance = 25', "25 m"),
        (DISTANCES, 'mode = "relative"\ntolerance = 0.2', "20%"),
    ],
)
def test_the_doctor_writes_the_unit_the_old_mode_implied(
    tmp_path: Path, template: str, uncertainty: str, expected: str
) -> None:
    path = tmp_path / "calibration.toml"
    path.write_text(template.format(uncertainty=uncertainty), encoding="utf-8")

    changes = fix_config_file(path)

    section = tomllib.loads(path.read_text(encoding="utf-8"))["calibration"]["uncertainty"]
    assert section == {"cost_margin": expected}
    assert any("cost_margin" in change for change in changes)


def test_the_doctor_leaves_an_absolute_width_that_has_no_unit_to_write(tmp_path: Path) -> None:
    path = tmp_path / "calibration.toml"
    path.write_text(
        EFFICIENCY.format(uncertainty='mode = "absolute"\ntolerance = 0.3'), encoding="utf-8"
    )

    changes = fix_config_file(path)

    section = tomllib.loads(path.read_text(encoding="utf-8"))["calibration"]["uncertainty"]
    assert section == {"mode": "absolute", "tolerance": 0.3}
    assert any("left" in change and "unit" in change for change in changes)


def test_the_doctor_leaves_a_width_it_cannot_read_the_search_of(tmp_path: Path) -> None:
    path = tmp_path / "calibration.toml"
    path.write_text(
        '[calibration]\nprotocol = "matching_hydrographic_network"\n'
        "[calibration.uncertainty]\ntolerance = 0.05\n",
        encoding="utf-8",
    )

    changes = fix_config_file(path)

    assert "tolerance = 0.05" in path.read_text(encoding="utf-8")
    assert any("protocol" in change and "left" in change for change in changes)


def test_the_doctor_reads_what_each_phase_scores_and_the_mode_it_inherits(tmp_path: Path) -> None:
    path = tmp_path / "calibration.toml"
    path.write_text(
        "[calibration.uncertainty]\n"
        'mode = "absolute"\n'
        "[[calibration.objective_blocks]]\n"
        'name = "network"\nmetric = "distance_gap"\n'
        "[[calibration.objective_blocks]]\n"
        'name = "hydrograph"\nmetric = "nse_log"\n'
        "[[calibration.phases]]\n"
        'name = "k"\nobjective_blocks = ["network"]\n'
        "uncertainty = { tolerance = 225.0 }\n"
        "[[calibration.phases]]\n"
        'name = "sy"\nobjective_blocks = { hydrograph = 99, network = 1 }\n'
        'uncertainty = { mode = "relative", tolerance = 0.1 }\n',
        encoding="utf-8",
    )

    fix_config_file(path)

    document = tomllib.loads(path.read_text(encoding="utf-8"))["calibration"]
    assert [phase["uncertainty"] for phase in document["phases"]] == [
        {"cost_margin": "225 m"},
        {"cost_margin": "10%"},
    ]
    assert "tolerance" not in path.read_text(encoding="utf-8")


def test_the_doctor_renames_the_precision_in_the_section_a_phase_and_the_protocol(
    tmp_path: Path,
) -> None:
    path = tmp_path / "calibration.toml"
    path.write_text(
        "[calibration]\ntolerance = 0.01  # one per cent\n"
        "[[calibration.phases]]\nname = 'a'\ntolerance = 0.05\n"
        "[calibration.protocol]\nname = 'matching_hydrographic_network'\n"
        "steady_tolerance = 0.01\ntransient_tolerance = 0.05\n",
        encoding="utf-8",
    )

    fix_config_file(path)

    text = path.read_text(encoding="utf-8")
    document = tomllib.loads(text)["calibration"]
    assert document["precision"] == 0.01
    assert document["phases"][0]["precision"] == 0.05
    assert (
        document["protocol"]["steady_precision"],
        document["protocol"]["transient_precision"],
    ) == (0.01, 0.05)
    assert "# one per cent" in text
    assert "tolerance" not in text


# -- a sealed run ------------------------------------------------------------
def test_a_sealed_document_reads_the_old_precision_and_width_keys() -> None:
    doc = {
        "calibration": {
            "tolerance": 0.02,
            "uncertainty": {"tolerance": 0.05},
            "objective_blocks": [
                {"name": "network", "metric": "distance_gap"},
                {"name": "hydrograph", "metric": "nse_log"},
            ],
            "phases": [
                {
                    "name": "k",
                    "tolerance": 0.01,
                    "objective_blocks": ["network"],
                    "uncertainty": {"tolerance": 80.0},
                },
                {
                    "name": "sy",
                    "objective_blocks": ["hydrograph"],
                    "uncertainty": {"mode": "absolute", "tolerance": 0.4},
                },
            ],
            "protocol": {"steady_tolerance": 0.01, "transient_tolerance": 0.05},
        }
    }

    migrate_sealed_config_doc(doc)

    section = doc["calibration"]
    assert section["precision"] == 0.02
    assert section["uncertainty"] == {"cost_margin": "5%"}
    k_phase, sy_phase = section["phases"]
    assert (k_phase["precision"], k_phase["uncertainty"]) == (0.01, {"cost_margin": "80 m"})
    # An absolute width on a search that is no distance has no unit: the run's
    # interval is read at the default, its calibrated value is untouched.
    assert sy_phase["uncertainty"] == {}
    assert section["protocol"] == {"steady_precision": 0.01, "transient_precision": 0.05}


def test_a_frozen_protocol_run_with_the_old_names_reads_back(tmp_path: Path) -> None:
    project = _project(tmp_path)
    toml = project / "project.toml"
    toml.write_text(
        PROJECT.replace(
            f'name = "{PROTOCOL}"',
            f'name = "{PROTOCOL}"\nsteady_precision = 0.02\ntransient_precision = 0.05'
            '\n\n[calibration.uncertainty]\ncost_margin = "5%"',
        ),
        encoding="utf-8",
    )
    cfg = HydroModPyConfig.from_toml(toml)
    run_dir = project / "runs" / "nancon"
    run_dir.mkdir(parents=True)
    frozen = portable_config_document(cfg, run_dir, project)
    old = re.sub(r"^precision = ", "tolerance = ", frozen, flags=re.MULTILINE)
    old = re.sub(r"\b(steady|transient)_precision\b", r"\1_tolerance", old)
    old = old.replace('cost_margin = "5%"', 'tolerance = 0.05\nmode = "relative"')
    assert old != frozen
    assert "tolerance" in old and "cost_margin" not in old
    sealed = run_dir / "config.toml"
    sealed.write_text(old, encoding="utf-8")

    replayed = HydroModPyConfig.from_toml(sealed)

    expected = [p.model_dump(mode="json") for p in cfg.calibration.phases]
    assert [p.model_dump(mode="json") for p in replayed.calibration.phases] == expected
    assert replayed.calibration.uncertainty.cost_margin == "5%"
    assert [phase.precision for phase in replayed.calibration.phases] == [0.02, 0.05]


# From test_schemas.py
# Unit tests for ``hydromodpy.calibration.config`` schemas.
#
# Ports the behavioral intent of the old ``test_config.py`` to the new
# :class:`CalibrationConfig`/``CalibParameterDecl`` pair. The old schema
# validated ``chronicle``/``bounds``/``calibration_method`` sections (all
# flattened at the top level); the new schema is a single ``[calibration]``
# block with structured parameter declarations. Tests below cover the
# equivalent ground:
#
# - a minimal valid payload validates cleanly,
# - unknown top-level and per-parameter keys are rejected (``extra="forbid"``),
# - ``method``/``save_runs``/``search_space``/``sampling`` literal constraints,
# - invalid ``max_trials`` / ``save_best_n`` values are rejected,
# - a small embedded TOML round-trips through ``tomllib.loads`` +
#   ``model_validate``.
#
# Case-specific chronicle configs (``brutsaert``/``groundwater_1d``/
# ``reservoir``) that existed in the old suite have been dropped: the new
# architecture does not ship their validators here, so porting those
# checks would require inventing API.


def _minimal_payload() -> dict:
    return {
        "method": "grid",
        "max_trials": 20,
        "save_runs": "none",
        "parameters": {
            "K": {"bounds": [1.0e-6, 1.0e-3], "search_space": "log"},
            "Sy": {"bounds": [0.02, 0.30]},
        },
    }


# ---------------------------------------------------------------------------
# CalibrationConfig top-level
# ---------------------------------------------------------------------------
class TestCalibrationConfigMinimalPayload:
    def test_empty_dict_yields_sensible_defaults(self):
        """An empty payload uses the declared defaults end-to-end."""
        cfg = CalibrationConfig.model_validate({})
        # Unwritten, the method follows from the criteria when the run starts.
        assert cfg.method is None
        assert cfg.max_trials == "auto"
        assert cfg.save_runs == "best_n"
        assert cfg.save_best_n == 1
        assert cfg.use_cache is True
        assert cfg.objective == "nse"
        assert cfg.variable == "head"
        assert cfg.parameters == {}

    def test_accepts_minimal_valid_payload(self):
        cfg = CalibrationConfig.model_validate(_minimal_payload())
        assert cfg.method == "grid"
        assert cfg.max_trials == 20
        assert set(cfg.parameters) == {"K", "Sy"}
        assert cfg.parameters["K"].search_space == "log"
        assert cfg.parameters["Sy"].search_space == "identity"  # default

    def test_parameters_typed_as_calib_parameter_decl(self):
        cfg = CalibrationConfig.model_validate(_minimal_payload())
        for decl in cfg.parameters.values():
            assert isinstance(decl, CalibParameterDecl)


class TestCalibrationConfigExtraForbidden:
    def test_unknown_top_level_key_is_rejected(self):
        payload = _minimal_payload()
        payload["legacy_section"] = {"K": 1.0e-4}
        with pytest.raises(ValidationError, match="Extra inputs"):
            CalibrationConfig.model_validate(payload)

    def test_unknown_per_parameter_key_is_rejected(self):
        payload = _minimal_payload()
        payload["parameters"]["K"]["legacy_alias"] = True
        with pytest.raises(ValidationError, match="Extra inputs"):
            CalibrationConfig.model_validate(payload)


# ---------------------------------------------------------------------------
# Literal field constraints
# ---------------------------------------------------------------------------
class TestCalibrationConfigMethodLiteral:
    @pytest.mark.parametrize("method", ["bayesian", "genetic", "GRID"])
    def test_rejects_unsupported_method(self, method: str):
        cfg = CalibrationConfig.model_validate({"method": method})
        with pytest.raises(ValueError, match="Unknown calibration method"):
            cfg.validate_registry()


class TestCalibrationConfigNumericBounds:
    def test_max_trials_must_be_at_least_one(self):
        with pytest.raises(ValidationError, match="max_trials"):
            CalibrationConfig.model_validate({"max_trials": 0})

    def test_max_trials_rejects_negative(self):
        with pytest.raises(ValidationError, match="max_trials"):
            CalibrationConfig.model_validate({"max_trials": -3})

    def test_save_best_n_cannot_be_negative(self):
        with pytest.raises(ValidationError, match="save_best_n"):
            CalibrationConfig.model_validate({"save_best_n": -1})

    def test_batch_size_must_be_at_least_one(self):
        with pytest.raises(ValidationError, match="batch_size"):
            CalibrationConfig.model_validate({"batch_size": 0})


# ---------------------------------------------------------------------------
# CalibParameterDecl
# ---------------------------------------------------------------------------
class TestCalibParameterDeclDefaults:
    def test_empty_declaration_inherits_defaults(self):
        decl = CalibParameterDecl.model_validate({})
        assert decl.bounds is None
        assert decl.search_space == "identity"
        assert decl.sampling == "uniform"
        assert decl.path is None
        assert decl.units is None

    def test_rejects_unknown_keys(self):
        with pytest.raises(ValidationError, match="Extra inputs"):
            CalibParameterDecl.model_validate({"legacy_hint": 1.0})


class TestCalibOutputDeclSelectors:
    def test_output_support_tag_is_required(self):
        with pytest.raises(ValidationError, match="support"):
            validate_calib_output({"variable": "head", "x": 10.0, "y": 20.0})

    def test_point_accepts_geojson_geometry(self):
        decl = validate_calib_output(
            {
                "variable": "head",
                "support": "point",
                "geometry": {"type": "Point", "coordinates": [10.0, 20.0]},
            }
        )
        assert decl.geometry["type"] == "Point"

    def test_cell_requires_structural_selector(self):
        with pytest.raises(ValidationError, match="row"):
            validate_calib_output({"variable": "head", "support": "cell"})

    def test_cell_accepts_row_col(self):
        decl = validate_calib_output({"variable": "head", "support": "cell", "row": 2, "col": 3})
        assert decl.row == 2
        assert decl.col == 3

    def test_cell_refuses_cell_id(self):
        with pytest.raises(ValidationError, match="'cell_id' is not accepted any more"):
            validate_calib_output({"variable": "head", "support": "cell", "cell_id": 42})


# ---------------------------------------------------------------------------
# TOML round-trip (the old test exercised load_calibration_toml; the new
# architecture uses plain tomllib + model_validate directly)
# ---------------------------------------------------------------------------
class TestTomlRoundTrip:
    def test_full_section_roundtrip(self):
        toml_src = """
        [calibration]
        method = "grid"
        max_trials = 50
        save_runs = "best_n"
        save_best_n = 5
        seed = 42
        objective = "kge"
        variable = "head"

        [calibration.parameters.K_aquifer]
        bounds = [1e-6, 1e-3]
        search_space = "log"
        sampling = "log_uniform"
        path = "flow.properties.k_aquifer"

        [calibration.parameters.Sy]
        bounds = [0.02, 0.30]
        """
        data = tomllib.loads(toml_src)
        cfg = CalibrationConfig.model_validate(data["calibration"])
        assert cfg.method == "grid"
        assert cfg.max_trials == 50
        assert cfg.save_runs == "best_n"
        assert cfg.save_best_n == 5
        assert cfg.seed == 42
        assert cfg.objective == "kge"
        assert set(cfg.parameters) == {"K_aquifer", "Sy"}
        assert cfg.parameters["K_aquifer"].search_space == "log"
        assert cfg.parameters["K_aquifer"].sampling == "log_uniform"
        assert cfg.parameters["K_aquifer"].path == "flow.properties.k_aquifer"
        assert cfg.parameters["Sy"].search_space == "identity"

    def test_minimal_section_roundtrip(self):
        toml_src = """
        [calibration]
        method = "grid"
        """
        data = tomllib.loads(toml_src)
        cfg = CalibrationConfig.model_validate(data["calibration"])
        assert cfg.method == "grid"
        assert cfg.parameters == {}

    def test_toml_unknown_section_key_rejected(self):
        toml_src = """
        [calibration]
        method = "grid"
        legacy_toggle = true
        """
        data = tomllib.loads(toml_src)
        with pytest.raises(ValidationError, match="Extra inputs"):
            CalibrationConfig.model_validate(data["calibration"])


# From test_the_calibration_persistence_table_is_retired.py
# ``[calibration.persistence]`` is retired: nothing ever read it.
#
# The run a calibration promotes follows ``[simulation.results.persistence]``,
# and the session writes its journal whatever the table says. The table loads
# with a warning, so the configuration frozen by an earlier session, which spells
# out every default, still reads back, and the schema no longer offers it.


SECTION = {"parameters": {"K": {"bounds": [1e-7, 1e-3]}}}


def test_the_table_loads_with_a_warning_and_is_dropped() -> None:
    with pytest.warns(DeprecationWarning, match="persistence"):
        cfg = CalibrationConfig.model_validate({**SECTION, "persistence": {"save_zarr": False}})

    assert "persistence" not in cfg.model_dump()


def test_the_schema_no_longer_offers_it() -> None:
    assert "persistence" not in CalibrationConfig.model_json_schema()["properties"]


# From test_the_criterion_descends_d8_by_default.py
# The stream criterion descends D8 by default, as the paper does.
#
# Abherve et al. (2023) trace their distances with WhiteboxTools on a D8
# pointer. The default is one object, ``STREAM_CRITERION_DEFAULTS``, and every
# place that rebuilds the criterion reads it: a figure drawn on another graph
# than the trial scored shows a partition the numbers were never computed on.


SIZE = 6
CELL = 10.0


def _default(function) -> object:
    return inspect.signature(function).parameters["diagonal_neighbors"].default


def test_the_shared_default_is_the_paper_s_d8() -> None:
    assert STREAM_CRITERION_DEFAULTS.diagonal_neighbors is True
    assert CalibOutputNetwork.model_fields["diagonal_neighbors"].default is True


@pytest.mark.parametrize(
    "function",
    [
        build_network_geometry,
        build_downslope_metric,
        network_comparison_from_run,
        routing_surface_from_run,
        DepressionMap.render,
    ],
    ids=lambda function: function.__qualname__,
)
def test_every_rebuild_reads_the_same_default(function) -> None:
    assert _default(function) is STREAM_CRITERION_DEFAULTS.diagonal_neighbors


def _diagonal_plane() -> np.ndarray:
    """A surface dropping one meter east and one south, to the south-east corner."""
    rows = np.arange(SIZE, dtype=float)[:, None]
    cols = np.arange(SIZE, dtype=float)[None, :]
    return (100.0 - rows - cols).reshape(-1)


def _geometry(topography, connectivity, vertices, **overrides):
    n_cells = topography.size
    observed = np.zeros(n_cells, dtype=bool)
    observed[-1] = True
    return build_network_geometry(
        topography=topography,
        face_node_connectivity=connectivity,
        vertices=vertices,
        observed=observed,
        cell_area_m2=np.full(n_cells, CELL * CELL),
        mean_recharge_m_s=1e-8,
        tau_specific_ratio=0.0,
        delineated_catchment=np.ones(n_cells, dtype=bool),
        **overrides,
    )


def test_the_flood_the_graph_and_the_cap_walk_the_same_eight_neighbours() -> None:
    vertices, connectivity = quad_mesh(SIZE, SIZE, cell_size=CELL)

    geometry = _geometry(_diagonal_plane(), connectivity, vertices)

    assert geometry.metric.diagonal_neighbors is True
    # Every cell reaches the sealed outlet after the flood: it was fed the
    # graph the metric descends.
    assert np.all(np.isfinite(geometry.distance_to_observed[geometry.catchment]))
    # A diagonal step is sqrt(2) cells long, centroid to centroid, so the
    # longest descent is the diagonal of the square and not its two sides.
    assert geometry.saturation_cap_m == pytest.approx(math.sqrt(2.0) * CELL * (SIZE - 1))


def test_d4_is_still_there_when_asked_for() -> None:
    vertices, connectivity = quad_mesh(SIZE, SIZE, cell_size=CELL)

    geometry = _geometry(_diagonal_plane(), connectivity, vertices, diagonal_neighbors=False)

    assert geometry.metric.diagonal_neighbors is False
    assert geometry.saturation_cap_m == pytest.approx(2.0 * CELL * (SIZE - 1))


def test_the_simulated_network_closes_downslope_over_the_diagonal() -> None:
    vertices, connectivity = quad_mesh(SIZE, SIZE, cell_size=CELL)
    geometry = _geometry(_diagonal_plane(), connectivity, vertices)
    release = np.zeros(SIZE * SIZE)
    release[0] = 1.0  # the highest corner

    network = build_simulated_network(
        release, threshold_m3_s=geometry.threshold_m3_s, metric=geometry.metric
    ).network

    diagonal = [row * SIZE + row for row in range(SIZE)]
    assert sorted(np.flatnonzero(network).tolist()) == diagonal


def _triangulated(nrow: int, ncol: int) -> tuple[np.ndarray, np.ndarray]:
    """Split every quad of a grid into two triangles."""
    vertices, quads = quad_mesh(nrow, ncol, cell_size=CELL)
    triangles = []
    for a, b, c, d in np.asarray(quads)[:, :4]:
        triangles.append([a, b, c])
        triangles.append([a, c, d])
    return vertices, np.asarray(triangles, dtype=int)


def test_a_mesh_without_quadrilaterals_is_scored_on_shared_edges_without_failing() -> None:
    vertices, triangles = _triangulated(4, 4)
    centres = np.asarray(vertices, dtype=float)[triangles][:, :, :2].mean(axis=1)
    topography = 100.0 - centres[:, 0] / CELL - centres[:, 1] / CELL

    geometry = _geometry(topography, triangles, vertices)

    assert geometry.metric.diagonal_neighbors is False
    assert np.all(np.isfinite(geometry.distance_to_observed[geometry.catchment]))


# From test_the_recipe_window_is_the_run_window_when_declared.py
# The window the recipe runs is ``[metrics] window`` once the file declares one.
#
# Since the protocol writes ``[metrics] window`` on its transient stage
# (d0390cb68), the first year after the start is the recipe's window only for a
# file without ``[metrics] window``. ``hmp config check`` still compared a
# protocol ``scoring_window`` with the spin-up year, and called the spin-up window
# "written as the recipe runs it" while the recipe now scores the run window.


NAME = "matching_hydrographic_network"
TIME = SimpleNamespace(start_datetime="2000-01-01", end_datetime="2002-12-31")
PLAIN = SimpleNamespace(scoring_window=None, warmup_periods=None)
RUN_WINDOW = MetricsWindow.model_validate({"start": "2001-01-01", "end": "2002-06-30"})


def _same(window: dict, metrics_window=RUN_WINDOW) -> frozenset[str]:
    declared = CalibrationProtocolDecl.model_validate({"name": NAME, "scoring_window": window})
    return options_the_recipe_already_runs(declared, PLAIN, TIME, metrics_window=metrics_window)


def test_the_spin_up_window_is_away_from_a_recipe_that_scores_the_run_window() -> None:
    assert _same({"start": "2001-01-01"}) == frozenset()
    assert _same({"start": "2001-01-01", "end": "2002-12-31"}) == frozenset()


def test_the_run_window_written_out_runs_as_the_recipe() -> None:
    assert _same({"start": "2001-01-01", "end": "2002-06-30"}) == {"scoring_window"}


def test_without_a_run_window_the_spin_up_year_is_still_the_recipe_s() -> None:
    assert _same({"start": "2001-01-01"}, metrics_window=None) == {"scoring_window"}
