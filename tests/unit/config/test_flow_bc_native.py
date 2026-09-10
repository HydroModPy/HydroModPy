"""Native Pydantic payload tests for flow boundary conditions."""

from hydromodpy.physics.flow.boundary_conditions import CauchyBC, DirichletBC, RobinBC
from hydromodpy.physics.flow.flow_config import FlowConfig


def test_flow_bc_native_round_trip_dirichlet_and_cauchy() -> None:
    cfg = FlowConfig.model_validate(
        {
            "bc": {
                "ocean": {"kind": "dirichlet", "value": 0.0},
                "stream": {"kind": "dirichlet", "value": 1.0},
                "north_side": {"kind": "dirichlet", "value": 2.0},
                "south_side": {"kind": "dirichlet", "value": 3.0},
                "east_side": {"kind": "dirichlet", "value": 4.0},
                "west_side": {"kind": "dirichlet", "value": 5.0},
                "drainage": {
                    "kind": "cauchy",
                    "value": "10 cm2/day",
                    "application_domain": "top",
                },
            }
        }
    )

    assert all(isinstance(cfg.bc[bc_id], DirichletBC) for bc_id in cfg.bc if bc_id != "drainage")
    assert isinstance(cfg.bc["drainage"], CauchyBC)

    reloaded = FlowConfig.model_validate_json(cfg.model_dump_json())

    assert reloaded == cfg


def test_flow_bc_native_round_trip_robin() -> None:
    cfg = FlowConfig.model_validate(
        {
            "bc": {
                "drainage": {
                    "kind": "robin",
                    "value": 2.0e-6,
                    "application_domain": "top",
                }
            }
        }
    )

    assert isinstance(cfg.bc["drainage"], RobinBC)

    reloaded = FlowConfig.model_validate_json(cfg.model_dump_json())

    assert reloaded == cfg
