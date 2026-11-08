"""The ``[solver.boussinesq]`` table: its validators, its defaults and its mesh bundle option."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from hydromodpy.config.section_loader import load_standard_section
from hydromodpy.solver.base.solver_config import SolverConfig
from hydromodpy.solver.boussinesq.options import (
    DEFAULT_PARTITION_RELEASE_DEPTH_M,
    BoussinesqOptions,
    normalize_bool,
    normalize_positive_float,
    normalize_positive_int,
    normalize_runtime_backend,
    normalize_surface_interaction_model,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, "auto"),
        ("local", "local"),
        (" PETSC ", "petsc"),
        ("scipy_sparse", "scipy_sparse"),
    ],
)
def test_runtime_backend_normalization_accepts_known_values(raw: object, expected: str) -> None:
    assert normalize_runtime_backend(raw) == expected


def test_runtime_validator_rejects_invalid_numbers_and_booleans() -> None:
    assert normalize_surface_interaction_model(" TS_VI_OBSTACLE ") == "ts_vi_obstacle"
    assert normalize_positive_int("", field="runtime_max_iterations") is None
    assert normalize_positive_int("4", field="vi_substeps_per_period", default=2) == 4
    assert normalize_bool("yes", field="vi_substep_on_failure")
    assert not normalize_bool("off", field="vi_substep_on_failure")
    assert normalize_positive_float("", field="runtime_tol", default=1.0e-6) == pytest.approx(
        1.0e-6
    )
    assert normalize_positive_float("0.25", field="runtime_tol") == pytest.approx(0.25)

    for call in (
        lambda: normalize_runtime_backend("gpu"),
        lambda: normalize_surface_interaction_model("wetdry"),
        lambda: normalize_positive_int(True, field="steps", default=1),
        lambda: normalize_positive_int("1.2", field="steps", default=1),
        lambda: normalize_bool("maybe", field="flag"),
        lambda: normalize_positive_float(False, field="tol", default=1.0),
        lambda: normalize_positive_float("0", field="tol"),
    ):
        with pytest.raises(ValueError):
            call()


def test_the_defaults_of_the_table_are_the_ones_the_solver_documents() -> None:
    options = BoussinesqOptions()

    assert options.backend == "auto"
    assert options.surface_interaction_model == "auto"
    assert options.partition_release_depth_m == DEFAULT_PARTITION_RELEASE_DEPTH_M == 0.05
    assert options.vi_substeps_per_period == 1
    assert options.ts_vi_steps_per_period == 4
    assert options.ts_vi_type == "beuler"
    assert options.ts_vi_snes_type == "vinewtonrsls"
    assert options.ts_vi_dt_min_fraction == pytest.approx(1.0 / 64.0)
    assert options.ts_vi_dt_max_fraction == pytest.approx(1.0 / 4.0)
    assert options.exchange_mesh is None


@pytest.mark.parametrize(
    "written",
    [
        {"backend": "gpu"},
        {"surface_interaction_model": "wetdry"},
        {"partition_release_depth_m": 0.0},
        {"max_iterations": 0},
        {"vi_substeps_per_period": 1.5},
        {"ts_vi_dt_max_fraction": -1.0},
        {"vi_substep_on_failure": "maybe"},
        {"ts_vi_adapt": "yes"},
        {"unknown_key": 1},
    ],
)
def test_the_table_refuses_what_the_solver_cannot_read(written: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        BoussinesqOptions.model_validate(written)


def test_the_table_reads_the_spelling_a_toml_file_uses() -> None:
    options = BoussinesqOptions.model_validate(
        {
            "backend": " PETSC ",
            "ts_vi_adapt": True,
            "tol_residual_inf": "1e-9",
            "max_iterations": "",
        }
    )

    assert options.backend == "petsc"
    assert options.ts_vi_adapt is True
    assert options.tol_residual_inf == pytest.approx(1.0e-9)
    assert options.max_iterations is None


def test_the_exchange_mesh_is_a_path_the_loader_resolves_against_the_toml_folder(
    tmp_path: Path,
) -> None:
    solver = load_standard_section(
        {"boussinesq": {"exchange_mesh": "bundles/strip"}}, SolverConfig, tmp_path
    )

    assert solver.options_of("boussinesq").exchange_mesh == tmp_path / "bundles" / "strip"


def test_the_exchange_mesh_stays_unset_when_the_table_does_not_name_one(tmp_path: Path) -> None:
    solver = load_standard_section({"boussinesq": {"backend": "petsc"}}, SolverConfig, tmp_path)

    assert solver.options_of("boussinesq").exchange_mesh is None
    assert solver.options_of("boussinesq").backend == "petsc"


def test_the_exchange_mesh_is_a_developer_option_only() -> None:
    from hydromodpy.core.config_kit.profile import Profile

    field = BoussinesqOptions.model_fields["exchange_mesh"]

    assert Profile.DEV in field.metadata
