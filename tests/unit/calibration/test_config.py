"""The ``[calibration]`` section: schema, defaults and refusals, read when the file loads.

Covers parameters, outputs (point, cell, network), objective blocks, phases, validation
windows, cost margins and the D8 default of the stream criterion. Dates are ISO days,
lengths are meters, cost margins are a share ("5%") or a length ("75 m").
"""

from __future__ import annotations

import inspect
import math
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError

from hydromodpy.calibration.config import CalibrationConfig, apply_project_defaults
from hydromodpy.calibration.config_network import (
    CalibNetworkMap,
    CalibNetworkModel,
    CalibNetworkVerdict,
    CalibOutputNetwork,
)
from hydromodpy.calibration.config_objective import (
    CalibObjectiveBlockDecl,
    CalibParameterDecl,
    CalibrationProtocolDecl,
)
from hydromodpy.calibration.config_outputs import validate_calib_output
from hydromodpy.calibration.config_phases import (
    CalibPhaseDecl,
    CalibPhaseUncertaintyDecl,
    CalibUncertaintyDecl,
    _same_instant,
)
from hydromodpy.calibration.protocols.matching_hydrographic_network import (
    options_the_recipe_already_runs,
)
from hydromodpy.catchment.drainage.distance import build_downslope_metric
from hydromodpy.catchment.stream_network.geometry import build_network_geometry
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.exceptions import ConfigValidationError
from hydromodpy.core.scoring.cost_margin import parse_cost_margin
from hydromodpy.core.scoring.stream_defaults import STREAM_CRITERION_DEFAULTS
from hydromodpy.core.site.config import GaugeConflictError
from hydromodpy.core.time.window import nominal_step_days
from hydromodpy.display.figures.depression_map import DepressionMap
from hydromodpy.results.derive.stream_network.comparison import network_comparison_from_run
from hydromodpy.results.derive.stream_network.routing_surface import routing_surface_from_run
from hydromodpy.results.metric_rule import MetricsWindow
from tests._helpers.ugrid_meshes import quad_mesh
from tests.unit.config.test_config_migration import PROJECT, _project

GAUGE = "J0014010"


def _defaults(section: dict, *, gauge: str | None = GAUGE, window: dict | None = None) -> dict:
    return apply_project_defaults(section, site_gauge=gauge, metrics_window=window)


@pytest.mark.parametrize(
    "located",
    [{"x": 1.0, "y": 2.0}, {"geometry": "POINT (1 2)"}, {"observed_values": [1.0, 2.0]}],
    ids=["x_y", "geometry", "observed_values"],
)
def test_located_output_takes_no_gauge(located) -> None:
    output = {"support": "point", "variable": "head", **located}

    resolved = _defaults({"outputs": {"piezo": output}})

    assert resolved["outputs"]["piezo"] == output
    assert "observes" not in resolved["outputs"]["piezo"]


def test_other_station_without_position_is_refused() -> None:
    with pytest.raises(GaugeConflictError, match="calibration.outputs.q.observes = 'J9'"):
        _defaults({"outputs": {"q": {"support": "point", "observes": "J9"}}})


WINDOW = {"start": "2001-01-01", "end": "2002-12-31"}


def test_half_window_is_no_default() -> None:
    assert "window" not in _defaults({}, window={"start": "2001-01-01", "end": None})


@pytest.mark.parametrize(
    ("first", "last", "expected"),
    [
        ("2002-01-01", "2002-12-31", {"start": "2001-01-01", "end": "2001-12-31"}),
        ("2001-01-01", "2001-06-30", {"start": "2001-07-01", "end": "2002-12-31"}),
        ("2001-06-01", "2001-07-31", None),
        ("2002-01-01", None, WINDOW),
        ("not a date", "2002-12-31", WINDOW),
    ],
)
def test_validation_days_leave_the_default_window(first, last, expected) -> None:
    section = {"validation_window": {"start": first, "end": last}, "phases": [{"name": "t"}]}

    assert _defaults(section, window=WINDOW)["phases"][0].get("window") == expected
    del section["phases"]
    assert _defaults(section, window=WINDOW).get("window") == expected


