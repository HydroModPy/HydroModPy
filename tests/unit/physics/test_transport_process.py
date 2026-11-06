from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.physics.transport.transport import Transport, TransportInitialConditions
from hydromodpy.physics.transport.transport_config import (
    Modflow6PrtParametersConfig,
    ModpathParametersConfig,
    TransportConfig,
)


def test_transport_mapping_config_populates_all_solver_parameter_blocks() -> None:
    transport = Transport(
        {
            "modpath": {"parameters": {"track_dir": "backward", "cell_div": 3}},
            "mt3dms": {"parameters": {"spc_name": "NO3", "sconc_input": 12.0}},
            "modflow6gwt": {"parameters": {"disp_long": 2.5}},
            "modflow6prt": {"parameters": {"release_zone": "upstream", "local_z": 0.25}},
        }
    )

    assert isinstance(transport.config, TransportConfig)
    assert transport.modpath.parameters["track_dir"] == "backward"
    assert transport.modpath.parameters["cell_div"] == 3
    assert transport.mt3dms.parameters["sconc_input"] == 12.0
    assert transport.modflow6gwt.parameters["disp_long"] == 2.5
    assert transport.modflow6prt.parameters["release_zone"] == "upstream"
    assert transport.parameters["modflow6prt"] is transport.modflow6prt.parameters


@pytest.mark.parametrize("name", ["param_list", "param", "ic", "bc", "sinks_sources"])
def test_transport_config_has_no_field_of_a_flow_process(name: str) -> None:
    assert name not in TransportConfig.model_fields
    assert not any(field.startswith("active_") for field in TransportConfig.model_fields)
    with pytest.raises(ValidationError):
        TransportConfig(**{name: {}})


def test_transport_config_dump_holds_the_solver_parameters() -> None:
    cfg = TransportConfig(mt3dms={"parameters": {"sconc_init": 7.5, "disp_long": 12.0}})

    dumped = cfg.model_dump()

    assert dumped["mt3dms"]["parameters"]["sconc_init"] == 7.5
    assert dumped["mt3dms"]["parameters"]["disp_long"] == 12.0


def test_transport_set_parameters_accepts_nested_and_flat_solver_payloads() -> None:
    transport = Transport()

    transport.set_parameters(
        {
            "modpath": {"parameters": {"cell_div": 4}},
            "mt3dms": {"rate_decay": 0.01},
            "modflow6gwt": {"parameters": {"plot_conc": False}},
            "modflow6prt": {"max_particles": 50},
            "custom": "kept",
        }
    )

    assert transport.modpath.parameters["cell_div"] == 4
    assert transport.mt3dms.parameters["rate_decay"] == 0.01
    assert transport.modflow6gwt.parameters["plot_conc"] is False
    assert transport.modflow6prt.parameters["max_particles"] == 50
    assert transport.parameters["custom"] == "kept"


def test_transport_initial_conditions_are_structural_and_validated() -> None:
    transport = Transport()

    built = transport.build_initial_conditions({"concentration": 2.0})
    existing = TransportInitialConditions(payload={"particle_release": "upstream"})

    assert built == TransportInitialConditions(payload={"concentration": 2.0})
    assert transport.build_initial_conditions(existing) is existing
    assert transport.build_initial_conditions(None) is None

    transport.set_initial_conditions({"concentration": 4.0})
    assert transport.initial_conditions == TransportInitialConditions(
        payload={"concentration": 4.0}
    )

    with pytest.raises(TypeError, match="mapping"):
        transport.build_initial_conditions(["bad"])


def test_transport_rejects_non_mapping_config_and_parameters() -> None:
    transport = Transport()

    with pytest.raises(TypeError, match="Transport config"):
        transport.set_config(object())
    with pytest.raises(TypeError, match="Transport parameters"):
        transport.set_parameters(["bad"])


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


def test_transport_boundary_conditions_and_sinks_sources_merge_payloads() -> None:
    transport = Transport()

    transport.set_boundary_conditions({"source": {"kind": "constant"}})
    transport.set_boundary_conditions({"outlet": {"kind": "concentration"}})
    transport.set_sinks_sources({"recharge_concentration": 1.0})

    assert sorted(transport.boundary_conditions) == ["outlet", "source"]
    assert transport.sinks_sources == {"recharge_concentration": 1.0}


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
