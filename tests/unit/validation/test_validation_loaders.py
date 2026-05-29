"""Tests for validation output loader contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from validation_cases.shared.loaders import (
    load_field,
    load_field_on_expected_grid,
    load_time_series_fields,
)


def test_load_field_requires_store_context() -> None:
    with pytest.raises(ValueError, match="no store/sim_id provided"):
        load_field(observable_name="watertable_elevation")


def test_load_time_series_fields_requires_store_context() -> None:
    with pytest.raises(ValueError, match="no store/sim_id provided"):
        load_time_series_fields(observable_name="watertable_elevation")


def test_load_field_on_expected_grid_requires_store_context(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no store/sim_id provided"):
        load_field_on_expected_grid(
            observable_name="watertable_elevation",
            case_dir=tmp_path,
            metadata={},
            solver="boussinesq",
            expected_shape=(1, 1),
        )