@pytest.mark.parametrize(
    ("first", "last"),
    [
        ("2000-12-31", "2001-06-30"),
        ("2002-01-01", "2003-01-01"),
        ("2001-01-01", "2002-12-31"),
    ],
    ids=["before", "after", "all_of_it"],
)
def test_validation_window_filling_the_metrics_window_is_refused(first, last) -> None:
    declared = {"validation_window": {"start": first, "end": last}, "window": WINDOW}
    with pytest.raises(ConfigValidationError, match="leave days to calibrate on"):
        _defaults(declared, window=WINDOW)


_LATE = {"start": "2002-01-01", "end": "2002-12-31"}
_EARLY = {"start": "2001-01-01", "end": "2001-12-31"}
_ON_Q = {"name": "t", "objective_blocks": ["q"], "window": _EARLY}
_STEADY = {"name": "s", "objective_blocks": ["q"], "regime": "steady"}
_STEADY_NET = {"name": "s", "objective_blocks": ["net"], "regime": "steady"}


def _validated(*phases, outputs=("q", "net"), **fields) -> CalibrationConfig:
    """A section on a dated record and a network, its validation window in 2002."""
    declared = {
        "q": {"support": "point", "variable": "discharge", "observes": "J1"},
        "net": {"support": "network", "map": {"complete": "n.gpkg"}},
    }
    metric = {"q": "rmse", "net": "distance_gap"}
    return CalibrationConfig.model_validate(
        {
            "parameters": {"K": {"path": "flow.param.K.field.value", "bounds": [1e-6, 1e-3]}},
            "outputs": {name: declared[name] for name in outputs},
            "objective_blocks": [
                {
                    "name": name,
                    "metric": metric[name],
                    "uses_outputs": [name],
                    "normalize_cost": True,
                }
                for name in outputs
            ],
            "phases": [{"parameters": ["K"], **phase} for phase in phases] or None,
            "validation_window": _LATE,
            **fields,
        }
    )


@pytest.mark.parametrize(
    ("phases", "fields"),
    [
        ((), {"window": _EARLY}),
        ((), {"window": {"start": "2003-01-01"}}),
        ((_ON_Q,), {}),
        (({**_STEADY, "steady_window": _EARLY}, _ON_Q), {}),
        ((_STEADY_NET, _ON_Q), {}),
    ],
    ids=["before", "after", "phase", "steady_apart", "steady_on_a_network"],
)
def test_validation_window_apart_from_costs_is_accepted(phases, fields) -> None:
    assert _validated(*phases, **fields).validation_window.end == "2002-12-31"


@pytest.mark.parametrize(
    ("phases", "fields", "match"),
    [
        ((), {"validation_window": {"start": "2002-01-01"}}, "leaves a bound open"),
        ((), {"window": _EARLY, "outputs": ("net",)}, "nothing to score"),
        ((_STEADY,), {}, "nothing to score"),
        ((), {}, r"overlaps the window None to None of \[calibration\]"),
        ((), {"window": {"start": "2001-01-01"}}, "overlaps"),
        ((), {"window": {"start": "2002-12-31", "end": "2003-12-31"}}, "overlaps"),
        ((), {"window": {"start": "2001-01-01", "end": "2002-01-01"}}, "overlaps"),
        (({"name": "t", "objective_blocks": ["q"]},), {}, "overlaps .* of t"),
        (({**_ON_Q, "window": _LATE},), {"window": _EARLY}, "overlaps .* of t"),
        ((_STEADY, _ON_Q), {}, "overlaps .* of s"),
    ],
)
def test_validation_window_refusals(phases, fields, match) -> None:
    with pytest.raises(ValidationError, match=match):
        _validated(*phases, **fields)


