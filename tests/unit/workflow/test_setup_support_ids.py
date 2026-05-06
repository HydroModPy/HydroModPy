from hydromodpy.physics.flow.flow_config import FlowConfig
from hydromodpy.workflow.steps.setup import collect_requested_support_ids


def test_collect_requested_support_ids_accepts_typed_flow_param():
    cfg = FlowConfig.model_validate(
        {
            "param_list": ["K", "Sy"],
            "param": {
                "K": {
                    "field": {"id": "K", "kind": "heterogeneous"},
                    "field_heterogeneous": {
                        "values": {"left": "1e-4 m/s", "right": "5e-5 m/s"},
                        "field_spatial_id": "k_bands",
                    },
                },
                "Sy": {
                    "field": {"id": "Sy", "kind": "homogeneous"},
                    "field_homogeneous": {"value": 0.12},
                },
            },
        }
    )

    assert collect_requested_support_ids(cfg) == ("k_bands",)


def test_collect_requested_support_ids_accepts_resolved_dict_payload():
    flow_cfg = type(
        "FlowCfg",
        (),
        {
            "param": {
                "K": {
                    "id": "K",
                    "kind": "heterogeneous",
                    "values": {"left": 1e-4},
                    "field_spatial_id": "k_bands",
                }
            }
        },
    )()

    assert collect_requested_support_ids(flow_cfg) == ("k_bands",)
