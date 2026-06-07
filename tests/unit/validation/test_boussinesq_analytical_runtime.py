"""Unit tests for analytical Boussinesq runtime defaults."""

from __future__ import annotations

import tomllib

from validation_cases.shared.boussinesq_analytical_runtime import (
    apply_analytical_boussinesq_runtime_defaults,
)
from validation_cases.shared.boussinesq_piecewise_strip import (
    write_piecewise_strip_launcher_config,
)


def test_analytical_boussinesq_defaults_fill_steady_petsc_vi() -> None:
    flow = apply_analytical_boussinesq_runtime_defaults({"flow_regime": "steady"})

    assert flow["runtime_backend"] == "petsc"
    assert flow["surface_interaction_model"] == "vi_obstacle"


def test_analytical_boussinesq_defaults_fill_transient_petsc_ts_vi() -> None:
    flow = apply_analytical_boussinesq_runtime_defaults({"flow_regime": "transient"})

    assert flow["runtime_backend"] == "petsc"
    assert flow["surface_interaction_model"] == "ts_vi_obstacle"
    assert flow["ts_vi_steps_per_period"] == 4
    assert flow["ts_vi_type"] == "beuler"


def test_analytical_boussinesq_defaults_keep_explicit_petsc_surface_model() -> None:
    flow = apply_analytical_boussinesq_runtime_defaults(
        {
            "flow_regime": "steady",
            "runtime_backend": "petsc",
            "surface_interaction_model": "complementarity",
        }
    )

    assert flow["runtime_backend"] == "petsc"
    assert flow["surface_interaction_model"] == "complementarity"


def test_analytical_boussinesq_defaults_force_replaces_explicit_model() -> None:
    flow = apply_analytical_boussinesq_runtime_defaults(
        {
            "flow_regime": "steady",
            "runtime_backend": "petsc",
            "surface_interaction_model": "complementarity",
        },
        force=True,
    )

    assert flow["runtime_backend"] == "petsc"
    assert flow["surface_interaction_model"] == "vi_obstacle"


def test_piecewise_launcher_config_can_preserve_explicit_runtime_defaults(tmp_path) -> None:
    config_path = write_piecewise_strip_launcher_config(
        tmp_path / "run_petsc.toml",
        run_id="petsc_regression",
        process_id="flow_main",
        simulation_name="PETSc regression",
        simulation_description="Explicit PETSc backend fixture",
        bundle_dir=tmp_path / "mesh_bundle",
        initial_head_m=6.0,
        runtime_backend="petsc",
        surface_interaction_model="vi_obstacle",
        apply_runtime_defaults=False,
    )

    payload = tomllib.loads(config_path.read_text(encoding="utf-8"))

    assert payload["flow"]["runtime_backend"] == "petsc"
    assert payload["flow"]["surface_interaction_model"] == "vi_obstacle"