def test_search_scored_on_validation_window() -> None:
    cfg = _validated({**_ON_Q, "name": "n", "objective_blocks": ["net"]}, _STEADY_NET, _ON_Q)

    assert [cfg.validation_scored_by(phase) for phase in cfg.phases] == [False, False, True]
    assert _validated(window=_EARLY).validation_scored_by(None) is True
    assert CalibrationConfig().validation_scored_by(None) is False


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


def test_mixed_units_are_refused() -> None:
    with pytest.raises(ValueError, match="unit"):
        CalibrationConfig.model_validate(_config([_rmse("heads", "head"), _rmse("flows", "q")]))


def test_raw_residual_beside_scores_is_refused() -> None:
    blocks = [_rmse("heads", "head"), {"name": "flows", "metric": "nse", "uses_outputs": ["q"]}]
    with pytest.raises(ValueError, match="pure numbers: 'heads' on head"):
        CalibrationConfig.model_validate(_config(blocks))


def test_path_and_target_are_exclusive() -> None:
    with pytest.raises(ValueError, match="two names for one address"):
        CalibParameterDecl.model_validate({"path": "a.b", "target": "a.c"})


def _network(**tables: object) -> CalibOutputNetwork:
    return CalibOutputNetwork(**{"map": ONE_MAP, **tables})


ONE_MAP = {"complete": "c.gpkg"}
TWO_MAPS = {**ONE_MAP, "permanent": "p.gpkg"}
EXTENT = {"extent": {"flowing_at_least": "1 month"}}


_SHARES = {"permanent": 0.5, "complete": 0.5}
_REFUSED_NETWORK_OUTPUTS = {
    "no map": ({"map": {}}, "no complete map"),
    "the permanent map alone": ({"map": {"permanent": "p.gpkg"}}, "no complete map"),
    "two maps and no role": ({"map": TWO_MAPS}, "does not say what it calibrates on"),
    "a role with one map": ({"map": {**ONE_MAP, "calibrate_on": "complete"}}, "only the complete"),
    "a share in one state": ({"map": {**TWO_MAPS, "calibrate_on": _SHARES}}, "has one cost"),
    "shares that do not sum to one": (
        {"map": {**TWO_MAPS, "calibrate_on": {"permanent": 0.6, "complete": 0.6}}},
        "calibrate_on sums to 1.2",
    ),
    "heads under crossing": (
        {"map": {**ONE_MAP, "drawn_by": "crossing", "heads": {}}},
        "map.heads is read only under drawn_by = 'heads', and drawn_by = 'crossing'",
    ),
    "a zero radius": ({"map": {**ONE_MAP, "heads": {"radius": "0 m"}}}, "radius = 0 m"),
    "an accuracy beside a length": (
        {"map": {**ONE_MAP, "position_accuracy": "50 m"}, "verdict": {"validity_length": "9 m"}},
        "enters the automatic validity length only",
    ),
    "a zero validity": ({"verdict": {"validity_length": "0 m"}}, "validity_length = 0 m"),
    "a time beside the extent": ({"model": EXTENT, "time": "first"}, "time = 'first'"),
    "a zero flow": ({"model": {"extent": {"flowing_at_least": "0 d"}}}, "longer than zero"),
}


@pytest.mark.parametrize(
    ("tables", "said"), _REFUSED_NETWORK_OUTPUTS.values(), ids=_REFUSED_NETWORK_OUTPUTS.keys()
)
def test_network_output_refusals(tables: dict, said: str) -> None:
    with pytest.raises(ValidationError, match=re.escape(said)):
        _network(**tables)


