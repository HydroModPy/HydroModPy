"""Unit tests for analytical Boussinesq runtime defaults."""

from __future__ import annotations

import tomllib

from validation_cases.shared.boussinesq_analytical_runtime import (
    apply_analytical_boussinesq_runtime_defaults,
    boussinesq_variant_flow_section,
)
from validation_cases.shared.boussinesq_piecewise_strip import (
    write_piecewise_strip_launcher_config,
)


def test_analytical_boussinesq_defaults_fill_steady_petsc_vi() -> None:
    runtime = apply_analytical_boussinesq_runtime_defaults({}, flow_regime="steady")

    assert runtime["backend"] == "petsc"
    assert runtime["surface_interaction_model"] == "vi_obstacle"


def test_analytical_boussinesq_defaults_fill_transient_petsc_ts_vi() -> None:
    runtime = apply_analytical_boussinesq_runtime_defaults({}, flow_regime="transient")

    assert runtime["backend"] == "petsc"
    assert runtime["surface_interaction_model"] == "ts_vi_obstacle"
    assert runtime["ts_vi_steps_per_period"] == 4
    assert runtime["ts_vi_type"] == "beuler"


def test_analytical_boussinesq_defaults_keep_explicit_petsc_surface_model() -> None:
    runtime = apply_analytical_boussinesq_runtime_defaults(
        {"backend": "petsc", "surface_interaction_model": "complementarity"},
        flow_regime="steady",
    )

    assert runtime["backend"] == "petsc"
    assert runtime["surface_interaction_model"] == "complementarity"


def test_analytical_boussinesq_defaults_force_replaces_explicit_model() -> None:
    runtime = apply_analytical_boussinesq_runtime_defaults(
        {"backend": "petsc", "surface_interaction_model": "complementarity"},
        flow_regime="steady",
        force=True,
    )

    assert runtime["backend"] == "petsc"
    assert runtime["surface_interaction_model"] == "vi_obstacle"


def test_a_variant_flow_section_holds_no_runtime_key() -> None:
    section = boussinesq_variant_flow_section(
        {"flow_regime": "steady", "runtime": {"backend": "local"}, "runtime_max_iterations": 5},
        flow_regime="steady",
    )

    assert section == {"flow_regime": "steady"}


def test_a_transient_variant_flow_section_starts_from_its_initial_condition() -> None:
    section = boussinesq_variant_flow_section({"flow_regime": "transient"})

    assert section["first_period_steady"] is False


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

    assert payload["solver"]["boussinesq"]["backend"] == "petsc"
    assert payload["solver"]["boussinesq"]["surface_interaction_model"] == "vi_obstacle"
    assert "runtime" not in payload["flow"]
