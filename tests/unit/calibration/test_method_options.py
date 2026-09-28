"""The options of a calibration method are called ``method_options``, and load checked.

They were ``optimizer_kwargs`` on a phase and on ``[calibration]``, and
``steady_engine_options`` / ``transient_engine_options`` on the protocol: Python
jargon for one concept under two names. The old spellings keep loading, with a
warning naming the new one. An option its method does not take is refused when
the file loads, naming where it was written, instead of when that phase starts,
after the phases before it have spent their budget.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.calibration.config import (
    CalibPhaseDecl,
    CalibrationConfig,
    CalibrationProtocolDecl,
)
from hydromodpy.calibration.optim.method_config import method_options_problem, typed_methods
from hydromodpy.core.config_kit.base import ConfigKeyRenamedWarning

PROTOCOL = "matching_hydrographic_network"


def _phase(**fields: object) -> CalibPhaseDecl:
    return CalibPhaseDecl.model_validate({"name": "sy", "parameters": ["Sy"], **fields})


def test_the_problem_names_the_foreign_key_and_what_the_method_takes() -> None:
    problem = method_options_problem("bisection", {"points_per_dim": 3})

    assert problem is not None
    assert "'bisection' does not take points_per_dim" in problem
    assert "bracket_expand, rel_tol, signed_component, sweep_points" in problem


def test_the_problem_names_a_value_of_the_wrong_type() -> None:
    problem = method_options_problem("bisection", {"sweep_points": "seven"})

    assert problem is not None
    assert "sweep_points = 'seven'" in problem


def test_options_the_method_takes_raise_no_problem() -> None:
    assert method_options_problem("bisection", {"sweep_points": 5}) is None
    assert method_options_problem("grid", {}) is None


def test_a_method_with_no_model_here_is_left_to_its_own_constructor() -> None:
    assert "a_plugin_engine" not in typed_methods()
    assert method_options_problem("a_plugin_engine", {"anything": 1}) is None


def test_a_phase_option_its_method_refuses_is_refused_at_load_with_the_phase() -> None:
    with pytest.raises(ValidationError, match="phase 'sy' method_options: 'grid' does not take"):
        _phase(method="grid", method_options={"rel_tol": 0.01})


def test_a_section_option_its_method_refuses_is_refused_at_load() -> None:
    with pytest.raises(ValidationError, match=r"\[calibration\] method_options: 'optuna'"):
        CalibrationConfig.model_validate({"method": "optuna", "method_options": {"popsize": 4}})


def test_a_protocol_stage_option_is_refused_under_the_key_the_file_wrote() -> None:
    with pytest.raises(ValidationError, match="transient_method_options: 'scipy_nelder_mead'"):
        CalibrationProtocolDecl.model_validate(
            {"name": PROTOCOL, "transient_method_options": {"sweep_points": 7}}
        )


def test_a_phase_s_old_key_loads_under_the_new_name_and_says_so() -> None:
    with pytest.warns(ConfigKeyRenamedWarning, match="'optimizer_kwargs' is now called"):
        phase = _phase(method="bisection", optimizer_kwargs={"sweep_points": 5})

    assert phase.method_options == {"sweep_points": 5}


def test_the_section_s_old_key_loads_under_the_new_name() -> None:
    with pytest.warns(ConfigKeyRenamedWarning, match="method_options"):
        cfg = CalibrationConfig.model_validate(
            {"method": "grid", "optimizer_kwargs": {"points_per_dim": 3}}
        )

    assert cfg.method_options == {"points_per_dim": 3}


def test_the_protocol_s_old_keys_load_under_the_new_names() -> None:
    with pytest.warns(ConfigKeyRenamedWarning) as caught:
        declared = CalibrationProtocolDecl.model_validate(
            {
                "name": PROTOCOL,
                "steady_engine_options": {"sweep_points": 5},
                "transient_engine_options": {"xatol": 0.01},
            }
        )

    assert declared.steady_method_options == {"sweep_points": 5}
    assert declared.transient_method_options == {"xatol": 0.01}
    renamed = " ".join(str(item.message) for item in caught)
    assert "'steady_engine_options' is now called 'steady_method_options'" in renamed
    assert "'transient_engine_options' is now called 'transient_method_options'" in renamed


def test_both_spellings_in_one_phase_are_refused() -> None:
    with pytest.raises(ValidationError, match="both 'optimizer_kwargs' and 'method_options'"):
        _phase(
            method="bisection",
            optimizer_kwargs={"sweep_points": 5},
            method_options={"sweep_points": 7},
        )


def test_the_schema_carries_the_new_names_as_user_keys_and_not_the_old_ones() -> None:
    schema = CalibrationConfig.model_json_schema()
    phase = schema["$defs"]["CalibPhaseDecl"]["properties"]
    protocol = schema["$defs"]["MatchingHydrographicNetworkOptions"]["properties"]

    assert schema["properties"]["method_options"]["x-hmp-profile"] == "user"
    assert phase["method_options"]["x-hmp-profile"] == "user"
    assert protocol["steady_method_options"]["x-hmp-profile"] == "user"
    assert protocol["transient_method_options"]["x-hmp-profile"] == "user"
    text = str(schema)
    assert "optimizer_kwargs" not in text
    assert "engine_options" not in text
    assert "model_legacy_keys" not in text


def test_a_dump_writes_the_new_name_only() -> None:
    with pytest.warns(ConfigKeyRenamedWarning):
        phase = _phase(method="bisection", optimizer_kwargs={"sweep_points": 5})

    dumped = phase.model_dump()
    assert dumped["method_options"] == {"sweep_points": 5}
    assert "optimizer_kwargs" not in dumped


def test_the_protocol_writes_its_stage_options_as_method_options() -> None:
    from hydromodpy.calibration.protocols import expand_calibration_protocol

    document = {
        "simulation": {"time": {"start_datetime": "2000-01-01", "end_datetime": "2002-12-31"}},
        "data": {"hydrometry": {"sources": [{"station_ids": ["G1"]}]}},
        "calibration": {
            "protocol": {"name": PROTOCOL, "steady_method_options": {"sweep_points": 5}},
            "parameters": {"K": {}, "Sy": {}},
            "outputs": {"streams": {"support": "network", "stream_geometry_path": "streams.gpkg"}},
        },
    }

    phases = expand_calibration_protocol(document)["calibration"]["phases"]

    assert phases[0]["method_options"] == {"sweep_points": 5}
    assert "optimizer_kwargs" not in phases[0]


def test_the_preflight_names_the_phase_whose_options_its_method_refuses() -> None:
    """A configuration assembled without validation still meets the check."""
    from hydromodpy.calibration.preflight import _check_engines

    phase = CalibPhaseDecl.model_construct(
        name="transient_storage",
        parameters=["Sy"],
        method="scipy_nelder_mead",
        method_options={"sweep_points": 7},
    )
    calibration = CalibrationConfig.model_construct(parameters={}, phases=[phase])

    findings = [item for item in _check_engines(calibration) if item.severity == "error"]

    assert len(findings) == 1
    assert findings[0].where == "[[calibration.phases]] 'transient_storage'"
    assert "'scipy_nelder_mead' does not take sweep_points" in findings[0].detail