@pytest.mark.parametrize(
    ("written", "permanent", "complete"),
    [
        ({"complete": "c.gpkg"}, 0.0, 1.0),
        ({**TWO_MAPS, "calibrate_on": "permanent"}, 1.0, 0.0),
        ({**TWO_MAPS, "calibrate_on": "complete"}, 0.0, 1.0),
        ({**TWO_MAPS, "calibrate_on": {"permanent": 0.25, "complete": 0.75}}, 0.25, 0.75),
    ],
)
def test_map_role_gives_shares(written, permanent, complete) -> None:
    weights = CalibNetworkMap(**written).bound_weights

    assert (weights.permanent, weights.complete) == (permanent, complete)


def test_sealed_read_takes_no_map() -> None:
    written = {"map": {"permanent": "p.gpkg", "calibrate_on": "permanent"}}

    output = CalibOutputNetwork.model_validate(written, context={"validation_context": "snapshot"})

    assert (output.map.complete, output.map.permanent) == (None, Path("p.gpkg"))


SUPPORTS = [
    ("point", {"variable": "head", "x": 0.0, "y": 0.0}),
    ("boundary", {"variable": "discharge", "boundary_id": "drainage"}),
    ("cell", {"variable": "head", "row": 0, "col": 0}),
    ("lake", {"variable": "stage", "lake_id": "lac0"}),
]


@pytest.mark.parametrize(("support", "where"), SUPPORTS)
@pytest.mark.parametrize("reducer", ["mean", "sum", "last"])
def test_reducer_beside_observes_is_refused(support: str, where: dict, reducer: str) -> None:
    with pytest.raises(ValidationError, match="reduced value is never scored"):
        validate_calib_output({"support": support, "observes": "PZ1", "reducer": reducer, **where})


@pytest.mark.parametrize(("support", "where"), SUPPORTS)
def test_list_of_dates_is_refused(support: str, where: dict) -> None:
    with pytest.raises(ValidationError, match="selects nothing"):
        validate_calib_output({"support": support, "time": ["2020-01-01"], **where})


H = {"variable": "head", "support": "point", "x": 10.0, "y": 20.0, "observed_values": [1.0, 2.0]}


def _output_section(**section: object) -> CalibrationConfig:
    payload = {"parameters": {"K": {"bounds": [1e-7, 1e-3], "path": "flow.param.K.field.value"}}}
    payload.update(section)
    return CalibrationConfig.model_validate(payload)


def test_unscored_output_is_refused() -> None:
    with pytest.raises(ValidationError, match=r"\['h'\] are declared and nothing scores them"):
        _output_section(outputs={"h": H})


def test_cell_output_refuses_timestamps():
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


def test_uses_outputs_must_be_declared():
    with pytest.raises(ValidationError, match="uses_outputs"):
        CalibrationConfig.model_validate(
            {
                "outputs": {"head_A": {"variable": "head", "support": "point", "x": 0.0, "y": 0.0}},
                "objective_blocks": [{"name": "b", "metric": "rmse", "uses_outputs": ["unknown"]}],
            }
        )


def _description(model: type, field_name: str) -> str:
    return model.model_fields[field_name].description or ""


def test_bisection_is_in_method_description() -> None:
    for model in (CalibrationConfig, CalibPhaseDecl):
        assert "bisection" in _description(model, "method")


def _network_kwargs(**overrides: object) -> dict[object, object]:
    base: dict[object, object] = {"support": "network", "map": {"complete": "streams.gpkg"}}
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    ("time", "said"),
    [
        ("all", ["one state", "'last', 'first' or one date", "'model.extent' table"]),
        (["2002-08-31"], ["one state", "'last', 'first' or one date"]),
    ],
    ids=["all", "list_of_dates"],
)
def test_network_time_of_several_states_is_refused(time, said: list[str]) -> None:
    with pytest.raises(ValidationError) as excinfo:
        CalibOutputNetwork(**_network_kwargs(time=time))
    for text in said:
        assert text in str(excinfo.value)


