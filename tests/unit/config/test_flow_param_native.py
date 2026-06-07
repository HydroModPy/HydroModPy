"""Native Pydantic payload tests for flow parameters."""

from hydromodpy.physics.flow.flow_config import FlowConfig, FlowParam


def test_flow_param_native_round_trip_all_sections() -> None:
    cfg = FlowConfig.model_validate(
        {
            "param": {
                "K": {
                    "field": {
                        "kind": "heterogeneous",
                        "unit": "m/s",
                        "values": {
                            "sand": "1e-4 m/s",
                            "clay": "1e-7 m/s",
                        },
                        "field_spatial_id": "geology",
                    },
                    "field_vertical_profile": {
                        "mode": "exponential",
                        "characteristic_depth": 20.0,
                    },
                },
                "Sy": {
                    "field": {
                        "kind": "homogeneous",
                        "unit": "-",
                        "value": 0.2,
                    },
                },
            }
        }
    )

    assert isinstance(cfg.param["K"], FlowParam)
    assert cfg.param["K"].field.id == "K"
    assert cfg.param["K"].field.kind == "heterogeneous"
    assert cfg.param["K"].field_vertical_profile is not None
    assert cfg.param["Sy"].field.kind == "homogeneous"

    reloaded = FlowConfig.model_validate_json(cfg.model_dump_json())

    assert reloaded == cfg
