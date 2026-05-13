"""Unit tests for optional simulation time-window configuration."""

from __future__ import annotations

import pytest

from hydromodpy.simulation.planning.config import SimulationConfig
from hydromodpy.simulation.planning.planner import SimulationPlanner


def test_simulation_time_window_parses_from_mapping() -> None:
    cfg = SimulationConfig.model_validate(
        {
            "name": "time-window",
            "description": "test",
            "time": {
                "start_datetime": "2020-01-01 00:00:00",
                "end_datetime": "2020-01-02 00:00:00",
                "step_value": 6,
                "step_unit": "hour",
                "coverage_policy": "warn",
            },
            "process": [],
        }
    )

    assert cfg.time is not None
    assert cfg.time.step_value == 6
    assert cfg.time.step_unit == "hour"
    assert cfg.time.coverage_policy == "warn"


def test_simulation_catalog_metadata_parses_from_mapping() -> None:
    cfg = SimulationConfig.model_validate(
        {
            "name": "metadata",
            "description": "test",
            "scientific_objective": "calibration",
            "contact_email": "user@example.org",
            "doi": "10.5281/zenodo.0",
            "study_area_name": "Nancon",
            "outlet_x": 350000.0,
            "outlet_y": 6780000.0,
            "process": [],
        }
    )

    assert cfg.scientific_objective == "calibration"
    assert cfg.outlet_x == 350000.0
    assert cfg.outlet_y == 6780000.0


def test_simulation_time_window_parses_inline_step_value_unit() -> None:
    cfg = SimulationConfig.model_validate(
        {
            "name": "time-window-inline",
            "description": "test",
            "time": {
                "start_datetime": "2020-01-01 00:00:00",
                "end_datetime": "2020-01-02 00:00:00",
                "step_value": "30 day",
                "coverage_policy": "warn",
            },
            "process": [],
        }
    )

    assert cfg.time is not None
    assert cfg.time.step_value == 30
    assert cfg.time.step_unit == "day"


def test_simulation_time_window_rejects_inverted_bounds() -> None:
    with pytest.raises(ValueError, match="end_datetime must be greater than or equal"):
        _ = SimulationConfig.model_validate(
            {
                "name": "bad-window",
                "time": {
                    "start_datetime": "2020-01-02 00:00:00",
                    "end_datetime": "2020-01-01 00:00:00",
                },
                "process": [],
            }
        )


def test_simulation_time_window_explicit_requires_bounds() -> None:
    with pytest.raises(ValueError, match="are required when \\[simulation.time\\] is declared"):
        _ = SimulationConfig.model_validate(
            {
                "name": "explicit-without-bounds",
                "time": {
                    "step_value": 1,
                },
                "process": [],
            }
        )


def test_simulation_time_window_rejects_from_modflow_mode() -> None:
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        _ = SimulationConfig.model_validate(
            {
                "name": "from-modflow",
                "time": {
                    "mode": "from_modflow",
                    "start_datetime": "2020-01-01 00:00:00",
                    "end_datetime": "2020-01-02 00:00:00",
                },
                "process": [],
            }
        )


def test_simulation_time_window_rejects_non_positive_step_value() -> None:
    with pytest.raises(ValueError, match="must be a positive integer"):
        _ = SimulationConfig.model_validate(
            {
                "name": "invalid-step",
                "time": {
                    "start_datetime": "2020-01-01 00:00:00",
                    "end_datetime": "2020-01-01 00:00:00",
                    "step_value": 0,
                    "step_unit": "day",
                },
                "process": [],
            }
        )


def test_simulation_time_window_rejects_conflicting_inline_and_explicit_units() -> None:
    with pytest.raises(ValueError, match="unit conflicts with simulation.time.step_unit"):
        _ = SimulationConfig.model_validate(
            {
                "name": "invalid-step-conflict",
                "time": {
                    "start_datetime": "2020-01-01 00:00:00",
                    "end_datetime": "2020-01-02 00:00:00",
                    "step_value": "30 day",
                    "step_unit": "hour",
                },
                "process": [],
            }
        )


def test_simulation_transient_helper_builds_flow_transport_processes() -> None:
    cfg = SimulationConfig.transient(
        time=("2020-01-01", "2020-01-02", "1 day"),
        flow="modflow_nwt",
        transport="mt3dms",
    )

    assert [process.id for process in cfg.process] == ["flow_main", "transport_main"]
    assert [process.type for process in cfg.process] == ["flow", "transport"]
    assert cfg.process[1].solvers == ["mt3dms"]


def test_simulation_mesh_process_uses_backend_not_solvers() -> None:
    cfg = SimulationConfig.model_validate(
        {
            "name": "mesh-only",
            "process": [
                {
                    "id": "mesh_main",
                    "type": "mesh",
                    "backend": "catchment",
                }
            ],
        }
    )

    process = cfg.process[0]
    assert process.type == "mesh"
    assert process.backend == "catchment"
    assert process.solvers == []

    plan = SimulationPlanner().build(cfg)
    assert len(plan.runs) == 1
    assert plan.runs[0].id == "mesh_main::catchment"
    assert plan.runs[0].process_type == "mesh"
    assert plan.runs[0].backend == "catchment"
    assert plan.runs[0].is_solver_backed is False


def test_simulation_mesh_process_rejects_solvers() -> None:
    with pytest.raises(ValueError, match="type='mesh' must use backend"):
        SimulationConfig.model_validate(
            {
                "name": "bad-mesh",
                "process": [
                    {
                        "id": "mesh_main",
                        "type": "mesh",
                        "solvers": ["mesh_catchment"],
                    }
                ],
            }
        )
