"""The ``[transport]`` section: one table per transport solver, under its registry name."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.model.transport.transport_config import (
    PARAMETER_TABLES,
    ConcentrationTransportParametersConfig,
    Modflow6PrtParametersConfig,
    ModpathParametersConfig,
    TransportConfig,
)
from hydromodpy.solver.base.registry import solvers


def test_table_is_read_under_its_solver_name():
    cfg = TransportConfig.model_validate({"mt3dms": {"sconc_init": 7.5, "disp_long": 12.0}})

    options = cfg.options_of("mt3dms")
    assert options.sconc_init == 7.5 and options.disp_long == 12.0
    assert isinstance(options, ConcentrationTransportParametersConfig)


def test_table_of_a_transport_that_does_not_run_is_checked():
    cfg = TransportConfig.model_validate({"modpath": {"zone_partic": "seepage_clip"}})

    assert cfg.options_of("modpath").zone_partic == "seepage_clip"


def test_table_read_back_holds_only_the_touched_tables():
    cfg = TransportConfig.model_validate({"mt3dms": {"sconc_init": 7.5}})

    assert cfg.model_dump() == {
        "mt3dms": {**ConcentrationTransportParametersConfig().model_dump(), "sconc_init": 7.5}
    }
    assert cfg.held_tables() == {"mt3dms": cfg.options_of("mt3dms")}
    assert cfg.written_tables() == {"mt3dms": cfg.options_of("mt3dms")}


NAMED_TABLES = [
    pytest.param("modflow6", ConcentrationTransportParametersConfig, id="modflow6"),
    pytest.param("modflow6_prt", Modflow6PrtParametersConfig, id="modflow6_prt"),
    pytest.param("mt3dms", ConcentrationTransportParametersConfig, id="mt3dms"),
    pytest.param("modpath", ModpathParametersConfig, id="modpath"),
]


@pytest.mark.parametrize(("name", "options"), NAMED_TABLES)
def test_named_tables(name, options):
    named = TransportConfig.named_tables(shipped_only=True)

    assert named[name] is options
    assert named[name]() == options()


def test_parameter_tables_follow_the_solver_registry():
    expected = {name: solvers.get("transport", name).options for name in solvers.names("transport")}

    assert PARAMETER_TABLES == expected


@pytest.mark.parametrize("name", ["param_list", "param", "ic", "bc", "sinks_sources"])
def test_no_field_of_a_flow_process(name):
    assert name not in TransportConfig.model_fields
    assert not any(field.startswith("active_") for field in TransportConfig.model_fields)


@pytest.mark.parametrize("direction", ["forward", "backward"])
def test_modpath_tracks_forward_and_backward(direction):
    assert ModpathParametersConfig(track_dir=direction).track_dir == direction


# Each row is a model, its input, and the part of the message that names the fix.
# MODPATH builds starting locations for forward and backward tracking only.
REFUSALS = [
    pytest.param(
        TransportConfig, {"modflow6gwt": {}}, "transport.modflow6gwt", id="unknown solver"
    ),
    pytest.param(TransportConfig, {"modflow6gwt": {}}, "modflow6_prt", id="served names listed"),
    pytest.param(
        TransportConfig,
        {"modflow6": {"no_transport_has_this_key": 1}},
        "no_transport_has_this_key",
        id="unknown key of a table",
    ),
    pytest.param(TransportConfig, {"param_list": {}}, "param_list", id="flow field param_list"),
    pytest.param(TransportConfig, {"param": {}}, "param", id="flow field param"),
    pytest.param(TransportConfig, {"ic": {}}, "ic", id="flow field ic"),
    pytest.param(TransportConfig, {"bc": {}}, "bc", id="flow field bc"),
    pytest.param(TransportConfig, {"sinks_sources": {}}, "sinks_sources", id="flow field sinks"),
    pytest.param(
        Modflow6PrtParametersConfig, {"upstream_top_quantile": 1.01}, "", id="quantile above 1"
    ),
    pytest.param(Modflow6PrtParametersConfig, {"local_z": -0.01}, "", id="local z below 0"),
    pytest.param(Modflow6PrtParametersConfig, {"porosity": 0.0}, "", id="zero porosity"),
    pytest.param(Modflow6PrtParametersConfig, {"track_time_step": 0.0}, "", id="zero time step"),
    pytest.param(Modflow6PrtParametersConfig, {"track_dir": "backward"}, "", id="prt backward"),
    pytest.param(
        ModpathParametersConfig,
        {"track_dir": "custom"},
        "no starting location",
        id="custom track_dir",
    ),
    pytest.param(
        ModpathParametersConfig, {"track_dir": "custom"}, "'forward' or 'backward'", id="values"
    ),
    pytest.param(ModpathParametersConfig, {"track_dir": "custom"}, "zone_partic", id="other field"),
]


@pytest.mark.parametrize(("model", "payload", "match"), REFUSALS)
def test_refusals(model, payload, match):
    with pytest.raises(ValidationError, match=match):
        model(**payload)


# One row per parameter: its unit, and whether the field warns that a per-day value is about
# 86 400 times too large. The MODFLOW 6 transport runs on the SI clock.
UNITS = [
    pytest.param("diffu_coeff", "m2/s", True, id="molecular diffusion"),
    pytest.param("rate_decay", "1/s, or mass/volume/s", True, id="decay rate"),
    pytest.param("disp_long", "m", False, id="longitudinal dispersivity"),
    pytest.param("sconc_init", "mass/volume", False, id="initial concentration"),
    pytest.param("porosity", "-", False, id="porosity"),
]


@pytest.mark.parametrize(("name", "unit", "warns_about_days"), UNITS)
def test_parameter_units(name, unit, warns_about_days):
    field = ConcentrationTransportParametersConfig.model_fields[name]

    assert field.json_schema_extra["unit"] == unit
    assert ("86400" in field.description) is warns_about_days
