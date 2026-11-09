"""The ``[transport]`` section: one table per transport solver, under its registry name."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.model.transport.transport_config import (
    ConcentrationTransportParametersConfig,
    Modflow6PrtParametersConfig,
    ModpathParametersConfig,
    TransportConfig,
)


def test_a_table_is_read_under_the_registry_name_of_its_solver() -> None:
    cfg = TransportConfig.model_validate({"mt3dms": {"sconc_init": 7.5, "disp_long": 12.0}})

    options = cfg.options_of("mt3dms")
    assert options.sconc_init == 7.5 and options.disp_long == 12.0
    assert isinstance(options, ConcentrationTransportParametersConfig)


def test_a_table_of_a_transport_that_does_not_run_is_accepted_and_checked() -> None:
    cfg = TransportConfig.model_validate({"modpath": {"zone_partic": "seepage_clip"}})

    assert cfg.options_of("modpath").zone_partic == "seepage_clip"


def test_a_name_nothing_serves_is_refused_with_the_names_served() -> None:
    with pytest.raises(ValidationError) as excinfo:
        TransportConfig.model_validate({"modflow6gwt": {}})

    message = str(excinfo.value)
    assert "transport.modflow6gwt" in message
    assert "modflow6" in message and "modflow6_prt" in message


def test_an_unknown_key_of_a_table_is_refused_at_its_own_key() -> None:
    with pytest.raises(ValidationError) as excinfo:
        TransportConfig.model_validate({"modflow6": {"no_transport_has_this_key": 1}})

    assert "no_transport_has_this_key" in str(excinfo.value)


def test_a_table_read_back_holds_no_parameters_level_and_no_untouched_table() -> None:
    cfg = TransportConfig.model_validate({"mt3dms": {"sconc_init": 7.5}})

    dumped = cfg.model_dump()

    assert dumped == {
        "mt3dms": {**ConcentrationTransportParametersConfig().model_dump(), "sconc_init": 7.5}
    }
    assert cfg.held_tables() == {"mt3dms": cfg.options_of("mt3dms")}
    assert cfg.written_tables() == {"mt3dms": cfg.options_of("mt3dms")}


@pytest.mark.parametrize(
    ("name", "options"),
    [
        ("modflow6", ConcentrationTransportParametersConfig),
        ("modflow6_prt", Modflow6PrtParametersConfig),
        ("mt3dms", ConcentrationTransportParametersConfig),
        ("modpath", ModpathParametersConfig),
    ],
)
def test_the_named_tables_are_the_parameter_classes_of_the_transports(
    name: str, options: type
) -> None:
    named = TransportConfig.named_tables(shipped_only=True)

    assert named[name] is options
    assert named[name]() == options()


def test_parameter_tables_agree_with_solver_registry() -> None:
    from hydromodpy.model.transport.transport_config import PARAMETER_TABLES
    from hydromodpy.solver.base.registry import solvers

    expected = {name: solvers.get("transport", name).options for name in solvers.names("transport")}
    assert PARAMETER_TABLES == expected


@pytest.mark.parametrize("name", ["param_list", "param", "ic", "bc", "sinks_sources"])
def test_transport_config_has_no_field_of_a_flow_process(name: str) -> None:
    assert name not in TransportConfig.model_fields
    assert not any(field.startswith("active_") for field in TransportConfig.model_fields)
    with pytest.raises(ValidationError):
        TransportConfig.model_validate({name: {}})


@pytest.mark.parametrize(
    "payload",
    [
        {"upstream_top_quantile": 1.01},
        {"local_z": -0.01},
        {"porosity": 0.0},
        {"track_time_step": 0.0},
        {"track_dir": "backward"},
    ],
)
def test_transport_prt_rejects_nonphysical_controls(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Modflow6PrtParametersConfig(**payload)


# MODPATH builds starting locations for forward and backward tracking only.


def test_custom_track_dir_is_refused_with_the_values_to_write() -> None:
    with pytest.raises(ValidationError) as excinfo:
        ModpathParametersConfig(track_dir="custom")
    message = str(excinfo.value)
    assert "no starting location" in message
    assert "'forward' or 'backward'" in message
    assert "zone_partic" in message


@pytest.mark.parametrize("direction", ["forward", "backward"])
def test_forward_and_backward_are_accepted(direction: str) -> None:
    assert ModpathParametersConfig(track_dir=direction).track_dir == direction
