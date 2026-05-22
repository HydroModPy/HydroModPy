"""Unit tests for the transport process wrapper."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.physics.transport.transport import Transport, TransportInitialConditions
from hydromodpy.physics.transport.transport_config import (
    Modflow6PrtParametersConfig,
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


def test_transport_config_dump_excludes_inherited_process_fields() -> None:
    cfg = TransportConfig(
        param_list=["legacy"],
        param={"legacy": True},
        ic={"legacy": 1},
        bc={"legacy": 2},
        sinks_sources={"legacy": 3},
        mt3dms={"parameters": {"sconc_init": 7.5, "disp_long": 12.0}},
    )

    dumped = cfg.model_dump()

    assert "param_list" not in dumped
    assert "param" not in dumped
    assert "ic" not in dumped
    assert "bc" not in dumped
    assert "sinks_sources" not in dumped
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


def test_transport_update_helpers_keep_public_parameter_mapping_in_sync() -> None:
    transport = Transport()

    transport.update_modpath_parameters(sel_slice=2)
    transport.update_mt3dms_parameters(sconc_init=3.0)
    transport.update_modflow6gwt_parameters(diffu_coeff=1.0e-6)
    transport.update_modflow6prt_parameters(stop_time_days=20.0)

    assert transport.parameters["modpath"]["sel_slice"] == 2
    assert transport.parameters["mt3dms"]["sconc_init"] == 3.0
    assert transport.parameters["modflow6gwt"]["diffu_coeff"] == 1.0e-6
    assert transport.parameters["modflow6prt"]["stop_time_days"] == 20.0


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
        {"track_time_step_days": 0.0},
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
