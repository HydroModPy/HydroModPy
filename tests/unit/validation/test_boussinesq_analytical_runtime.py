"""Unit tests for analytical Boussinesq runtime defaults."""

from __future__ import annotations

import tomllib

from validation_cases.shared.boussinesq_analytical_runtime import (
    apply_analytical_boussinesq_runtime_defaults,
)
from validation_cases.shared.boussinesq_piecewise_strip import (
    write_piecewise_strip_launcher_config,
)


def test_analytical_boussinesq_defaults_use_steady_petsc_vi() -> None:
    flow = apply_analytical_boussinesq_runtime_defaults(
        {"flow_regime": "steady", "runtime_backend": "scipy_sparse"}
    )

    assert flow["runtime_backend"] == "petsc"
    assert flow["surface_interaction_model"] == "vi_obstacle"


def test_analytical_boussinesq_defaults_use_transient_petsc_ts_vi() -> None:
    flow = apply_analytical_boussinesq_runtime_defaults(
        {"flow_regime": "transient", "runtime_backend": "local"}
    )

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


def test_piecewise_launcher_config_can_preserve_explicit_sparse_backend(tmp_path) -> None:
    config_path = write_piecewise_strip_launcher_config(
        tmp_path / "run_sparse.toml",
        run_id="sparse_regression",
        process_id="flow_main",
        simulation_name="Sparse regression",
        simulation_description="Sparse regression backend fixture",
        bundle_dir=tmp_path / "mesh_bundle",
        initial_head_m=6.0,
        runtime_backend="scipy_sparse",
        surface_interaction_model="regularized_partition",
        apply_runtime_defaults=False,
    )

    payload = tomllib.loads(config_path.read_text(encoding="utf-8"))

    assert payload["flow"]["runtime_backend"] == "scipy_sparse"
    assert payload["flow"]["surface_interaction_model"] == "regularized_partition"