def _phase_section(phases: list[dict], **overrides) -> CalibrationConfig:
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
    ],
)
def test_phase_table_refusals(phases, overrides, match) -> None:
    with pytest.raises(ValueError, match=match):
        _phase_section(phases, **overrides)


def _network_config(blocks: list[dict]) -> CalibrationConfig:
    return CalibrationConfig.model_validate(
        {
            "method": "bisection",
            "parameters": {"K": {"bounds": [1e-9, 1e-3], "path": "flow.param.K.field.value"}},
            "outputs": {
                "net": {"support": "network", "map": {"complete": "streams.gpkg"}},
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
def test_block_on_wrong_support_is_refused(block, match) -> None:
    with pytest.raises(ValueError, match=match):
        _network_config([block])


PROTOCOL = "matching_hydrographic_network"
K = {"K": {"bounds": [1e-7, 1e-3]}}


def _section(**fields: Any) -> CalibrationConfig:
    return CalibrationConfig.model_validate({"parameters": K, **fields})


def _phase(**fields: Any) -> CalibPhaseDecl:
    return CalibPhaseDecl.model_validate({"name": "sy", "parameters": ["K"], **fields})


def test_margin_kind_and_value() -> None:
    share = parse_cost_margin("5%")
    assert (share.kind, share.value) == ("relative", pytest.approx(0.05))
    length = parse_cost_margin("0.1 km")
    assert (length.kind, length.value) == ("absolute", pytest.approx(100.0))


@pytest.mark.parametrize("value", [0.05, 25, 25.0, "0.05", "25", True])
def test_bare_margin_is_refused(value: object) -> None:
    with pytest.raises(ValidationError, match=r"write '5%' or '25 m'"):
        CalibUncertaintyDecl.model_validate({"cost_margin": value})
    with pytest.raises(ValidationError, match=r"write '5%' or '25 m'"):
        CalibPhaseUncertaintyDecl.model_validate({"cost_margin": value})


@pytest.mark.parametrize("text", ["0%", "-5%", "0 m", "-3 m", "abc", "5 s", "% 5", "", "nan %"])
def test_invalid_margin_is_refused(text: str) -> None:
    with pytest.raises(ValidationError, match="cost_margin"):
        CalibUncertaintyDecl.model_validate({"cost_margin": text})


def test_length_margin_needs_network_distance() -> None:
    with pytest.raises(ValidationError, match="network distance"):
        _section(uncertainty={"cost_margin": "75 m"})
    with pytest.raises(ValidationError, match="network distance"):
        _section(
            phases=[{"name": "sy", "parameters": ["K"], "uncertainty": {"cost_margin": "75 m"}}]
        )

    assert _section(objective="distance_gap", uncertainty={"cost_margin": "75 m"})
    assert _section(uncertainty={"cost_margin": "5%"})


def test_width_follows_the_margin() -> None:
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


def test_section_length_margin_reaches_distance_phases() -> None:
    cfg = _section(
        outputs={
            "net": {"support": "network", "map": {"complete": "s.gpkg"}},
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


_Q_OUTPUT = {
    "variable": "discharge",
    "support": "boundary",
    "boundary_id": "outlet",
    "observes": "G",
}
_Q_BLOCK = {"name": "b", "metric": "rmse", "uses_outputs": ["q"]}


@pytest.mark.parametrize(
    ("model", "document", "match"),
    [
        (CalibrationConfig, {"warmup_periods": 12}, r"warmup_periods.*window = \{start"),
        (CalibrationConfig, {"scoring_window": {}}, r"renamed to 'window'"),
        (CalibPhaseDecl, {"name": "p", "scoring_window": {}}, r"renamed to 'window'"),
        (
            CalibrationProtocolDecl,
            {"name": "matching_hydrographic_network", "scoring_window": {}},
            r"renamed to 'window'",
        ),
        (CalibrationConfig, {"observed_station_id": "G"}, r"observed_station_id.*\[site\] gauge"),
        (CalibPhaseDecl, {"name": "p", "observed_station_id": "G"}, r"\[site\] gauge"),
        (
            CalibrationProtocolDecl,
            {"name": "matching_hydrographic_network", "observed_station_id": "G"},
            r"\[site\] gauge",
        ),
        (
            CalibObjectiveBlockDecl,
            {**_Q_BLOCK, "warmup": 3},
            "a window bounds every block",
        ),
        (
            CalibObjectiveBlockDecl,
            {"name": "b", "uses_outputs": ["q"]},
            "(?s)metric.*Field required",
        ),
        (
            CalibrationConfig,
            {"objective": "kge", "outputs": {"q": _Q_OUTPUT}, "objective_blocks": [_Q_BLOCK]},
            "objective is written beside",
        ),
    ],
    ids=[
        "a sample count",
        "a section scoring_window",
        "a phase scoring_window",
        "a protocol scoring_window",
        "a section station",
        "a phase station",
        "a protocol station",
        "a block burn-in",
        "a block without a metric",
        "an objective beside blocks",
    ],
)
def test_removed_forms_are_refused(model, document, match) -> None:
    with pytest.raises(ValidationError, match=match):
        model.model_validate(document)


@pytest.mark.parametrize(
    ("station", "refused"), [("NANCON", False), ("OTHER", True)], ids=["the gauge", "another"]
)
def test_metrics_station_must_be_the_gauge(tmp_path, station, refused) -> None:
    toml = _project(tmp_path) / "project.toml"
    toml.write_text(PROJECT + f'\n[metrics]\nstation = "{station}"\n', encoding="utf-8")

    if refused:
        with pytest.raises(ConfigValidationError, match=r"site.gauge = 'NANCON'.*metrics.station"):
            HydroModPyConfig.from_toml(toml)
    else:
        assert HydroModPyConfig.from_toml(toml).metrics.station == "NANCON"


SIZE = 6
CELL = 10.0


def _default(function) -> object:
    return inspect.signature(function).parameters["diagonal_neighbors"].default


def test_shared_default_is_d8() -> None:
    assert STREAM_CRITERION_DEFAULTS.diagonal_neighbors is True
    assert CalibNetworkModel.model_fields["neighbours"].default == "D8"


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
def test_every_rebuild_reads_the_default(function) -> None:
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


def test_eight_neighbours_by_default() -> None:
    vertices, connectivity = quad_mesh(SIZE, SIZE, cell_size=CELL)

    geometry = _geometry(_diagonal_plane(), connectivity, vertices)

    assert geometry.metric.diagonal_neighbors is True
    # Every cell reaches the sealed outlet after the flood: it was fed the
    # graph the metric descends.
    assert np.all(np.isfinite(geometry.distance_to_observed[geometry.catchment]))
    # A diagonal step is sqrt(2) cells long, centroid to centroid, so the
    # longest descent is the diagonal of the square and not its two sides.
    assert geometry.saturation_cap_m == pytest.approx(math.sqrt(2.0) * CELL * (SIZE - 1))


def test_d4_on_request() -> None:
    vertices, connectivity = quad_mesh(SIZE, SIZE, cell_size=CELL)

    geometry = _geometry(_diagonal_plane(), connectivity, vertices, diagonal_neighbors=False)

    assert geometry.metric.diagonal_neighbors is False
    assert geometry.saturation_cap_m == pytest.approx(2.0 * CELL * (SIZE - 1))


NAME = "matching_hydrographic_network"
TIME = SimpleNamespace(start_datetime="2000-01-01", end_datetime="2002-12-31")
PLAIN = SimpleNamespace(window=None)
RUN_WINDOW = MetricsWindow.model_validate({"start": "2001-01-01", "end": "2002-06-30"})


def _same(window: dict, metrics_window=RUN_WINDOW) -> frozenset[str]:
    declared = CalibrationProtocolDecl.model_validate({"name": NAME, "window": window})
    return options_the_recipe_already_runs(declared, PLAIN, TIME, metrics_window=metrics_window)


def test_run_window_is_the_recipe_window() -> None:
    assert _same({"start": "2001-01-01", "end": "2002-06-30"}) == {"window"}


@pytest.mark.parametrize(
    ("validation", "written", "same"),
    [
        (
            {"start": "2002-01-01", "end": "2002-06-30"},
            {"start": "2001-01-01", "end": "2001-12-31"},
            {"window"},
        ),
        (
            {"start": "2002-01-01", "end": "2002-06-30"},
            {"start": "2001-01-01", "end": "2002-06-30"},
            frozenset(),
        ),
        (
            {"start": "2001-01-01", "end": "2001-06-30"},
            {"start": "2001-07-01", "end": "2002-06-30"},
            {"window"},
        ),
        ({"start": "2001-06-01", "end": "2001-06-30"}, {"start": "2001-01-01"}, {"window"}),
    ],
    ids=[
        "the run window less a validation at its end",
        "the whole run window also scores the validation days",
        "the run window less a validation at its start",
        "a validation inside leaves the spin-up year",
    ],
)
def test_recipe_window_leaves_out_validation_days(
    validation: dict, written: dict, same: frozenset[str]
) -> None:
    calibration = SimpleNamespace(window=None, validation_window=validation)
    declared = CalibrationProtocolDecl.model_validate({"name": NAME, "window": written})

    assert (
        options_the_recipe_already_runs(declared, calibration, TIME, metrics_window=RUN_WINDOW)
        == same
    )


def test_no_run_window_keeps_spin_up_year() -> None:
    assert _same({"start": "2001-01-01"}, metrics_window=None) == {"window"}


@pytest.mark.parametrize(
    ("uncertainty", "said"),
    [
        ({"method": "multistart"}, "needs 'restarts'"),
        ({"method": "linearized"}, "needs 'perturbation'"),
        ({"method": "cost_profile", "perturbation": 0.01}, "only read by method='linearized'"),
        ({"method": "cost_profile", "restarts": 2}, "only read by method='multistart'"),
    ],
)
def test_uncertainty_option_goes_with_its_method(uncertainty, said) -> None:
    with pytest.raises(ValidationError, match=said):
        CalibUncertaintyDecl.model_validate(uncertainty)


def test_integer_zero_mismatch_stays_a_share() -> None:
    verdict = CalibNetworkVerdict.model_validate({"max_catchment_mismatch": 0})

    assert repr(verdict.max_catchment_mismatch) == "0.0"


def test_length_margin_without_distance_phase_is_refused() -> None:
    phases = [{"name": "sy", "parameters": ["K"]}]

    with pytest.raises(ValidationError, match="network distance"):
        _section(phases=phases, uncertainty={"cost_margin": "75 m"})
    assert _section(phases=phases, uncertainty={"cost_margin": "5%"})


def test_section_options_without_phase() -> None:
    cfg = _section(precision=0.02, method="scipy_nelder_mead", method_options={"xatol": 1e-3})

    assert cfg.precision_for(None) == 0.02
    assert cfg.method_options_for(None) == {"xatol": 1e-3}


def test_same_instant() -> None:
    assert _same_instant("2000-01-01", "2000-01-01T00:00")
    assert not _same_instant("2000-01-01", "not a date")


def test_point_output_without_any_station() -> None:
    output = {"support": "point", "variable": "discharge"}

    assert _defaults({"outputs": {"q": output}}, gauge=None)["outputs"]["q"] == output


@pytest.mark.parametrize(
    ("value", "unit", "days"),
    [(1, "hour", 1 / 24), (1, "day", 1.0), (7, "day", 7.0), (1, "month", 30.4375)],
)
def test_nominal_step_days(value, unit, days) -> None:
    assert nominal_step_days(value, unit) == pytest.approx(days)
